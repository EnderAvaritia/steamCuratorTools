"""Best-effort Steam app metadata and support email extraction."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any

import requests
from bs4 import BeautifulSoup

from ..http import buildSession

_appidPatterns = (
    re.compile(r"/app/(\d+)"),
    re.compile(r"/recommended/(\d+)"),
    re.compile(r"[?&]appid=(\d+)"),
)
_emailPattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


class SteamInfoExtractor:
    def __init__(
        self,
        proxyProvider: Callable[[], Mapping[str, str]] | None = None,
        session: Any | None = None,
        timeout: float = 10.0,
        helpTimeout: float = 6.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.session = session if session is not None else buildSession()
        self.proxyProvider = proxyProvider
        self.timeout = timeout
        self.helpTimeout = helpTimeout
        self.logger = logger or logging.getLogger(f"{__name__}.SteamInfoExtractor")
        self._applyProxies()

    def _applyProxies(self) -> None:
        if self.proxyProvider is None:
            self.session.proxies = {}
            return
        self.session.proxies = dict(self.proxyProvider())

    @staticmethod
    def extractAppidFromUrl(url: str | None) -> str | None:
        """Extract an appid from store, community recommendation, or help URLs."""
        if not isinstance(url, str) or not url.strip():
            return None
        for pattern in _appidPatterns:
            match = pattern.search(url)
            if match:
                return match.group(1)
        return None

    def getGameInfoFromAppid(self, appid: str) -> dict[str, str]:
        """Return ``game_name``/``publisher_name``, or an empty dict on failure."""
        value = str(appid).strip()
        if not value.isdigit():
            self.logger.warning("AppID 不是纯数字: %r", appid)
            return {}

        url = f"https://store.steampowered.com/api/appdetails?appids={value}&l=schinese"
        try:
            self._applyProxies()
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            self.logger.error("获取 AppID %s 的游戏信息失败: %s", value, exc)
            return {}
        except ValueError as exc:
            self.logger.error("解析 AppID %s 的 API 响应失败: %s", value, exc)
            return {}

        entry = payload.get(value) if isinstance(payload, dict) else None
        if not isinstance(entry, dict) or not entry.get("success"):
            self.logger.warning("AppID %s 在 API 响应中不存在或请求失败", value)
            return {}
        info = entry.get("data")
        if not isinstance(info, dict):
            return {}

        gameName = str(info.get("name") or "").strip()
        publishers = info.get("publishers")
        publisherName = (
            ", ".join(str(name).strip() for name in publishers if str(name).strip())
            if isinstance(publishers, list)
            else ""
        )
        if not gameName:
            self.logger.warning("AppID %s 的 API 响应缺少游戏名", value)
        if not publisherName:
            self.logger.warning("AppID %s 的 API 响应缺少发行商", value)
        return {"game_name": gameName, "publisher_name": publisherName}

    def getEmailFromSteamHelp(self, appid: str) -> str | None:
        """Read the official support email from Steam's help wizard page."""
        value = str(appid).strip()
        if not value.isdigit():
            return None
        url = (
            "https://help.steampowered.com/zh-cn/wizard/"
            f"HelpWithGameTechnicalIssue?appid={value}"
        )
        try:
            self._applyProxies()
            response = self.session.get(url, timeout=self.helpTimeout)
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            status = getattr(exc.response, "status_code", "?")
            if status == 429:
                self.logger.warning("Steam 帮助页面限流 (AppID %s)", value)
            else:
                self.logger.warning("Steam 帮助页面请求失败 (AppID %s, HTTP %s)", value, status)
            return None
        except requests.exceptions.RequestException as exc:
            self.logger.warning("无法访问 Steam 帮助页面 (AppID %s): %s", value, exc)
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        nodes = soup.select(".help_official_support_row")
        text = " ".join(node.get_text(" ", strip=True) for node in nodes)
        if not text:
            text = soup.get_text(" ", strip=True)
        match = _emailPattern.search(text)
        if match:
            return match.group(0)
        self.logger.warning("Steam 帮助页面未找到邮箱 (AppID %s)", value)
        return None

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()
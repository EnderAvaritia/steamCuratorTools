"""HTTP transport with retries, backoff, proxy rotation, and masking."""

from __future__ import annotations

import importlib
import logging
import random
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests

from .config import DEFAULT_RETRIES, DEFAULT_TIMEOUT
from .errors import AuthError, ConfigError, SteamError
from .urls import BASE_URL

ALLOWED_PROXY_SCHEMES = ("http", "https", "socks4", "socks5", "socks5h")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) "
    "Gecko/20100101 Firefox/159.0"
)


class HttpResponse(Protocol):
    status_code: int
    reason: str
    headers: Mapping[str, str]
    text: str

    def json(self) -> Any: ...


def mask_proxy(proxy: str) -> str:
    """Hide proxy credentials before logging."""
    parts = urlsplit(proxy)
    if parts.username or parts.password:
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://***@{host}{port}"
    return proxy


def normalize_proxy(value: str) -> str:
    """Normalize one proxy value, accepting bare ``host:port``."""
    value = value.strip().strip('"').strip("'")
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in ALLOWED_PROXY_SCHEMES or not parts.hostname:
        raise ConfigError(
            f"无效代理地址: {mask_proxy(value)!r}，"
            "应形如 http://127.0.0.1:10279 或 socks5://127.0.0.1:1080"
        )
    return value


def _import_socks() -> ModuleType:
    """Import seam for PySocks (monkeypatched in tests)."""
    return importlib.import_module("socks")


def ensure_socks_support(proxies: list[str]) -> None:
    if any(urlsplit(proxy).scheme.lower().startswith("socks") for proxy in proxies):
        try:
            _import_socks()
        except ImportError as exc:
            raise ConfigError(
                "检测到 socks 代理，但缺少依赖，请先安装："
                'pip install "requests[socks]"'
            ) from exc


def collect_proxies(
    values: list[str] | None,
    proxy_file: str | None,
) -> list[str]:
    """Merge CLI proxies and a proxy file, normalizing and deduplicating."""
    raw: list[str] = []
    for value in values or []:
        raw.extend(value.split(","))

    if proxy_file:
        try:
            lines = Path(proxy_file).expanduser().read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ConfigError(f"读取代理文件失败: {exc}") from exc
        for line in lines:
            line = line.split("#", 1)[0].strip()
            if line:
                raw.append(line)

    proxies: list[str] = []
    for value in raw:
        normalized = normalize_proxy(value)
        if normalized and normalized not in proxies:
            proxies.append(normalized)

    ensure_socks_support(proxies)
    return proxies


class ProxyPool:
    """Round-robin proxy rotation; empty pool defers to requests' env handling."""

    def __init__(self, proxies: list[str] | None = None) -> None:
        self._proxies = list(proxies or [])
        self._index = 0

    def __len__(self) -> int:
        return len(self._proxies)

    @property
    def proxies(self) -> tuple[str, ...]:
        return tuple(self._proxies)

    def next(self) -> str | None:
        if not self._proxies:
            return None
        proxy = self._proxies[self._index % len(self._proxies)]
        self._index += 1
        return proxy


def build_session() -> requests.Session:
    """Create a Firefox-like session with no cookies preloaded."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "DNT": "1",
        }
    )
    return session


class HttpTransport:
    """Request executor with retries, exponential backoff, and proxy rotation."""

    def __init__(
        self,
        session: Any | None = None,
        proxies: list[str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        logger: logging.Logger | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[float, float], float] | None = None,
        base_backoff: float = 3.0,
        max_backoff: float = 60.0,
    ) -> None:
        self.session = session if session is not None else build_session()
        self.proxy_pool = ProxyPool(proxies)
        self.timeout = timeout
        self.retries = retries
        self.logger = logger or logging.getLogger("steam_curator_exporter")
        self._sleep = sleep if sleep is not None else time.sleep
        self._jitter = jitter if jitter is not None else random.uniform
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff

    @property
    def proxies(self) -> tuple[str, ...]:
        return self.proxy_pool.proxies

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        last_error: Exception | None = None
        effective_timeout = self.timeout if timeout is None else timeout

        for attempt in range(1, self.retries + 1):
            proxy = self.proxy_pool.next()
            if proxy:
                self.session.proxies = {"http": proxy, "https": proxy}
                self.logger.debug(
                    "本次使用代理: %s（第 %d/%d 次尝试）",
                    mask_proxy(proxy),
                    attempt,
                    self.retries,
                )
            try:
                specific = getattr(self.session, method.lower(), None)
                if callable(specific) and method.upper() in {"GET", "POST"}:
                    response = specific(
                        url,
                        params=params,
                        data=data,
                        headers=headers,
                        timeout=effective_timeout,
                    )
                else:
                    response = self.session.request(
                        method,
                        url,
                        params=params,
                        data=data,
                        headers=headers,
                        timeout=effective_timeout,
                    )
            except requests.exceptions.RequestException as exc:
                last_error = exc
                self.logger.warning("网络错误（第 %d/%d 次）: %s", attempt, self.retries, exc)
            else:
                status = int(response.status_code)
                if status in (401, 403):
                    raise AuthError(
                        f"HTTP {status}：Cookie/sessionid 无效或已过期，"
                        "请重新导出 HAR 或更新 Cookie"
                    )
                if status == 429:
                    last_error = SteamError("HTTP 429：请求过于频繁")
                    self.logger.warning("被限流（第 %d/%d 次），稍后重试", attempt, self.retries)
                elif status >= 500:
                    last_error = SteamError(f"HTTP {status}")
                    self.logger.warning(
                        "服务端错误 %s（第 %d/%d 次）", status, attempt, self.retries
                    )
                elif status >= 400:
                    raise SteamError(f"HTTP {status}: {response.reason}")
                else:
                    return response

            if attempt < self.retries:
                backoff = min(self.base_backoff * (2 ** (attempt - 1)), self.max_backoff)
                wait = backoff + self._jitter(0.0, 2.0)
                self.logger.info("等待 %.1f 秒后重试...", wait)
                self._sleep(wait)

        raise SteamError(f"请求 {url}（start={params.get('start') if params else '?'}）"
                         f"连续失败 {self.retries} 次: {last_error}")

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()


def default_headers(referer: str, cookie: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE_URL,
        "Referer": referer,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "DNT": "1",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers

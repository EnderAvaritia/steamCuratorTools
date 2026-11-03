"""Review page sources: admin AJAX (JSON) and public curator page (HTML)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import Config
from .errors import AuthError, SteamError
from .http import HttpResponse, HttpTransport, defaultHeaders
from .urls import baseUrl, buildReferer, sourceAdmin, sourcePublic

publicHeaders = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass(slots=True)
class Page:
    """One fetched page of recommendations."""

    recommendations: list[dict[str, Any]]
    serverStart: int
    totalCount: int | None
    raw: Any = None


class ReviewSource(Protocol):
    source: str

    def fetchPage(self, url: str, start: int, count: int) -> Page: ...


def _intOrNone(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AdminSource:
    """Curator admin AJAX endpoint; requires a logged-in cookie and sessionid."""

    source = sourceAdmin

    def __init__(
        self,
        transport: HttpTransport,
        sessionid: str,
        cookie: str,
        clanId: str | None = None,
        referer: str | None = None,
    ) -> None:
        self.transport = transport
        self.sessionid = sessionid
        self.cookie = cookie
        self.clanId = clanId
        self.referer = referer

    def fetchPage(self, url: str, start: int, count: int) -> Page:
        referer = self.referer or buildReferer(url, self.clanId, sourceAdmin)
        headers = defaultHeaders(referer, self.cookie)
        params = {"start": str(start), "count": str(count)}
        data = {"sessionid": self.sessionid, "start": str(start), "count": str(count)}
        response = self.transport.request(
            "POST",
            url,
            params=params,
            data=data,
            headers=headers,
        )
        return self._parse(response, start)

    def _parse(self, response: HttpResponse, requestedStart: int) -> Page:
        contentType = str(response.headers.get("content-type", ""))
        if "json" not in contentType.lower():
            snippet = response.text[:200].replace("\n", " ")
            raise AuthError(
                "接口返回的不是 JSON（大概率登录态失效或 Cookie 已过期，被重定向到登录页）。"
                f"content-type={contentType!r}, body 开头={snippet!r}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SteamError(f"JSON 解析失败: {exc}") from exc

        if not isinstance(payload, dict):
            raise SteamError(f"响应结构异常: {type(payload).__name__}")
        if payload.get("success") != 1:
            raise AuthError(
                f"接口 success != 1（start={requestedStart}）："
                f"{json.dumps(payload, ensure_ascii=False)[:300]}"
            )
        rawRecommendations = payload.get("recommendations")
        if rawRecommendations is None:
            raise SteamError(
                "响应缺少 recommendations 字段: "
                f"{json.dumps(payload, ensure_ascii=False)[:300]}"
            )
        if not isinstance(rawRecommendations, list):
            raise SteamError(
                f"响应 recommendations 不是数组: {type(rawRecommendations).__name__}"
            )
        recommendations = [item for item in rawRecommendations if isinstance(item, dict)]
        serverStart = _intOrNone(payload.get("start"))
        if serverStart is None:
            serverStart = requestedStart
        totalCount = _intOrNone(payload.get("total_count"))
        return Page(
            recommendations=recommendations,
            serverStart=serverStart,
            totalCount=totalCount,
            raw=payload,
        )


def _appidFromAnchor(anchor: Any) -> str:
    raw = anchor.get("data-ds-appid", "")
    # Some payloads contain escaped quotes (\"123\") or HTML entities ("123").
    text = str(raw).strip().strip("\"'\\").strip()
    return text if text.isdigit() else ""


def _appNameFromAnchor(anchor: Any) -> str:
    text = anchor.get_text(" ", strip=True)
    if text:
        return text
    title = anchor.get("title")
    if title:
        return str(title).strip()
    image = anchor.find("img")
    if image is not None:
        alt = image.get("alt") or image.get("title")
        if alt:
            return str(alt).strip()
    return ""


class PublicSource:
    """Public curator page; no authentication, limited fields, HTML parsing."""

    source = sourcePublic

    def __init__(self, transport: HttpTransport, clanId: str | None = None) -> None:
        self.transport = transport
        self.clanId = clanId

    def fetchPage(self, url: str, start: int, count: int) -> Page:
        referer = buildReferer(url, self.clanId, sourcePublic)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) "
                "Gecko/20100101 Firefox/159.0"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
            "DNT": "1",
            **publicHeaders,
        }
        params = {
            "query": "",
            "start": str(start),
            "count": str(count),
            "dynamic_data": "",
            "tagids": "",
            "sort": "recent",
            "app_types": "",
            "curations": "",
            "reset": "false",
        }
        response = self.transport.request("GET", url, params=params, headers=headers)
        return self._parse(response.text, start)

    def _parse(self, html: str, requestedStart: int) -> Page:
        soup = BeautifulSoup(html, "html.parser")
        recommendations: list[dict[str, Any]] = []
        for anchor in soup.select("a[data-ds-appid]"):
            appid = _appidFromAnchor(anchor)
            if not appid:
                continue
            name = _appNameFromAnchor(anchor)
            href = urljoin(baseUrl, str(anchor.get("href") or ""))
            recommendations.append(
                {
                    "appid": int(appid),
                    "app_name": name,
                    "recommendation": {
                        "appid": int(appid),
                        "link_url": href,
                        "link_text": name,
                        "blurb": "",
                        "time_recommended": None,
                        "accountid_creator": None,
                        "upvote_count": 0,
                        "comment_count": 0,
                        "received_for_free": 0,
                        "received_compensation": 0,
                        "recommendation_state": 0,
                    },
                }
            )
        return Page(
            recommendations=recommendations,
            serverStart=requestedStart,
            totalCount=0,
            raw=html,
        )


def buildSource(config: Config, transport: HttpTransport, sessionid: str | None) -> ReviewSource:
    if config.source == sourcePublic:
        return PublicSource(transport, config.clanId)
    if not sessionid:
        raise SteamError("admin 数据源需要 sessionid")
    return AdminSource(
        transport,
        sessionid,
        config.cookie or "",
        config.clanId,
        config.referer,
    )


def pageMeta(page: Page) -> Mapping[str, Any]:
    return {
        "server_start": page.serverStart,
        "returned": len(page.recommendations),
        "total_count": page.totalCount,
    }

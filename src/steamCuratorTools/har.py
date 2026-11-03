"""Extract request details (URL, cookie, sessionid, referer) from a HAR file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from .errors import ConfigError
from .urls import extractSessionid, sourcePublic

endpointRecommendations = "recommendations"
endpointDelete = "delete"


@dataclass(slots=True)
class HarInfo:
    url: str | None = None
    cookie: str | None = None
    sessionid: str | None = None
    referer: str | None = None


def _headersByName(request: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in request.get("headers", []) or []:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name", "")).lower()
        if name:
            headers[name] = str(header.get("value", ""))
    return headers


def _sessionidFromPostData(postData: Any) -> str | None:
    if not isinstance(postData, dict):
        return None
    for param in postData.get("params", []) or []:
        if isinstance(param, dict) and param.get("name") == "sessionid":
            value = str(param.get("value") or "").strip()
            if value:
                return value
    text = postData.get("text")
    if isinstance(text, str) and text:
        values = parse_qs(text).get("sessionid")
        if values:
            value = values[0].strip()
            if value:
                return value
    return None


def _sessionidFromQuery(request: dict[str, Any]) -> str | None:
    for param in request.get("queryString", []) or []:
        if isinstance(param, dict) and param.get("name") == "sessionid":
            value = str(param.get("value") or "").strip()
            if value:
                return value
    return None


def _isAdminEntry(entry: dict[str, Any]) -> bool:
    url = str((entry.get("request") or {}).get("url", ""))
    return "/admin/ajaxgetrecommendations" in url


def _isDeleteEntry(entry: dict[str, Any]) -> bool:
    url = str((entry.get("request") or {}).get("url", ""))
    return "/admin/ajaxdeletereview" in url


def _isPublicEntry(entry: dict[str, Any]) -> bool:
    url = str((entry.get("request") or {}).get("url", ""))
    return "ajaxgetfilteredrecommendations" in url and "/admin/" not in url


def loadHar(
    path: Path,
    source: str | None = None,
    *,
    endpoint: str = endpointRecommendations,
) -> HarInfo:
    """Read a browser HAR and return the best matching curator request.

    ``source`` lets callers prefer the entry that matches the requested mode.
    ``endpoint="delete"`` prefers the ``ajaxdeletereview`` entry so a HAR that
    only captured a delete click still yields usable credentials. The admin
    entry remains the default and wins for export/check flows.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"读取 HAR 失败: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("log"), dict):
        raise ConfigError("HAR 结构异常：缺少 log 对象")
    entries = raw["log"].get("entries") or []
    if not isinstance(entries, list):
        raise ConfigError("HAR 结构异常：log.entries 不是数组")
    adminEntries = [entry for entry in entries if _isAdminEntry(entry)]
    deleteEntries = [entry for entry in entries if _isDeleteEntry(entry)]
    publicEntries = [entry for entry in entries if _isPublicEntry(entry)]

    if endpoint == endpointDelete:
        selected = deleteEntries or adminEntries or publicEntries
    elif source == sourcePublic:
        selected = publicEntries or adminEntries or deleteEntries
    else:
        selected = adminEntries or deleteEntries or publicEntries

    if not selected:
        raise ConfigError(
            "HAR 中没有找到包含 ajaxgetrecommendations、ajaxdeletereview 或 "
            "ajaxgetfilteredrecommendations 的请求"
        )

    request = selected[-1].get("request") or {}
    headers = _headersByName(request)
    cookie = headers.get("cookie") or None
    referer = headers.get("referer") or None
    sessionid = _sessionidFromPostData(request.get("postData"))
    if not sessionid:
        sessionid = _sessionidFromQuery(request)
    if not sessionid:
        sessionid = extractSessionid(cookie or "")

    return HarInfo(
        url=request.get("url") or None,
        cookie=cookie,
        sessionid=sessionid,
        referer=referer,
    )

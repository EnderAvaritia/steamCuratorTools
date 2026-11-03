"""Extract request details (URL, cookie, sessionid, referer) from a HAR file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from .errors import ConfigError
from .urls import SOURCE_PUBLIC, extract_sessionid

ENDPOINT_RECOMMENDATIONS = "recommendations"
ENDPOINT_DELETE = "delete"


@dataclass(slots=True)
class HarInfo:
    url: str | None = None
    cookie: str | None = None
    sessionid: str | None = None
    referer: str | None = None


def _headers_by_name(request: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in request.get("headers", []) or []:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name", "")).lower()
        if name:
            headers[name] = str(header.get("value", ""))
    return headers


def _sessionid_from_post_data(post_data: Any) -> str | None:
    if not isinstance(post_data, dict):
        return None
    for param in post_data.get("params", []) or []:
        if isinstance(param, dict) and param.get("name") == "sessionid":
            value = str(param.get("value") or "").strip()
            if value:
                return value
    text = post_data.get("text")
    if isinstance(text, str) and text:
        values = parse_qs(text).get("sessionid")
        if values:
            value = values[0].strip()
            if value:
                return value
    return None


def _sessionid_from_query(request: dict[str, Any]) -> str | None:
    for param in request.get("queryString", []) or []:
        if isinstance(param, dict) and param.get("name") == "sessionid":
            value = str(param.get("value") or "").strip()
            if value:
                return value
    return None


def _is_admin_entry(entry: dict[str, Any]) -> bool:
    url = str((entry.get("request") or {}).get("url", ""))
    return "/admin/ajaxgetrecommendations" in url


def _is_delete_entry(entry: dict[str, Any]) -> bool:
    url = str((entry.get("request") or {}).get("url", ""))
    return "/admin/ajaxdeletereview" in url


def _is_public_entry(entry: dict[str, Any]) -> bool:
    url = str((entry.get("request") or {}).get("url", ""))
    return "ajaxgetfilteredrecommendations" in url and "/admin/" not in url


def load_har(
    path: Path,
    source: str | None = None,
    *,
    endpoint: str = ENDPOINT_RECOMMENDATIONS,
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
    admin_entries = [entry for entry in entries if _is_admin_entry(entry)]
    delete_entries = [entry for entry in entries if _is_delete_entry(entry)]
    public_entries = [entry for entry in entries if _is_public_entry(entry)]

    if endpoint == ENDPOINT_DELETE:
        selected = delete_entries or admin_entries or public_entries
    elif source == SOURCE_PUBLIC:
        selected = public_entries or admin_entries or delete_entries
    else:
        selected = admin_entries or delete_entries or public_entries

    if not selected:
        raise ConfigError(
            "HAR 中没有找到包含 ajaxgetrecommendations、ajaxdeletereview 或 "
            "ajaxgetfilteredrecommendations 的请求"
        )

    request = selected[-1].get("request") or {}
    headers = _headers_by_name(request)
    cookie = headers.get("cookie") or None
    referer = headers.get("referer") or None
    sessionid = _sessionid_from_post_data(request.get("postData"))
    if not sessionid:
        sessionid = _sessionid_from_query(request)
    if not sessionid:
        sessionid = extract_sessionid(cookie or "")

    return HarInfo(
        url=request.get("url") or None,
        cookie=cookie,
        sessionid=sessionid,
        referer=referer,
    )

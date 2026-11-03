from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from steam_curator_exporter.config import Config

FIXTURES = Path(__file__).parent / "fixtures"
ADMIN_HAR = FIXTURES / "admin.har"
PUBLIC_HAR = FIXTURES / "public.har"


@dataclass
class FakeResponse:
    status_code: int = 200
    reason: str = "OK"
    headers: Mapping[str, str] = field(
        default_factory=lambda: {"content-type": "application/json; charset=utf-8"}
    )
    text: str = ""
    payload: Any = None

    def json(self) -> Any:
        if self.payload is not None:
            return self.payload
        return json.loads(self.text)


def json_response(payload: dict[str, Any], status: int = 200) -> FakeResponse:
    return FakeResponse(
        status_code=status,
        headers={"content-type": "application/json; charset=utf-8"},
        text=json.dumps(payload, ensure_ascii=False),
        payload=payload,
    )


def html_response(text: str, status: int = 200) -> FakeResponse:
    return FakeResponse(
        status_code=status,
        headers={"content-type": "text/html; charset=utf-8"},
        text=text,
        payload=None,
    )


def admin_response(
    items: list[dict[str, Any]],
    total: int | None,
    start: int | None = None,
) -> FakeResponse:
    payload: dict[str, Any] = {
        "success": 1,
        "recommendations": items,
    }
    if total is not None:
        payload["total_count"] = total
    if start is not None:
        payload["start"] = start
    return json_response(payload)


def make_item(
    appid: int = 10,
    creator: int | None = 100,
    time_recommended: int | None = 1_700_000_000,
    name: str = "Test Game",
    blurb: str = "blurb",
    link: str | None = None,
) -> dict[str, Any]:
    recommendation: dict[str, Any] = {
        "appid": appid,
        "clanid": 26214428,
        "link_url": link if link is not None else f"https://steamcommunity.com/id/user/recommended/{appid}",
        "link_text": "",
        "blurb": blurb,
        "time_recommended": time_recommended,
        "comment_count": 0,
        "upvote_count": 0,
        "accountid_creator": creator,
        "recommendation_state": 0,
        "received_compensation": 0,
        "received_for_free": 0,
    }
    return {"appid": appid, "app_name": name, "recommendation": recommendation}


class FakeTransport:
    """In-memory transport implementing the same request surface as HttpTransport."""

    def __init__(
        self,
        handler: Callable[..., Any] | None = None,
        responses: list[Any] | None = None,
    ) -> None:
        self.handler = handler
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        call = {
            "method": method,
            "url": url,
            "params": dict(params or {}),
            "data": dict(data or {}),
            "headers": dict(headers or {}),
            "timeout": timeout,
        }
        self.calls.append(call)
        if self.handler is not None:
            result = self.handler(len(self.calls) - 1, call)
        else:
            result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self) -> None:
        return None


def make_config(tmp_path: Path, **overrides: Any) -> Config:
    base = {
        "clan_id": "26214428",
        "name": "测试组",
        "url": "https://store.steampowered.com/curator/26214428-TEST/admin/ajaxgetrecommendations/",
        "source": "admin",
        "cookie": "sessionid=0123456789abcdef01234567; browserid=1",
        "sessionid": "0123456789abcdef01234567",
        "out": str(tmp_path / "out"),
        "count": 25,
        "delay": 0.0,
        "timeout": 1.0,
        "retries": 1,
        "max_pages": 100,
        "formats": ["json", "csv"],
        "fresh": False,
        "keep_raw": False,
        "log_level": "INFO",
    }
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def logger() -> logging.Logger:
    log = logging.getLogger(f"test.steam_curator_exporter.{id(object())}")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    for handler in list(log.handlers):
        log.removeHandler(handler)
    log.addHandler(logging.NullHandler())
    return log

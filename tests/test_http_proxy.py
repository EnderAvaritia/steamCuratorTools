from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

import steam_curator_exporter.http as http_module
from conftest import FakeResponse, html_response
from steam_curator_exporter.errors import AuthError, ConfigError, SteamError
from steam_curator_exporter.http import (
    HttpTransport,
    ProxyPool,
    collect_proxies,
    mask_proxy,
    normalize_proxy,
)


def test_normalize_proxy_variants() -> None:
    assert normalize_proxy("127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert normalize_proxy('"socks5://127.0.0.1:1080"') == "socks5://127.0.0.1:1080"
    assert normalize_proxy("  https://proxy.test:443  ") == "https://proxy.test:443"


def test_invalid_proxy_scheme_and_missing_host() -> None:
    with pytest.raises(ConfigError, match="无效代理地址"):
        normalize_proxy("ftp://127.0.0.1:21")
    with pytest.raises(ConfigError, match="无效代理地址"):
        normalize_proxy("http://")


def test_collect_proxies_dedupes_and_reads_file(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "# comment\n127.0.0.1:8080\n\nhttp://127.0.0.1:8080\nhttps://proxy.test:443 # inline\n",
        encoding="utf-8",
    )
    proxies = collect_proxies(
        ["http://127.0.0.1:8080,http://proxy.test:3128"],
        str(proxy_file),
    )
    assert proxies == [
        "http://127.0.0.1:8080",
        "http://proxy.test:3128",
        "https://proxy.test:443",
    ]


def test_socks_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import() -> Any:
        raise ImportError("no socks")

    monkeypatch.setattr(http_module, "_import_socks", fake_import)
    with pytest.raises(ConfigError, match='pip install "requests\\[socks\\]"'):
        collect_proxies(["socks5://127.0.0.1:1080"], None)


def test_mask_proxy_hides_credentials() -> None:
    assert mask_proxy("http://user:pass@127.0.0.1:8080") == "http://***@127.0.0.1:8080"
    assert mask_proxy("http://127.0.0.1:8080") == "http://127.0.0.1:8080"


def test_proxy_pool_rotation_order() -> None:
    pool = ProxyPool(["p1", "p2"])
    assert [pool.next(), pool.next(), pool.next()] == ["p1", "p2", "p1"]
    assert len(pool) == 2
    assert ProxyPool().next() is None


class RecordingSession:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.proxies: dict[str, str] = {}
        self.seen_proxies: list[dict[str, str]] = []
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.seen_proxies.append(dict(self.proxies))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self) -> None:
        return None


def test_proxy_rotates_per_attempt_and_is_applied_to_session(logger) -> None:
    session = RecordingSession([requests.ConnectionError("boom"), FakeResponse()])
    waits: list[float] = []
    transport = HttpTransport(
        session=session,
        proxies=["http://p1:1", "http://p2:2"],
        retries=2,
        logger=logger,
        sleep=waits.append,
        jitter=lambda low, high: 0.0,
    )
    response = transport.request("GET", "https://example.test/")
    assert response.status_code == 200
    assert session.calls == 2
    assert session.seen_proxies == [
        {"http": "http://p1:1", "https": "http://p1:1"},
        {"http": "http://p2:2", "https": "http://p2:2"},
    ]
    assert waits == [3.0]


def test_retry_on_server_error_then_success(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=500), FakeResponse()])
    waits: list[float] = []
    transport = HttpTransport(
        session=session,
        retries=3,
        logger=logger,
        sleep=waits.append,
        jitter=lambda low, high: 0.0,
    )
    assert transport.request("GET", "https://example.test/").status_code == 200
    assert session.calls == 2
    assert waits == [3.0]


def test_401_becomes_auth_error(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=401, reason="Unauthorized")])
    transport = HttpTransport(session=session, retries=3, logger=logger, sleep=lambda s: None)
    with pytest.raises(AuthError, match="Cookie/sessionid"):
        transport.request("GET", "https://example.test/")
    assert session.calls == 1


def test_non_retriable_404_is_steam_error(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=404, reason="Not Found")])
    transport = HttpTransport(session=session, retries=2, logger=logger, sleep=lambda s: None)
    with pytest.raises(SteamError, match="404"):
        transport.request("GET", "https://example.test/")


def test_exhausted_retries_fail(logger) -> None:
    session = RecordingSession([requests.ConnectionError("x"), requests.ConnectionError("y")])
    transport = HttpTransport(
        session=session,
        retries=2,
        logger=logger,
        sleep=lambda s: None,
        jitter=lambda low, high: 0.0,
    )
    with pytest.raises(SteamError, match="连续失败 2 次"):
        transport.request("GET", "https://example.test/")


def test_html_login_page_helper_is_usable() -> None:
    response = html_response("<html>login</html>")
    assert "html" in response.headers["content-type"]


def test_raise_for_status_false_returns_5xx_without_retry(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=500, text='{"success":42}')])
    transport = HttpTransport(session=session, retries=5, logger=logger, sleep=lambda s: None)
    response = transport.request(
        "POST", "https://example.test/", raise_for_status=False
    )
    assert response.status_code == 500
    assert session.calls == 1


def test_request_retries_override(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=500), FakeResponse(status_code=500)])
    transport = HttpTransport(
        session=session,
        retries=5,
        logger=logger,
        sleep=lambda s: None,
        jitter=lambda low, high: 0.0,
    )
    with pytest.raises(SteamError, match="连续失败 2 次"):
        transport.request("GET", "https://example.test/", retries=2)
    assert session.calls == 2

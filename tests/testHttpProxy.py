from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

import steamCuratorTools.http as httpModule
from conftest import FakeResponse, htmlResponse
from steamCuratorTools.errors import AuthError, ConfigError, SteamError
from steamCuratorTools.http import (
    HttpTransport,
    ProxyPool,
    collectProxies,
    maskProxy,
    normalizeProxy,
)


def testNormalizeProxyVariants() -> None:
    assert normalizeProxy("127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert normalizeProxy('"socks5://127.0.0.1:1080"') == "socks5://127.0.0.1:1080"
    assert normalizeProxy("  https://proxy.test:443  ") == "https://proxy.test:443"


def testInvalidProxySchemeAndMissingHost() -> None:
    with pytest.raises(ConfigError, match="无效代理地址"):
        normalizeProxy("ftp://127.0.0.1:21")
    with pytest.raises(ConfigError, match="无效代理地址"):
        normalizeProxy("http://")


def testCollectProxiesDedupesAndReadsFile(tmp_path: Path) -> None:
    proxyFile = tmp_path / "proxies.txt"
    proxyFile.write_text(
        "# comment\n127.0.0.1:8080\n\nhttp://127.0.0.1:8080\nhttps://proxy.test:443 # inline\n",
        encoding="utf-8",
    )
    proxies = collectProxies(
        ["http://127.0.0.1:8080,http://proxy.test:3128"],
        str(proxyFile),
    )
    assert proxies == [
        "http://127.0.0.1:8080",
        "http://proxy.test:3128",
        "https://proxy.test:443",
    ]


def testSocksMissingDependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def fakeImport() -> Any:
        raise ImportError("no socks")

    monkeypatch.setattr(httpModule, "_importSocks", fakeImport)
    with pytest.raises(ConfigError, match='pip install "requests\\[socks\\]"'):
        collectProxies(["socks5://127.0.0.1:1080"], None)


def testMaskProxyHidesCredentials() -> None:
    assert maskProxy("http://user:pass@127.0.0.1:8080") == "http://***@127.0.0.1:8080"
    assert maskProxy("http://127.0.0.1:8080") == "http://127.0.0.1:8080"


def testProxyPoolRotationOrder() -> None:
    pool = ProxyPool(["p1", "p2"])
    assert [pool.next(), pool.next(), pool.next()] == ["p1", "p2", "p1"]
    assert len(pool) == 2
    assert ProxyPool().next() is None


class RecordingSession:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.proxies: dict[str, str] = {}
        self.seenProxies: list[dict[str, str]] = []
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.seenProxies.append(dict(self.proxies))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self) -> None:
        return None


def testProxyRotatesPerAttemptAndIsAppliedToSession(logger) -> None:
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
    assert session.seenProxies == [
        {"http": "http://p1:1", "https": "http://p1:1"},
        {"http": "http://p2:2", "https": "http://p2:2"},
    ]
    assert waits == [3.0]


def testRetryOnServerErrorThenSuccess(logger) -> None:
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


def test401BecomesAuthError(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=401, reason="Unauthorized")])
    transport = HttpTransport(session=session, retries=3, logger=logger, sleep=lambda s: None)
    with pytest.raises(AuthError, match="Cookie/sessionid"):
        transport.request("GET", "https://example.test/")
    assert session.calls == 1


def testNonRetriable404IsSteamError(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=404, reason="Not Found")])
    transport = HttpTransport(session=session, retries=2, logger=logger, sleep=lambda s: None)
    with pytest.raises(SteamError, match="404"):
        transport.request("GET", "https://example.test/")


def testExhaustedRetriesFail(logger) -> None:
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


def testHtmlLoginPageHelperIsUsable() -> None:
    response = htmlResponse("<html>login</html>")
    assert "html" in response.headers["content-type"]


def testRaiseForStatusFalseReturns5xxWithoutRetry(logger) -> None:
    session = RecordingSession([FakeResponse(status_code=500, text='{"success":42}')])
    transport = HttpTransport(session=session, retries=5, logger=logger, sleep=lambda s: None)
    response = transport.request(
        "POST", "https://example.test/", raiseForStatus=False
    )
    assert response.status_code == 500
    assert session.calls == 1


def testRequestRetriesOverride(logger) -> None:
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

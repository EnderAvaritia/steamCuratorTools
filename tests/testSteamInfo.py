from __future__ import annotations

from typing import Any

import requests

from steamCuratorTools.emailHelper.steamInfo import SteamInfoExtractor


class FakeResponse:
    def __init__(self, payload: Any = None, text: str = "", status: int = 200) -> None:
        self.payload = payload
        self.text = text
        self.status_code = status

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.proxies: dict[str, str] = {}
        self.closed = False

    def get(self, url: str, timeout: float, **kwargs: Any) -> Any:
        self.calls.append((url, {"timeout": timeout, **kwargs}))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self) -> None:
        self.closed = True


def makeExtractor(session: FakeSession) -> SteamInfoExtractor:
    return SteamInfoExtractor(
        session=session,
        proxyProvider=lambda: {"https": "http://127.0.0.1:7890"},
    )


def testExtractAppidFromSupportedUrls() -> None:
    cases = {
        "https://store.steampowered.com/app/730/CounterStrike/": "730",
        "https://steamcommunity.com/id/me/recommended/2875610?tscn=1": "2875610",
        "https://help.steampowered.com/zh-cn/wizard/HelpWithGameTechnicalIssue?appid=123": "123",
    }
    for url, expected in cases.items():
        assert SteamInfoExtractor.extractAppidFromUrl(url) == expected
    assert SteamInfoExtractor.extractAppidFromUrl("https://example.com/") is None
    assert SteamInfoExtractor.extractAppidFromUrl(None) is None
    assert SteamInfoExtractor.extractAppidFromUrl("") is None


def testGetGameInfoJoinsPublishers() -> None:
    session = FakeSession(
        [
            FakeResponse(
                payload={
                    "730": {
                        "success": True,
                        "data": {
                            "name": "Counter-Strike 2",
                            "publishers": ["Valve", "Valve Corp"],
                        },
                    }
                }
            )
        ]
    )
    extractor = makeExtractor(session)
    info = extractor.getGameInfoFromAppid("730")
    assert info == {
        "game_name": "Counter-Strike 2",
        "publisher_name": "Valve, Valve Corp",
    }
    assert session.proxies == {"https": "http://127.0.0.1:7890"}
    assert "appdetails?appids=730" in session.calls[0][0]


def testGetGameInfoHandlesFailurePayloads() -> None:
    session = FakeSession(
        [
            FakeResponse(payload={"730": {"success": False}}),
            FakeResponse(payload={"730": {"success": True, "data": None}}),
        ]
    )
    extractor = makeExtractor(session)
    assert extractor.getGameInfoFromAppid("730") == {}
    assert extractor.getGameInfoFromAppid("730") == {}
    assert extractor.getGameInfoFromAppid("not-a-number") == {}


def testGetGameInfoHandlesNetworkErrors() -> None:
    session = FakeSession([requests.exceptions.Timeout("slow")])
    extractor = makeExtractor(session)
    assert extractor.getGameInfoFromAppid("730") == {}


def testGetEmailFromSteamHelpExtractsAddress() -> None:
    html = """
    <html><body>
      <div class="help_official_support_row">
        Contact support: <a href="mailto:support@example.com">support@example.com</a>
      </div>
    </body></html>
    """
    session = FakeSession([FakeResponse(text=html)])
    extractor = makeExtractor(session)
    assert extractor.getEmailFromSteamHelp("730") == "support@example.com"
    assert "HelpWithGameTechnicalIssue?appid=730" in session.calls[0][0]


def testGetEmailFromSteamHelpFallsBackToPageText() -> None:
    html = "<html><body>Email us at publisher@example.org for help.</body></html>"
    session = FakeSession([FakeResponse(text=html)])
    extractor = makeExtractor(session)
    assert extractor.getEmailFromSteamHelp("730") == "publisher@example.org"


def testGetEmailFromSteamHelpHandlesRateLimit() -> None:
    session = FakeSession([FakeResponse(status=429)])
    extractor = makeExtractor(session)
    assert extractor.getEmailFromSteamHelp("730") is None


def testCloseDelegatesToSession() -> None:
    session = FakeSession([])
    extractor = makeExtractor(session)
    extractor.close()
    assert session.closed
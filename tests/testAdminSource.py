from __future__ import annotations

import pytest

from conftest import FakeResponse, FakeTransport, adminResponse, htmlResponse, makeItem
from steamCuratorTools.errors import AuthError, SteamError
from steamCuratorTools.sources import AdminSource


def makeSource(transport: FakeTransport) -> AdminSource:
    return AdminSource(
        transport,
        sessionid="abc123",
        cookie="sessionid=abc123; browserid=1",
        clanId="26214428",
    )


def testAdminRequestShapeAndHeaders() -> None:
    item = makeItem(appid=99)
    transport = FakeTransport(handler=lambda index, call: adminResponse([item], 1, 0))
    page = makeSource(transport).fetchPage("https://example.test/admin/ajaxgetrecommendations/", 5, 25)

    assert page.serverStart == 0
    assert page.totalCount == 1
    assert len(page.recommendations) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["params"] == {"start": "5", "count": "25"}
    assert call["data"] == {"sessionid": "abc123", "start": "5", "count": "25"}
    headers = call["headers"]
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Origin"] == "https://store.steampowered.com"
    assert "reviews_manage" in headers["Referer"]
    assert headers["Cookie"] == "sessionid=abc123; browserid=1"


def testHtmlLoginPageRaisesAuthError() -> None:
    transport = FakeTransport(responses=[htmlResponse("<html>请登录</html>")])
    with pytest.raises(AuthError, match="不是 JSON"):
        makeSource(transport).fetchPage("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def testSuccessNotOneRaisesAuthError() -> None:
    transport = FakeTransport(
        responses=[
            FakeResponse(
                payload={"success": 0, "message": "denied"},
                text='{"success":0}',
            )
        ]
    )
    with pytest.raises(AuthError, match="success != 1"):
        makeSource(transport).fetchPage("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def testMissingRecommendationsRaisesSteamError() -> None:
    transport = FakeTransport(responses=[FakeResponse(payload={"success": 1, "total_count": 2})])
    with pytest.raises(SteamError, match="recommendations"):
        makeSource(transport).fetchPage("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def testInvalidJsonRaisesSteamError() -> None:
    transport = FakeTransport(
        responses=[FakeResponse(text="{broken", headers={"content-type": "application/json"})]
    )
    with pytest.raises(SteamError, match="JSON 解析失败"):
        makeSource(transport).fetchPage("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def testMissingTotalCountIsUnknown() -> None:
    transport = FakeTransport(
        responses=[
            FakeResponse(
                payload={"success": 1, "recommendations": [], "start": 0},
                text="{}",
            )
        ]
    )
    page = makeSource(transport).fetchPage("https://example.test/admin/ajaxgetrecommendations/", 0, 25)
    assert page.totalCount is None
    assert page.serverStart == 0


def testHarRefererOverrideIsUsed() -> None:
    transport = FakeTransport(responses=[adminResponse([], 0, 0)])
    source = AdminSource(
        transport,
        sessionid="abc123",
        cookie="sessionid=abc123",
        referer="https://store.steampowered.com/curator/1-x/admin/reviews_manage?x=1",
    )
    source.fetchPage("https://example.test/admin/ajaxgetrecommendations/", 0, 25)
    assert transport.calls[0]["headers"]["Referer"].endswith("?x=1")

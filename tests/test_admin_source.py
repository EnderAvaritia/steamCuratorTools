from __future__ import annotations

import pytest

from conftest import FakeResponse, FakeTransport, admin_response, html_response, make_item
from steam_curator_exporter.errors import AuthError, SteamError
from steam_curator_exporter.sources import AdminSource


def make_source(transport: FakeTransport) -> AdminSource:
    return AdminSource(
        transport,
        sessionid="abc123",
        cookie="sessionid=abc123; browserid=1",
        clan_id="26214428",
    )


def test_admin_request_shape_and_headers() -> None:
    item = make_item(appid=99)
    transport = FakeTransport(handler=lambda index, call: admin_response([item], 1, 0))
    page = make_source(transport).fetch_page("https://example.test/admin/ajaxgetrecommendations/", 5, 25)

    assert page.server_start == 0
    assert page.total_count == 1
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


def test_html_login_page_raises_auth_error() -> None:
    transport = FakeTransport(responses=[html_response("<html>请登录</html>")])
    with pytest.raises(AuthError, match="不是 JSON"):
        make_source(transport).fetch_page("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def test_success_not_one_raises_auth_error() -> None:
    transport = FakeTransport(
        responses=[
            FakeResponse(
                payload={"success": 0, "message": "denied"},
                text='{"success":0}',
            )
        ]
    )
    with pytest.raises(AuthError, match="success != 1"):
        make_source(transport).fetch_page("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def test_missing_recommendations_raises_steam_error() -> None:
    transport = FakeTransport(responses=[FakeResponse(payload={"success": 1, "total_count": 2})])
    with pytest.raises(SteamError, match="recommendations"):
        make_source(transport).fetch_page("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def test_invalid_json_raises_steam_error() -> None:
    transport = FakeTransport(
        responses=[FakeResponse(text="{broken", headers={"content-type": "application/json"})]
    )
    with pytest.raises(SteamError, match="JSON 解析失败"):
        make_source(transport).fetch_page("https://example.test/admin/ajaxgetrecommendations/", 0, 25)


def test_missing_total_count_is_unknown() -> None:
    transport = FakeTransport(
        responses=[
            FakeResponse(
                payload={"success": 1, "recommendations": [], "start": 0},
                text="{}",
            )
        ]
    )
    page = make_source(transport).fetch_page("https://example.test/admin/ajaxgetrecommendations/", 0, 25)
    assert page.total_count is None
    assert page.server_start == 0


def test_har_referer_override_is_used() -> None:
    transport = FakeTransport(responses=[admin_response([], 0, 0)])
    source = AdminSource(
        transport,
        sessionid="abc123",
        cookie="sessionid=abc123",
        referer="https://store.steampowered.com/curator/1-x/admin/reviews_manage?x=1",
    )
    source.fetch_page("https://example.test/admin/ajaxgetrecommendations/", 0, 25)
    assert transport.calls[0]["headers"]["Referer"].endswith("?x=1")

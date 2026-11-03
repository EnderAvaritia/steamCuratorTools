from __future__ import annotations

from conftest import FakeTransport, html_response
from steam_curator_exporter.sources import PublicSource

PUBLIC_HTML = """
<div class="curator_recommendations">
  <a href="/app/10" data-ds-appid="10"><div class="name">Game Ten</div></a>
  <a href="https://store.steampowered.com/app/20?snr=1" data-ds-appid="&quot;20&quot;">
    <span>Game Twenty</span>
  </a>
  <a href="/app/30" data-ds-appid="not-a-number">Broken</a>
</div>
"""


def test_public_parses_appids_and_best_effort_fields() -> None:
    transport = FakeTransport(responses=[html_response(PUBLIC_HTML)])
    source = PublicSource(transport, clan_id="26214428")
    page = source.fetch_page(
        "https://store.steampowered.com/curator/26214428-x/ajaxgetfilteredrecommendations/",
        0,
        25,
    )

    assert [item["appid"] for item in page.recommendations] == [10, 20]
    assert page.recommendations[0]["app_name"] == "Game Ten"
    assert page.recommendations[0]["recommendation"]["link_url"] == (
        "https://store.steampowered.com/app/10"
    )
    assert page.recommendations[1]["recommendation"]["link_url"].endswith("/app/20?snr=1")
    assert page.recommendations[0]["recommendation"]["time_recommended"] is None
    assert page.recommendations[0]["recommendation"]["accountid_creator"] is None
    assert page.recommendations[0]["recommendation"]["upvote_count"] == 0
    assert page.total_count == 0

    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["params"] == {
        "query": "",
        "start": "0",
        "count": "25",
        "dynamic_data": "",
        "tagids": "",
        "sort": "recent",
        "app_types": "",
        "curations": "",
        "reset": "false",
    }
    assert "Cookie" not in call["headers"]


def test_public_empty_page_has_no_recommendations() -> None:
    transport = FakeTransport(responses=[html_response("<div>nothing here</div>")])
    source = PublicSource(transport)
    page = source.fetch_page("https://example.test/ajaxgetfilteredrecommendations/", 0, 25)
    assert page.recommendations == []
    assert page.total_count == 0

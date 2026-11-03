from __future__ import annotations

from conftest import FakeTransport, htmlResponse
from steamCuratorTools.sources import PublicSource

publicHtml = """
<div class="curator_recommendations">
  <a href="/app/10" data-ds-appid="10"><div class="name">Game Ten</div></a>
  <a href="https://store.steampowered.com/app/20?snr=1" data-ds-appid="&quot;20&quot;">
    <span>Game Twenty</span>
  </a>
  <a href="/app/30" data-ds-appid="not-a-number">Broken</a>
</div>
"""


def testPublicParsesAppidsAndBestEffortFields() -> None:
    transport = FakeTransport(responses=[htmlResponse(publicHtml)])
    source = PublicSource(transport, clanId="26214428")
    page = source.fetchPage(
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
    assert page.totalCount == 0

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


def testPublicEmptyPageHasNoRecommendations() -> None:
    transport = FakeTransport(responses=[htmlResponse("<div>nothing here</div>")])
    source = PublicSource(transport)
    page = source.fetchPage("https://example.test/ajaxgetfilteredrecommendations/", 0, 25)
    assert page.recommendations == []
    assert page.totalCount == 0

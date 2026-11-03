from __future__ import annotations

import json
from pathlib import Path

from conftest import (
    FakeTransport,
    adminResponse,
    htmlResponse,
    makeConfig,
    makeItem,
)
from steamCuratorTools.config import Config
from steamCuratorTools.errors import AuthError
from steamCuratorTools.runner import Runner, printStatus
from steamCuratorTools.sources import AdminSource, PublicSource
from steamCuratorTools.storage import appendEntry, loadState, saveState

adminUrl = "https://store.steampowered.com/curator/26214428-TEST/admin/ajaxgetrecommendations/"
publicUrl = "https://store.steampowered.com/curator/26214428-TEST/ajaxgetfilteredrecommendations/"


def runAdmin(config: Config, logger, transport: FakeTransport) -> int:
    source = AdminSource(
        transport,
        sessionid=config.sessionid or "sid",
        cookie=config.cookie or "sessionid=sid",
        clanId=config.clanId,
    )
    return Runner(config, logger, transport, source).run()


def testAdminPaginationAdvancesWhenServerClampsPageSize(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        take = min(3, max(0, 7 - start))
        items = [
            makeItem(appid=100 + start + offset, creator=1, timeRecommended=1000 + start + offset)
            for offset in range(take)
        ]
        return adminResponse(items, 7, start)

    transport = FakeTransport(handler=handler)
    config = makeConfig(tmp_path, count=100)
    assert runAdmin(config, logger, transport) == 0

    assert [int(call["params"]["start"]) for call in transport.calls] == [0, 3, 6]
    assert all(call["params"]["count"] == "100" for call in transport.calls)
    state = loadState(Path(config.out))
    assert state["next_start"] == 7
    assert state["total_count"] == 7


def testIgnoredStartAbortsWithoutInfiniteLoop(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        items = [
            makeItem(appid=1, creator=1, timeRecommended=100),
            makeItem(appid=2, creator=1, timeRecommended=101),
        ]
        return adminResponse(items, 100, 0)

    transport = FakeTransport(handler=handler)
    config = makeConfig(tmp_path)
    assert runAdmin(config, logger, transport) == 1
    assert len(transport.calls) == 2
    assert loadState(Path(config.out))["next_start"] == 2


def testMaxPagesReportsIncomplete(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        items = [
            makeItem(appid=200 + start + offset, creator=1, timeRecommended=2000 + start)
            for offset in range(2)
        ]
        return adminResponse(items, 100, start)

    config = makeConfig(tmp_path, maxPages=2)
    assert runAdmin(config, logger, FakeTransport(handler=handler)) == 4


def testCompletedRunThenRerunMakesZeroRequests(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        items = [
            makeItem(appid=300 + start + offset, creator=1, timeRecommended=3000 + start)
            for offset in range(2)
        ]
        return adminResponse(items, 4, start)

    config = makeConfig(tmp_path)
    transport = FakeTransport(handler=handler)
    assert runAdmin(config, logger, transport) == 0
    assert len(transport.calls) == 2

    def forbidden(index: int, call: dict) -> object:
        raise AssertionError("resume should not make requests")

    second = FakeTransport(handler=forbidden)
    assert runAdmin(config, logger, second) == 0
    assert second.calls == []


def testFreshRefetchesAfterCompletion(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        return adminResponse(
            [makeItem(appid=400, creator=1, timeRecommended=4000)], 1, start
        )

    config = makeConfig(tmp_path)
    assert runAdmin(config, logger, FakeTransport(handler=handler)) == 0

    config.fresh = True
    transport = FakeTransport(handler=handler)
    assert runAdmin(config, logger, transport) == 0
    assert len(transport.calls) == 1


def testResumeContinuesFromStateNextStart(tmp_path: Path, logger) -> None:
    def firstHandler(index: int, call: dict) -> object:
        items = [
            makeItem(appid=500 + offset, creator=1, timeRecommended=5000 + offset)
            for offset in range(2)
        ]
        return adminResponse(items, 5, 0)

    config = makeConfig(tmp_path, maxPages=1)
    assert runAdmin(config, logger, FakeTransport(handler=firstHandler)) == 4
    state = loadState(Path(config.out))
    assert state["next_start"] == 2

    def secondHandler(index: int, call: dict) -> object:
        assert call["params"]["start"] == "2"
        items = [
            makeItem(appid=502 + offset, creator=1, timeRecommended=5002 + offset)
            for offset in range(3)
        ]
        return adminResponse(items, 5, 2)

    config.maxPages = 10
    transport = FakeTransport(handler=secondHandler)
    assert runAdmin(config, logger, transport) == 0
    assert [call["params"]["start"] for call in transport.calls] == ["2"]
    assert loadState(Path(config.out))["next_start"] == 5


def testSameAppidDifferentCreatorsExportedSeparately(tmp_path: Path, logger) -> None:
    first = makeItem(appid=600, creator=1, timeRecommended=6000, blurb="one")
    otherCreator = makeItem(appid=600, creator=2, timeRecommended=6000, blurb="two")
    duplicate = makeItem(appid=600, creator=1, timeRecommended=6000, blurb="one")

    transport = FakeTransport(
        handler=lambda index, call: adminResponse([first, otherCreator, duplicate], 3, 0)
    )
    config = makeConfig(tmp_path)
    assert runAdmin(config, logger, transport) == 0

    jsonlLines = (Path(config.out) / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonlLines) == 3

    payload = json.loads((Path(config.out) / "reviews.json").read_text(encoding="utf-8"))
    assert payload["fetched_count"] == 2
    assert len(payload["recommendations"]) == 2

    csvLines = (Path(config.out) / "reviews.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(csvLines) == 3


def testAdminEmptyPageWithKnownTotalIsIncomplete(tmp_path: Path, logger) -> None:
    transport = FakeTransport(responses=[adminResponse([], 100, 0)])
    config = makeConfig(tmp_path)
    assert runAdmin(config, logger, transport) == 4


def testAuthErrorOnFirstPageReturnsThree(tmp_path: Path, logger) -> None:
    transport = FakeTransport(responses=[htmlResponse("<html>login</html>")])
    config = makeConfig(tmp_path)
    assert runAdmin(config, logger, transport) == 3


def testAuthErrorMidRunExportsAndReturnsThree(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        if index == 0:
            return adminResponse(
                [makeItem(appid=700, creator=1, timeRecommended=7000)],
                10,
                0,
            )
        raise AuthError("cookie expired")

    config = makeConfig(tmp_path)
    assert runAdmin(config, logger, FakeTransport(handler=handler)) == 3
    assert (Path(config.out) / "reviews.json").exists()


def testUnexpectedErrorExportsBeforeFailing(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        if index == 0:
            return adminResponse(
                [makeItem(appid=800, creator=1, timeRecommended=8000)],
                10,
                0,
            )
        raise RuntimeError("boom")

    config = makeConfig(tmp_path)
    assert runAdmin(config, logger, FakeTransport(handler=handler)) == 1
    payload = json.loads((Path(config.out) / "reviews.json").read_text(encoding="utf-8"))
    assert payload["fetched_count"] == 1


def testKeepRawWritesPagePayload(tmp_path: Path, logger) -> None:
    transport = FakeTransport(
        handler=lambda index, call: adminResponse(
            [makeItem(appid=900, creator=1, timeRecommended=9000)], 1, 0
        )
    )
    config = makeConfig(tmp_path, keepRaw=True)
    assert runAdmin(config, logger, transport) == 0
    raw = Path(config.out) / "raw" / "page_000000.json"
    assert raw.exists()
    assert json.loads(raw.read_text(encoding="utf-8"))["success"] == 1


def testSqliteOnlyFormat(tmp_path: Path, logger) -> None:
    transport = FakeTransport(
        handler=lambda index, call: adminResponse(
            [makeItem(appid=901, creator=1, timeRecommended=9001)], 1, 0
        )
    )
    config = makeConfig(tmp_path, formats=["sqlite"])
    assert runAdmin(config, logger, transport) == 0
    out = Path(config.out)
    assert (out / "reviews.sqlite3").exists()
    assert not (out / "reviews.json").exists()
    assert not (out / "reviews.csv").exists()


def testPublicSourceStopsOnEmptyPage(tmp_path: Path, logger) -> None:
    pageOne = """
    <a href="/app/1" data-ds-appid="1">One</a>
    <a href="/app/2" data-ds-appid="2">Two</a>
    """

    def handler(index: int, call: dict) -> object:
        if call["params"]["start"] == "0":
            return htmlResponse(pageOne)
        return htmlResponse("<div>empty</div>")

    config = makeConfig(tmp_path, source="public", url=publicUrl, cookie=None)
    source = PublicSource(FakeTransport(), clanId=config.clanId)
    transport = FakeTransport(handler=handler)
    source.transport = transport
    assert Runner(config, logger, transport, source).run() == 0

    assert [call["params"]["start"] for call in transport.calls] == ["0", "2"]
    state = loadState(Path(config.out))
    assert state["next_start"] == 2
    assert state["total_count"] == 0
    payload = json.loads((Path(config.out) / "reviews.json").read_text(encoding="utf-8"))
    assert payload["fetched_count"] == 2
    assert state["complete"] is True

    def forbidden(index: int, call: dict) -> object:
        raise AssertionError("completed public run should not make requests")

    secondTransport = FakeTransport(handler=forbidden)
    secondSource = PublicSource(secondTransport, clanId=config.clanId)
    assert Runner(config, logger, secondTransport, secondSource).run() == 0
    assert secondTransport.calls == []


def testStatusWorksWithoutCookie(tmp_path: Path, capsys) -> None:
    out = tmp_path / "status_out"
    out.mkdir()
    appendEntry(out, makeItem(appid=1, creator=1, timeRecommended=10))
    appendEntry(out, makeItem(appid=2, creator=1, timeRecommended=11))
    saveState(
        out,
        {
            "next_start": 5,
            "total_count": 10,
            "url": adminUrl,
            "clan_id": "26214428",
            "source": "admin",
            "updated_at": "2026-01-01T00:00:00+08:00",
        },
    )

    assert printStatus(out) == 0
    printed = capsys.readouterr().out
    assert "唯一组评数：2" in printed
    assert "10" in printed
    assert "50.0%" in printed
    assert "next_start=5" in printed
    assert "未完成" in printed


def testStatusMissingDirectoryReturnsOne(tmp_path: Path, capsys) -> None:
    assert printStatus(tmp_path / "missing") == 1
    assert "输出目录不存在" in capsys.readouterr().out


def testStatusComplete(tmp_path: Path, capsys) -> None:
    out = tmp_path / "complete_out"
    out.mkdir()
    appendEntry(out, makeItem())
    saveState(out, {"next_start": 10, "total_count": 10})
    assert printStatus(out) == 0
    assert "已完成" in capsys.readouterr().out

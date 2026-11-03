from __future__ import annotations

from pathlib import Path

import pytest

import steamCuratorTools.deleter as deleter
from conftest import FakeResponse, FakeTransport, jsonResponse, makeConfig
from steamCuratorTools.deleter import (
    DeleteResult,
    appendLog,
    deleteOne,
    loadDone,
    parseAppidLine,
    runCheck,
    runDelete,
)
from steamCuratorTools.errors import AuthError

deleteUrl = (
    "https://store.steampowered.com/curator/26214428-TEST/admin/ajaxdeletereview/"
)


@pytest.mark.parametrize(
    ("line", "interactive", "expected"),
    [
        ("", True, ("blank", "")),
        ("   ", False, ("blank", "")),
        ("# note", True, ("comment", "")),
        ("3048420", True, ("appid", "3048420")),
        ("3048420", False, ("appid", "3048420")),
        ("https://store.steampowered.com/app/999/foo/", True, ("appid", "999")),
        ("https://steamcommunity.com/id/u/recommended/123/", True, ("appid", "123")),
        ("q", True, ("quit", "")),
        ("Q", True, ("quit", "")),
        ("quit", True, ("quit", "")),
        ("q", False, ("error", "无法识别的 appid: q")),
        ("1 2", True, ("error", "一行只能输入一个 appid")),
        ("abc", True, ("error", "无法识别的 appid: abc")),
        ("12345678901", True, ("error", "无法识别的 appid: 12345678901")),
    ],
)
def testParseAppidLine(
    line: str,
    interactive: bool,
    expected: tuple[str, str],
) -> None:
    assert parseAppidLine(line, interactive=interactive) == expected


def testLogRoundtripAndDoneFilter(tmp_path: Path) -> None:
    log = tmp_path / "deleted.log"
    assert loadDone(log) == set()
    appendLog(log, "111", "OK", '{"success":1}')
    appendLog(log, "222", "FAIL", "status=500")
    appendLog(log, "333", "DRY", "dry-run")
    assert loadDone(log) == {"111"}
    assert "111\tOK" in log.read_text(encoding="utf-8")


def testDeleteOneSuccess(logger) -> None:
    transport = FakeTransport(responses=[jsonResponse({"success": 1, "clanid": 1})])
    result = deleteOne(
        transport,
        url=deleteUrl,
        sessionid="deadbeef",
        cookie="sessionid=deadbeef",
        referer="https://store.steampowered.com/curator/1/admin/reviews_manage",
        appid="123",
        timeout=1.0,
        logger=logger,
    )
    assert result == DeleteResult("OK", '{"success":1,"clanid":1}', "200")
    (call,) = transport.calls
    assert call["data"] == {"appid": "123", "sessionid": "deadbeef"}
    assert call["raise_for_status"] is False
    assert call["retries"] == 1
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"


def testDeleteOneDoesNotRetryJsonError(logger) -> None:
    transport = FakeTransport(responses=[jsonResponse({"success": 42}, status=500)])
    result = deleteOne(
        transport,
        url=deleteUrl,
        sessionid="s",
        cookie="c",
        referer="r",
        appid="123",
        timeout=1.0,
        logger=logger,
    )
    assert result.status == "FAIL"
    assert result.httpStatus == "500"
    assert "'success':42" in result.detail.replace('"', "'")
    assert len(transport.calls) == 1


def testDeleteOneRetriesTransient5xx(logger, monkeypatch) -> None:
    monkeypatch.setattr(deleter.time, "sleep", lambda _seconds: None)
    transport = FakeTransport(
        responses=[
            FakeResponse(status_code=500, text="upstream error"),
            jsonResponse({"success": 1}),
        ]
    )
    result = deleteOne(
        transport,
        url=deleteUrl,
        sessionid="s",
        cookie="c",
        referer="r",
        appid="123",
        attempts=2,
        timeout=1.0,
        logger=logger,
    )
    assert result.status == "OK"
    assert len(transport.calls) == 2


def testDeleteOneAuthErrorPropagates(logger) -> None:
    transport = FakeTransport(handler=lambda index, call: AuthError("expired"))
    with pytest.raises(AuthError, match="expired"):
        deleteOne(
            transport,
            url=deleteUrl,
            sessionid="s",
            cookie="c",
            referer="r",
            appid="123",
            timeout=1.0,
            logger=logger,
        )


def testRunDeleteDryRunNeverCallsTransport(tmp_path: Path, capsys, logger) -> None:
    config = makeConfig(tmp_path)
    log = tmp_path / "deleted.log"
    code = runDelete(
        config,
        deleteUrl=deleteUrl,
        logPath=log,
        lines=["111", "# skip", "", "bad line", "222"],
        interactive=True,
        dryRun=True,
        force=False,
        logger=logger,
        transport=None,
    )
    printed = capsys.readouterr().out
    assert code == 1  # the invalid line counts as a failure
    assert "[DRY] 111" in printed
    assert "[DRY] 222" in printed
    assert "sessionid=<hidden>" in printed
    assert "预演 2" in printed
    assert log.read_text(encoding="utf-8").count("DRY") == 2


def testRunDeleteSkipsLoggedAppids(tmp_path: Path, capsys, logger) -> None:
    config = makeConfig(tmp_path)
    log = tmp_path / "deleted.log"
    appendLog(log, "111", "OK", "done")
    transport = FakeTransport(responses=[])
    code = runDelete(
        config,
        deleteUrl=deleteUrl,
        logPath=log,
        lines=["111"],
        interactive=False,
        dryRun=False,
        force=False,
        logger=logger,
        transport=transport,
    )
    assert code == 0
    assert "[SKIP] 111" in capsys.readouterr().out
    assert transport.calls == []


def testRunDeleteSuccessAndFailure(tmp_path: Path, capsys, logger) -> None:
    config = makeConfig(tmp_path)
    log = tmp_path / "deleted.log"
    transport = FakeTransport(
        responses=[
            jsonResponse({"success": 1, "clanid": 1}),
            jsonResponse({"success": 42}, status=500),
        ]
    )
    code = runDelete(
        config,
        deleteUrl=deleteUrl,
        logPath=log,
        lines=["111", "222"],
        interactive=False,
        dryRun=False,
        force=False,
        logger=logger,
        transport=transport,
    )
    printed = capsys.readouterr().out
    assert code == 1
    assert "[OK] 111" in printed
    assert "[FAIL] 222 status=500" in printed
    assert [call["data"]["appid"] for call in transport.calls] == ["111", "222"]
    assert loadDone(log) == {"111"}


def testRunDeleteForceIgnoresLog(tmp_path: Path, logger) -> None:
    config = makeConfig(tmp_path)
    log = tmp_path / "deleted.log"
    appendLog(log, "111", "OK", "done")
    transport = FakeTransport(responses=[jsonResponse({"success": 1})])
    code = runDelete(
        config,
        deleteUrl=deleteUrl,
        logPath=log,
        lines=["111"],
        interactive=False,
        dryRun=False,
        force=True,
        logger=logger,
        transport=transport,
    )
    assert code == 0
    assert len(transport.calls) == 1


def testRunCheckSuccess(tmp_path: Path, capsys, logger) -> None:
    config = makeConfig(tmp_path)
    transport = FakeTransport(
        responses=[jsonResponse({"success": 1, "recommendations": [{"appid": 1}]})]
    )
    code = runCheck(config, url=deleteUrl, logger=logger, transport=transport)
    assert code == 0
    assert "检查成功" in capsys.readouterr().out


def testRunCheckRejectsNonSuccessPayload(tmp_path: Path, logger) -> None:
    config = makeConfig(tmp_path)
    transport = FakeTransport(responses=[jsonResponse({"success": 0})])
    with pytest.raises(AuthError, match="success != 1"):
        runCheck(config, url=deleteUrl, logger=logger, transport=transport)
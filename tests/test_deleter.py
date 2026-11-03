from __future__ import annotations

from pathlib import Path

import pytest

import steam_curator_exporter.deleter as deleter
from conftest import FakeResponse, FakeTransport, json_response, make_config
from steam_curator_exporter.deleter import (
    DeleteResult,
    append_log,
    delete_one,
    load_done,
    parse_appid_line,
    run_check,
    run_delete,
)
from steam_curator_exporter.errors import AuthError

DELETE_URL = (
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
def test_parse_appid_line(
    line: str,
    interactive: bool,
    expected: tuple[str, str],
) -> None:
    assert parse_appid_line(line, interactive=interactive) == expected


def test_log_roundtrip_and_done_filter(tmp_path: Path) -> None:
    log = tmp_path / "deleted.log"
    assert load_done(log) == set()
    append_log(log, "111", "OK", '{"success":1}')
    append_log(log, "222", "FAIL", "status=500")
    append_log(log, "333", "DRY", "dry-run")
    assert load_done(log) == {"111"}
    assert "111\tOK" in log.read_text(encoding="utf-8")


def test_delete_one_success(logger) -> None:
    transport = FakeTransport(responses=[json_response({"success": 1, "clanid": 1})])
    result = delete_one(
        transport,
        url=DELETE_URL,
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


def test_delete_one_does_not_retry_json_error(logger) -> None:
    transport = FakeTransport(responses=[json_response({"success": 42}, status=500)])
    result = delete_one(
        transport,
        url=DELETE_URL,
        sessionid="s",
        cookie="c",
        referer="r",
        appid="123",
        timeout=1.0,
        logger=logger,
    )
    assert result.status == "FAIL"
    assert result.http_status == "500"
    assert "'success':42" in result.detail.replace('"', "'")
    assert len(transport.calls) == 1


def test_delete_one_retries_transient_5xx(logger, monkeypatch) -> None:
    monkeypatch.setattr(deleter.time, "sleep", lambda _seconds: None)
    transport = FakeTransport(
        responses=[
            FakeResponse(status_code=500, text="upstream error"),
            json_response({"success": 1}),
        ]
    )
    result = delete_one(
        transport,
        url=DELETE_URL,
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


def test_delete_one_auth_error_propagates(logger) -> None:
    transport = FakeTransport(handler=lambda index, call: AuthError("expired"))
    with pytest.raises(AuthError, match="expired"):
        delete_one(
            transport,
            url=DELETE_URL,
            sessionid="s",
            cookie="c",
            referer="r",
            appid="123",
            timeout=1.0,
            logger=logger,
        )


def test_run_delete_dry_run_never_calls_transport(tmp_path: Path, capsys, logger) -> None:
    config = make_config(tmp_path)
    log = tmp_path / "deleted.log"
    code = run_delete(
        config,
        delete_url=DELETE_URL,
        log_path=log,
        lines=["111", "# skip", "", "bad line", "222"],
        interactive=True,
        dry_run=True,
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


def test_run_delete_skips_logged_appids(tmp_path: Path, capsys, logger) -> None:
    config = make_config(tmp_path)
    log = tmp_path / "deleted.log"
    append_log(log, "111", "OK", "done")
    transport = FakeTransport(responses=[])
    code = run_delete(
        config,
        delete_url=DELETE_URL,
        log_path=log,
        lines=["111"],
        interactive=False,
        dry_run=False,
        force=False,
        logger=logger,
        transport=transport,
    )
    assert code == 0
    assert "[SKIP] 111" in capsys.readouterr().out
    assert transport.calls == []


def test_run_delete_success_and_failure(tmp_path: Path, capsys, logger) -> None:
    config = make_config(tmp_path)
    log = tmp_path / "deleted.log"
    transport = FakeTransport(
        responses=[
            json_response({"success": 1, "clanid": 1}),
            json_response({"success": 42}, status=500),
        ]
    )
    code = run_delete(
        config,
        delete_url=DELETE_URL,
        log_path=log,
        lines=["111", "222"],
        interactive=False,
        dry_run=False,
        force=False,
        logger=logger,
        transport=transport,
    )
    printed = capsys.readouterr().out
    assert code == 1
    assert "[OK] 111" in printed
    assert "[FAIL] 222 status=500" in printed
    assert [call["data"]["appid"] for call in transport.calls] == ["111", "222"]
    assert load_done(log) == {"111"}


def test_run_delete_force_ignores_log(tmp_path: Path, logger) -> None:
    config = make_config(tmp_path)
    log = tmp_path / "deleted.log"
    append_log(log, "111", "OK", "done")
    transport = FakeTransport(responses=[json_response({"success": 1})])
    code = run_delete(
        config,
        delete_url=DELETE_URL,
        log_path=log,
        lines=["111"],
        interactive=False,
        dry_run=False,
        force=True,
        logger=logger,
        transport=transport,
    )
    assert code == 0
    assert len(transport.calls) == 1


def test_run_check_success(tmp_path: Path, capsys, logger) -> None:
    config = make_config(tmp_path)
    transport = FakeTransport(
        responses=[json_response({"success": 1, "recommendations": [{"appid": 1}]})]
    )
    code = run_check(config, url=DELETE_URL, logger=logger, transport=transport)
    assert code == 0
    assert "检查成功" in capsys.readouterr().out


def test_run_check_rejects_non_success_payload(tmp_path: Path, logger) -> None:
    config = make_config(tmp_path)
    transport = FakeTransport(responses=[json_response({"success": 0})])
    with pytest.raises(AuthError, match="success != 1"):
        run_check(config, url=DELETE_URL, logger=logger, transport=transport)
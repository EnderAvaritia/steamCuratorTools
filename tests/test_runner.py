from __future__ import annotations

import json
from pathlib import Path

from conftest import (
    FakeTransport,
    admin_response,
    html_response,
    make_config,
    make_item,
)
from steam_curator_exporter.config import Config
from steam_curator_exporter.errors import AuthError
from steam_curator_exporter.runner import Runner, print_status
from steam_curator_exporter.sources import AdminSource, PublicSource
from steam_curator_exporter.storage import append_entry, load_state, save_state

ADMIN_URL = "https://store.steampowered.com/curator/26214428-TEST/admin/ajaxgetrecommendations/"
PUBLIC_URL = "https://store.steampowered.com/curator/26214428-TEST/ajaxgetfilteredrecommendations/"


def run_admin(config: Config, logger, transport: FakeTransport) -> int:
    source = AdminSource(
        transport,
        sessionid=config.sessionid or "sid",
        cookie=config.cookie or "sessionid=sid",
        clan_id=config.clan_id,
    )
    return Runner(config, logger, transport, source).run()


def test_admin_pagination_advances_when_server_clamps_page_size(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        take = min(3, max(0, 7 - start))
        items = [
            make_item(appid=100 + start + offset, creator=1, time_recommended=1000 + start + offset)
            for offset in range(take)
        ]
        return admin_response(items, 7, start)

    transport = FakeTransport(handler=handler)
    config = make_config(tmp_path, count=100)
    assert run_admin(config, logger, transport) == 0

    assert [int(call["params"]["start"]) for call in transport.calls] == [0, 3, 6]
    assert all(call["params"]["count"] == "100" for call in transport.calls)
    state = load_state(Path(config.out))
    assert state["next_start"] == 7
    assert state["total_count"] == 7


def test_ignored_start_aborts_without_infinite_loop(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        items = [
            make_item(appid=1, creator=1, time_recommended=100),
            make_item(appid=2, creator=1, time_recommended=101),
        ]
        return admin_response(items, 100, 0)

    transport = FakeTransport(handler=handler)
    config = make_config(tmp_path)
    assert run_admin(config, logger, transport) == 1
    assert len(transport.calls) == 2
    assert load_state(Path(config.out))["next_start"] == 2


def test_max_pages_reports_incomplete(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        items = [
            make_item(appid=200 + start + offset, creator=1, time_recommended=2000 + start)
            for offset in range(2)
        ]
        return admin_response(items, 100, start)

    config = make_config(tmp_path, max_pages=2)
    assert run_admin(config, logger, FakeTransport(handler=handler)) == 4


def test_completed_run_then_rerun_makes_zero_requests(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        items = [
            make_item(appid=300 + start + offset, creator=1, time_recommended=3000 + start)
            for offset in range(2)
        ]
        return admin_response(items, 4, start)

    config = make_config(tmp_path)
    transport = FakeTransport(handler=handler)
    assert run_admin(config, logger, transport) == 0
    assert len(transport.calls) == 2

    def forbidden(index: int, call: dict) -> object:
        raise AssertionError("resume should not make requests")

    second = FakeTransport(handler=forbidden)
    assert run_admin(config, logger, second) == 0
    assert second.calls == []


def test_fresh_refetches_after_completion(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        start = int(call["params"]["start"])
        return admin_response(
            [make_item(appid=400, creator=1, time_recommended=4000)], 1, start
        )

    config = make_config(tmp_path)
    assert run_admin(config, logger, FakeTransport(handler=handler)) == 0

    config.fresh = True
    transport = FakeTransport(handler=handler)
    assert run_admin(config, logger, transport) == 0
    assert len(transport.calls) == 1


def test_resume_continues_from_state_next_start(tmp_path: Path, logger) -> None:
    def first_handler(index: int, call: dict) -> object:
        items = [
            make_item(appid=500 + offset, creator=1, time_recommended=5000 + offset)
            for offset in range(2)
        ]
        return admin_response(items, 5, 0)

    config = make_config(tmp_path, max_pages=1)
    assert run_admin(config, logger, FakeTransport(handler=first_handler)) == 4
    state = load_state(Path(config.out))
    assert state["next_start"] == 2

    def second_handler(index: int, call: dict) -> object:
        assert call["params"]["start"] == "2"
        items = [
            make_item(appid=502 + offset, creator=1, time_recommended=5002 + offset)
            for offset in range(3)
        ]
        return admin_response(items, 5, 2)

    config.max_pages = 10
    transport = FakeTransport(handler=second_handler)
    assert run_admin(config, logger, transport) == 0
    assert [call["params"]["start"] for call in transport.calls] == ["2"]
    assert load_state(Path(config.out))["next_start"] == 5


def test_same_appid_different_creators_exported_separately(tmp_path: Path, logger) -> None:
    first = make_item(appid=600, creator=1, time_recommended=6000, blurb="one")
    other_creator = make_item(appid=600, creator=2, time_recommended=6000, blurb="two")
    duplicate = make_item(appid=600, creator=1, time_recommended=6000, blurb="one")

    transport = FakeTransport(
        handler=lambda index, call: admin_response([first, other_creator, duplicate], 3, 0)
    )
    config = make_config(tmp_path)
    assert run_admin(config, logger, transport) == 0

    jsonl_lines = (Path(config.out) / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) == 3

    payload = json.loads((Path(config.out) / "reviews.json").read_text(encoding="utf-8"))
    assert payload["fetched_count"] == 2
    assert len(payload["recommendations"]) == 2

    csv_lines = (Path(config.out) / "reviews.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(csv_lines) == 3


def test_admin_empty_page_with_known_total_is_incomplete(tmp_path: Path, logger) -> None:
    transport = FakeTransport(responses=[admin_response([], 100, 0)])
    config = make_config(tmp_path)
    assert run_admin(config, logger, transport) == 4


def test_auth_error_on_first_page_returns_three(tmp_path: Path, logger) -> None:
    transport = FakeTransport(responses=[html_response("<html>login</html>")])
    config = make_config(tmp_path)
    assert run_admin(config, logger, transport) == 3


def test_auth_error_mid_run_exports_and_returns_three(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        if index == 0:
            return admin_response(
                [make_item(appid=700, creator=1, time_recommended=7000)],
                10,
                0,
            )
        raise AuthError("cookie expired")

    config = make_config(tmp_path)
    assert run_admin(config, logger, FakeTransport(handler=handler)) == 3
    assert (Path(config.out) / "reviews.json").exists()


def test_unexpected_error_exports_before_failing(tmp_path: Path, logger) -> None:
    def handler(index: int, call: dict) -> object:
        if index == 0:
            return admin_response(
                [make_item(appid=800, creator=1, time_recommended=8000)],
                10,
                0,
            )
        raise RuntimeError("boom")

    config = make_config(tmp_path)
    assert run_admin(config, logger, FakeTransport(handler=handler)) == 1
    payload = json.loads((Path(config.out) / "reviews.json").read_text(encoding="utf-8"))
    assert payload["fetched_count"] == 1


def test_keep_raw_writes_page_payload(tmp_path: Path, logger) -> None:
    transport = FakeTransport(
        handler=lambda index, call: admin_response(
            [make_item(appid=900, creator=1, time_recommended=9000)], 1, 0
        )
    )
    config = make_config(tmp_path, keep_raw=True)
    assert run_admin(config, logger, transport) == 0
    raw = Path(config.out) / "raw" / "page_000000.json"
    assert raw.exists()
    assert json.loads(raw.read_text(encoding="utf-8"))["success"] == 1


def test_sqlite_only_format(tmp_path: Path, logger) -> None:
    transport = FakeTransport(
        handler=lambda index, call: admin_response(
            [make_item(appid=901, creator=1, time_recommended=9001)], 1, 0
        )
    )
    config = make_config(tmp_path, formats=["sqlite"])
    assert run_admin(config, logger, transport) == 0
    out = Path(config.out)
    assert (out / "reviews.sqlite3").exists()
    assert not (out / "reviews.json").exists()
    assert not (out / "reviews.csv").exists()


def test_public_source_stops_on_empty_page(tmp_path: Path, logger) -> None:
    page_one = """
    <a href="/app/1" data-ds-appid="1">One</a>
    <a href="/app/2" data-ds-appid="2">Two</a>
    """

    def handler(index: int, call: dict) -> object:
        if call["params"]["start"] == "0":
            return html_response(page_one)
        return html_response("<div>empty</div>")

    config = make_config(tmp_path, source="public", url=PUBLIC_URL, cookie=None)
    source = PublicSource(FakeTransport(), clan_id=config.clan_id)
    transport = FakeTransport(handler=handler)
    source.transport = transport
    assert Runner(config, logger, transport, source).run() == 0

    assert [call["params"]["start"] for call in transport.calls] == ["0", "2"]
    state = load_state(Path(config.out))
    assert state["next_start"] == 2
    assert state["total_count"] == 0
    payload = json.loads((Path(config.out) / "reviews.json").read_text(encoding="utf-8"))
    assert payload["fetched_count"] == 2
    assert state["complete"] is True

    def forbidden(index: int, call: dict) -> object:
        raise AssertionError("completed public run should not make requests")

    second_transport = FakeTransport(handler=forbidden)
    second_source = PublicSource(second_transport, clan_id=config.clan_id)
    assert Runner(config, logger, second_transport, second_source).run() == 0
    assert second_transport.calls == []


def test_status_works_without_cookie(tmp_path: Path, capsys) -> None:
    out = tmp_path / "status_out"
    out.mkdir()
    append_entry(out, make_item(appid=1, creator=1, time_recommended=10))
    append_entry(out, make_item(appid=2, creator=1, time_recommended=11))
    save_state(
        out,
        {
            "next_start": 5,
            "total_count": 10,
            "url": ADMIN_URL,
            "clan_id": "26214428",
            "source": "admin",
            "updated_at": "2026-01-01T00:00:00+08:00",
        },
    )

    assert print_status(out) == 0
    printed = capsys.readouterr().out
    assert "唯一组评数：2" in printed
    assert "10" in printed
    assert "50.0%" in printed
    assert "next_start=5" in printed
    assert "未完成" in printed


def test_status_missing_directory_returns_one(tmp_path: Path, capsys) -> None:
    assert print_status(tmp_path / "missing") == 1
    assert "输出目录不存在" in capsys.readouterr().out


def test_status_complete(tmp_path: Path, capsys) -> None:
    out = tmp_path / "complete_out"
    out.mkdir()
    append_entry(out, make_item())
    save_state(out, {"next_start": 10, "total_count": 10})
    assert print_status(out) == 0
    assert "已完成" in capsys.readouterr().out

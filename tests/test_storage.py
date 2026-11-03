from __future__ import annotations

import contextlib
import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import steam_curator_exporter.storage as storage
from conftest import make_item
from steam_curator_exporter.storage import (
    CSV_COLUMNS,
    append_entry,
    clean_outputs,
    export_csv,
    export_json,
    export_sqlite,
    load_existing_entries,
    load_state,
    save_state,
)


def test_jsonl_append_and_truncated_line_skip(tmp_path: Path) -> None:
    out = tmp_path / "out"
    append_entry(out, make_item(appid=1, creator=1, time_recommended=10))
    append_entry(out, make_item(appid=1, creator=1, time_recommended=10))
    with (out / "reviews.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"appid": 2, "recommendation": {')
    entries = load_existing_entries(out)
    assert list(entries) == ["1|1|10"]


def test_csv_columns_encoding_and_steamid(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    item = make_item(appid=55, creator=123, time_recommended=1_700_000_000, name="游戏")
    count, skipped = export_csv(out, [item])
    assert (count, skipped) == (1, 0)

    raw = (out / "reviews.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    assert tuple(reader.fieldnames or ()) == CSV_COLUMNS
    row = next(reader)
    assert row["appid"] == "55"
    assert row["creator_steamid64"] == str(76561197960265728 + 123)
    expected_local = datetime.fromtimestamp(
        1_700_000_000, tz=timezone(timedelta(hours=8))
    ).isoformat(timespec="seconds")
    assert row["time_recommended_local"] == expected_local
    assert row["app_name"] == "游戏"


def test_json_export_meta_and_dedupe(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    item = make_item(appid=9, creator=1, time_recommended=99)
    duplicate = make_item(appid=9, creator=1, time_recommended=99)
    count = export_json(out, [item, duplicate], {"clan_id": "1", "total_count": 9})
    assert count == 1

    payload = json.loads((out / "reviews.json").read_text(encoding="utf-8"))
    assert payload["clan_id"] == "1"
    assert payload["total_count"] == 9
    assert payload["fetched_count"] == 1
    assert len(payload["recommendations"]) == 1
    assert "exported_at" in payload


def test_sqlite_upsert_dedupes_and_updates(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    first = make_item(appid=77, creator=5, time_recommended=500, blurb="old")
    updated = make_item(appid=77, creator=5, time_recommended=500, blurb="new")

    assert export_sqlite(out, [first]) == 1
    assert export_sqlite(out, [updated]) == 1

    with contextlib.closing(sqlite3.connect(out / "reviews.sqlite3")) as connection:
        cursor = connection.execute("SELECT COUNT(*), blurb, fetched_at FROM reviews")
        count, blurb, fetched_at = cursor.fetchone()
    assert count == 1
    assert blurb == "new"
    assert fetched_at


def test_atomic_state_write_leaves_valid_json(tmp_path: Path) -> None:
    out = tmp_path / "out"
    save_state(out, {"next_start": 1, "total_count": 2})
    state_path = out / "state.json"
    assert not (out / "state.json.tmp").exists()
    first = json.loads(state_path.read_text(encoding="utf-8"))
    assert first["next_start"] == 1

    def fail_replace(src: Path, dst: Path) -> None:
        raise OSError("simulated crash")

    original = storage.os.replace
    storage.os.replace = fail_replace  # type: ignore[attr-defined]
    try:
        with pytest.raises(OSError):
            save_state(out, {"next_start": 2, "total_count": 2})
    finally:
        storage.os.replace = original  # type: ignore[attr-defined]

    second = json.loads(state_path.read_text(encoding="utf-8"))
    assert second["next_start"] == 1
    assert load_state(out)["next_start"] == 1


def test_clean_outputs_only_removes_managed_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "reviews.json").write_text("{}", encoding="utf-8")
    (out / "reviews.csv").write_text("x", encoding="utf-8")
    (out / "state.json").write_text("{}", encoding="utf-8")
    (out / "state.json.tmp").write_text("partial", encoding="utf-8")
    (out / "keep.txt").write_text("keep", encoding="utf-8")
    raw = out / "raw"
    raw.mkdir()
    (raw / "page_000000.json").write_text("{}", encoding="utf-8")
    (raw / "notes.txt").write_text("keep", encoding="utf-8")

    clean_outputs(out)

    assert not (out / "reviews.json").exists()
    assert not (out / "reviews.csv").exists()
    assert not (out / "state.json").exists()
    assert not (out / "state.json.tmp").exists()
    assert not (raw / "page_000000.json").exists()
    assert (out / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (raw / "notes.txt").read_text(encoding="utf-8") == "keep"

from __future__ import annotations

import contextlib
import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import steamCuratorTools.storage as storage
from conftest import makeItem
from steamCuratorTools.storage import (
    appendEntry,
    cleanOutputs,
    csvColumns,
    exportCsv,
    exportJson,
    exportSqlite,
    loadExistingEntries,
    loadState,
    saveState,
)


def testJsonlAppendAndTruncatedLineSkip(tmp_path: Path) -> None:
    out = tmp_path / "out"
    appendEntry(out, makeItem(appid=1, creator=1, timeRecommended=10))
    appendEntry(out, makeItem(appid=1, creator=1, timeRecommended=10))
    with (out / "reviews.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"appid": 2, "recommendation": {')
    entries = loadExistingEntries(out)
    assert list(entries) == ["1|1|10"]


def testCsvColumnsEncodingAndSteamid(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    item = makeItem(appid=55, creator=123, timeRecommended=1_700_000_000, name="游戏")
    count, skipped = exportCsv(out, [item])
    assert (count, skipped) == (1, 0)

    raw = (out / "reviews.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    assert tuple(reader.fieldnames or ()) == csvColumns
    row = next(reader)
    assert row["appid"] == "55"
    assert row["creator_steamid64"] == str(76561197960265728 + 123)
    expectedLocal = datetime.fromtimestamp(
        1_700_000_000, tz=timezone(timedelta(hours=8))
    ).isoformat(timespec="seconds")
    assert row["time_recommended_local"] == expectedLocal
    assert row["app_name"] == "游戏"


def testJsonExportMetaAndDedupe(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    item = makeItem(appid=9, creator=1, timeRecommended=99)
    duplicate = makeItem(appid=9, creator=1, timeRecommended=99)
    count = exportJson(out, [item, duplicate], {"clan_id": "1", "total_count": 9})
    assert count == 1

    payload = json.loads((out / "reviews.json").read_text(encoding="utf-8"))
    assert payload["clan_id"] == "1"
    assert payload["total_count"] == 9
    assert payload["fetched_count"] == 1
    assert len(payload["recommendations"]) == 1
    assert "exported_at" in payload


def testSqliteUpsertDedupesAndUpdates(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    first = makeItem(appid=77, creator=5, timeRecommended=500, blurb="old")
    updated = makeItem(appid=77, creator=5, timeRecommended=500, blurb="new")

    assert exportSqlite(out, [first]) == 1
    assert exportSqlite(out, [updated]) == 1

    with contextlib.closing(sqlite3.connect(out / "reviews.sqlite3")) as connection:
        cursor = connection.execute("SELECT COUNT(*), blurb, fetched_at FROM reviews")
        count, blurb, fetchedAt = cursor.fetchone()
    assert count == 1
    assert blurb == "new"
    assert fetchedAt


def testAtomicStateWriteLeavesValidJson(tmp_path: Path) -> None:
    out = tmp_path / "out"
    saveState(out, {"next_start": 1, "total_count": 2})
    statePath = out / "state.json"
    assert not (out / "state.json.tmp").exists()
    first = json.loads(statePath.read_text(encoding="utf-8"))
    assert first["next_start"] == 1

    def failReplace(src: Path, dst: Path) -> None:
        raise OSError("simulated crash")

    original = storage.os.replace
    storage.os.replace = failReplace  # type: ignore[attr-defined]
    try:
        with pytest.raises(OSError):
            saveState(out, {"next_start": 2, "total_count": 2})
    finally:
        storage.os.replace = original  # type: ignore[attr-defined]

    second = json.loads(statePath.read_text(encoding="utf-8"))
    assert second["next_start"] == 1
    assert loadState(out)["next_start"] == 1


def testCleanOutputsOnlyRemovesManagedFiles(tmp_path: Path) -> None:
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

    cleanOutputs(out)

    assert not (out / "reviews.json").exists()
    assert not (out / "reviews.csv").exists()
    assert not (out / "state.json").exists()
    assert not (out / "state.json.tmp").exists()
    assert not (raw / "page_000000.json").exists()
    assert (out / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (raw / "notes.txt").read_text(encoding="utf-8") == "keep"

"""Durable storage: JSONL append, atomic state/snapshots, and exporters."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Review, dedupeItems, entryKey, itemAppid, localIso

jsonlName = "reviews.jsonl"
jsonName = "reviews.json"
csvName = "reviews.csv"
sqliteName = "reviews.sqlite3"
stateName = "state.json"
rawDirName = "raw"

managedFiles = (jsonlName, jsonName, csvName, sqliteName, stateName)

csvColumns = (
    "appid",
    "app_name",
    "time_recommended",
    "time_recommended_local",
    "creator_account_id",
    "creator_steamid64",
    "upvote_count",
    "comment_count",
    "received_for_free",
    "received_compensation",
    "recommendation_state",
    "link_url",
    "link_text",
    "blurb",
)

sqliteColumns = ("review_key", *csvColumns, "fetched_at")


def _atomicWriteText(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding=encoding, newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def nowIso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def loadState(outDir: Path) -> dict[str, Any]:
    path = outDir / stateName
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def saveState(outDir: Path, state: Mapping[str, Any]) -> None:
    payload = dict(state)
    payload["updated_at"] = nowIso()
    _atomicWriteText(
        outDir / stateName,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def appendEntry(outDir: Path, item: Mapping[str, Any]) -> None:
    """Append one raw recommendation and fsync before dedupe."""
    outDir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(item, ensure_ascii=False) + "\n"
    with (outDir / jsonlName).open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def loadExistingEntries(outDir: Path) -> dict[str, Mapping[str, Any]]:
    """Read the JSONL, deduplicating by review identity.

    A truncated final line from a killed process is the only value we skip.
    """
    entries: dict[str, Mapping[str, Any]] = {}
    path = outDir / jsonlName
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if not isinstance(item, dict):
                continue
            if not itemAppid(item):
                continue
            entries.setdefault(entryKey(item), item)
    return entries


def countJsonlRows(outDir: Path) -> int:
    path = outDir / jsonlName
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def cleanOutputs(outDir: Path) -> None:
    """Remove only files managed by this tool."""
    for name in managedFiles:
        path = outDir / name
        if path.exists():
            path.unlink()
    for tmpFile in outDir.glob("*.tmp"):
        tmpFile.unlink()
    rawDir = outDir / rawDirName
    if rawDir.is_dir():
        for rawFile in rawDir.glob("page_*.json"):
            rawFile.unlink()


def saveRawPage(outDir: Path, pageStart: int, raw: Any) -> None:
    rawDir = outDir / rawDirName
    rawDir.mkdir(parents=True, exist_ok=True)
    if isinstance(raw, str):
        payload: Any = {"format": "html", "html": raw}
    else:
        payload = raw
    _atomicWriteText(
        rawDir / f"page_{pageStart:06d}.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def exportJson(
    outDir: Path,
    items: Iterable[Mapping[str, Any]],
    meta: Mapping[str, Any],
) -> int:
    unique = dedupeItems(items)
    payload = {
        **meta,
        "exported_at": nowIso(),
        "fetched_count": len(unique),
        "recommendations": unique,
    }
    _atomicWriteText(
        outDir / jsonName,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    return len(unique)


def exportCsv(outDir: Path, items: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    unique = dedupeItems(items)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(csvColumns))
    writer.writeheader()
    skipped = 0
    for item in unique:
        review = Review.fromPayload(item)
        if not review.appid:
            skipped += 1
        writer.writerow(review.asRow())
    _atomicWriteText(outDir / csvName, buffer.getvalue(), encoding="utf-8-sig")
    return len(unique), skipped


def _sqlValue(value: Any) -> Any:
    return None if value == "" else value


def exportSqlite(outDir: Path, items: Iterable[Mapping[str, Any]]) -> int:
    unique = dedupeItems(items)
    outDir.mkdir(parents=True, exist_ok=True)
    path = outDir / sqliteName
    fetchedAt = nowIso()
    placeholders = ", ".join("?" for _ in sqliteColumns)
    updates = ", ".join(
        f"{column} = excluded.{column}" for column in sqliteColumns if column != "review_key"
    )
    statement = (
        f"INSERT INTO reviews ({', '.join(sqliteColumns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(review_key) DO UPDATE SET {updates}"
    )
    rows = []
    for item in unique:
        review = Review.fromPayload(item)
        row = review.asRow()
        row["time_recommended_local"] = localIso(row["time_recommended"])
        values = tuple(_sqlValue(row[column]) for column in csvColumns)
        rows.append((entryKey(item), *values, fetchedAt))

    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                review_key TEXT PRIMARY KEY,
                appid TEXT,
                app_name TEXT,
                time_recommended INTEGER,
                time_recommended_local TEXT,
                creator_account_id TEXT,
                creator_steamid64 TEXT,
                upvote_count INTEGER,
                comment_count INTEGER,
                received_for_free INTEGER,
                received_compensation INTEGER,
                recommendation_state INTEGER,
                link_url TEXT,
                link_text TEXT,
                blurb TEXT,
                fetched_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(statement, rows)
        connection.commit()
    return len(unique)


def exportOutputs(
    outDir: Path,
    items: Iterable[Mapping[str, Any]],
    meta: Mapping[str, Any],
    formats: Iterable[str],
) -> dict[str, int]:
    """Write selected export formats; the input is deduplicated per format."""
    materialized = list(items)
    counts: dict[str, int] = {}
    for name in formats:
        if name == "json":
            counts["json"] = exportJson(outDir, materialized, meta)
        elif name == "csv":
            counts["csv"], skipped = exportCsv(outDir, materialized)
            if skipped:
                counts["csv_skipped"] = skipped
        elif name == "sqlite":
            counts["sqlite"] = exportSqlite(outDir, materialized)
    return counts

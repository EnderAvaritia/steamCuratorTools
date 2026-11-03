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

from .models import Review, dedupe_items, entry_key, item_appid, local_iso

JSONL_NAME = "reviews.jsonl"
JSON_NAME = "reviews.json"
CSV_NAME = "reviews.csv"
SQLITE_NAME = "reviews.sqlite3"
STATE_NAME = "state.json"
RAW_DIR_NAME = "raw"

MANAGED_FILES = (JSONL_NAME, JSON_NAME, CSV_NAME, SQLITE_NAME, STATE_NAME)

CSV_COLUMNS = (
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

SQLITE_COLUMNS = ("review_key", *CSV_COLUMNS, "fetched_at")


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state(out_dir: Path) -> dict[str, Any]:
    path = out_dir / STATE_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(out_dir: Path, state: Mapping[str, Any]) -> None:
    payload = dict(state)
    payload["updated_at"] = now_iso()
    _atomic_write_text(
        out_dir / STATE_NAME,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def append_entry(out_dir: Path, item: Mapping[str, Any]) -> None:
    """Append one raw recommendation and fsync before dedupe."""
    out_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(item, ensure_ascii=False) + "\n"
    with (out_dir / JSONL_NAME).open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def load_existing_entries(out_dir: Path) -> dict[str, Mapping[str, Any]]:
    """Read the JSONL, deduplicating by review identity.

    A truncated final line from a killed process is the only value we skip.
    """
    entries: dict[str, Mapping[str, Any]] = {}
    path = out_dir / JSONL_NAME
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
            if not item_appid(item):
                continue
            entries.setdefault(entry_key(item), item)
    return entries


def count_jsonl_rows(out_dir: Path) -> int:
    path = out_dir / JSONL_NAME
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def clean_outputs(out_dir: Path) -> None:
    """Remove only files managed by this tool."""
    for name in MANAGED_FILES:
        path = out_dir / name
        if path.exists():
            path.unlink()
    for tmp_file in out_dir.glob("*.tmp"):
        tmp_file.unlink()
    raw_dir = out_dir / RAW_DIR_NAME
    if raw_dir.is_dir():
        for raw_file in raw_dir.glob("page_*.json"):
            raw_file.unlink()


def save_raw_page(out_dir: Path, page_start: int, raw: Any) -> None:
    raw_dir = out_dir / RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(raw, str):
        payload: Any = {"format": "html", "html": raw}
    else:
        payload = raw
    _atomic_write_text(
        raw_dir / f"page_{page_start:06d}.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def export_json(
    out_dir: Path,
    items: Iterable[Mapping[str, Any]],
    meta: Mapping[str, Any],
) -> int:
    unique = dedupe_items(items)
    payload = {
        **meta,
        "exported_at": now_iso(),
        "fetched_count": len(unique),
        "recommendations": unique,
    }
    _atomic_write_text(
        out_dir / JSON_NAME,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    return len(unique)


def export_csv(out_dir: Path, items: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    unique = dedupe_items(items)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS))
    writer.writeheader()
    skipped = 0
    for item in unique:
        review = Review.from_payload(item)
        if not review.appid:
            skipped += 1
        writer.writerow(review.as_row())
    _atomic_write_text(out_dir / CSV_NAME, buffer.getvalue(), encoding="utf-8-sig")
    return len(unique), skipped


def _sql_value(value: Any) -> Any:
    return None if value == "" else value


def export_sqlite(out_dir: Path, items: Iterable[Mapping[str, Any]]) -> int:
    unique = dedupe_items(items)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SQLITE_NAME
    fetched_at = now_iso()
    placeholders = ", ".join("?" for _ in SQLITE_COLUMNS)
    updates = ", ".join(
        f"{column} = excluded.{column}" for column in SQLITE_COLUMNS if column != "review_key"
    )
    statement = (
        f"INSERT INTO reviews ({', '.join(SQLITE_COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(review_key) DO UPDATE SET {updates}"
    )
    rows = []
    for item in unique:
        review = Review.from_payload(item)
        row = review.as_row()
        row["time_recommended_local"] = local_iso(row["time_recommended"])
        values = tuple(_sql_value(row[column]) for column in CSV_COLUMNS)
        rows.append((entry_key(item), *values, fetched_at))

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


def export_outputs(
    out_dir: Path,
    items: Iterable[Mapping[str, Any]],
    meta: Mapping[str, Any],
    formats: Iterable[str],
) -> dict[str, int]:
    """Write selected export formats; the input is deduplicated per format."""
    materialized = list(items)
    counts: dict[str, int] = {}
    for name in formats:
        if name == "json":
            counts["json"] = export_json(out_dir, materialized, meta)
        elif name == "csv":
            counts["csv"], skipped = export_csv(out_dir, materialized)
            if skipped:
                counts["csv_skipped"] = skipped
        elif name == "sqlite":
            counts["sqlite"] = export_sqlite(out_dir, materialized)
    return counts

"""Publisher email CSV lookup and safe upsert."""

from __future__ import annotations

import contextlib
import csv
import io
import os
from pathlib import Path

from .settings import isValidEmail

defaultHeader = ["Publisher", "Email"]
_headerNames = {"publisher", "发行商", "发行商名"}


def ensurePublisherCsv(path: Path) -> None:
    """Create a header-only CSV when it does not exist yet."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerow(defaultHeader)


def readPublisherTable(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read header and data rows, tolerating a missing header/BOM."""
    if not path.exists():
        return list(defaultHeader), []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        raise
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        return list(defaultHeader), []

    first = rows[0]
    if first and first[0].strip().casefold() in _headerNames:
        header = first
        data = rows[1:]
    else:
        header = list(defaultHeader)
        data = rows
    return header, data


def _publisherTokens(cell: str) -> list[str]:
    return [token.strip() for token in cell.split(",") if token.strip()]


def matchPublisher(target: str, cell: str) -> tuple[int, int] | None:
    """Return ``(quality, length)`` for a CSV publisher cell.

    Exact matches beat substring matches; longer matches beat shorter ones.
    Empty cells never match, which prevents a blank CSV row from matching
    every publisher.
    """
    normalized = target.strip().casefold()
    if not normalized:
        return None

    best: tuple[int, int] | None = None
    for token in _publisherTokens(cell):
        candidate = token.casefold()
        if candidate == normalized:
            score = (2, len(candidate))
        elif candidate in normalized or normalized in candidate:
            score = (1, len(candidate))
        else:
            continue
        if best is None or score > best:
            best = score
    return best


def _rowMatch(target: str, row: list[str]) -> tuple[int, int] | None:
    if not row:
        return None
    return matchPublisher(target, row[0])


def _rowEmail(row: list[str]) -> str:
    return row[1].strip() if len(row) >= 2 else ""


def lookupPublisherEmail(publisherName: str, path: Path) -> str | None:
    """Find the best matching publisher email, or ``None``."""
    if not publisherName.strip():
        return None
    _, data = readPublisherTable(path)
    best: tuple[tuple[int, int], str] | None = None
    for row in data:
        score = _rowMatch(publisherName, row)
        email = _rowEmail(row)
        if score is None or not email:
            continue
        if best is None or score > best[0]:
            best = (score, email)
    return best[1] if best is not None else None


def upsertPublisherEmail(publisherName: str, email: str, path: Path) -> bool:
    """Insert or update one publisher row, preserving the rest of the file."""
    name = publisherName.strip()
    address = email.strip()
    if not name:
        raise ValueError("发行商名称不能为空。")
    if not isValidEmail(address):
        raise ValueError(f"邮箱格式不正确: {address!r}")

    header, data = readPublisherTable(path)
    updated = False
    for row in data:
        if _rowMatch(name, row) is None:
            continue
        while len(row) < len(header):
            row.append("")
        row[1] = address
        updated = True
        break

    if not updated:
        row = [name, address]
        if len(header) > 2:
            row.extend("" for _ in range(len(header) - 2))
        data.append(row)

    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    writer.writerows(data)

    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
            handle.write(buffer.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return True
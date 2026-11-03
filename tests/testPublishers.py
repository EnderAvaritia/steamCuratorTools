from __future__ import annotations

from pathlib import Path

import pytest

from steamCuratorTools.emailHelper.publishers import (
    ensurePublisherCsv,
    lookupPublisherEmail,
    matchPublisher,
    readPublisherTable,
    upsertPublisherEmail,
)


def writeCsv(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def testEnsureCreatesHeaderOnlyFile(tmp_path: Path) -> None:
    path = tmp_path / "publishers.csv"
    ensurePublisherCsv(path)
    assert path.read_text(encoding="utf-8-sig").strip() == "Publisher,Email"
    header, data = readPublisherTable(path)
    assert header == ["Publisher", "Email"]
    assert data == []


def testReadWithoutHeaderTreatsFirstRowAsData(tmp_path: Path) -> None:
    path = tmp_path / "publishers.csv"
    writeCsv(path, "Valve,contact@valve.example\n")
    header, data = readPublisherTable(path)
    assert header == ["Publisher", "Email"]
    assert data == [["Valve", "contact@valve.example"]]


def testMatchEmptyCellNeverMatches() -> None:
    assert matchPublisher("Valve", "") is None
    assert matchPublisher("", "Valve") is None
    assert matchPublisher("Valve", ",") is None
    assert matchPublisher("Valve", "Valve") == (2, 5)


def testLookupPrefersExactThenLongestSubstring(tmp_path: Path) -> None:
    path = tmp_path / "publishers.csv"
    writeCsv(
        path,
        'Publisher,Email\n'
        'Valve Corporation,corp@example.com\n'
        'Valve,exact@example.com\n'
        '"Studio A, Studio B",both@example.com\n',
    )
    assert lookupPublisherEmail("Valve", path) == "exact@example.com"
    assert lookupPublisherEmail("Valve Corporation", path) == "corp@example.com"
    assert lookupPublisherEmail("Studio B", path) == "both@example.com"
    assert lookupPublisherEmail("Unknown", path) is None
    assert lookupPublisherEmail("", path) is None


def testLookupIgnoresRowsWithEmptyEmail(tmp_path: Path) -> None:
    path = tmp_path / "publishers.csv"
    writeCsv(path, "Publisher,Email\nValve,\nValve,ok@example.com\n")
    assert lookupPublisherEmail("Valve", path) == "ok@example.com"


def testUpsertUpdatesExistingAndPreservesExtraColumns(tmp_path: Path) -> None:
    path = tmp_path / "publishers.csv"
    writeCsv(path, "Publisher,Email,Note\nValve,old@example.com,keep\n")
    assert upsertPublisherEmail("Valve", "new@example.com", path)
    header, data = readPublisherTable(path)
    assert header == ["Publisher", "Email", "Note"]
    assert data == [["Valve", "new@example.com", "keep"]]


def testUpsertAppendsNewRowAndWritesBom(tmp_path: Path) -> None:
    path = tmp_path / "publishers.csv"
    assert upsertPublisherEmail("New Studio", "press@example.com", path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    header, data = readPublisherTable(path)
    assert header == ["Publisher", "Email"]
    assert data == [["New Studio", "press@example.com"]]


def testUpsertRejectsInvalidInput(tmp_path: Path) -> None:
    path = tmp_path / "publishers.csv"
    with pytest.raises(ValueError):
        upsertPublisherEmail("", "a@example.com", path)
    with pytest.raises(ValueError):
        upsertPublisherEmail("Studio", "bad-email", path)


def testManagerRespectsCustomCsvPath(tmp_path: Path) -> None:
    from steamCuratorTools.emailHelper.manager import EmailManager

    manager = EmailManager(baseDir=tmp_path)
    custom = tmp_path / "custom.csv"
    assert manager.savePublisherEmail("Studio", "a@example.com", custom)
    assert manager.lookupPublisherEmail("Studio", custom) == "a@example.com"
    assert manager.lookupPublisherEmail("Studio") is None
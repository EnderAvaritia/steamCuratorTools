from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from conftest import make_item
from steam_curator_exporter.models import (
    Review,
    dedupe_items,
    entry_key,
    format_duration,
    local_iso,
    steamid64,
)


def test_same_appid_different_creator_are_distinct() -> None:
    first = make_item(appid=42, creator=100, time_recommended=1000)
    second = make_item(appid=42, creator=200, time_recommended=1000)
    assert entry_key(first) == "42|100|1000"
    assert entry_key(second) == "42|200|1000"
    assert entry_key(first) != entry_key(second)


def test_exact_duplicate_has_same_key() -> None:
    first = make_item(appid=42, creator=100, time_recommended=1000)
    second = make_item(appid=42, creator=100, time_recommended=1000)
    assert entry_key(first) == entry_key(second)


def test_missing_creator_and_time_use_content_fingerprint() -> None:
    item = make_item(
        appid=7,
        creator=None,
        time_recommended=None,
        blurb="hello",
        link="https://example.test/review",
    )
    expected = hashlib.sha1(b"https://example.test/review|hello").hexdigest()
    assert entry_key(item) == f"7|{expected}"


def test_dedupe_keeps_first_and_preserves_order() -> None:
    first = make_item(appid=1, creator=1, time_recommended=10, blurb="first")
    duplicate = make_item(appid=1, creator=1, time_recommended=10, blurb="second")
    other = make_item(appid=1, creator=2, time_recommended=10)
    unique = dedupe_items([first, duplicate, other])
    assert len(unique) == 2
    assert unique[0]["recommendation"]["blurb"] == "first"


def test_review_normalizes_unknown_fields() -> None:
    review = Review.from_payload({"appid": "12", "recommendation": {}})
    assert review.appid == "12"
    assert review.time_recommended is None
    assert review.creator_account_id == ""
    assert review.upvote_count is None
    assert review.as_row()["creator_steamid64"] == ""


def test_steamid64_math() -> None:
    assert steamid64(223504326) == str(76561197960265728 + 223504326)
    assert steamid64("123") == "76561197960265851"
    assert steamid64(None) == ""
    assert steamid64("not-a-number") == ""


def test_local_iso_uses_plus_eight() -> None:
    expected = datetime.fromtimestamp(
        1_700_000_000, tz=timezone(timedelta(hours=8))
    ).isoformat(timespec="seconds")
    assert local_iso(1_700_000_000) == expected
    assert local_iso(None) == ""


def test_format_duration() -> None:
    assert format_duration(5) == "5s"
    assert format_duration(65) == "1m05s"
    assert format_duration(3660) == "1h01m"

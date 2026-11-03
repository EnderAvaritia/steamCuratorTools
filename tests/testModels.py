from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from conftest import makeItem
from steamCuratorTools.models import (
    Review,
    dedupeItems,
    entryKey,
    formatDuration,
    localIso,
    steamid64,
)


def testSameAppidDifferentCreatorAreDistinct() -> None:
    first = makeItem(appid=42, creator=100, timeRecommended=1000)
    second = makeItem(appid=42, creator=200, timeRecommended=1000)
    assert entryKey(first) == "42|100|1000"
    assert entryKey(second) == "42|200|1000"
    assert entryKey(first) != entryKey(second)


def testExactDuplicateHasSameKey() -> None:
    first = makeItem(appid=42, creator=100, timeRecommended=1000)
    second = makeItem(appid=42, creator=100, timeRecommended=1000)
    assert entryKey(first) == entryKey(second)


def testMissingCreatorAndTimeUseContentFingerprint() -> None:
    item = makeItem(
        appid=7,
        creator=None,
        timeRecommended=None,
        blurb="hello",
        link="https://example.test/review",
    )
    expected = hashlib.sha1(b"https://example.test/review|hello").hexdigest()
    assert entryKey(item) == f"7|{expected}"


def testDedupeKeepsFirstAndPreservesOrder() -> None:
    first = makeItem(appid=1, creator=1, timeRecommended=10, blurb="first")
    duplicate = makeItem(appid=1, creator=1, timeRecommended=10, blurb="second")
    other = makeItem(appid=1, creator=2, timeRecommended=10)
    unique = dedupeItems([first, duplicate, other])
    assert len(unique) == 2
    assert unique[0]["recommendation"]["blurb"] == "first"


def testReviewNormalizesUnknownFields() -> None:
    review = Review.fromPayload({"appid": "12", "recommendation": {}})
    assert review.appid == "12"
    assert review.timeRecommended is None
    assert review.creatorAccountId == ""
    assert review.upvoteCount is None
    assert review.asRow()["creator_steamid64"] == ""


def testSteamid64Math() -> None:
    assert steamid64(223504326) == str(76561197960265728 + 223504326)
    assert steamid64("123") == "76561197960265851"
    assert steamid64(None) == ""
    assert steamid64("not-a-number") == ""


def testLocalIsoUsesPlusEight() -> None:
    expected = datetime.fromtimestamp(
        1_700_000_000, tz=timezone(timedelta(hours=8))
    ).isoformat(timespec="seconds")
    assert localIso(1_700_000_000) == expected
    assert localIso(None) == ""


def testFormatDuration() -> None:
    assert formatDuration(5) == "5s"
    assert formatDuration(65) == "1m05s"
    assert formatDuration(3660) == "1h01m"

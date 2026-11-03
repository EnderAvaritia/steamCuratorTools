"""Review normalization, stable identity keys, and time helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

steamid64Base = 76561197960265728
shanghaiFallback = timezone(timedelta(hours=8))


def _asText(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _asRawText(value: Any) -> str:
    """Preserve the server's text exactly (whitespace included)."""
    if value is None:
        return ""
    return str(value)


def _asInt(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recommendation(item: Mapping[str, Any]) -> Mapping[str, Any]:
    recommendation = item.get("recommendation")
    return recommendation if isinstance(recommendation, Mapping) else {}


def itemAppid(item: Mapping[str, Any]) -> str:
    """Return the appid from the row or its nested recommendation."""
    return _asText(item.get("appid") or _recommendation(item).get("appid"))


def entryKey(item: Mapping[str, Any]) -> str:
    """Stable identity for one curator recommendation.

    A game can be recommended by several curators of the same group, so the
    appid alone is not unique. The canonical key is
    ``appid|accountid_creator|time_recommended``. When either creator or time
    is missing we fall back to a content fingerprint.
    """
    recommendation = _recommendation(item)
    appid = itemAppid(item)
    creator = _asText(recommendation.get("accountid_creator"))
    recommendedAt = _asText(recommendation.get("time_recommended"))
    if creator or recommendedAt:
        return f"{appid}|{creator}|{recommendedAt}"
    fingerprint = hashlib.sha1(
        f"{recommendation.get('link_url', '')}|{recommendation.get('blurb', '')}".encode()
    ).hexdigest()
    return f"{appid}|{fingerprint}"


@dataclass(slots=True)
class Review:
    """Normalized view of one recommendation row."""

    appid: str
    appName: str
    timeRecommended: int | None
    creatorAccountId: str
    upvoteCount: int | None
    commentCount: int | None
    receivedForFree: int | None
    receivedCompensation: int | None
    recommendationState: int | None
    linkUrl: str
    linkText: str
    blurb: str

    @classmethod
    def fromPayload(cls, item: Mapping[str, Any]) -> Review:
        recommendation = _recommendation(item)
        return cls(
            appid=itemAppid(item),
            appName=_asRawText(item.get("app_name")),
            timeRecommended=_asInt(recommendation.get("time_recommended")),
            creatorAccountId=_asText(recommendation.get("accountid_creator")),
            upvoteCount=_asInt(recommendation.get("upvote_count")),
            commentCount=_asInt(recommendation.get("comment_count")),
            receivedForFree=_asInt(recommendation.get("received_for_free")),
            receivedCompensation=_asInt(recommendation.get("received_compensation")),
            recommendationState=_asInt(recommendation.get("recommendation_state")),
            linkUrl=_asRawText(recommendation.get("link_url")),
            linkText=_asRawText(recommendation.get("link_text")),
            blurb=_asRawText(recommendation.get("blurb")),
        )

    @property
    def steamid64(self) -> str:
        return steamid64(self.creatorAccountId)

    @property
    def timeRecommendedLocal(self) -> str:
        return localIso(self.timeRecommended)

    def asRow(self) -> dict[str, Any]:
        """CSV-friendly row using the exact documented column set."""
        return {
            "appid": self.appid,
            "app_name": self.appName,
            "time_recommended": self.timeRecommended if self.timeRecommended is not None else "",
            "time_recommended_local": self.timeRecommendedLocal,
            "creator_account_id": self.creatorAccountId,
            "creator_steamid64": self.steamid64,
            "upvote_count": self.upvoteCount if self.upvoteCount is not None else "",
            "comment_count": self.commentCount if self.commentCount is not None else "",
            "received_for_free": (
                self.receivedForFree if self.receivedForFree is not None else ""
            ),
            "received_compensation": (
                self.receivedCompensation if self.receivedCompensation is not None else ""
            ),
            "recommendation_state": (
                self.recommendationState if self.recommendationState is not None else ""
            ),
            "link_url": self.linkUrl,
            "link_text": self.linkText,
            "blurb": self.blurb,
        }


def steamid64(accountId: Any) -> str:
    """Convert a Steam account id to SteamID64, or return an empty string."""
    value = _asInt(accountId)
    if value is None:
        return ""
    return str(steamid64Base + value)


def localIso(timestamp: Any) -> str:
    """Render a Unix timestamp in Asia/Shanghai time, falling back to +08:00."""
    seconds = _asInt(timestamp)
    if seconds is None:
        return ""
    try:
        zone = ZoneInfo("Asia/Shanghai")
    except (ZoneInfoNotFoundError, ImportError, OSError):
        zone = shanghaiFallback
    try:
        return datetime.fromtimestamp(seconds, tz=zone).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def dedupeItems(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Keep the first item per identity key, preserving input order."""
    unique: dict[str, Mapping[str, Any]] = {}
    for item in items:
        unique.setdefault(entryKey(item), item)
    return list(unique.values())


def formatDuration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"

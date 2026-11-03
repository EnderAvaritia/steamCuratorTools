"""Review normalization, stable identity keys, and time helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STEAMID64_BASE = 76561197960265728
SHANGHAI_FALLBACK = timezone(timedelta(hours=8))


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_raw_text(value: Any) -> str:
    """Preserve the server's text exactly (whitespace included)."""
    if value is None:
        return ""
    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recommendation(item: Mapping[str, Any]) -> Mapping[str, Any]:
    recommendation = item.get("recommendation")
    return recommendation if isinstance(recommendation, Mapping) else {}


def item_appid(item: Mapping[str, Any]) -> str:
    """Return the appid from the row or its nested recommendation."""
    return _as_text(item.get("appid") or _recommendation(item).get("appid"))


def entry_key(item: Mapping[str, Any]) -> str:
    """Stable identity for one curator recommendation.

    A game can be recommended by several curators of the same group, so the
    appid alone is not unique. The canonical key is
    ``appid|accountid_creator|time_recommended``. When either creator or time
    is missing we fall back to a content fingerprint.
    """
    recommendation = _recommendation(item)
    appid = item_appid(item)
    creator = _as_text(recommendation.get("accountid_creator"))
    recommended_at = _as_text(recommendation.get("time_recommended"))
    if creator or recommended_at:
        return f"{appid}|{creator}|{recommended_at}"
    fingerprint = hashlib.sha1(
        f"{recommendation.get('link_url', '')}|{recommendation.get('blurb', '')}".encode()
    ).hexdigest()
    return f"{appid}|{fingerprint}"


@dataclass(slots=True)
class Review:
    """Normalized view of one recommendation row."""

    appid: str
    app_name: str
    time_recommended: int | None
    creator_account_id: str
    upvote_count: int | None
    comment_count: int | None
    received_for_free: int | None
    received_compensation: int | None
    recommendation_state: int | None
    link_url: str
    link_text: str
    blurb: str

    @classmethod
    def from_payload(cls, item: Mapping[str, Any]) -> Review:
        recommendation = _recommendation(item)
        return cls(
            appid=item_appid(item),
            app_name=_as_raw_text(item.get("app_name")),
            time_recommended=_as_int(recommendation.get("time_recommended")),
            creator_account_id=_as_text(recommendation.get("accountid_creator")),
            upvote_count=_as_int(recommendation.get("upvote_count")),
            comment_count=_as_int(recommendation.get("comment_count")),
            received_for_free=_as_int(recommendation.get("received_for_free")),
            received_compensation=_as_int(recommendation.get("received_compensation")),
            recommendation_state=_as_int(recommendation.get("recommendation_state")),
            link_url=_as_raw_text(recommendation.get("link_url")),
            link_text=_as_raw_text(recommendation.get("link_text")),
            blurb=_as_raw_text(recommendation.get("blurb")),
        )

    @property
    def steamid64(self) -> str:
        return steamid64(self.creator_account_id)

    @property
    def time_recommended_local(self) -> str:
        return local_iso(self.time_recommended)

    def as_row(self) -> dict[str, Any]:
        """CSV-friendly row using the exact documented column set."""
        return {
            "appid": self.appid,
            "app_name": self.app_name,
            "time_recommended": self.time_recommended if self.time_recommended is not None else "",
            "time_recommended_local": self.time_recommended_local,
            "creator_account_id": self.creator_account_id,
            "creator_steamid64": self.steamid64,
            "upvote_count": self.upvote_count if self.upvote_count is not None else "",
            "comment_count": self.comment_count if self.comment_count is not None else "",
            "received_for_free": (
                self.received_for_free if self.received_for_free is not None else ""
            ),
            "received_compensation": (
                self.received_compensation if self.received_compensation is not None else ""
            ),
            "recommendation_state": (
                self.recommendation_state if self.recommendation_state is not None else ""
            ),
            "link_url": self.link_url,
            "link_text": self.link_text,
            "blurb": self.blurb,
        }


def steamid64(account_id: Any) -> str:
    """Convert a Steam account id to SteamID64, or return an empty string."""
    value = _as_int(account_id)
    if value is None:
        return ""
    return str(STEAMID64_BASE + value)


def local_iso(timestamp: Any) -> str:
    """Render a Unix timestamp in Asia/Shanghai time, falling back to +08:00."""
    seconds = _as_int(timestamp)
    if seconds is None:
        return ""
    try:
        zone = ZoneInfo("Asia/Shanghai")
    except (ZoneInfoNotFoundError, ImportError, OSError):
        zone = SHANGHAI_FALLBACK
    try:
        return datetime.fromtimestamp(seconds, tz=zone).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def dedupe_items(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Keep the first item per identity key, preserving input order."""
    unique: dict[str, Mapping[str, Any]] = {}
    for item in items:
        unique.setdefault(entry_key(item), item)
    return list(unique.values())


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"

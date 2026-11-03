"""Steam curator URL construction helpers."""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

BASE_URL = "https://store.steampowered.com"

ADMIN_AJAX_SUFFIX = "/admin/ajaxgetrecommendations/"
ADMIN_REFERER_SUFFIX = "/admin/reviews_manage"
PUBLIC_AJAX_SUFFIX = "/ajaxgetfilteredrecommendations/"

SOURCE_ADMIN = "admin"
SOURCE_PUBLIC = "public"

SOURCE_SUFFIXES = {
    SOURCE_ADMIN: ADMIN_AJAX_SUFFIX,
    SOURCE_PUBLIC: PUBLIC_AJAX_SUFFIX,
}


def encode_curator_name(name: str) -> str:
    """Return the double-encoded slug Steam uses in curator URLs."""
    return quote(quote(name, safe=""), safe="")


def encode_curator_name_legacy(name: str) -> str:
    """Return the older ``^%^25`` escaped slug variant."""
    return quote(quote(name, safe="").replace("%", "^%^25"), safe="")


def build_url_candidates(
    clan_id: str | None,
    name: str,
    explicit_url: str | None,
    source: str = SOURCE_ADMIN,
) -> list[str]:
    """Build candidate endpoint URLs in decreasing likelihood order."""
    if explicit_url:
        return [explicit_url]

    suffix = SOURCE_SUFFIXES.get(source, ADMIN_AJAX_SUFFIX)
    candidates: list[str] = []
    if clan_id:
        if name:
            candidates.append(f"{BASE_URL}/curator/{clan_id}-{encode_curator_name(name)}{suffix}")
            candidates.append(
                f"{BASE_URL}/curator/{clan_id}-{encode_curator_name_legacy(name)}{suffix}"
            )
        candidates.append(f"{BASE_URL}/curator/{clan_id}{suffix}")

    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def build_referer(url: str, clan_id: str | None, source: str = SOURCE_ADMIN) -> str:
    """Build a plausible browser Referer header for a request URL."""
    suffix = SOURCE_SUFFIXES.get(source, ADMIN_AJAX_SUFFIX)
    if url.endswith(suffix):
        curator_url = url[: -len(suffix)]
        if source == SOURCE_PUBLIC:
            return curator_url
        return curator_url + ADMIN_REFERER_SUFFIX
    if url.endswith(suffix.rstrip("/")):
        curator_url = url[: -len(suffix.rstrip("/"))]
        if source == SOURCE_PUBLIC:
            return curator_url
        return curator_url + ADMIN_REFERER_SUFFIX
    if clan_id:
        base = f"{BASE_URL}/curator/{clan_id}"
        return base if source == SOURCE_PUBLIC else base + ADMIN_REFERER_SUFFIX
    return f"{BASE_URL}/"


def convert_endpoint_source(url: str, source: str) -> str:
    """Rewrite a known curator endpoint path suffix to the requested source."""
    target = SOURCE_SUFFIXES.get(source)
    if not target:
        return url
    parts = urlsplit(url)
    for suffix in SOURCE_SUFFIXES.values():
        if parts.path.endswith(suffix):
            path = parts.path[: -len(suffix)] + target
            return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
    return url


def extract_clan_id(url: str | None) -> str | None:
    match = re.search(r"/curator/(\d+)", url or "")
    return match.group(1) if match else None


def extract_sessionid(cookie: str) -> str | None:
    match = re.search(r"(?:^|;\s*)sessionid=([0-9a-fA-F]+)", cookie or "")
    return match.group(1) if match else None

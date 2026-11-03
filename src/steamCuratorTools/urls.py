"""Steam curator URL construction helpers."""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

baseUrl = "https://store.steampowered.com"

adminAjaxSuffix = "/admin/ajaxgetrecommendations/"
adminDeleteSuffix = "/admin/ajaxdeletereview/"
adminRefererSuffix = "/admin/reviews_manage"
publicAjaxSuffix = "/ajaxgetfilteredrecommendations/"

sourceAdmin = "admin"
sourcePublic = "public"

sourceSuffixes = {
    sourceAdmin: adminAjaxSuffix,
    sourcePublic: publicAjaxSuffix,
}

knownSuffixes = (adminAjaxSuffix, adminDeleteSuffix, publicAjaxSuffix)


def encodeCuratorName(name: str) -> str:
    """Return the double-encoded slug Steam uses in curator URLs."""
    return quote(quote(name, safe=""), safe="")


def encodeCuratorNameLegacy(name: str) -> str:
    """Return the older ``^%^25`` escaped slug variant."""
    return quote(quote(name, safe="").replace("%", "^%^25"), safe="")


def buildUrlCandidates(
    clanId: str | None,
    name: str,
    explicitUrl: str | None,
    source: str = sourceAdmin,
) -> list[str]:
    """Build candidate endpoint URLs in decreasing likelihood order."""
    if explicitUrl:
        return [explicitUrl]

    suffix = sourceSuffixes.get(source, adminAjaxSuffix)
    candidates: list[str] = []
    if clanId:
        if name:
            candidates.append(f"{baseUrl}/curator/{clanId}-{encodeCuratorName(name)}{suffix}")
            candidates.append(
                f"{baseUrl}/curator/{clanId}-{encodeCuratorNameLegacy(name)}{suffix}"
            )
        candidates.append(f"{baseUrl}/curator/{clanId}{suffix}")

    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _stripSuffix(url: str, suffix: str) -> str | None:
    """Return the URL prefix before a known endpoint suffix.

    The trailing slash is optional so HAR exports and hand-written URLs both work.
    """
    for candidate in (suffix, suffix.rstrip("/")):
        if candidate and url.endswith(candidate):
            return url[: -len(candidate)]
    return None


def swapEndpoint(url: str, targetSuffix: str) -> str | None:
    """Rewrite a known curator endpoint suffix, preserving the rest of the URL."""
    parts = urlsplit(url)
    for suffix in knownSuffixes:
        prefix = _stripSuffix(parts.path, suffix)
        if prefix is not None:
            path = prefix + targetSuffix
            return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
    return None


def buildDeleteUrl(clanId: str | None, url: str | None = None) -> str | None:
    """Build the admin delete endpoint from a HAR/API URL or a clan id."""
    if url:
        swapped = swapEndpoint(url, adminDeleteSuffix)
        if swapped:
            return swapped
    if clanId:
        return f"{baseUrl}/curator/{clanId}{adminDeleteSuffix}"
    return None


def buildRecommendationsUrl(clanId: str | None, url: str | None = None) -> str | None:
    """Build the admin recommendations endpoint from a HAR/API URL or a clan id."""
    if url:
        swapped = swapEndpoint(url, adminAjaxSuffix)
        if swapped:
            return swapped
    if clanId:
        return f"{baseUrl}/curator/{clanId}{adminAjaxSuffix}"
    return None


def buildReferer(url: str, clanId: str | None, source: str = sourceAdmin) -> str:
    """Build a plausible browser Referer header for a request URL."""
    suffix = sourceSuffixes.get(source, adminAjaxSuffix)
    for candidate in (suffix, adminDeleteSuffix):
        curatorUrl = _stripSuffix(url, candidate)
        if curatorUrl is not None:
            if source == sourcePublic and candidate == suffix:
                return curatorUrl
            return curatorUrl + adminRefererSuffix
    if clanId:
        base = f"{baseUrl}/curator/{clanId}"
        return base if source == sourcePublic else base + adminRefererSuffix
    return f"{baseUrl}/"


def convertEndpointSource(url: str, source: str) -> str:
    """Rewrite a known curator endpoint path suffix to the requested source."""
    target = sourceSuffixes.get(source)
    if not target:
        return url
    parts = urlsplit(url)
    for suffix in sourceSuffixes.values():
        if parts.path.endswith(suffix):
            path = parts.path[: -len(suffix)] + target
            return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
    return url


def extractClanId(url: str | None) -> str | None:
    match = re.search(r"/curator/(\d+)", url or "")
    return match.group(1) if match else None


def extractSessionid(cookie: str) -> str | None:
    match = re.search(r"(?:^|;\s*)sessionid=([0-9a-fA-F]+)", cookie or "")
    return match.group(1) if match else None

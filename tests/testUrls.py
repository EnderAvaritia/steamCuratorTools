from __future__ import annotations

from steamCuratorTools.urls import (
    adminAjaxSuffix,
    adminDeleteSuffix,
    adminRefererSuffix,
    buildDeleteUrl,
    buildRecommendationsUrl,
    buildReferer,
    buildUrlCandidates,
    convertEndpointSource,
    encodeCuratorName,
    encodeCuratorNameLegacy,
    extractClanId,
    extractSessionid,
    publicAjaxSuffix,
    swapEndpoint,
)


def testEncodeCuratorNameIsDoubleEncoded() -> None:
    encoded = encodeCuratorName("测试组")
    assert encoded.startswith("%25")
    assert "%E6" not in encoded
    assert encodeCuratorName("abc") == "abc"


def testLegacyEncodingUsesCaretForm() -> None:
    # The outer quote() escapes the inserted carets, matching the reference script.
    legacy = encodeCuratorNameLegacy("测试组")
    assert legacy.startswith("%5E%25%5E25")
    assert legacy != encodeCuratorName("测试组")


def testCandidatesAdminOrderAndSuffix() -> None:
    candidates = buildUrlCandidates("123", "测试组", None, "admin")
    assert len(candidates) == 3
    assert candidates[0].endswith(adminAjaxSuffix)
    assert "-%25" in candidates[0]
    assert "%5E%25%5E25" in candidates[1]
    assert candidates[2].endswith("/curator/123" + adminAjaxSuffix)


def testCandidatesPublicSuffix() -> None:
    candidates = buildUrlCandidates("123", "", None, "public")
    assert candidates == [
        "https://store.steampowered.com/curator/123" + publicAjaxSuffix
    ]


def testExplicitUrlWins() -> None:
    assert buildUrlCandidates("123", "x", "https://example.test/endpoint", "admin") == [
        "https://example.test/endpoint"
    ]


def testReferers() -> None:
    adminUrl = "https://store.steampowered.com/curator/1-x" + adminAjaxSuffix
    assert buildReferer(adminUrl, "1", "admin").endswith(adminRefererSuffix)
    publicUrl = "https://store.steampowered.com/curator/1-x" + publicAjaxSuffix
    assert buildReferer(publicUrl, "1", "public") == (
        "https://store.steampowered.com/curator/1-x"
    )


def testConvertEndpointSource() -> None:
    admin = "https://store.steampowered.com/curator/1-x" + adminAjaxSuffix
    public = convertEndpointSource(admin, "public")
    assert public.endswith(publicAjaxSuffix)
    assert convertEndpointSource(public, "admin").endswith(adminAjaxSuffix)


def testExtractIds() -> None:
    assert extractClanId("https://store.steampowered.com/curator/26214428-x/") == "26214428"
    assert extractClanId("https://example.test/") is None
    assert extractSessionid("a=1; sessionid=deadbeef; b=2") == "deadbeef"
    assert extractSessionid("a=1") is None


def testBuildDeleteUrlVariants() -> None:
    admin = "https://store.steampowered.com/curator/1-x" + adminAjaxSuffix
    delete = "https://store.steampowered.com/curator/1-x" + adminDeleteSuffix
    assert buildDeleteUrl("1", admin) == delete
    assert buildDeleteUrl("1") == (
        "https://store.steampowered.com/curator/1" + adminDeleteSuffix
    )
    assert buildDeleteUrl(None, delete) == delete
    assert buildDeleteUrl(None, "https://example.test/endpoint") is None


def testBuildRecommendationsUrlFromDelete() -> None:
    delete = "https://store.steampowered.com/curator/1-x" + adminDeleteSuffix
    assert buildRecommendationsUrl("1", delete).endswith(adminAjaxSuffix)
    assert buildRecommendationsUrl("1").endswith(adminAjaxSuffix)


def testSwapEndpointPreservesQueryAndToleratesNoSlash() -> None:
    url = "https://store.steampowered.com/curator/1-x/admin/ajaxgetrecommendations?a=1"
    swapped = swapEndpoint(url, adminDeleteSuffix)
    assert swapped == (
        "https://store.steampowered.com/curator/1-x/admin/ajaxdeletereview/?a=1"
    )


def testRefererForDeleteEndpoint() -> None:
    delete = "https://store.steampowered.com/curator/1-x" + adminDeleteSuffix
    assert buildReferer(delete, "1").endswith(adminRefererSuffix)

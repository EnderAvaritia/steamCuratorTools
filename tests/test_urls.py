from __future__ import annotations

from steam_curator_exporter.urls import (
    ADMIN_AJAX_SUFFIX,
    ADMIN_DELETE_SUFFIX,
    ADMIN_REFERER_SUFFIX,
    PUBLIC_AJAX_SUFFIX,
    build_delete_url,
    build_recommendations_url,
    build_referer,
    build_url_candidates,
    convert_endpoint_source,
    encode_curator_name,
    encode_curator_name_legacy,
    extract_clan_id,
    extract_sessionid,
    swap_endpoint,
)


def test_encode_curator_name_is_double_encoded() -> None:
    encoded = encode_curator_name("测试组")
    assert encoded.startswith("%25")
    assert "%E6" not in encoded
    assert encode_curator_name("abc") == "abc"


def test_legacy_encoding_uses_caret_form() -> None:
    # The outer quote() escapes the inserted carets, matching the reference script.
    legacy = encode_curator_name_legacy("测试组")
    assert legacy.startswith("%5E%25%5E25")
    assert legacy != encode_curator_name("测试组")


def test_candidates_admin_order_and_suffix() -> None:
    candidates = build_url_candidates("123", "测试组", None, "admin")
    assert len(candidates) == 3
    assert candidates[0].endswith(ADMIN_AJAX_SUFFIX)
    assert "-%25" in candidates[0]
    assert "%5E%25%5E25" in candidates[1]
    assert candidates[2].endswith("/curator/123" + ADMIN_AJAX_SUFFIX)


def test_candidates_public_suffix() -> None:
    candidates = build_url_candidates("123", "", None, "public")
    assert candidates == [
        "https://store.steampowered.com/curator/123" + PUBLIC_AJAX_SUFFIX
    ]


def test_explicit_url_wins() -> None:
    assert build_url_candidates("123", "x", "https://example.test/endpoint", "admin") == [
        "https://example.test/endpoint"
    ]


def test_referers() -> None:
    admin_url = "https://store.steampowered.com/curator/1-x" + ADMIN_AJAX_SUFFIX
    assert build_referer(admin_url, "1", "admin").endswith(ADMIN_REFERER_SUFFIX)
    public_url = "https://store.steampowered.com/curator/1-x" + PUBLIC_AJAX_SUFFIX
    assert build_referer(public_url, "1", "public") == (
        "https://store.steampowered.com/curator/1-x"
    )


def test_convert_endpoint_source() -> None:
    admin = "https://store.steampowered.com/curator/1-x" + ADMIN_AJAX_SUFFIX
    public = convert_endpoint_source(admin, "public")
    assert public.endswith(PUBLIC_AJAX_SUFFIX)
    assert convert_endpoint_source(public, "admin").endswith(ADMIN_AJAX_SUFFIX)


def test_extract_ids() -> None:
    assert extract_clan_id("https://store.steampowered.com/curator/26214428-x/") == "26214428"
    assert extract_clan_id("https://example.test/") is None
    assert extract_sessionid("a=1; sessionid=deadbeef; b=2") == "deadbeef"
    assert extract_sessionid("a=1") is None


def test_build_delete_url_variants() -> None:
    admin = "https://store.steampowered.com/curator/1-x" + ADMIN_AJAX_SUFFIX
    delete = "https://store.steampowered.com/curator/1-x" + ADMIN_DELETE_SUFFIX
    assert build_delete_url("1", admin) == delete
    assert build_delete_url("1") == (
        "https://store.steampowered.com/curator/1" + ADMIN_DELETE_SUFFIX
    )
    assert build_delete_url(None, delete) == delete
    assert build_delete_url(None, "https://example.test/endpoint") is None


def test_build_recommendations_url_from_delete() -> None:
    delete = "https://store.steampowered.com/curator/1-x" + ADMIN_DELETE_SUFFIX
    assert build_recommendations_url("1", delete).endswith(ADMIN_AJAX_SUFFIX)
    assert build_recommendations_url("1").endswith(ADMIN_AJAX_SUFFIX)


def test_swap_endpoint_preserves_query_and_tolerates_no_slash() -> None:
    url = "https://store.steampowered.com/curator/1-x/admin/ajaxgetrecommendations?a=1"
    swapped = swap_endpoint(url, ADMIN_DELETE_SUFFIX)
    assert swapped == (
        "https://store.steampowered.com/curator/1-x/admin/ajaxdeletereview/?a=1"
    )


def test_referer_for_delete_endpoint() -> None:
    delete = "https://store.steampowered.com/curator/1-x" + ADMIN_DELETE_SUFFIX
    assert build_referer(delete, "1").endswith(ADMIN_REFERER_SUFFIX)

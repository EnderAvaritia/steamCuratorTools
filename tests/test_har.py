from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import ADMIN_HAR, PUBLIC_HAR
from steam_curator_exporter.errors import ConfigError
from steam_curator_exporter.har import ENDPOINT_DELETE, load_har


def test_admin_entry_preferred_and_sessionid_from_post_data() -> None:
    info = load_har(ADMIN_HAR)
    assert info.url is not None
    assert "/admin/ajaxgetrecommendations/" in info.url
    assert info.sessionid == "bbbbbbbbbbbbbbbbbbbbbbbb"
    assert "steamLoginSecure=FAKE" in (info.cookie or "")
    assert (info.referer or "").endswith("/admin/reviews_manage")


def test_public_entry_and_sessionid_from_cookie() -> None:
    info = load_har(PUBLIC_HAR, "public")
    assert info.url is not None
    assert "ajaxgetfilteredrecommendations" in info.url
    assert info.sessionid == "cccccccccccccccccccccccc"


def test_sessionid_from_urlencoded_text(tmp_path: Path) -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://store.steampowered.com/curator/1-x/admin/ajaxgetrecommendations/",
                        "headers": [{"name": "Cookie", "value": "sessionid=aaaa"}],
                        "postData": {
                            "mimeType": "application/x-www-form-urlencoded",
                            "text": "start=0&sessionid=feedface",
                        },
                    }
                }
            ]
        }
    }
    path = tmp_path / "text.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    assert load_har(path).sessionid == "feedface"


def test_gzip_flagged_entry_is_tolerated(tmp_path: Path) -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://store.steampowered.com/curator/1-x/admin/ajaxgetrecommendations/",
                        "headers": [{"name": "Cookie", "value": "sessionid=abcd"}],
                    },
                    "response": {"content": {"compression": 1000}},
                }
            ]
        }
    }
    path = tmp_path / "gzip.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    assert load_har(path).sessionid == "abcd"


def test_missing_endpoint_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.har"
    path.write_text(json.dumps({"log": {"entries": []}}), encoding="utf-8")
    with pytest.raises(ConfigError, match="HAR"):
        load_har(path)


def test_invalid_json_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.har"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="读取 HAR 失败"):
        load_har(path)


def _write_delete_har(tmp_path: Path) -> Path:
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://store.steampowered.com/curator/1-x"
                        "/admin/ajaxdeletereview/",
                        "headers": [
                            {"name": "Cookie", "value": "sessionid=abcd; steamLoginSecure=X"},
                            {"name": "Referer", "value": "https://store.steampowered.com/r"},
                        ],
                        "postData": {
                            "mimeType": "application/x-www-form-urlencoded",
                            "text": "appid=1&sessionid=abcd",
                        },
                    }
                }
            ]
        }
    }
    path = tmp_path / "delete.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    return path


def test_delete_har_is_usable_for_delete_endpoint(tmp_path: Path) -> None:
    info = load_har(_write_delete_har(tmp_path), endpoint=ENDPOINT_DELETE)
    assert info.url is not None
    assert "/admin/ajaxdeletereview/" in info.url
    assert info.sessionid == "abcd"
    assert info.cookie is not None
    assert info.referer == "https://store.steampowered.com/r"


def test_delete_only_har_falls_back_for_credentials(tmp_path: Path) -> None:
    info = load_har(_write_delete_har(tmp_path))
    assert "/admin/ajaxdeletereview/" in (info.url or "")
    assert info.sessionid == "abcd"

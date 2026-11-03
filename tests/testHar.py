from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import adminHar, publicHar
from steamCuratorTools.errors import ConfigError
from steamCuratorTools.har import endpointDelete, loadHar


def testAdminEntryPreferredAndSessionidFromPostData() -> None:
    info = loadHar(adminHar)
    assert info.url is not None
    assert "/admin/ajaxgetrecommendations/" in info.url
    assert info.sessionid == "bbbbbbbbbbbbbbbbbbbbbbbb"
    assert "steamLoginSecure=FAKE" in (info.cookie or "")
    assert (info.referer or "").endswith("/admin/reviews_manage")


def testPublicEntryAndSessionidFromCookie() -> None:
    info = loadHar(publicHar, "public")
    assert info.url is not None
    assert "ajaxgetfilteredrecommendations" in info.url
    assert info.sessionid == "cccccccccccccccccccccccc"


def testSessionidFromUrlencodedText(tmp_path: Path) -> None:
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
    assert loadHar(path).sessionid == "feedface"


def testGzipFlaggedEntryIsTolerated(tmp_path: Path) -> None:
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
    assert loadHar(path).sessionid == "abcd"


def testMissingEndpointRaisesConfigError(tmp_path: Path) -> None:
    path = tmp_path / "empty.har"
    path.write_text(json.dumps({"log": {"entries": []}}), encoding="utf-8")
    with pytest.raises(ConfigError, match="HAR"):
        loadHar(path)


def testInvalidJsonRaisesConfigError(tmp_path: Path) -> None:
    path = tmp_path / "bad.har"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="读取 HAR 失败"):
        loadHar(path)


def _writeDeleteHar(tmp_path: Path) -> Path:
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


def testDeleteHarIsUsableForDeleteEndpoint(tmp_path: Path) -> None:
    info = loadHar(_writeDeleteHar(tmp_path), endpoint=endpointDelete)
    assert info.url is not None
    assert "/admin/ajaxdeletereview/" in info.url
    assert info.sessionid == "abcd"
    assert info.cookie is not None
    assert info.referer == "https://store.steampowered.com/r"


def testDeleteOnlyHarFallsBackForCredentials(tmp_path: Path) -> None:
    info = loadHar(_writeDeleteHar(tmp_path))
    assert "/admin/ajaxdeletereview/" in (info.url or "")
    assert info.sessionid == "abcd"

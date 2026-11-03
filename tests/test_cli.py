from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import steam_curator_exporter.cli as cli
from conftest import ADMIN_HAR, FakeTransport, admin_response, html_response, make_item
from steam_curator_exporter.storage import append_entry, save_state

EXPLICIT_ADMIN_URL = (
    "https://store.steampowered.com/curator/26214428-TEST/admin/ajaxgetrecommendations/"
)


def test_cli_admin_dry_run_with_synthetic_har(tmp_path: Path, capsys) -> None:
    out = tmp_path / "dry"
    code = cli.main(["--har", str(ADMIN_HAR), "--out", str(out), "--dry-run"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "dry-run" in printed
    assert "输出目录" in printed
    assert "bbbbbbbbbbbbbbbbbbbbbbbb" not in printed
    assert (out / "run.log").exists()


def test_cli_public_dry_run_needs_no_cookie(tmp_path: Path) -> None:
    code = cli.main(
        [
            "--source",
            "public",
            "--clan-id",
            "26214428",
            "--name",
            "测试组",
            "--out",
            str(tmp_path / "public"),
            "--dry-run",
        ]
    )
    assert code == 0


def test_cli_admin_without_cookie_is_usage_error(tmp_path: Path, capsys) -> None:
    code = cli.main(["--clan-id", "26214428", "--out", str(tmp_path / "nocookie")])
    assert code == 2
    assert "缺少 Cookie" in capsys.readouterr().err


def test_cli_status_missing_directory(tmp_path: Path, capsys) -> None:
    code = cli.main(["--status", "--out", str(tmp_path / "missing")])
    assert code == 1
    assert "输出目录不存在" in capsys.readouterr().out


def test_cli_status_existing_directory(tmp_path: Path, capsys) -> None:
    out = tmp_path / "status"
    out.mkdir()
    append_entry(out, make_item(appid=1, creator=1, time_recommended=10))
    save_state(out, {"next_start": 1, "total_count": 4})
    code = cli.main(["--status", "--out", str(out)])
    assert code == 0
    assert "25.0%" in capsys.readouterr().out


def test_cli_bad_config_path(tmp_path: Path, capsys) -> None:
    code = cli.main(["--config", str(tmp_path / "nope.toml")])
    assert code == 2
    assert "读取配置文件失败" in capsys.readouterr().err


def test_cli_invalid_format(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [
            "--source",
            "public",
            "--clan-id",
            "1",
            "--name",
            "x",
            "--format",
            "xml",
            "--out",
            str(tmp_path / "fmt"),
            "--dry-run",
        ]
    )
    assert code == 2
    assert "无效导出格式" in capsys.readouterr().err


def test_cli_dry_run_from_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'clan_id = "26214428"\nname = "测试组"\nsource = "public"\nformats = ["json"]\n',
        encoding="utf-8",
    )
    code = cli.main(
        ["--config", str(config_path), "--out", str(tmp_path / "cfg"), "--dry-run"]
    )
    assert code == 0


def test_cli_auth_error_maps_to_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class HtmlTransport:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def request(self, *args: Any, **kwargs: Any) -> Any:
            return html_response("<html>login</html>")

        def close(self) -> None:
            return None

    monkeypatch.setattr(cli, "HttpTransport", HtmlTransport)
    code = cli.main(
        [
            "--url",
            EXPLICIT_ADMIN_URL,
            "--cookie",
            "sessionid=0123456789abcdef01234567",
            "--sessionid",
            "0123456789abcdef01234567",
            "--out",
            str(tmp_path / "auth"),
            "--delay",
            "0",
        ]
    )
    assert code == 3


def test_cli_end_to_end_with_fake_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeTransport(
        handler=lambda index, call: admin_response(
            [make_item(appid=1234, creator=1, time_recommended=100)], 1, 0
        )
    )

    def factory(**kwargs: Any) -> FakeTransport:
        return transport

    monkeypatch.setattr(cli, "HttpTransport", factory)
    out = tmp_path / "e2e"
    code = cli.main(
        [
            "--url",
            EXPLICIT_ADMIN_URL,
            "--cookie",
            "sessionid=0123456789abcdef01234567",
            "--sessionid",
            "0123456789abcdef01234567",
            "--out",
            str(out),
            "--delay",
            "0",
            "--retries",
            "1",
            "--format",
            "json,csv",
        ]
    )
    assert code == 0
    payload = json.loads((out / "reviews.json").read_text(encoding="utf-8"))
    assert payload["fetched_count"] == 1
    assert (out / "reviews.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_cli_delete_requires_har(tmp_path: Path, capsys) -> None:
    code = cli.main(["--delete", "--clan-id", "26214428", "--out", str(tmp_path / "d")])
    assert code == 2
    assert "--har" in capsys.readouterr().err


def test_cli_delete_file_dry_run(tmp_path: Path, capsys) -> None:
    appids = tmp_path / "appids.txt"
    appids.write_text("111\n# comment\n222\n", encoding="utf-8")
    out = tmp_path / "del"
    code = cli.main(
        [
            "--har",
            str(ADMIN_HAR),
            "--delete-file",
            str(appids),
            "--out",
            str(out),
            "--dry-run",
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "[DRY] 111" in printed
    assert "[DRY] 222" in printed
    assert "sessionid=<hidden>" in printed
    log = out / "deleted.log"
    assert log.read_text(encoding="utf-8").count("DRY") == 2


def test_cli_check_dry_run(tmp_path: Path, capsys) -> None:
    code = cli.main(
        ["--har", str(ADMIN_HAR), "--check", "--dry-run", "--out", str(tmp_path / "chk")]
    )
    assert code == 0
    assert "[DRY] --check" in capsys.readouterr().out


def test_cli_delete_rejects_public_source(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [
            "--har",
            str(ADMIN_HAR),
            "--delete",
            "--source",
            "public",
            "--out",
            str(tmp_path / "pub"),
        ]
    )
    assert code == 2
    assert "admin" in capsys.readouterr().err


def test_cli_export_rejects_delete_only_har(tmp_path: Path, capsys) -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://store.steampowered.com/curator/1-x"
                        "/admin/ajaxdeletereview/",
                        "headers": [{"name": "Cookie", "value": "sessionid=abcd"}],
                    }
                }
            ]
        }
    }
    path = tmp_path / "delete.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    code = cli.main(["--har", str(path), "--out", str(tmp_path / "exp")])
    assert code == 2
    assert "ajaxdeletereview" in capsys.readouterr().err


def test_cli_delete_accepts_delete_only_har(tmp_path: Path, capsys) -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://store.steampowered.com/curator/1-x"
                        "/admin/ajaxdeletereview/",
                        "headers": [{"name": "Cookie", "value": "sessionid=abcd"}],
                    }
                }
            ]
        }
    }
    path = tmp_path / "delete.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    appids = tmp_path / "appids.txt"
    appids.write_text("555", encoding="utf-8")
    out = tmp_path / "del"
    code = cli.main(
        [
            "--har",
            str(path),
            "--delete-file",
            str(appids),
            "--out",
            str(out),
            "--dry-run",
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "/admin/ajaxdeletereview/" in printed
    assert "[DRY] 555" in printed

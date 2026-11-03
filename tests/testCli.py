from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import steamCuratorTools.cli as cli
from conftest import FakeTransport, adminHar, adminResponse, htmlResponse, makeItem
from steamCuratorTools.storage import appendEntry, saveState

explicitAdminUrl = (
    "https://store.steampowered.com/curator/26214428-TEST/admin/ajaxgetrecommendations/"
)


def testEmailHelperFlagLaunchesGui(monkeypatch: pytest.MonkeyPatch) -> None:
    import steamCuratorTools.emailHelper.gui as emailGui

    calls: list[bool] = []
    monkeypatch.setattr(emailGui, "main", lambda: calls.append(True) or 0)
    assert cli.main(["--email-helper"]) == 0
    assert calls == [True]


def testCliAdminDryRunWithSyntheticHar(tmp_path: Path, capsys) -> None:
    out = tmp_path / "dry"
    code = cli.main(["--har", str(adminHar), "--out", str(out), "--dry-run"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "dry-run" in printed
    assert "输出目录" in printed
    assert "bbbbbbbbbbbbbbbbbbbbbbbb" not in printed
    assert (out / "run.log").exists()


def testCliPublicDryRunNeedsNoCookie(tmp_path: Path) -> None:
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


def testCliAdminWithoutCookieIsUsageError(tmp_path: Path, capsys) -> None:
    code = cli.main(["--clan-id", "26214428", "--out", str(tmp_path / "nocookie")])
    assert code == 2
    assert "缺少 Cookie" in capsys.readouterr().err


def testCliStatusMissingDirectory(tmp_path: Path, capsys) -> None:
    code = cli.main(["--status", "--out", str(tmp_path / "missing")])
    assert code == 1
    assert "输出目录不存在" in capsys.readouterr().out


def testCliStatusExistingDirectory(tmp_path: Path, capsys) -> None:
    out = tmp_path / "status"
    out.mkdir()
    appendEntry(out, makeItem(appid=1, creator=1, timeRecommended=10))
    saveState(out, {"next_start": 1, "total_count": 4})
    code = cli.main(["--status", "--out", str(out)])
    assert code == 0
    assert "25.0%" in capsys.readouterr().out


def testCliBadConfigPath(tmp_path: Path, capsys) -> None:
    code = cli.main(["--config", str(tmp_path / "nope.toml")])
    assert code == 2
    assert "读取配置文件失败" in capsys.readouterr().err


def testCliInvalidFormat(tmp_path: Path, capsys) -> None:
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


def testCliDryRunFromConfigFile(tmp_path: Path) -> None:
    configPath = tmp_path / "config.toml"
    configPath.write_text(
        'clan_id = "26214428"\nname = "测试组"\nsource = "public"\nformats = ["json"]\n',
        encoding="utf-8",
    )
    code = cli.main(
        ["--config", str(configPath), "--out", str(tmp_path / "cfg"), "--dry-run"]
    )
    assert code == 0


def testCliAuthErrorMapsToExitThree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class HtmlTransport:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def request(self, *args: Any, **kwargs: Any) -> Any:
            return htmlResponse("<html>login</html>")

        def close(self) -> None:
            return None

    monkeypatch.setattr(cli, "HttpTransport", HtmlTransport)
    code = cli.main(
        [
            "--url",
            explicitAdminUrl,
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


def testCliEndToEndWithFakeTransport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeTransport(
        handler=lambda index, call: adminResponse(
            [makeItem(appid=1234, creator=1, timeRecommended=100)], 1, 0
        )
    )

    def factory(**kwargs: Any) -> FakeTransport:
        return transport

    monkeypatch.setattr(cli, "HttpTransport", factory)
    out = tmp_path / "e2e"
    code = cli.main(
        [
            "--url",
            explicitAdminUrl,
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


def testCliDeleteRequiresHar(tmp_path: Path, capsys) -> None:
    code = cli.main(["--delete", "--clan-id", "26214428", "--out", str(tmp_path / "d")])
    assert code == 2
    assert "--har" in capsys.readouterr().err


def testCliDeleteFileDryRun(tmp_path: Path, capsys) -> None:
    appids = tmp_path / "appids.txt"
    appids.write_text("111\n# comment\n222\n", encoding="utf-8")
    out = tmp_path / "del"
    code = cli.main(
        [
            "--har",
            str(adminHar),
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


def testCliCheckDryRun(tmp_path: Path, capsys) -> None:
    code = cli.main(
        ["--har", str(adminHar), "--check", "--dry-run", "--out", str(tmp_path / "chk")]
    )
    assert code == 0
    assert "[DRY] --check" in capsys.readouterr().out


def testCliDeleteRejectsPublicSource(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [
            "--har",
            str(adminHar),
            "--delete",
            "--source",
            "public",
            "--out",
            str(tmp_path / "pub"),
        ]
    )
    assert code == 2
    assert "admin" in capsys.readouterr().err


def _writeDeleteHar(tmp_path: Path) -> Path:
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
    return path


def testCliExportDerivesRecommendationsUrlFromDeleteHar(
    tmp_path: Path, capsys
) -> None:
    path = _writeDeleteHar(tmp_path)
    code = cli.main(
        ["--har", str(path), "--out", str(tmp_path / "exp"), "--dry-run"]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "/admin/ajaxgetrecommendations/" in printed


def testCliExportRejectsDeleteOnlyHarForPublicSource(
    tmp_path: Path, capsys
) -> None:
    path = _writeDeleteHar(tmp_path)
    code = cli.main(
        [
            "--har",
            str(path),
            "--source",
            "public",
            "--out",
            str(tmp_path / "exp"),
            "--dry-run",
        ]
    )
    assert code == 2
    assert "ajaxdeletereview" in capsys.readouterr().err


def testCliDeleteAcceptsDeleteOnlyHar(tmp_path: Path, capsys) -> None:
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


def testParserExposesCamelCaseDestinations() -> None:
    args = cli.buildParser().parse_args(
        [
            "--har",
            "capture.har",
            "--clan-id",
            "1",
            "--cookie-file",
            "cookie.txt",
            "--proxy-file",
            "proxies.txt",
            "--max-pages",
            "3",
            "--keep-raw",
            "--dry-run",
            "--delete-file",
            "appids.txt",
            "--delete-log",
            "deleted.log",
            "--log-level",
            "DEBUG",
        ]
    )
    assert args.clanId == "1"
    assert args.cookieFile == "cookie.txt"
    assert args.proxyFile == "proxies.txt"
    assert args.maxPages == 3
    assert args.keepRaw is True
    assert args.dryRun is True
    assert args.deleteFile == "appids.txt"
    assert args.deleteLog == "deleted.log"
    assert args.logLevel == "DEBUG"


def testCliRejectsDeleteAndDeleteFileTogether(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [
            "--har",
            str(adminHar),
            "--delete",
            "--delete-file",
            str(tmp_path / "appids.txt"),
            "--out",
            str(tmp_path / "both"),
        ]
    )
    assert code == 2
    assert "--delete" in capsys.readouterr().err

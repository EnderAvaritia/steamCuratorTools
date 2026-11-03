from __future__ import annotations

from pathlib import Path

import pytest

from steam_curator_exporter.config import (
    load_config_file,
    merge_config,
    parse_formats,
    resolve_cookie,
    resolve_sessionid,
    validate_config,
)
from steam_curator_exporter.errors import ConfigError


def test_load_toml_and_cli_override(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
clan_id = 26214428
name = "测试组"
source = "admin"
count = 50
delay = 0.5
formats = ["json", "sqlite"]
proxy = ["127.0.0.1:8080", "socks5://127.0.0.1:1080"]
fresh = true
""",
        encoding="utf-8",
    )
    data = load_config_file(path)
    assert data["clan_id"] == "26214428"
    assert data["formats"] == ["json", "sqlite"]

    config = merge_config({"count": 100, "name": None}, data)
    assert config.count == 100
    assert config.name == "测试组"
    assert config.formats == ["json", "sqlite"]
    assert config.fresh is True
    assert config.proxy == ["127.0.0.1:8080", "socks5://127.0.0.1:1080"]


def test_unknown_config_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("unknown_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="未知配置项"):
        load_config_file(path)


def test_invalid_toml_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("clan_id = [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="解析配置文件失败"):
        load_config_file(path)


def test_parse_formats_repeated_and_comma() -> None:
    assert parse_formats(["json,csv", "sqlite", "json"]) == ["json", "csv", "sqlite"]
    assert parse_formats(None) == ["json", "csv"]
    with pytest.raises(ConfigError, match="无效导出格式"):
        parse_formats(["xml"])


def test_validate_config_rules() -> None:
    with pytest.raises(ConfigError, match="count"):
        merge_config({"count": 0}, {})
    config = merge_config({}, {})
    with pytest.raises(ConfigError, match="count"):
        config.count = 0
        validate_config(config)


def test_merge_rejects_invalid_source() -> None:
    with pytest.raises(ConfigError, match="无效数据源"):
        merge_config({}, {"source": "magic"})


def test_cookie_resolution_order(tmp_path: Path) -> None:
    cli_file = tmp_path / "cli-cookie.txt"
    cli_file.write_text("cli-file-cookie\n", encoding="utf-8")
    config_file = tmp_path / "config-cookie.txt"
    config_file.write_text("config-file-cookie\n", encoding="utf-8")
    env = {"STEAM_COOKIE": "env-cookie"}

    assert resolve_cookie("cli-cookie", str(cli_file), {}, "har-cookie", env) == "cli-cookie"
    assert resolve_cookie(None, str(cli_file), {}, "har-cookie", env) == "cli-file-cookie"
    assert resolve_cookie(None, None, {"cookie": "config-cookie"}, "har-cookie", env) == (
        "config-cookie"
    )
    assert resolve_cookie(
        None, None, {"cookie_file": str(config_file)}, "har-cookie", env
    ) == "config-file-cookie"
    assert resolve_cookie(None, None, {}, "har-cookie", env) == "har-cookie"
    assert resolve_cookie(None, None, {}, None, env) == "env-cookie"
    assert resolve_cookie(None, None, {}, None, {}) == ""


def test_cookie_file_read_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="读取 Cookie 文件失败"):
        resolve_cookie(None, str(tmp_path / "missing.txt"), {}, None, {})


def test_sessionid_resolution_order() -> None:
    env = {"STEAM_SESSIONID": "env-sid"}
    assert resolve_sessionid("merged", "har", "sessionid=cookie", env) == "merged"
    assert resolve_sessionid(None, "har", "sessionid=cookie", env) == "har"
    assert resolve_sessionid(None, None, "sessionid=cookie", env) == "env-sid"
    assert resolve_sessionid(None, None, "sessionid=abcdef", {}) == "abcdef"
    assert resolve_sessionid(None, None, "nothing", {}) is None

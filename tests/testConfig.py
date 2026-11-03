from __future__ import annotations

from pathlib import Path

import pytest

from steamCuratorTools.config import (
    loadConfigFile,
    mergeConfig,
    parseFormats,
    resolveCookie,
    resolveSessionid,
    validateConfig,
)
from steamCuratorTools.errors import ConfigError


def testLoadTomlAndCliOverride(tmp_path: Path) -> None:
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
    data = loadConfigFile(path)
    assert data["clan_id"] == "26214428"
    assert data["formats"] == ["json", "sqlite"]

    config = mergeConfig({"count": 100, "name": None}, data)
    assert config.count == 100
    assert config.name == "测试组"
    assert config.formats == ["json", "sqlite"]
    assert config.fresh is True
    assert config.proxy == ["127.0.0.1:8080", "socks5://127.0.0.1:1080"]


def testUnknownConfigKeyRejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("unknown_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="未知配置项"):
        loadConfigFile(path)


def testInvalidTomlRejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("clan_id = [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="解析配置文件失败"):
        loadConfigFile(path)


def testParseFormatsRepeatedAndComma() -> None:
    assert parseFormats(["json,csv", "sqlite", "json"]) == ["json", "csv", "sqlite"]
    assert parseFormats(None) == ["json", "csv"]
    with pytest.raises(ConfigError, match="无效导出格式"):
        parseFormats(["xml"])


def testValidateConfigRules() -> None:
    with pytest.raises(ConfigError, match="count"):
        mergeConfig({"count": 0}, {})
    config = mergeConfig({}, {})
    with pytest.raises(ConfigError, match="count"):
        config.count = 0
        validateConfig(config)


def testMergeRejectsInvalidSource() -> None:
    with pytest.raises(ConfigError, match="无效数据源"):
        mergeConfig({}, {"source": "magic"})


def testCookieResolutionOrder(tmp_path: Path) -> None:
    cliFile = tmp_path / "cli-cookie.txt"
    cliFile.write_text("cli-file-cookie\n", encoding="utf-8")
    configFile = tmp_path / "config-cookie.txt"
    configFile.write_text("config-file-cookie\n", encoding="utf-8")
    env = {"STEAM_COOKIE": "env-cookie"}

    assert resolveCookie("cli-cookie", str(cliFile), {}, "har-cookie", env) == "cli-cookie"
    assert resolveCookie(None, str(cliFile), {}, "har-cookie", env) == "cli-file-cookie"
    assert resolveCookie(None, None, {"cookie": "config-cookie"}, "har-cookie", env) == (
        "config-cookie"
    )
    assert resolveCookie(
        None, None, {"cookie_file": str(configFile)}, "har-cookie", env
    ) == "config-file-cookie"
    assert resolveCookie(None, None, {}, "har-cookie", env) == "har-cookie"
    assert resolveCookie(None, None, {}, None, env) == "env-cookie"
    assert resolveCookie(None, None, {}, None, {}) == ""


def testCookieFileReadError(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="读取 Cookie 文件失败"):
        resolveCookie(None, str(tmp_path / "missing.txt"), {}, None, {})


def testSessionidResolutionOrder() -> None:
    env = {"STEAM_SESSIONID": "env-sid"}
    assert resolveSessionid("merged", "har", "sessionid=cookie", env) == "merged"
    assert resolveSessionid(None, "har", "sessionid=cookie", env) == "har"
    assert resolveSessionid(None, None, "sessionid=cookie", env) == "env-sid"
    assert resolveSessionid(None, None, "sessionid=abcdef", {}) == "abcdef"
    assert resolveSessionid(None, None, "nothing", {}) is None

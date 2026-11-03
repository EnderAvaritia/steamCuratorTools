"""TOML configuration loading, merging, and validation."""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .urls import sourceAdmin, sourcePublic

defaultOut = "curator_reviews"
defaultPageSize = 25
defaultDelay = 1.5
defaultTimeout = 30.0
defaultRetries = 5
defaultMaxPages = 5000
defaultFormats = ("json", "csv")
defaultLogLevel = "INFO"

allowedFormats = ("json", "csv", "sqlite")
allowedSources = (sourceAdmin, sourcePublic)
allowedLogLevels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

configKeys = frozenset(
    {
        "clan_id",
        "name",
        "url",
        "source",
        "cookie",
        "cookie_file",
        "sessionid",
        "proxy",
        "proxy_file",
        "out",
        "count",
        "delay",
        "timeout",
        "retries",
        "max_pages",
        "formats",
        "fresh",
        "keep_raw",
        "log_level",
    }
)


@dataclass(slots=True)
class Config:
    clanId: str | None = None
    name: str = ""
    url: str | None = None
    source: str = sourceAdmin
    cookie: str | None = None
    sessionid: str | None = None
    referer: str | None = None
    proxy: list[str] = field(default_factory=list)
    proxyFile: str | None = None
    out: str = defaultOut
    count: int = defaultPageSize
    delay: float = defaultDelay
    timeout: float = defaultTimeout
    retries: int = defaultRetries
    maxPages: int = defaultMaxPages
    formats: list[str] = field(default_factory=lambda: list(defaultFormats))
    fresh: bool = False
    keepRaw: bool = False
    logLevel: str = defaultLogLevel
    resume: bool = False


def _expectType(key: str, value: Any, expected: type | tuple[type, ...]) -> None:
    if isinstance(value, bool) and expected is not bool and bool not in _asTuple(expected):
        raise ConfigError(f"配置项 {key} 类型不正确: 期望 {expected}, 实际 bool")
    if not isinstance(value, expected):
        raise ConfigError(f"配置项 {key} 类型不正确: 期望 {expected}, 实际 {type(value).__name__}")


def _asTuple(expected: type | tuple[type, ...]) -> tuple[type, ...]:
    return expected if isinstance(expected, tuple) else (expected,)


def _stringList(key: str, value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ConfigError(f"配置项 {key} 应为字符串列表（或逗号分隔字符串）")


def loadConfigFile(path: Path) -> dict[str, Any]:
    """Load a TOML config file and validate its shape."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"读取配置文件失败: {exc}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"解析配置文件失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("配置文件顶层必须是 TOML 表")

    unknown = sorted(set(data) - configKeys)
    if unknown:
        raise ConfigError(f"配置文件包含未知配置项: {', '.join(unknown)}")

    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if key == "clan_id":
            _expectType(key, value, (str, int))
            normalized[key] = str(value).strip()
        elif key in {"name", "url", "source", "cookie", "cookie_file", "sessionid",
                     "proxy_file", "out", "log_level"}:
            _expectType(key, value, str)
            normalized[key] = value
        elif key in {"proxy", "formats"}:
            normalized[key] = _stringList(key, value)
        elif key == "count" or key in {"retries", "max_pages"}:
            _expectType(key, value, int)
            normalized[key] = value
        elif key in {"delay", "timeout"}:
            _expectType(key, value, (int, float))
            normalized[key] = float(value)
        elif key in {"fresh", "keep_raw"}:
            _expectType(key, value, bool)
            normalized[key] = value
    return normalized


def parseFormats(values: list[str] | str | None) -> list[str]:
    """Parse repeated/comma-separated format flags, preserving order."""
    if not values:
        return list(defaultFormats)
    if isinstance(values, str):
        values = [values]
    formats: list[str] = []
    for value in values:
        for part in value.split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name not in allowedFormats:
                raise ConfigError(
                    f"无效导出格式: {name!r}，可选值: {', '.join(allowedFormats)}"
                )
            if name not in formats:
                formats.append(name)
    if not formats:
        raise ConfigError("至少需要一种导出格式")
    return formats


def _pick(cli: Mapping[str, Any], fileData: Mapping[str, Any], key: str,
          default: Any) -> Any:
    value = cli.get(key)
    if value is not None:
        return value
    if key in fileData:
        return fileData[key]
    return default


def mergeConfig(cli: Mapping[str, Any], fileData: Mapping[str, Any]) -> Config:
    """Merge CLI values over TOML values over defaults.

    ``cli`` values must be ``None`` when the user did not pass the option.
    """
    proxyValues = _pick(cli, fileData, "proxy", [])
    if isinstance(proxyValues, str):
        proxyValues = _stringList("proxy", proxyValues)
    config = Config(
        clanId=_pick(cli, fileData, "clan_id", None),
        name=_pick(cli, fileData, "name", ""),
        url=_pick(cli, fileData, "url", None),
        source=_pick(cli, fileData, "source", sourceAdmin),
        cookie=None,
        sessionid=_pick(cli, fileData, "sessionid", None),
        proxy=list(proxyValues or []),
        proxyFile=_pick(cli, fileData, "proxy_file", None),
        out=_pick(cli, fileData, "out", defaultOut),
        count=_pick(cli, fileData, "count", defaultPageSize),
        delay=_pick(cli, fileData, "delay", defaultDelay),
        timeout=_pick(cli, fileData, "timeout", defaultTimeout),
        retries=_pick(cli, fileData, "retries", defaultRetries),
        maxPages=_pick(cli, fileData, "max_pages", defaultMaxPages),
        formats=parseFormats(_pick(cli, fileData, "formats", None)),
        fresh=bool(_pick(cli, fileData, "fresh", False)),
        keepRaw=bool(_pick(cli, fileData, "keep_raw", False)),
        logLevel=str(_pick(cli, fileData, "log_level", defaultLogLevel)).upper(),
        resume=bool(cli.get("resume", False)),
    )
    if config.clanId is not None:
        config.clanId = str(config.clanId).strip() or None
    if config.source not in allowedSources:
        raise ConfigError(f"无效数据源: {config.source!r}，可选值: admin, public")
    validateConfig(config)
    return config


def validateConfig(config: Config) -> None:
    if config.count < 1:
        raise ConfigError("--count 必须 >= 1")
    if config.retries < 1:
        raise ConfigError("--retries 必须 >= 1")
    if config.maxPages < 1:
        raise ConfigError("--max-pages 必须 >= 1")
    if config.delay < 0:
        raise ConfigError("--delay 不能为负数")
    if config.timeout <= 0:
        raise ConfigError("--timeout 必须大于 0")
    if not config.out.strip():
        raise ConfigError("--out 不能为空")
    if config.logLevel not in allowedLogLevels:
        raise ConfigError(
            f"无效日志级别: {config.logLevel!r}，可选值: {', '.join(allowedLogLevels)}"
        )


def _readCookieFile(path: str | None) -> str | None:
    if not path:
        return None
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError(f"读取 Cookie 文件失败: {exc}") from exc
    return text or None


def resolveCookie(
    cliCookie: str | None,
    cliCookieFile: str | None,
    fileData: Mapping[str, Any],
    harCookie: str | None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve a cookie using the documented precedence order."""
    env = os.environ if environ is None else environ
    if isinstance(cliCookie, str) and cliCookie.strip():
        return cliCookie.strip()
    cliFileCookie = _readCookieFile(cliCookieFile)
    if cliFileCookie:
        return cliFileCookie
    configCookie = fileData.get("cookie")
    if isinstance(configCookie, str) and configCookie.strip():
        return configCookie.strip()
    configFileCookie = _readCookieFile(fileData.get("cookie_file"))
    if configFileCookie:
        return configFileCookie
    if isinstance(harCookie, str) and harCookie.strip():
        return harCookie.strip()
    envCookie = env.get("STEAM_COOKIE")
    if isinstance(envCookie, str) and envCookie.strip():
        return envCookie.strip()
    return ""


def resolveSessionid(
    mergedSessionid: str | None,
    harSessionid: str | None,
    cookie: str,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve sessionid, falling back to env and then the cookie value."""
    env = os.environ if environ is None else environ
    values = [
        mergedSessionid,
        harSessionid,
        env.get("STEAM_SESSIONID"),
    ]
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    from .urls import extractSessionid

    return extractSessionid(cookie)


def describeConfig(config: Config) -> list[str]:
    """Human-readable, secret-free description used by ``--dry-run``."""
    lines = [
        f"输出目录：{Path(config.out).expanduser().resolve()}",
        f"数据源：{config.source}",
        f"组 ID：{config.clanId or '(未知)'}",
        f"组名称：{config.name or '(未提供)'}",
        f"接口 URL：{config.url or '(自动探测)'}",
        f"Cookie：{f'已提供（长度 {len(config.cookie)} 字符）' if config.cookie else '未提供'}",
        f"sessionid：{'已提供' if config.sessionid else '未提供'}",
        f"每页条数：{config.count}",
        f"页间隔：{config.delay}s",
        f"超时：{config.timeout}s",
        f"重试：{config.retries}",
        f"最大页数：{config.maxPages}",
        f"导出格式：{', '.join(config.formats)}",
        f"保留原始响应：{'是' if config.keepRaw else '否'}",
        f"清空重来：{'是' if config.fresh else '否'}",
        f"日志级别：{config.logLevel}",
    ]
    if config.proxy:
        from .http import maskProxy

        masked = ", ".join(maskProxy(proxy) for proxy in config.proxy)
        lines.append(f"代理：{len(config.proxy)} 个 -> {masked}")
    else:
        lines.append("代理：未指定（使用 HTTP_PROXY/HTTPS_PROXY 环境变量或直连）")
    return lines


def loggingLevel(name: str) -> int:
    return logging.getLevelNamesMapping().get(name.upper(), logging.INFO)

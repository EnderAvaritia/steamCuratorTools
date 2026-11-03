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
from .urls import SOURCE_ADMIN, SOURCE_PUBLIC

DEFAULT_OUT = "curator_reviews"
DEFAULT_PAGE_SIZE = 25
DEFAULT_DELAY = 1.5
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 5
DEFAULT_MAX_PAGES = 5000
DEFAULT_FORMATS = ("json", "csv")
DEFAULT_LOG_LEVEL = "INFO"

ALLOWED_FORMATS = ("json", "csv", "sqlite")
ALLOWED_SOURCES = (SOURCE_ADMIN, SOURCE_PUBLIC)
ALLOWED_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

CONFIG_KEYS = frozenset(
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
    clan_id: str | None = None
    name: str = ""
    url: str | None = None
    source: str = SOURCE_ADMIN
    cookie: str | None = None
    sessionid: str | None = None
    referer: str | None = None
    proxy: list[str] = field(default_factory=list)
    proxy_file: str | None = None
    out: str = DEFAULT_OUT
    count: int = DEFAULT_PAGE_SIZE
    delay: float = DEFAULT_DELAY
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    max_pages: int = DEFAULT_MAX_PAGES
    formats: list[str] = field(default_factory=lambda: list(DEFAULT_FORMATS))
    fresh: bool = False
    keep_raw: bool = False
    log_level: str = DEFAULT_LOG_LEVEL
    resume: bool = False


def _expect_type(key: str, value: Any, expected: type | tuple[type, ...]) -> None:
    if isinstance(value, bool) and expected is not bool and bool not in _as_tuple(expected):
        raise ConfigError(f"配置项 {key} 类型不正确: 期望 {expected}, 实际 bool")
    if not isinstance(value, expected):
        raise ConfigError(f"配置项 {key} 类型不正确: 期望 {expected}, 实际 {type(value).__name__}")


def _as_tuple(expected: type | tuple[type, ...]) -> tuple[type, ...]:
    return expected if isinstance(expected, tuple) else (expected,)


def _string_list(key: str, value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ConfigError(f"配置项 {key} 应为字符串列表（或逗号分隔字符串）")


def load_config_file(path: Path) -> dict[str, Any]:
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

    unknown = sorted(set(data) - CONFIG_KEYS)
    if unknown:
        raise ConfigError(f"配置文件包含未知配置项: {', '.join(unknown)}")

    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if key == "clan_id":
            _expect_type(key, value, (str, int))
            normalized[key] = str(value).strip()
        elif key in {"name", "url", "source", "cookie", "cookie_file", "sessionid",
                     "proxy_file", "out", "log_level"}:
            _expect_type(key, value, str)
            normalized[key] = value
        elif key in {"proxy", "formats"}:
            normalized[key] = _string_list(key, value)
        elif key == "count" or key in {"retries", "max_pages"}:
            _expect_type(key, value, int)
            normalized[key] = value
        elif key in {"delay", "timeout"}:
            _expect_type(key, value, (int, float))
            normalized[key] = float(value)
        elif key in {"fresh", "keep_raw"}:
            _expect_type(key, value, bool)
            normalized[key] = value
    return normalized


def parse_formats(values: list[str] | str | None) -> list[str]:
    """Parse repeated/comma-separated format flags, preserving order."""
    if not values:
        return list(DEFAULT_FORMATS)
    if isinstance(values, str):
        values = [values]
    formats: list[str] = []
    for value in values:
        for part in value.split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name not in ALLOWED_FORMATS:
                raise ConfigError(
                    f"无效导出格式: {name!r}，可选值: {', '.join(ALLOWED_FORMATS)}"
                )
            if name not in formats:
                formats.append(name)
    if not formats:
        raise ConfigError("至少需要一种导出格式")
    return formats


def _pick(cli: Mapping[str, Any], file_data: Mapping[str, Any], key: str,
          default: Any) -> Any:
    value = cli.get(key)
    if value is not None:
        return value
    if key in file_data:
        return file_data[key]
    return default


def merge_config(cli: Mapping[str, Any], file_data: Mapping[str, Any]) -> Config:
    """Merge CLI values over TOML values over defaults.

    ``cli`` values must be ``None`` when the user did not pass the option.
    """
    proxy_values = _pick(cli, file_data, "proxy", [])
    if isinstance(proxy_values, str):
        proxy_values = _string_list("proxy", proxy_values)
    config = Config(
        clan_id=_pick(cli, file_data, "clan_id", None),
        name=_pick(cli, file_data, "name", ""),
        url=_pick(cli, file_data, "url", None),
        source=_pick(cli, file_data, "source", SOURCE_ADMIN),
        cookie=None,
        sessionid=_pick(cli, file_data, "sessionid", None),
        proxy=list(proxy_values or []),
        proxy_file=_pick(cli, file_data, "proxy_file", None),
        out=_pick(cli, file_data, "out", DEFAULT_OUT),
        count=_pick(cli, file_data, "count", DEFAULT_PAGE_SIZE),
        delay=_pick(cli, file_data, "delay", DEFAULT_DELAY),
        timeout=_pick(cli, file_data, "timeout", DEFAULT_TIMEOUT),
        retries=_pick(cli, file_data, "retries", DEFAULT_RETRIES),
        max_pages=_pick(cli, file_data, "max_pages", DEFAULT_MAX_PAGES),
        formats=parse_formats(_pick(cli, file_data, "formats", None)),
        fresh=bool(_pick(cli, file_data, "fresh", False)),
        keep_raw=bool(_pick(cli, file_data, "keep_raw", False)),
        log_level=str(_pick(cli, file_data, "log_level", DEFAULT_LOG_LEVEL)).upper(),
        resume=bool(cli.get("resume", False)),
    )
    if config.clan_id is not None:
        config.clan_id = str(config.clan_id).strip() or None
    if config.source not in ALLOWED_SOURCES:
        raise ConfigError(f"无效数据源: {config.source!r}，可选值: admin, public")
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    if config.count < 1:
        raise ConfigError("--count 必须 >= 1")
    if config.retries < 1:
        raise ConfigError("--retries 必须 >= 1")
    if config.max_pages < 1:
        raise ConfigError("--max-pages 必须 >= 1")
    if config.delay < 0:
        raise ConfigError("--delay 不能为负数")
    if config.timeout <= 0:
        raise ConfigError("--timeout 必须大于 0")
    if not config.out.strip():
        raise ConfigError("--out 不能为空")
    if config.log_level not in ALLOWED_LOG_LEVELS:
        raise ConfigError(
            f"无效日志级别: {config.log_level!r}，可选值: {', '.join(ALLOWED_LOG_LEVELS)}"
        )


def _read_cookie_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError(f"读取 Cookie 文件失败: {exc}") from exc
    return text or None


def resolve_cookie(
    cli_cookie: str | None,
    cli_cookie_file: str | None,
    file_data: Mapping[str, Any],
    har_cookie: str | None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve a cookie using the documented precedence order."""
    env = os.environ if environ is None else environ
    if isinstance(cli_cookie, str) and cli_cookie.strip():
        return cli_cookie.strip()
    cli_file_cookie = _read_cookie_file(cli_cookie_file)
    if cli_file_cookie:
        return cli_file_cookie
    config_cookie = file_data.get("cookie")
    if isinstance(config_cookie, str) and config_cookie.strip():
        return config_cookie.strip()
    config_file_cookie = _read_cookie_file(file_data.get("cookie_file"))
    if config_file_cookie:
        return config_file_cookie
    if isinstance(har_cookie, str) and har_cookie.strip():
        return har_cookie.strip()
    env_cookie = env.get("STEAM_COOKIE")
    if isinstance(env_cookie, str) and env_cookie.strip():
        return env_cookie.strip()
    return ""


def resolve_sessionid(
    merged_sessionid: str | None,
    har_sessionid: str | None,
    cookie: str,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve sessionid, falling back to env and then the cookie value."""
    env = os.environ if environ is None else environ
    values = [
        merged_sessionid,
        har_sessionid,
        env.get("STEAM_SESSIONID"),
    ]
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    from .urls import extract_sessionid

    return extract_sessionid(cookie)


def describe_config(config: Config) -> list[str]:
    """Human-readable, secret-free description used by ``--dry-run``."""
    lines = [
        f"输出目录：{Path(config.out).expanduser().resolve()}",
        f"数据源：{config.source}",
        f"组 ID：{config.clan_id or '(未知)'}",
        f"组名称：{config.name or '(未提供)'}",
        f"接口 URL：{config.url or '(自动探测)'}",
        f"Cookie：{f'已提供（长度 {len(config.cookie)} 字符）' if config.cookie else '未提供'}",
        f"sessionid：{'已提供' if config.sessionid else '未提供'}",
        f"每页条数：{config.count}",
        f"页间隔：{config.delay}s",
        f"超时：{config.timeout}s",
        f"重试：{config.retries}",
        f"最大页数：{config.max_pages}",
        f"导出格式：{', '.join(config.formats)}",
        f"保留原始响应：{'是' if config.keep_raw else '否'}",
        f"清空重来：{'是' if config.fresh else '否'}",
        f"日志级别：{config.log_level}",
    ]
    if config.proxy:
        from .http import mask_proxy

        masked = ", ".join(mask_proxy(proxy) for proxy in config.proxy)
        lines.append(f"代理：{len(config.proxy)} 个 -> {masked}")
    else:
        lines.append("代理：未指定（使用 HTTP_PROXY/HTTPS_PROXY 环境变量或直连）")
    return lines


def logging_level(name: str) -> int:
    return logging.getLevelNamesMapping().get(name.upper(), logging.INFO)

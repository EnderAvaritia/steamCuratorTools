"""Command-line entry point: argument parsing, config merge, and wiring."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import __version__
from .config import (
    Config,
    describe_config,
    load_config_file,
    logging_level,
    merge_config,
    resolve_cookie,
    resolve_sessionid,
)
from .deleter import iter_stdin, run_check, run_delete
from .errors import AuthError, ConfigError, SteamError, UsageError
from .har import ENDPOINT_DELETE, HarInfo, load_har
from .http import HttpTransport, collect_proxies, mask_proxy
from .runner import Runner, print_status
from .sources import build_source
from .urls import (
    ADMIN_AJAX_SUFFIX,
    SOURCE_ADMIN,
    SOURCE_PUBLIC,
    build_delete_url,
    build_recommendations_url,
    build_url_candidates,
    convert_endpoint_source,
    extract_clan_id,
    swap_endpoint,
)

LOGGER_NAME = "steam_curator_exporter"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steam-curator-exporter",
        description="拉取或删除 Steam 鉴赏家组评（支持断点续传、代理轮换、多种导出格式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  steam-curator-exporter --har capture.har --out curator_reviews\n"
            "  steam-curator-exporter --clan-id 26214428 --name \"组名\" "
            "--cookie-file cookie.txt\n"
            "  steam-curator-exporter --source public --clan-id 26214428 --name \"组名\"\n"
            "  steam-curator-exporter --status --out curator_reviews\n"
            "  steam-curator-exporter --har capture.har --delete\n"
            "  steam-curator-exporter --har capture.har --delete-file appids.txt\n"
            "  steam-curator-exporter --har capture.har --check"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", metavar="FILE", help="TOML 配置文件（命令行参数优先）")
    parser.add_argument("--har", metavar="FILE",
                        help="从浏览器导出的 HAR 自动读取 URL / Cookie / sessionid")
    parser.add_argument("--clan-id", help="鉴赏家组 ID（纯数字，如 26214428）")
    parser.add_argument("--name", default=None,
                        help="鉴赏家组名称，用于拼接 URL（--har/--url 存在时可省略）")
    parser.add_argument("--url", default=None,
                        help="直接指定接口完整 URL（最高优先级）")
    parser.add_argument("--source", choices=[SOURCE_ADMIN, SOURCE_PUBLIC], default=None,
                        help="数据源：admin 后台接口（默认，需要登录态）或 public 公开页")
    parser.add_argument("--cookie", default=None, help="完整 Cookie 字符串")
    parser.add_argument("--cookie-file", default=None,
                        help="从文本文件读取 Cookie（推荐，避免命令行转义问题）")
    parser.add_argument("--sessionid", default=None,
                        help="会话 ID；缺省时依次从 HAR / 环境变量 / Cookie 提取")
    parser.add_argument("--proxy", action="append", metavar="URL",
                        help="代理地址（可重复或逗号分隔，支持 http/https/socks4/socks5/socks5h）")
    parser.add_argument("--proxy-file", default=None, metavar="FILE",
                        help="代理列表文件（每行一个，支持 # 注释）")
    parser.add_argument("--out", default=None, help="输出目录（默认 curator_reviews）")
    parser.add_argument("--count", type=int, default=None,
                        help="每页请求条数（默认 25；服务端可能自行截断）")
    parser.add_argument("--delay", type=float, default=None,
                        help="每页之间的基础间隔秒数（默认 1.5）")
    parser.add_argument("--timeout", type=float, default=None,
                        help="单次请求超时秒数（默认 30）")
    parser.add_argument("--retries", type=int, default=None,
                        help="单页最大尝试次数（默认 5）")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="最多请求页数，防御性上限（默认 5000）")
    parser.add_argument("--format", dest="formats", action="append", metavar="NAME",
                        help="导出格式：json,csv,sqlite（可重复或逗号分隔，默认 json,csv）")
    parser.add_argument("--resume", action="store_true",
                        help="从 state.json 断点续传（存在 state.json 时默认即续传）")
    parser.add_argument("--fresh", action="store_true", default=None,
                        help="忽略已有输出，清空后重新全量拉取")
    parser.add_argument("--keep-raw", action="store_true", default=None,
                        help="保存每页原始响应到 raw/ 目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="只解析参数并打印将要请求的目标，不发起网络请求")
    parser.add_argument("--status", action="store_true",
                        help="只读取输出目录并打印已拉取条数/进度，不发起网络请求")
    parser.add_argument("--delete", action="store_true",
                        help="交互删除模式：从标准输入逐行读取 appid（必须配合 --har）")
    parser.add_argument("--delete-file", metavar="FILE",
                        help="从文本文件逐行读取 appid 批量删除（必须配合 --har）")
    parser.add_argument("--delete-log", metavar="FILE",
                        help="删除日志路径（默认 <out>/deleted.log）")
    parser.add_argument("--check", action="store_true",
                        help="只读校验登录态，打印后台组评数量，不修改数据（必须配合 --har）")
    parser.add_argument("--force", action="store_true",
                        help="忽略删除日志中已成功的 appid，强制重发")
    parser.add_argument("--log-level", default=None,
                        help="日志级别：DEBUG/INFO/WARNING/ERROR/CRITICAL（默认 INFO）")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _cli_values(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "clan_id": args.clan_id,
        "name": args.name,
        "url": args.url,
        "source": args.source,
        "sessionid": args.sessionid,
        "proxy": args.proxy,
        "proxy_file": args.proxy_file,
        "out": args.out,
        "count": args.count,
        "delay": args.delay,
        "timeout": args.timeout,
        "retries": args.retries,
        "max_pages": args.max_pages,
        "formats": args.formats,
        "fresh": args.fresh,
        "keep_raw": args.keep_raw,
        "log_level": args.log_level,
        "resume": args.resume,
    }


def setup_logging(out_dir: Path, level: str, log_name: str = "run.log") -> logging.Logger:
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging_level(level))
    logger.propagate = False
    close_logging(logger)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = logging.FileHandler(out_dir / log_name, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def close_logging(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _load_config(args: argparse.Namespace) -> tuple[Config, dict[str, Any]]:
    file_data: dict[str, Any] = {}
    if args.config:
        file_data = load_config_file(Path(args.config).expanduser())
    config = merge_config(_cli_values(args), file_data)
    return config, file_data


def _apply_har(
    args: argparse.Namespace,
    config: Config,
    *,
    endpoint: str = "recommendations",
) -> HarInfo:
    if not args.har:
        return HarInfo()
    return load_har(Path(args.har).expanduser(), config.source, endpoint=endpoint)


def _prepare_inputs(args: argparse.Namespace, config: Config, file_data: dict[str, Any],
                    har_info: HarInfo) -> None:
    cookie = resolve_cookie(args.cookie, args.cookie_file, file_data, har_info.cookie)
    config.cookie = cookie or None
    config.sessionid = resolve_sessionid(config.sessionid, har_info.sessionid, cookie)
    config.referer = har_info.referer

    if not config.url and har_info.url:
        parts = urlsplit(har_info.url)
        base_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        config.url = convert_endpoint_source(base_url, config.source)
    if config.url and "ajaxdeletereview" in config.url and config.source == SOURCE_ADMIN:
        # A delete-only HAR still carries valid credentials; reuse it for export/check
        # by pointing at the read-only recommendations endpoint.
        config.url = swap_endpoint(config.url, ADMIN_AJAX_SUFFIX) or config.url
    if not config.clan_id:
        config.clan_id = extract_clan_id(config.url)

    if config.source == SOURCE_ADMIN:
        if not config.cookie:
            raise UsageError(
                "缺少 Cookie（--cookie / --cookie-file / 配置文件 / --har / "
                "环境变量 STEAM_COOKIE 均未提供）"
            )
        if not config.sessionid:
            raise UsageError("找不到 sessionid，请用 --sessionid 显式指定")

    if not config.url and not config.clan_id:
        raise UsageError("需要 --clan-id 或 --url（也可以直接用 --har 自动解析）")


def _delete_mode(args: argparse.Namespace) -> bool:
    return bool(args.delete or args.delete_file)


def _validate_modes(args: argparse.Namespace, config: Config, delete_mode: bool) -> None:
    if args.delete and args.delete_file:
        raise UsageError("--delete 与 --delete-file 只能二选一")
    if delete_mode and args.check:
        raise UsageError("--check 不能与删除模式同时使用")
    if args.check and args.status:
        raise UsageError("--check 不能与 --status 同时使用")
    if delete_mode and args.status:
        raise UsageError("--status 不能与删除模式同时使用")
    if (delete_mode or args.check) and not args.har:
        raise UsageError("删除/校验模式必须用 --har 指定 HAR 文件")
    if (delete_mode or args.check) and config.source != SOURCE_ADMIN:
        raise UsageError("删除/校验需要 admin 登录态，不能使用 --source public")


def _appid_lines(args: argparse.Namespace) -> tuple[Iterable[str], bool]:
    if not args.delete_file:
        return iter_stdin(), True
    path = Path(args.delete_file).expanduser()
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ConfigError(f"读取 appid 文件失败: {exc}") from exc
    return text.splitlines(), False


def _run_delete(args: argparse.Namespace, config: Config, out_dir: Path) -> int:
    delete_url = build_delete_url(config.clan_id, config.url)
    if not delete_url:
        raise UsageError("无法构造删除接口地址，请提供 --har 或 --clan-id")
    log_path = (
        Path(args.delete_log).expanduser() if args.delete_log else out_dir / "deleted.log"
    )
    lines, interactive = _appid_lines(args)
    logger = setup_logging(out_dir, config.log_level, "delete.log")
    transport: HttpTransport | None = None
    try:
        logger.info("删除接口: %s", delete_url)
        logger.info("删除日志: %s", log_path)
        logger.info("交互输入 q / quit / exit 结束；Ctrl+C 中断")
        if args.dry_run:
            logger.info("--dry-run 已启用，不会发送删除请求。")
        else:
            transport = HttpTransport(
                proxies=config.proxy,
                timeout=config.timeout,
                retries=config.retries,
                logger=logger,
            )
        return run_delete(
            config,
            delete_url=delete_url,
            log_path=log_path,
            lines=lines,
            interactive=interactive,
            dry_run=args.dry_run,
            force=args.force,
            logger=logger,
            transport=transport,
        )
    finally:
        if transport is not None:
            transport.close()
        close_logging(logger)


def _run_check(args: argparse.Namespace, config: Config, out_dir: Path) -> int:
    check_url = build_recommendations_url(config.clan_id, config.url)
    if not check_url:
        raise UsageError("无法构造校验接口地址，请提供 --har 或 --clan-id")
    if args.dry_run:
        print(f"[DRY] --check POST {check_url} data=sessionid=<hidden>")
        return 0
    logger = setup_logging(out_dir, config.log_level, "check.log")
    transport: HttpTransport | None = None
    try:
        transport = HttpTransport(
            proxies=config.proxy,
            timeout=config.timeout,
            retries=config.retries,
            logger=logger,
        )
        return run_check(config, url=check_url, logger=logger, transport=transport)
    finally:
        if transport is not None:
            transport.close()
        close_logging(logger)


def _run(args: argparse.Namespace) -> int:
    config, file_data = _load_config(args)
    out_dir = Path(config.out).expanduser().resolve()
    delete_mode = _delete_mode(args)
    _validate_modes(args, config, delete_mode)

    if args.status:
        return print_status(out_dir)

    endpoint = ENDPOINT_DELETE if delete_mode else "recommendations"
    har_info = _apply_har(args, config, endpoint=endpoint)
    _prepare_inputs(args, config, file_data, har_info)
    config.proxy = collect_proxies(config.proxy, config.proxy_file)

    if delete_mode:
        return _run_delete(args, config, out_dir)
    if args.check:
        return _run_check(args, config, out_dir)
    if config.url and "ajaxdeletereview" in config.url:
        raise UsageError(
            "该 HAR 只包含 ajaxdeletereview 请求，无法用于导出；"
            "请在 reviews_manage 页面加载列表后重新导出 HAR"
        )

    candidates = build_url_candidates(
        config.clan_id,
        config.name,
        config.url,
        config.source,
    )
    if not candidates:
        raise UsageError("无法构造接口地址，请提供 --clan-id 或 --url")

    logger = setup_logging(out_dir, config.log_level)
    transport: HttpTransport | None = None
    try:
        logger.info("组 ID: %s", config.clan_id or "(未知)")
        logger.info("数据源: %s", config.source)
        cookie_state = (
            f"已提供（{len(config.cookie)} 字符）" if config.cookie else "未提供"
        )
        logger.info("Cookie: %s", cookie_state)
        logger.info("sessionid: %s", "已提供" if config.sessionid else "未提供")
        if config.referer:
            logger.info("Referer（来自 HAR）: %s", config.referer)
        logger.info("输出目录: %s", out_dir)
        if config.proxy:
            logger.info(
                "代理: %d 个，按请求轮换 -> %s",
                len(config.proxy),
                ", ".join(mask_proxy(proxy) for proxy in config.proxy),
            )
        else:
            logger.info("代理: 未指定（将使用 HTTP_PROXY/HTTPS_PROXY 环境变量，未设置则直连）")

        if args.dry_run:
            logger.info("--dry-run 已启用，未发起任何网络请求。")
            for line in describe_config(config):
                logger.info(line)
            for candidate in candidates:
                logger.info("候选 URL: %s", candidate)
            return 0

        transport = HttpTransport(
            proxies=config.proxy,
            timeout=config.timeout,
            retries=config.retries,
            logger=logger,
        )
        source = build_source(config, transport, config.sessionid)
        runner = Runner(config, logger, transport, source, out_dir=out_dir)
        return runner.run()
    finally:
        if transport is not None:
            transport.close()
        close_logging(logger)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return _run(args)
    except AuthError as exc:
        print(f"错误：登录态异常：{exc}", file=sys.stderr)
        return 3
    except ConfigError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except SteamError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断。", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - final CLI safety net
        traceback.print_exc()
        print(f"错误：未预期异常：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

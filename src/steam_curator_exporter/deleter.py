"""Delete curator reviews through the admin AJAX delete endpoint."""

from __future__ import annotations

import json
import logging
import random
import re
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .errors import AuthError, ConfigError, SteamError
from .http import HttpTransport, default_headers
from .urls import SOURCE_ADMIN, build_referer

APPID_TOKEN_RE = re.compile(r"[0-9]{1,10}\Z")
APP_LINK_RE = re.compile(r"/(?:app|recommended)/(\d+)")
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
MAX_DETAIL_CHARS = 200

STATUS_OK = "OK"
STATUS_FAIL = "FAIL"
STATUS_DRY = "DRY"


@dataclass(slots=True)
class DeleteResult:
    """Outcome of one delete request."""

    status: str
    detail: str = ""
    http_status: str = ""


@dataclass(slots=True)
class DeleteStats:
    ok: int = 0
    fail: int = 0
    skip: int = 0
    preview: int = 0


def parse_appid_line(line: str, *, interactive: bool) -> tuple[str, str]:
    """Classify one input line as blank/comment/quit/appid/error.

    Interactive mode accepts ``q``/``quit``/``exit``; batch mode never quits
    early, so an appid file containing ``exit`` is reported as invalid instead
    of silently stopping halfway through.
    """
    text = line.strip()
    if not text:
        return "blank", ""
    if text.startswith("#"):
        return "comment", ""
    tokens = text.split()
    if len(tokens) > 1:
        return "error", "一行只能输入一个 appid"
    token = tokens[0]
    if interactive and token.lower() in {"q", "quit", "exit"}:
        return "quit", ""
    if APPID_TOKEN_RE.match(token):
        return "appid", token
    match = APP_LINK_RE.search(token)
    if match:
        return "appid", match.group(1)
    return "error", f"无法识别的 appid: {token}"


def iter_stdin() -> Iterator[str]:
    """Yield lines from stdin, showing a prompt only on a real terminal."""
    prompt = "appid> " if sys.stdin.isatty() else ""
    while True:
        try:
            yield input(prompt)
        except EOFError:
            return


def append_log(path: Path, appid: str, status: str, detail: str) -> None:
    """Append one tab-separated result line; flushed immediately."""
    detail_line = detail.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{timestamp}\t{appid}\t{status}\t{detail_line}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()
    except OSError as exc:
        raise ConfigError(f"写入删除日志失败: {exc}") from exc


def load_done(path: Path) -> set[str]:
    """Read previously successful appids from the delete log."""
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ConfigError(f"读取删除日志失败: {exc}") from exc
    done: set[str] = set()
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() == STATUS_OK:
            done.add(parts[1].strip())
    return done


def _json_payload(response: Any) -> Any:
    try:
        return response.json()
    except (ValueError, TypeError):
        return None


def _compact(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _failure_detail(payload: Any, response: Any) -> str:
    text = _compact(payload) if payload is not None else str(response.text)
    return text[:MAX_DETAIL_CHARS]


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None:
        try:
            seconds = int(retry_after.strip())
        except ValueError:
            seconds = -1
        if seconds >= 0:
            return float(seconds)
    return 2.0 * attempt + random.uniform(0.0, 0.5)


def delete_one(
    transport: HttpTransport,
    *,
    url: str,
    sessionid: str,
    cookie: str,
    referer: str,
    appid: str,
    attempts: int = MAX_ATTEMPTS,
    timeout: float,
    logger: logging.Logger,
) -> DeleteResult:
    """Send one delete request with a small, response-aware retry policy.

    A JSON body with ``success != 1`` is a definitive server answer (for example
    ``{"success": 42}`` for an unknown appid), so it is never retried even when
    the HTTP status is 500.
    """
    headers = default_headers(referer, cookie)
    data = {"appid": appid, "sessionid": sessionid}
    budget = max(1, attempts)
    result = DeleteResult(STATUS_FAIL, "", "ERR")

    for attempt in range(1, budget + 1):
        try:
            response = transport.request(
                "POST",
                url,
                data=data,
                headers=headers,
                timeout=timeout,
                retries=1,
                raise_for_status=False,
            )
        except AuthError:
            raise
        except SteamError as exc:
            result = DeleteResult(STATUS_FAIL, str(exc), "ERR")
            if attempt < budget:
                wait = _backoff(attempt, None)
                logger.info("网络错误，%.1f 秒后重试（第 %d/%d 次）", wait, attempt, budget)
                time.sleep(wait)
                continue
            return result

        status = int(response.status_code)
        payload = _json_payload(response)
        if status == 200 and isinstance(payload, dict) and payload.get("success") == 1:
            return DeleteResult(STATUS_OK, _compact(payload), str(status))

        result = DeleteResult(STATUS_FAIL, _failure_detail(payload, response), str(status))
        transient = status in RETRY_STATUSES and payload is None
        if transient and attempt < budget:
            wait = _backoff(attempt, response.headers.get("Retry-After"))
            logger.info(
                "服务端返回 %s，%.1f 秒后重试（第 %d/%d 次）",
                status,
                wait,
                attempt,
                budget,
            )
            time.sleep(wait)
            continue
        return result

    return result


def _print_summary(stats: DeleteStats, dry_run: bool) -> None:
    parts = [f"成功 {stats.ok}", f"失败 {stats.fail}", f"跳过 {stats.skip}"]
    if dry_run:
        parts.append(f"预演 {stats.preview}")
    print("汇总: " + " / ".join(parts))


def run_delete(
    config: Config,
    *,
    delete_url: str,
    log_path: Path,
    lines: Iterable[str],
    interactive: bool,
    dry_run: bool,
    force: bool,
    logger: logging.Logger,
    transport: HttpTransport | None,
) -> int:
    """Consume appid lines and delete each review in order."""
    done = set() if force else load_done(log_path)
    referer = config.referer or build_referer(delete_url, config.clan_id, SOURCE_ADMIN)
    stats = DeleteStats()
    requested = False

    try:
        for raw in lines:
            kind, value = parse_appid_line(raw, interactive=interactive)
            if kind in {"blank", "comment"}:
                continue
            if kind == "quit":
                break
            if kind == "error":
                print(value)
                stats.fail += 1
                continue

            appid = value
            if not force and appid in done:
                print(f"[SKIP] {appid} 之前已成功删除")
                stats.skip += 1
                continue
            if not dry_run and requested and config.delay > 0:
                time.sleep(config.delay)
            requested = True

            if dry_run:
                print(f"[DRY] {appid} POST {delete_url} data=appid={appid}&sessionid=<hidden>")
                append_log(log_path, appid, STATUS_DRY, "dry-run")
                stats.preview += 1
                continue

            if transport is None:
                raise ConfigError("内部错误：删除模式缺少 HTTP transport")

            result = delete_one(
                transport,
                url=delete_url,
                sessionid=config.sessionid or "",
                cookie=config.cookie or "",
                referer=referer,
                appid=appid,
                timeout=config.timeout,
                logger=logger,
            )
            if result.status == STATUS_OK:
                print(f"[OK] {appid} {result.detail}")
                append_log(log_path, appid, STATUS_OK, result.detail)
                done.add(appid)
                stats.ok += 1
            else:
                print(f"[FAIL] {appid} status={result.http_status} {result.detail}")
                append_log(
                    log_path,
                    appid,
                    STATUS_FAIL,
                    f"status={result.http_status} {result.detail}",
                )
                stats.fail += 1
    except KeyboardInterrupt:
        print()
        _print_summary(stats, dry_run)
        print("已中断。")
        return 1

    _print_summary(stats, dry_run)
    return 0 if stats.fail == 0 else 1


def run_check(
    config: Config,
    *,
    url: str,
    logger: logging.Logger,
    transport: HttpTransport,
) -> int:
    """Verify the login session with a read-only recommendations request."""
    referer = config.referer or build_referer(url, config.clan_id, SOURCE_ADMIN)
    headers = default_headers(referer, config.cookie)
    try:
        response = transport.request(
            "POST",
            url,
            data={"sessionid": config.sessionid or ""},
            headers=headers,
            timeout=config.timeout,
        )
    except AuthError:
        raise
    except SteamError as exc:
        print(f"检查失败: {exc}")
        return 1

    status = int(response.status_code)
    if status != 200:
        print(f"检查失败: HTTP {status}")
        return 1

    payload = _json_payload(response)
    if not isinstance(payload, dict) or payload.get("success") != 1:
        detail = _failure_detail(payload, response)
        raise AuthError(f"接口 success != 1，登录态可能已失效：{detail}")

    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        print("检查失败: 响应缺少 recommendations 列表")
        return 1

    total = payload.get("total_count")
    if isinstance(total, int):
        print(f"检查成功: 后台组评共 {total} 条（本页 {len(recommendations)} 条）")
    else:
        print(f"检查成功: 本页返回 {len(recommendations)} 条组评")
    for item in recommendations[:5]:
        if isinstance(item, dict):
            print(f"{item.get('appid')} {item.get('app_name', '')}")
    logger.debug("凭据校验完成，共 %d 条组评", len(recommendations))
    return 0
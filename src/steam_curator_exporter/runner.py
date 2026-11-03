"""Orchestration: endpoint resolution, pagination, resume, progress, exports."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .config import Config
from .errors import AuthError, SteamError
from .http import HttpTransport
from .models import entry_key, format_duration, item_appid
from .sources import Page, ReviewSource
from .storage import (
    append_entry,
    clean_outputs,
    export_outputs,
    load_existing_entries,
    load_state,
    save_raw_page,
    save_state,
)
from .urls import SOURCE_ADMIN, build_url_candidates

SNAPSHOT_EVERY_PAGES = 10


class Runner:
    """Run one export job against an injected source and transport."""

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        transport: HttpTransport,
        source: ReviewSource,
        out_dir: Path | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.transport = transport
        self.source = source
        self.out_dir = (out_dir or Path(config.out)).expanduser().resolve()
        self._sleep = sleep if sleep is not None else time.sleep
        self._jitter = jitter if jitter is not None else random.uniform

        self.state: dict[str, Any] = {}
        self.entries: dict[str, Mapping[str, Any]] = {}
        self.resolved_url: str | None = None
        self.next_start = 0
        self.total_count = 0
        self.pages = 0
        self.empty_seen = False
        self.run_started_at = 0.0
        self.run_start_offset = 0

    def run(self) -> int:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if self.config.fresh:
            clean_outputs(self.out_dir)

        self.state = load_state(self.out_dir)
        self.entries = load_existing_entries(self.out_dir)
        resume = bool(self.state) and not self.config.fresh
        if self.config.resume and self.state:
            resume = True

        if resume:
            self.next_start = _int(self.state.get("next_start"))
            self.total_count = _int(self.state.get("total_count"))
            self.resolved_url = self.config.url or _text(self.state.get("url")) or None
            self.empty_seen = bool(self.state.get("complete"))
            self.logger.info(
                "检测到断点：已抓取 %d 条，下次从 start=%d 继续",
                len(self.entries),
                self.next_start,
            )
        elif self.entries:
            self.logger.warning(
                "输出目录已有 %d 条旧数据；如需重来请加 --fresh",
                len(self.entries),
            )

        candidates = build_url_candidates(
            self.config.clan_id,
            self.config.name,
            self.config.url,
            self.config.source,
        )
        for candidate in candidates:
            self.logger.info("候选 URL: %s", candidate)

        first_payload: Page | None = None
        if self.resolved_url:
            self.logger.info("沿用断点记录的接口地址: %s", self.resolved_url)
        else:
            try:
                self.resolved_url, first_payload = self._resolve_endpoint(candidates)
            except AuthError as exc:
                self.logger.error("登录态异常：%s", exc)
                self._save_state()
                self._write_final_outputs()
                return 3
            except SteamError as exc:
                self.logger.error("抓取失败：%s", exc)
                self._save_state()
                self._write_final_outputs()
                return 1
            except Exception as exc:  # noqa: BLE001 - still export whatever exists
                self.logger.exception("未预期错误：%s", exc)
                self._save_state()
                self._write_final_outputs()
                return 1
            self.state.update(
                {
                    "url": self.resolved_url,
                    "clan_id": self.config.clan_id,
                    "source": self.config.source,
                    "next_start": self.next_start,
                    "total_count": self.total_count,
                }
            )
            self._save_state()

        self.run_started_at = time.monotonic()
        self.run_start_offset = self.next_start
        failed = False
        auth_failed = False

        try:
            if first_payload is not None:
                server_start = self._consume(first_payload)
                returned = len(first_payload.recommendations)
                self.next_start = max(self.next_start, server_start + returned)
                self.pages += 1
                self._save_state()
                self._log_progress()
                self._snapshot()
                if not first_payload.recommendations:
                    self.logger.info("首屏返回 0 条，视为抓取结束。")
                    self.empty_seen = True
                if self.config.keep_raw:
                    save_raw_page(self.out_dir, server_start, first_payload.raw)

            while self.pages < self.config.max_pages and not self.empty_seen:
                if self.total_count and self.next_start >= self.total_count:
                    self.logger.info("已到达 total_count=%d，抓取完成。", self.total_count)
                    break

                page = self.source.fetch_page(
                    self.resolved_url or "",
                    self.next_start,
                    self.config.count,
                )
                recommendations = page.recommendations
                if not recommendations:
                    self.logger.info("本次返回 0 条，视为抓取结束。")
                    self.empty_seen = True
                    if self.config.keep_raw:
                        save_raw_page(self.out_dir, page.server_start, page.raw)
                    break

                server_start = page.server_start
                if server_start != self.next_start and self.next_start > 0:
                    self.logger.warning(
                        "服务端返回 start=%d（请求 %d），以服务端为准",
                        server_start,
                        self.next_start,
                    )

                self._consume(page)
                self.pages += 1

                page_end = server_start + len(recommendations)
                if page_end <= self.next_start:
                    self.logger.error(
                        "分页没有前进（start=%d, 返回 %d 条），为避免死循环中止。",
                        server_start,
                        len(recommendations),
                    )
                    failed = True
                    break
                self.next_start = page_end
                self._save_state()
                self._log_progress()
                if self.pages % SNAPSHOT_EVERY_PAGES == 0:
                    self._snapshot()
                if self.config.keep_raw:
                    save_raw_page(self.out_dir, server_start, page.raw)
                if self.total_count and self.next_start >= self.total_count:
                    break
                if self.config.delay > 0:
                    wait = self.config.delay * self._jitter(0.8, 1.2)
                    self._sleep(wait)

        except KeyboardInterrupt:
            self.logger.warning("已被用户中断，正在保存进度...")
            failed = True
        except AuthError as exc:
            self.logger.error("登录态异常：%s", exc)
            auth_failed = True
        except SteamError as exc:
            self.logger.error("抓取失败：%s", exc)
            failed = True
        except Exception as exc:  # noqa: BLE001 - catch-all must still export data
            self.logger.exception("未预期错误：%s", exc)
            failed = True
        finally:
            self._save_state()

        self._write_final_outputs()

        if auth_failed:
            return 3
        if failed:
            return 1
        if (
            self.config.source == SOURCE_ADMIN
            and self.total_count
            and self.next_start < self.total_count
        ):
            return 4
        return 0

    def _resolve_endpoint(self, candidates: list[str]) -> tuple[str, Page]:
        errors: list[str] = []
        for url in candidates:
            self.logger.info("尝试接口地址: %s", url)
            try:
                page = self.source.fetch_page(url, 0, self.config.count)
            except AuthError:
                raise
            except SteamError as exc:
                self.logger.warning("该地址不可用: %s", exc)
                errors.append(f"{url} -> {exc}")
                continue
            self.logger.info("接口地址可用，total_count=%s", page.total_count)
            return url, page
        raise SteamError("所有候选接口地址均不可用:\n  " + "\n  ".join(errors))

    def _consume(self, page: Page) -> int:
        """Persist every row before deduplicating, then update unique entries."""
        if page.total_count is not None:
            self.total_count = page.total_count
        new_count = 0
        for item in page.recommendations:
            append_entry(self.out_dir, item)
            if not item_appid(item):
                continue
            key = entry_key(item)
            if key in self.entries:
                continue
            self.entries[key] = item
            new_count += 1

        self.logger.info(
            "start=%-6d 返回 %2d 条（新增 %2d），累计 %d / %d",
            page.server_start,
            len(page.recommendations),
            new_count,
            len(self.entries),
            self.total_count,
        )
        return page.server_start

    def _log_progress(self) -> None:
        if not self.total_count:
            self.logger.info("进度：已拉取 %d 条（服务端总数未知）", len(self.entries))
            return
        percent = min(100.0, self.next_start / self.total_count * 100)
        elapsed = time.monotonic() - self.run_started_at
        handled = self.next_start - self.run_start_offset
        if handled > 0 and elapsed > 0:
            remaining = max(0, self.total_count - self.next_start)
            eta = remaining / (handled / elapsed)
            self.logger.info(
                "进度：%d/%d（%.1f%%），本轮用时 %s，预计剩余 %s",
                self.next_start,
                self.total_count,
                percent,
                format_duration(elapsed),
                format_duration(eta),
            )
        else:
            self.logger.info("进度：%d/%d（%.1f%%）", self.next_start, self.total_count, percent)

    def _snapshot(self) -> None:
        if not self.entries:
            return
        export_outputs(
            self.out_dir,
            self.entries.values(),
            self._meta(),
            self.config.formats,
        )

    def _meta(self) -> dict[str, Any]:
        return {
            "source": self.config.source,
            "source_url": self.resolved_url,
            "clan_id": self.config.clan_id,
            "total_count": self.total_count,
        }

    def _is_complete(self) -> bool:
        if self.total_count:
            return self.next_start >= self.total_count
        return self.empty_seen

    def _save_state(self) -> None:
        self.state.update(
            {
                "next_start": self.next_start,
                "total_count": self.total_count,
                "url": self.resolved_url,
                "clan_id": self.config.clan_id,
                "source": self.config.source,
                "complete": self._is_complete(),
            }
        )
        save_state(self.out_dir, self.state)

    def _write_final_outputs(self) -> None:
        counts = export_outputs(
            self.out_dir,
            self.entries.values(),
            self._meta(),
            self.config.formats,
        )
        total = len(self.entries)
        self.logger.info("-" * 50)
        for name in self.config.formats:
            if name == "json":
                self.logger.info(
                    "导出 %d 条到 %s",
                    counts.get("json", total),
                    self.out_dir / "reviews.json",
                )
            elif name == "csv":
                self.logger.info(
                    "导出 %d 条到 %s",
                    counts.get("csv", total),
                    self.out_dir / "reviews.csv",
                )
            elif name == "sqlite":
                self.logger.info(
                    "导出 %d 条到 %s",
                    counts.get("sqlite", total),
                    self.out_dir / "reviews.sqlite3",
                )
        if counts.get("csv_skipped"):
            self.logger.warning(
                "有 %d 条记录缺少 appid（已写入 CSV 但内容可能异常）",
                counts["csv_skipped"],
            )

        pagination_done = self._is_complete()
        if self.total_count and not pagination_done:
            self.logger.warning(
                "尚未抓完：分页 %d/%d，重跑原命令可断点续传",
                self.next_start,
                self.total_count,
            )
        elif pagination_done:
            if self.total_count:
                self.logger.info("分页已完成：%d/%d", self.next_start, self.total_count)
            else:
                self.logger.info("抓取已完成（服务端未提供总数字段）")
            if self.total_count and total < self.total_count:
                self.logger.info(
                    "本地唯一组评 %d 条，比 total_count 少 %d 条；"
                    "差额来自重复/已删除条目，导出时已按组评身份去重",
                    total,
                    self.total_count - total,
                )
        self.logger.info("-" * 50)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def print_status(out_dir: Path) -> int:
    """Read only the output directory and print resume progress."""
    if not out_dir.exists():
        print(f"输出目录不存在：{out_dir}")
        return 1

    state = load_state(out_dir)
    entries = load_existing_entries(out_dir)
    total_count = _int(state.get("total_count"))
    next_start = _int(state.get("next_start"))
    unique_count = len(entries)

    print(f"输出目录：{out_dir}")
    print(f"唯一组评数：{unique_count} 条（按 游戏+评测者+时间 去重）")
    if total_count:
        percent = min(100.0, next_start / total_count * 100)
        print(f"服务端总数：{total_count}")
        print(f"抓取进度：{next_start}/{total_count}（{percent:.1f}%）")
    else:
        print("服务端总数：未知（尚未成功请求，或 state.json 缺失）")
        print(f"抓取进度：{next_start}/未知")
    print(f"分页偏移：next_start={next_start}")
    print(f"上次更新：{state.get('updated_at', '未知')}")

    complete = bool(state.get("complete")) or (
        bool(total_count) and next_start >= total_count
    )
    if complete:
        print("状态：已完成（complete）")
    elif next_start > 0:
        print("状态：未完成（incomplete），重跑原命令即可断点续传")
    else:
        print("状态：尚未开始（not started）")
    return 0

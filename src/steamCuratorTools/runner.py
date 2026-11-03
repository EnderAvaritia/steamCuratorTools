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
from .models import entryKey, formatDuration, itemAppid
from .sources import Page, ReviewSource
from .storage import (
    appendEntry,
    cleanOutputs,
    exportOutputs,
    loadExistingEntries,
    loadState,
    saveRawPage,
    saveState,
)
from .urls import buildUrlCandidates, sourceAdmin

snapshotEveryPages = 10


class Runner:
    """Run one export job against an injected source and transport."""

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        transport: HttpTransport,
        source: ReviewSource,
        outDir: Path | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.transport = transport
        self.source = source
        self.outDir = (outDir or Path(config.out)).expanduser().resolve()
        self._sleep = sleep if sleep is not None else time.sleep
        self._jitter = jitter if jitter is not None else random.uniform

        self.state: dict[str, Any] = {}
        self.entries: dict[str, Mapping[str, Any]] = {}
        self.resolvedUrl: str | None = None
        self.nextStart = 0
        self.totalCount = 0
        self.pages = 0
        self.emptySeen = False
        self.runStartedAt = 0.0
        self.runStartOffset = 0

    def run(self) -> int:
        self.outDir.mkdir(parents=True, exist_ok=True)
        if self.config.fresh:
            cleanOutputs(self.outDir)

        self.state = loadState(self.outDir)
        self.entries = loadExistingEntries(self.outDir)
        resume = bool(self.state) and not self.config.fresh
        if self.config.resume and self.state:
            resume = True

        if resume:
            self.nextStart = _int(self.state.get("next_start"))
            self.totalCount = _int(self.state.get("total_count"))
            self.resolvedUrl = self.config.url or _text(self.state.get("url")) or None
            self.emptySeen = bool(self.state.get("complete"))
            self.logger.info(
                "检测到断点：已抓取 %d 条，下次从 start=%d 继续",
                len(self.entries),
                self.nextStart,
            )
        elif self.entries:
            self.logger.warning(
                "输出目录已有 %d 条旧数据；如需重来请加 --fresh",
                len(self.entries),
            )

        candidates = buildUrlCandidates(
            self.config.clanId,
            self.config.name,
            self.config.url,
            self.config.source,
        )
        for candidate in candidates:
            self.logger.info("候选 URL: %s", candidate)

        firstPayload: Page | None = None
        if self.resolvedUrl:
            self.logger.info("沿用断点记录的接口地址: %s", self.resolvedUrl)
        else:
            try:
                self.resolvedUrl, firstPayload = self._resolveEndpoint(candidates)
            except AuthError as exc:
                self.logger.error("登录态异常：%s", exc)
                self._saveState()
                self._writeFinalOutputs()
                return 3
            except SteamError as exc:
                self.logger.error("抓取失败：%s", exc)
                self._saveState()
                self._writeFinalOutputs()
                return 1
            except Exception as exc:  # noqa: BLE001 - still export whatever exists
                self.logger.exception("未预期错误：%s", exc)
                self._saveState()
                self._writeFinalOutputs()
                return 1
            self.state.update(
                {
                    "url": self.resolvedUrl,
                    "clan_id": self.config.clanId,
                    "source": self.config.source,
                    "next_start": self.nextStart,
                    "total_count": self.totalCount,
                }
            )
            self._saveState()

        self.runStartedAt = time.monotonic()
        self.runStartOffset = self.nextStart
        failed = False
        authFailed = False

        try:
            if firstPayload is not None:
                serverStart = self._consume(firstPayload)
                returned = len(firstPayload.recommendations)
                self.nextStart = max(self.nextStart, serverStart + returned)
                self.pages += 1
                self._saveState()
                self._logProgress()
                self._snapshot()
                if not firstPayload.recommendations:
                    self.logger.info("首屏返回 0 条，视为抓取结束。")
                    self.emptySeen = True
                if self.config.keepRaw:
                    saveRawPage(self.outDir, serverStart, firstPayload.raw)

            while self.pages < self.config.maxPages and not self.emptySeen:
                if self.totalCount and self.nextStart >= self.totalCount:
                    self.logger.info("已到达 total_count=%d，抓取完成。", self.totalCount)
                    break

                page = self.source.fetchPage(
                    self.resolvedUrl or "",
                    self.nextStart,
                    self.config.count,
                )
                recommendations = page.recommendations
                if not recommendations:
                    self.logger.info("本次返回 0 条，视为抓取结束。")
                    self.emptySeen = True
                    if self.config.keepRaw:
                        saveRawPage(self.outDir, page.serverStart, page.raw)
                    break

                serverStart = page.serverStart
                if serverStart != self.nextStart and self.nextStart > 0:
                    self.logger.warning(
                        "服务端返回 start=%d（请求 %d），以服务端为准",
                        serverStart,
                        self.nextStart,
                    )

                self._consume(page)
                self.pages += 1

                pageEnd = serverStart + len(recommendations)
                if pageEnd <= self.nextStart:
                    self.logger.error(
                        "分页没有前进（start=%d, 返回 %d 条），为避免死循环中止。",
                        serverStart,
                        len(recommendations),
                    )
                    failed = True
                    break
                self.nextStart = pageEnd
                self._saveState()
                self._logProgress()
                if self.pages % snapshotEveryPages == 0:
                    self._snapshot()
                if self.config.keepRaw:
                    saveRawPage(self.outDir, serverStart, page.raw)
                if self.totalCount and self.nextStart >= self.totalCount:
                    break
                if self.config.delay > 0:
                    wait = self.config.delay * self._jitter(0.8, 1.2)
                    self._sleep(wait)

        except KeyboardInterrupt:
            self.logger.warning("已被用户中断，正在保存进度...")
            failed = True
        except AuthError as exc:
            self.logger.error("登录态异常：%s", exc)
            authFailed = True
        except SteamError as exc:
            self.logger.error("抓取失败：%s", exc)
            failed = True
        except Exception as exc:  # noqa: BLE001 - catch-all must still export data
            self.logger.exception("未预期错误：%s", exc)
            failed = True
        finally:
            self._saveState()

        self._writeFinalOutputs()

        if authFailed:
            return 3
        if failed:
            return 1
        if (
            self.config.source == sourceAdmin
            and self.totalCount
            and self.nextStart < self.totalCount
        ):
            return 4
        return 0

    def _resolveEndpoint(self, candidates: list[str]) -> tuple[str, Page]:
        errors: list[str] = []
        for url in candidates:
            self.logger.info("尝试接口地址: %s", url)
            try:
                page = self.source.fetchPage(url, 0, self.config.count)
            except AuthError:
                raise
            except SteamError as exc:
                self.logger.warning("该地址不可用: %s", exc)
                errors.append(f"{url} -> {exc}")
                continue
            self.logger.info("接口地址可用，total_count=%s", page.totalCount)
            return url, page
        raise SteamError("所有候选接口地址均不可用:\n  " + "\n  ".join(errors))

    def _consume(self, page: Page) -> int:
        """Persist every row before deduplicating, then update unique entries."""
        if page.totalCount is not None:
            self.totalCount = page.totalCount
        newCount = 0
        for item in page.recommendations:
            appendEntry(self.outDir, item)
            if not itemAppid(item):
                continue
            key = entryKey(item)
            if key in self.entries:
                continue
            self.entries[key] = item
            newCount += 1

        self.logger.info(
            "start=%-6d 返回 %2d 条（新增 %2d），累计 %d / %d",
            page.serverStart,
            len(page.recommendations),
            newCount,
            len(self.entries),
            self.totalCount,
        )
        return page.serverStart

    def _logProgress(self) -> None:
        if not self.totalCount:
            self.logger.info("进度：已拉取 %d 条（服务端总数未知）", len(self.entries))
            return
        percent = min(100.0, self.nextStart / self.totalCount * 100)
        elapsed = time.monotonic() - self.runStartedAt
        handled = self.nextStart - self.runStartOffset
        if handled > 0 and elapsed > 0:
            remaining = max(0, self.totalCount - self.nextStart)
            eta = remaining / (handled / elapsed)
            self.logger.info(
                "进度：%d/%d（%.1f%%），本轮用时 %s，预计剩余 %s",
                self.nextStart,
                self.totalCount,
                percent,
                formatDuration(elapsed),
                formatDuration(eta),
            )
        else:
            self.logger.info("进度：%d/%d（%.1f%%）", self.nextStart, self.totalCount, percent)

    def _snapshot(self) -> None:
        if not self.entries:
            return
        exportOutputs(
            self.outDir,
            self.entries.values(),
            self._meta(),
            self.config.formats,
        )

    def _meta(self) -> dict[str, Any]:
        return {
            "source": self.config.source,
            "source_url": self.resolvedUrl,
            "clan_id": self.config.clanId,
            "total_count": self.totalCount,
        }

    def _isComplete(self) -> bool:
        if self.totalCount:
            return self.nextStart >= self.totalCount
        return self.emptySeen

    def _saveState(self) -> None:
        self.state.update(
            {
                "next_start": self.nextStart,
                "total_count": self.totalCount,
                "url": self.resolvedUrl,
                "clan_id": self.config.clanId,
                "source": self.config.source,
                "complete": self._isComplete(),
            }
        )
        saveState(self.outDir, self.state)

    def _writeFinalOutputs(self) -> None:
        counts = exportOutputs(
            self.outDir,
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
                    self.outDir / "reviews.json",
                )
            elif name == "csv":
                self.logger.info(
                    "导出 %d 条到 %s",
                    counts.get("csv", total),
                    self.outDir / "reviews.csv",
                )
            elif name == "sqlite":
                self.logger.info(
                    "导出 %d 条到 %s",
                    counts.get("sqlite", total),
                    self.outDir / "reviews.sqlite3",
                )
        if counts.get("csv_skipped"):
            self.logger.warning(
                "有 %d 条记录缺少 appid（已写入 CSV 但内容可能异常）",
                counts["csv_skipped"],
            )

        paginationDone = self._isComplete()
        if self.totalCount and not paginationDone:
            self.logger.warning(
                "尚未抓完：分页 %d/%d，重跑原命令可断点续传",
                self.nextStart,
                self.totalCount,
            )
        elif paginationDone:
            if self.totalCount:
                self.logger.info("分页已完成：%d/%d", self.nextStart, self.totalCount)
            else:
                self.logger.info("抓取已完成（服务端未提供总数字段）")
            if self.totalCount and total < self.totalCount:
                self.logger.info(
                    "本地唯一组评 %d 条，比 total_count 少 %d 条；"
                    "差额来自重复/已删除条目，导出时已按组评身份去重",
                    total,
                    self.totalCount - total,
                )
        self.logger.info("-" * 50)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def printStatus(outDir: Path) -> int:
    """Read only the output directory and print resume progress."""
    if not outDir.exists():
        print(f"输出目录不存在：{outDir}")
        return 1

    state = loadState(outDir)
    entries = loadExistingEntries(outDir)
    totalCount = _int(state.get("total_count"))
    nextStart = _int(state.get("next_start"))
    uniqueCount = len(entries)

    print(f"输出目录：{outDir}")
    print(f"唯一组评数：{uniqueCount} 条（按 游戏+评测者+时间 去重）")
    if totalCount:
        percent = min(100.0, nextStart / totalCount * 100)
        print(f"服务端总数：{totalCount}")
        print(f"抓取进度：{nextStart}/{totalCount}（{percent:.1f}%）")
    else:
        print("服务端总数：未知（尚未成功请求，或 state.json 缺失）")
        print(f"抓取进度：{nextStart}/未知")
    print(f"分页偏移：next_start={nextStart}")
    print(f"上次更新：{state.get('updated_at', '未知')}")

    complete = bool(state.get("complete")) or (
        bool(totalCount) and nextStart >= totalCount
    )
    if complete:
        print("状态：已完成（complete）")
    elif nextStart > 0:
        print("状态：未完成（incomplete），重跑原命令即可断点续传")
    else:
        print("状态：尚未开始（not started）")
    return 0

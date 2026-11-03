"""Tkinter application shell and background workflow orchestration."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from email.utils import getaddresses
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any

from ..manager import EmailContent, EmailManager
from ..settings import isValidEmail
from ..steamInfo import SteamInfoExtractor
from .buttonPanel import ButtonPanel
from .dialogs import openConfigDialog, openTemplateDialog
from .emailPanel import EmailPanel
from .infoPanel import InfoPanel
from .inputPanel import InputPanel

loggerName = "steamCuratorTools.emailHelper"
statusColors = {"info": "black", "warning": "#b36b00", "error": "red", "success": "green"}


def configureLogging(logPath: Path) -> logging.Logger:
    logger = logging.getLogger(loggerName)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        logPath.parent.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fileHandler = logging.FileHandler(logPath, encoding="utf-8")
        fileHandler.setLevel(logging.DEBUG)
        fileHandler.setFormatter(formatter)
        consoleHandler = logging.StreamHandler()
        consoleHandler.setLevel(logging.INFO)
        consoleHandler.setFormatter(formatter)
        logger.addHandler(fileHandler)
        logger.addHandler(consoleHandler)
    return logger


class EmailHelperApp(tk.Tk):
    def __init__(
        self,
        manager: EmailManager | None = None,
        extractor: SteamInfoExtractor | None = None,
    ) -> None:
        super().__init__()
        self.manager = manager or EmailManager()
        self.logger = configureLogging(self.manager.logPath)
        self.extractor = extractor or SteamInfoExtractor(
            proxyProvider=self.manager.requestsProxies,
            logger=self.logger.getChild("steam"),
        )

        self.title("Steam 发行商邮件助手")
        self.geometry("920x760")
        self._closing = False
        self._busy = False
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()

        self.appid = ""
        self.gameName = ""
        self.publisherName = ""
        self.publisherEmail = ""
        self.steamUrl = ""
        self.emailContent: EmailContent | None = None

        self._createWidgets()
        self.protocol("WM_DELETE_WINDOW", self._onClose)
        self.updateStatus("准备就绪，请输入 Steam URL。", "info")
        self.after(100, self._drainQueue)

    def _createWidgets(self) -> None:
        self.inputPanel = InputPanel(self, self)
        self.infoPanel = InfoPanel(self, self)
        self.emailPanel = EmailPanel(self)
        self.buttonPanel = ButtonPanel(self, self)

        self.inputPanel.pack(padx=5, pady=5, fill="x")
        self.infoPanel.pack(padx=5, pady=5, fill="x")
        self.emailPanel.pack(padx=5, pady=5, fill="both", expand=True)
        self.buttonPanel.pack(pady=5)

    # ---- main-thread helpers -----------------------------------------
    def updateStatus(self, message: str, messageType: str = "info") -> None:
        color = statusColors.get(messageType, "black")
        self.inputPanel.setStatus(message, color)
        if messageType == "error":
            self.logger.error(message)
        elif messageType == "warning":
            self.logger.warning(message)
        else:
            self.logger.info(message)

    def postStatus(self, message: str, messageType: str = "info") -> None:
        if not self._closing:
            self._queue.put({"kind": "status", "message": message, "type": messageType})

    def postCall(self, func: Callable[..., Any], *args: Any) -> None:
        if not self._closing:
            self._queue.put({"kind": "call", "func": func, "args": args})

    def postBusy(self, value: bool) -> None:
        if not self._closing:
            self._queue.put({"kind": "busy", "value": value})

    def _drainQueue(self) -> None:
        if self._closing:
            return
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            kind = item.get("kind")
            try:
                if kind == "status":
                    self.updateStatus(item["message"], item["type"])
                elif kind == "call":
                    item["func"](*item["args"])
                elif kind == "busy":
                    self._setBusy(bool(item["value"]))
            except Exception as exc:  # noqa: BLE001 - keep the UI alive
                self.logger.exception("处理界面更新失败: %s", exc)
        self.after(100, self._drainQueue)

    def _setBusy(self, value: bool) -> None:
        self._busy = value
        enabled = not value
        self.inputPanel.setEnabled(enabled)
        self.infoPanel.setEnabled(enabled)
        self.buttonPanel.setEnabled(enabled)

    # ---- input actions ------------------------------------------------
    def pasteFromClipboard(self) -> None:
        try:
            import pyperclip
        except ImportError:
            messagebox.showerror(
                "缺少依赖",
                '未安装 pyperclip，请先运行：pip install -e ".[gui]"',
                parent=self,
            )
            return
        try:
            text = pyperclip.paste()
        except Exception as exc:  # pyperclip raises platform-specific errors
            self.updateStatus(f"读取剪贴板失败：{exc}", "error")
            return
        self.inputPanel.setUrlsText(text)
        self.updateStatus("剪贴板内容已粘贴。", "success")

    def browseCsvFile(self) -> None:
        path = filedialog.askopenfilename(
            title="选择发行商邮箱 CSV 文件",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self,
        )
        if not path:
            return
        self.inputPanel.setCsvPath(path)
        self.updateStatus(f"已选择 CSV：{Path(path).name}", "success")

    def clearAllFields(self) -> None:
        if self._busy:
            self.updateStatus("正在处理中，请稍后再清空。", "warning")
            return
        self.inputPanel.clear()
        self.infoPanel.clear()
        self.emailPanel.clear()
        self.appid = ""
        self.gameName = ""
        self.publisherName = ""
        self.publisherEmail = ""
        self.steamUrl = ""
        self.emailContent = None
        self.updateStatus("所有字段已清空。", "info")

    # ---- config and templates ----------------------------------------
    def openTemplateDialog(self, kind: str) -> None:
        openTemplateDialog(
            self,
            self.manager,
            kind,
            onSaved=lambda: self.startProcessUrls(auto=True),
        )

    def openConfigDialog(self) -> None:
        openConfigDialog(
            self,
            self.manager,
            onSaved=lambda: self.startProcessUrls(auto=True),
        )

    # ---- URL processing ----------------------------------------------
    def startProcessUrls(self, auto: bool = False) -> None:
        if self._busy:
            return
        urlsText = self.inputPanel.getUrlsText()
        csvPath = self.inputPanel.getCsvPath()
        if auto and (not urlsText or not csvPath):
            return
        if not urlsText:
            self.updateStatus("请输入至少一个 Steam URL。", "warning")
            return
        if not csvPath:
            self.updateStatus("请选择发行商邮箱 CSV 文件。", "warning")
            return

        urls = [line.strip() for line in urlsText.splitlines() if line.strip()]
        if not urls:
            self.updateStatus("未检测到有效的 Steam URL。", "warning")
            return

        self.infoPanel.clear()
        self.emailPanel.clear()
        self.emailContent = None
        self.publisherEmail = ""
        self._setBusy(True)
        self.updateStatus("正在后台获取游戏信息，请稍候...", "info")
        thread = threading.Thread(
            target=self._processUrls, args=(urls, csvPath), daemon=True
        )
        thread.start()

    def _processUrls(self, urls: list[str], csvPath: str) -> None:
        try:
            appids: list[str] = []
            for url in urls:
                appid = self.extractor.extractAppidFromUrl(url)
                if not appid:
                    self.postStatus(f"无法从 URL 提取 AppID：{url}", "error")
                    return
                appids.append(appid)

            unique = set(appids)
            if len(unique) != 1:
                self.postStatus(
                    f"检测到多个不同 AppID（{', '.join(sorted(unique))}），"
                    "请确保所有 URL 指向同一个游戏。",
                    "error",
                )
                return

            appid = appids[0]
            self.postCall(self.infoPanel.setAppid, appid)

            info = self.extractor.getGameInfoFromAppid(appid)
            if not info:
                self.postStatus("获取游戏信息失败，请检查 AppID 或网络连接。", "error")
                return

            gameName = info.get("game_name") or "未知游戏名"
            publisherName = info.get("publisher_name") or "未知发行商"
            self.postCall(
                self._applyGameInfo,
                appid,
                gameName,
                publisherName,
                "\n".join(urls),
            )

            email = self.manager.lookupPublisherEmail(publisherName, csvPath)
            source = "CSV"
            if not email:
                self.postStatus(
                    f"CSV 中未匹配到发行商 '{publisherName}'，"
                    "正在尝试从 Steam 帮助页面提取邮箱...",
                    "warning",
                )
                email = self.extractor.getEmailFromSteamHelp(appid)
                source = "Steam 帮助页面"

            if email:
                self.postCall(self._applyPublisherEmail, email)
            else:
                self.postCall(self._applyPublisherEmail, "")

            content = self.manager.buildContent(
                toEmail=email or "",
                gameName=gameName,
                publisherName=publisherName,
                appid=appid,
                steamUrl="\n".join(urls),
            )
            self.postCall(self._applyContent, content)

            if (
                email
                and source != "CSV"
                and not self.manager.savePublisherEmail(publisherName, email, csvPath)
            ):
                self.postStatus("邮箱已提取，但写入 CSV 失败。", "warning")

            if email:
                self.postStatus(f"信息已获取，发行商邮箱来自{source}。", "success")
            else:
                self.postStatus(
                    "未找到发行商邮箱，请点击“修改发行商邮箱”手动填写。",
                    "warning",
                )
        except Exception as exc:  # noqa: BLE001 - report to the status bar
            self.logger.exception("处理 URL 时发生未预期错误: %s", exc)
            self.postStatus(f"处理 URL 时发生意外错误：{exc}", "error")
        finally:
            self.postBusy(False)

    def _applyGameInfo(
        self, appid: str, gameName: str, publisherName: str, steamUrl: str
    ) -> None:
        self.appid = appid
        self.gameName = gameName
        self.publisherName = publisherName
        self.steamUrl = steamUrl
        self.infoPanel.setAppid(appid)
        self.infoPanel.setGameName(gameName)
        self.infoPanel.setPublisherName(publisherName)

    def _applyPublisherEmail(self, email: str) -> None:
        self.publisherEmail = email
        self.infoPanel.setPublisherEmail(email)
        self.emailPanel.setToEmail(email)

    def _applyContent(self, content: EmailContent) -> None:
        self.emailContent = content
        self.emailPanel.setContent(content)

    # ---- info editing -------------------------------------------------
    def editPublisherName(self) -> None:
        current = self.infoPanel.getPublisherName()
        newName = simpledialog.askstring(
            "修改发行商名称", "请输入新的发行商名称:", initialvalue=current, parent=self
        )
        if not newName or not newName.strip():
            return
        self.publisherName = newName.strip()
        self.infoPanel.setPublisherName(self.publisherName)
        self.regenerateContent()
        self.updateStatus(f"发行商名称已修改为：{self.publisherName}", "info")

    def editPublisherEmail(self) -> None:
        newEmail = simpledialog.askstring(
            "修改发行商邮箱",
            "请输入新的邮箱地址:",
            initialvalue=self.infoPanel.getPublisherEmail(),
            parent=self,
        )
        if newEmail is None:
            return
        value = newEmail.strip()
        if not isValidEmail(value):
            self.updateStatus("邮箱地址格式不正确。", "error")
            return
        self.publisherEmail = value
        self.infoPanel.setPublisherEmail(value)
        self.emailPanel.setToEmail(value)
        if self.manager.savePublisherEmail(
            self.infoPanel.getPublisherName(), value, self.inputPanel.getCsvPath()
        ):
            self.updateStatus(f"发行商邮箱已修改并写入 CSV：{value}", "success")
        else:
            self.updateStatus(f"发行商邮箱已修改为：{value}（写入 CSV 失败）", "warning")

    def savePublisherToCsv(self) -> None:
        name = self.infoPanel.getPublisherName()
        email = self.infoPanel.getPublisherEmail()
        if not name or not email:
            self.updateStatus("发行商名称或邮箱为空，未保存。", "warning")
            return
        if not isValidEmail(email):
            self.updateStatus("邮箱地址格式不正确。", "error")
            return
        if self.manager.savePublisherEmail(name, email, self.inputPanel.getCsvPath()):
            self.updateStatus("已保存到 CSV。", "success")
        else:
            self.updateStatus("保存到 CSV 失败。", "error")

    def regenerateContent(self) -> None:
        if not self.appid:
            return
        content = self.manager.buildContent(
            toEmail=self.infoPanel.getPublisherEmail(),
            gameName=self.gameName,
            publisherName=self.publisherName,
            appid=self.appid,
            steamUrl=self.steamUrl or self.inputPanel.getUrlsText(),
        )
        self._applyContent(content)

    # ---- sending ------------------------------------------------------
    def startSendEmail(self) -> None:
        if self._busy:
            return
        content = self.emailPanel.getContent()
        recipients = [
            address
            for _, address in getaddresses([content.toEmail.replace(";", ",")])
            if address
        ]
        if not recipients or any(not isValidEmail(address) for address in recipients):
            self.updateStatus("收件人邮箱地址无效。", "error")
            return
        if not content.subject:
            self.updateStatus("邮件主题不能为空。", "error")
            return
        if not content.body:
            self.updateStatus("邮件正文不能为空。", "error")
            return

        self._setBusy(True)
        self.updateStatus("正在后台发送邮件，请稍候...", "info")
        thread = threading.Thread(
            target=self._sendEmail, args=(content,), daemon=True
        )
        thread.start()

    def _sendEmail(self, content: EmailContent) -> None:
        try:
            success, message = self.manager.sendEmail(
                content.toEmail,
                content.subject,
                content.body,
                content.fromDisplay,
            )
            if success:
                self.postStatus(f"邮件已发送至 {content.toEmail}。", "success")
            else:
                self.postStatus(f"发送失败：{message}", "error")
        except Exception as exc:  # noqa: BLE001 - report to the status bar
            self.logger.exception("发送邮件时发生未预期错误: %s", exc)
            self.postStatus(f"发送邮件时发生意外错误：{exc}", "error")
        finally:
            self.postBusy(False)

    # ---- lifecycle ----------------------------------------------------
    def _onClose(self) -> None:
        self._closing = True
        try:
            self.extractor.close()
        finally:
            self.destroy()


def run(argv: list[str] | None = None) -> int:
    del argv
    app = EmailHelperApp()
    app.mainloop()
    return 0
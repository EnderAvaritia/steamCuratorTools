"""URL/CSV input panel."""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import EmailHelperApp


class InputPanel(tk.LabelFrame):
    def __init__(self, parent: tk.Misc, app: EmailHelperApp) -> None:
        super().__init__(parent, text="输入信息", padx=5, pady=5)
        self.app = app
        self._createWidgets()

    def _createWidgets(self) -> None:
        self.grid_columnconfigure(1, weight=1)

        tk.Label(self, text="Steam URL(s):").grid(
            row=0, column=0, sticky="nw", padx=2, pady=2
        )
        self.urlEntry = scrolledtext.ScrolledText(self, wrap=tk.WORD, width=50, height=4)
        self.urlEntry.grid(row=0, column=1, sticky="ew", padx=2, pady=2)

        self.pasteButton = tk.Button(self, text="粘贴", command=self.app.pasteFromClipboard)
        self.pasteButton.grid(row=0, column=2, sticky="n", padx=2, pady=2)

        tk.Label(self, text="发行商邮箱 CSV:").grid(
            row=1, column=0, sticky="w", padx=2, pady=2
        )
        self.csvPathEntry = tk.Entry(self, width=50)
        self.csvPathEntry.grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        self.csvPathEntry.insert(0, str(self.app.manager.publishersPath))

        self.browseCsvButton = tk.Button(self, text="选择 CSV", command=self.app.browseCsvFile)
        self.browseCsvButton.grid(row=1, column=2, padx=2, pady=2)

        templateBar = tk.Frame(self)
        templateBar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=2)
        self.templateButtons = [
            tk.Button(
                templateBar,
                text="编辑主题",
                command=lambda: self.app.openTemplateDialog("subject"),
            ),
            tk.Button(
                templateBar,
                text="编辑发件人",
                command=lambda: self.app.openTemplateDialog("from"),
            ),
            tk.Button(
                templateBar,
                text="编辑正文",
                command=lambda: self.app.openTemplateDialog("body"),
            ),
        ]
        for button in self.templateButtons:
            button.pack(side=tk.LEFT, padx=2, pady=2)

        actionBar = tk.Frame(self)
        actionBar.grid(row=3, column=0, columnspan=3, sticky="ew", pady=5)
        actionBar.grid_columnconfigure(2, weight=1)

        self.configButton = tk.Button(
            actionBar, text="配置邮件服务", command=self.app.openConfigDialog
        )
        self.configButton.grid(row=0, column=0, sticky="w", padx=2, pady=2)

        self.processButton = tk.Button(
            actionBar, text="处理 URL 并生成邮件", command=self.app.startProcessUrls
        )
        self.processButton.grid(row=0, column=1, sticky="w", padx=2, pady=2)

        self.statusLabel = tk.Label(
            actionBar, text="", fg="black", wraplength=420, justify="left"
        )
        self.statusLabel.grid(row=0, column=2, sticky="ew", padx=2, pady=2)

    def getUrlsText(self) -> str:
        return self.urlEntry.get(1.0, tk.END).strip()

    def setUrlsText(self, text: str) -> None:
        self.urlEntry.delete(1.0, tk.END)
        self.urlEntry.insert(1.0, text)

    def getCsvPath(self) -> str:
        return self.csvPathEntry.get().strip()

    def setCsvPath(self, path: str) -> None:
        self.csvPathEntry.delete(0, tk.END)
        self.csvPathEntry.insert(0, path)

    def setStatus(self, message: str, color: str = "black") -> None:
        self.statusLabel.config(text=message, fg=color)

    def setEnabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.pasteButton,
            self.browseCsvButton,
            self.configButton,
            self.processButton,
            *self.templateButtons,
        ):
            widget.config(state=state)

    def clear(self) -> None:
        self.setUrlsText("")
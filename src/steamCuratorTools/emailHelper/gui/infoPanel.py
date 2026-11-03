"""Game and publisher info panel."""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import EmailHelperApp


class InfoPanel(tk.LabelFrame):
    def __init__(self, parent: tk.Misc, app: EmailHelperApp) -> None:
        super().__init__(parent, text="游戏与发行商信息", padx=5, pady=5)
        self.app = app
        self._publisherEmail = ""
        self._createWidgets()

    def _createWidgets(self) -> None:
        tk.Label(self, text="AppID:").grid(row=0, column=0, sticky="w", padx=2, pady=1)
        self.appidLabel = tk.Label(self, text="", fg="blue")
        self.appidLabel.grid(row=0, column=1, sticky="w", padx=2, pady=1)

        tk.Label(self, text="游戏名:").grid(row=1, column=0, sticky="w", padx=2, pady=1)
        self.gameNameLabel = tk.Label(self, text="", fg="blue")
        self.gameNameLabel.grid(row=1, column=1, sticky="w", padx=2, pady=1)

        tk.Label(self, text="发行商名:").grid(row=2, column=0, sticky="w", padx=2, pady=1)
        self.publisherNameLabel = tk.Label(self, text="", fg="blue")
        self.publisherNameLabel.grid(row=2, column=1, sticky="w", padx=2, pady=1)

        tk.Label(self, text="发行商邮箱:").grid(
            row=3, column=0, sticky="w", padx=2, pady=1
        )
        self.publisherEmailLabel = tk.Label(self, text="", fg="green")
        self.publisherEmailLabel.grid(row=3, column=1, sticky="w", padx=2, pady=1)

        buttonBar = tk.Frame(self)
        buttonBar.grid(row=4, column=0, columnspan=2, sticky="ew", pady=5, padx=2)
        self.editNameButton = tk.Button(
            buttonBar, text="修改发行商名", command=self.app.editPublisherName
        )
        self.editNameButton.pack(side=tk.LEFT, padx=5)
        self.editEmailButton = tk.Button(
            buttonBar, text="修改发行商邮箱", command=self.app.editPublisherEmail
        )
        self.editEmailButton.pack(side=tk.LEFT, padx=5)
        self.saveButton = tk.Button(
            buttonBar, text="保存到 CSV", command=self.app.savePublisherToCsv
        )
        self.saveButton.pack(side=tk.LEFT, padx=5)

    def setAppid(self, appid: str) -> None:
        self.appidLabel.config(text=appid)

    def setGameName(self, name: str) -> None:
        self.gameNameLabel.config(text=name)

    def setPublisherName(self, name: str) -> None:
        self.publisherNameLabel.config(text=name)

    def setPublisherEmail(self, email: str) -> None:
        self._publisherEmail = email.strip()
        if self._publisherEmail:
            self.publisherEmailLabel.config(text=self._publisherEmail, fg="green")
        else:
            self.publisherEmailLabel.config(text="未找到（可手动填写）", fg="red")

    def getPublisherName(self) -> str:
        return self.publisherNameLabel.cget("text").strip()

    def getPublisherEmail(self) -> str:
        return self._publisherEmail

    def setEnabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self.editNameButton, self.editEmailButton, self.saveButton):
            widget.config(state=state)

    def clear(self) -> None:
        self._publisherEmail = ""
        self.appidLabel.config(text="")
        self.gameNameLabel.config(text="")
        self.publisherNameLabel.config(text="")
        self.publisherEmailLabel.config(text="", fg="green")
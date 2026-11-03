"""Primary action buttons."""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import EmailHelperApp


class ButtonPanel(tk.Frame):
    def __init__(self, parent: tk.Misc, app: EmailHelperApp) -> None:
        super().__init__(parent)
        self.app = app
        self.sendButton = tk.Button(self, text="发送邮件", command=app.startSendEmail)
        self.sendButton.pack(side=tk.LEFT, padx=5)
        self.clearButton = tk.Button(self, text="清空", command=app.clearAllFields)
        self.clearButton.pack(side=tk.LEFT, padx=5)
        self.loadCsvButton = tk.Button(self, text="加载 CSV", command=app.browseCsvFile)
        self.loadCsvButton.pack(side=tk.LEFT, padx=5)

    def setEnabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self.sendButton, self.clearButton, self.loadCsvButton):
            widget.config(state=state)
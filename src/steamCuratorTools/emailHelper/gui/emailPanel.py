"""Editable constructed-email panel."""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext

from ..manager import EmailContent


class EmailPanel(tk.LabelFrame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(
            parent,
            text="构造的邮件内容（主题、收件人、正文均可编辑）",
            padx=5,
            pady=5,
        )
        self._fromAddress = ""
        self._fromDisplay = ""
        self._createWidgets()

    def _createWidgets(self) -> None:
        self.grid_columnconfigure(1, weight=1)

        tk.Label(self, text="主题:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.subjectEntry = tk.Entry(self)
        self.subjectEntry.grid(row=0, column=1, sticky="ew", padx=2, pady=2)

        tk.Label(self, text="收件人:").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.toEntry = tk.Entry(self)
        self.toEntry.grid(row=1, column=1, sticky="ew", padx=2, pady=2)

        tk.Label(self, text="发件人:").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.fromLabel = tk.Label(self, text="", fg="darkgreen")
        self.fromLabel.grid(row=2, column=1, sticky="ew", padx=2, pady=2)

        tk.Label(self, text="正文:").grid(row=3, column=0, sticky="nw", padx=2, pady=2)
        self.bodyText = scrolledtext.ScrolledText(
            self, wrap=tk.WORD, width=80, height=12, font=("Courier New", 10)
        )
        self.bodyText.grid(row=3, column=1, sticky="nsew", padx=2, pady=2)
        self.grid_rowconfigure(3, weight=1)

    def setContent(self, content: EmailContent) -> None:
        self._fromAddress = content.fromAddress
        self._fromDisplay = content.fromDisplay
        self.fromLabel.config(text=content.fromEmail)

        self.subjectEntry.delete(0, tk.END)
        self.subjectEntry.insert(0, content.subject)
        self.toEntry.delete(0, tk.END)
        self.toEntry.insert(0, content.toEmail)
        self.bodyText.delete(1.0, tk.END)
        self.bodyText.insert(1.0, content.body)

    def setToEmail(self, email: str) -> None:
        self.toEntry.delete(0, tk.END)
        self.toEntry.insert(0, email)

    def getContent(self) -> EmailContent:
        return EmailContent(
            subject=self.subjectEntry.get().strip(),
            toEmail=self.toEntry.get().strip(),
            fromEmail=self.fromLabel.cget("text"),
            fromAddress=self._fromAddress,
            fromDisplay=self._fromDisplay,
            body=self.bodyText.get(1.0, tk.END).strip(),
        )

    def clear(self) -> None:
        self._fromAddress = ""
        self._fromDisplay = ""
        self.fromLabel.config(text="")
        self.subjectEntry.delete(0, tk.END)
        self.toEntry.delete(0, tk.END)
        self.bodyText.delete(1.0, tk.END)
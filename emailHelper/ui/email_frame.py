# ui/email_frame.py
import tkinter as tk
import requests
from tkinter import scrolledtext

class EmailFrame(tk.LabelFrame):
    def __init__(self, parent, app):
        super().__init__(parent, text="构造的邮件内容 (可编辑)", padx=5, pady=5)
        self.app = app
        self.parent = parent
        self._create_widgets()

    def _create_widgets(self):
        self.grid_columnconfigure(1, weight=1)

        tk.Label(self, text="主题:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.email_subject_label = tk.Label(self, text="", fg="darkblue", wraplength=700, justify="left")
        self.email_subject_label.grid(row=0, column=1, sticky="ew", padx=2, pady=2)

        tk.Label(self, text="收件人:").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.email_to_label = tk.Label(self, text="", fg="darkgreen")
        self.email_to_label.grid(row=1, column=1, sticky="ew", padx=2, pady=2)

        tk.Label(self, text="发件人:").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.email_from_label = tk.Label(self, text="", fg="darkgreen")
        self.email_from_label.grid(row=2, column=1, sticky="ew", padx=2, pady=2)

        tk.Label(self, text="正文:").grid(row=3, column=0, sticky="nw", padx=2, pady=2)
        self.email_text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, width=80, height=10, font=("Courier New", 10))
        self.email_text_area.grid(row=3, column=1, padx=2, pady=2, sticky="nsew")
        self.grid_rowconfigure(3, weight=1)

    def _clear_email_fields(self):
        self.email_subject_label.config(text="")
        self.email_to_label.config(text="")
        self.email_from_label.config(text="")
        self.email_text_area.delete(1.0, tk.END)

"""Template and SMTP/proxy configuration dialogs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, scrolledtext, ttk

from ..manager import EmailManager
from ..settings import ProxySettings, SmtpSettings

templateTitles = {
    "subject": "编辑邮件主题模板",
    "from": "编辑发件人显示名称",
    "body": "编辑邮件正文模板",
}

templateHints = {
    "subject": "可用占位符：{publisher_name}、{game_name}、{appid}",
    "from": "发件人显示名称（Nickname）。实际发件地址使用 SMTP 配置中的邮箱。",
    "body": (
        "可用占位符：{publisher_name}、{game_name}、{appid}、{steam_url}。\n"
        "{steam_url} 会展开为所有输入的 Steam URL。"
    ),
}

encryptionLabels = {
    "SSL（端口 465，推荐）": "ssl",
    "STARTTLS（端口 587）": "starttls",
    "不加密（端口 25，仅限可信网络）": "none",
}


def openTemplateDialog(
    parent: tk.Misc,
    manager: EmailManager,
    kind: str,
    onSaved: Callable[[], None] | None = None,
) -> None:
    window = tk.Toplevel(parent)
    window.title(templateTitles[kind])
    window.geometry("640x520")
    window.transient(parent)
    window.grab_set()

    tk.Label(
        window, text=templateHints[kind], fg="blue", wraplength=600, justify="left"
    ).pack(padx=10, pady=5, anchor="w")

    textArea = scrolledtext.ScrolledText(
        window, wrap=tk.WORD, width=74, height=20, font=("Courier New", 10)
    )
    textArea.pack(padx=10, pady=5, fill="both", expand=True)
    textArea.insert(1.0, manager.getTemplate(kind))

    buttonBar = tk.Frame(window)
    buttonBar.pack(pady=8)

    def save() -> None:
        try:
            manager.saveTemplate(kind, textArea.get(1.0, tk.END).strip())
        except OSError as exc:
            messagebox.showerror("保存失败", f"保存模板失败：{exc}", parent=window)
            return
        messagebox.showinfo("保存成功", "模板已保存。", parent=window)
        window.destroy()
        if onSaved is not None:
            onSaved()

    tk.Button(buttonBar, text="保存", command=save).pack(side=tk.LEFT, padx=10)
    tk.Button(buttonBar, text="取消", command=window.destroy).pack(side=tk.LEFT, padx=10)
    parent.wait_window(window)


def openConfigDialog(
    parent: tk.Misc,
    manager: EmailManager,
    onSaved: Callable[[], None] | None = None,
) -> None:
    window = tk.Toplevel(parent)
    window.title("配置邮件服务与代理")
    window.geometry("540x430")
    window.transient(parent)
    window.grab_set()

    notebook = ttk.Notebook(window)
    notebook.pack(expand=True, fill="both", padx=10, pady=8)

    smtpFrame = ttk.Frame(notebook)
    notebook.add(smtpFrame, text="SMTP（发送邮件）")
    currentSmtp = manager.config.smtp

    def addRow(row: int, label: str, widget: tk.Widget) -> None:
        tk.Label(smtpFrame, text=label).grid(row=row, column=0, sticky="w", padx=5, pady=5)
        widget.grid(row=row, column=1, sticky="ew", padx=5, pady=5)

    smtpFrame.grid_columnconfigure(1, weight=1)
    hostEntry = tk.Entry(smtpFrame)
    hostEntry.insert(0, currentSmtp.host)
    addRow(0, "SMTP 主机:", hostEntry)

    portEntry = tk.Entry(smtpFrame)
    portEntry.insert(0, str(currentSmtp.port))
    addRow(1, "端口:", portEntry)

    usernameEntry = tk.Entry(smtpFrame)
    usernameEntry.insert(0, currentSmtp.username)
    addRow(2, "发件邮箱地址:", usernameEntry)

    passwordEntry = tk.Entry(smtpFrame, show="*")
    passwordEntry.insert(0, currentSmtp.password)
    addRow(3, "授权码/密码:", passwordEntry)

    labelByMode = {mode: label for label, mode in encryptionLabels.items()}
    encryptionBox = ttk.Combobox(
        smtpFrame,
        values=list(encryptionLabels),
        state="readonly",
    )
    encryptionBox.set(labelByMode.get(currentSmtp.encryption, next(iter(encryptionLabels))))
    addRow(4, "加密方式:", encryptionBox)
    tk.Label(
        smtpFrame,
        text="QQ/163 等使用授权码而非登录密码；SSL 常用 465，STARTTLS 常用 587。",
        fg="gray",
        wraplength=460,
        justify="left",
    ).grid(row=5, column=0, columnspan=2, sticky="w", padx=5, pady=2)

    proxyFrame = ttk.Frame(notebook)
    notebook.add(proxyFrame, text="代理")
    currentProxy = manager.config.proxy
    proxyEnabledVar = tk.BooleanVar(value=currentProxy.enabled)
    tk.Checkbutton(
        proxyFrame,
        text="启用代理（访问 Steam 商店/帮助页面时使用）",
        variable=proxyEnabledVar,
    ).grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5)

    tk.Label(proxyFrame, text="代理地址:").grid(
        row=1, column=0, sticky="w", padx=5, pady=5
    )
    proxyEntry = tk.Entry(proxyFrame, width=40)
    proxyEntry.insert(0, currentProxy.url)
    proxyEntry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
    proxyFrame.grid_columnconfigure(1, weight=1)

    tk.Label(
        proxyFrame,
        text="支持 http/https/socks5，例如 http://127.0.0.1:7890。SMTP 发送不走代理。",
        fg="gray",
        wraplength=460,
        justify="left",
    ).grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=2)

    buttonBar = tk.Frame(window)
    buttonBar.pack(pady=8)

    def save() -> None:
        try:
            port = int(portEntry.get().strip())
        except ValueError:
            messagebox.showerror("配置错误", "端口必须是数字。", parent=window)
            return
        smtp = SmtpSettings(
            host=hostEntry.get().strip(),
            port=port,
            username=usernameEntry.get().strip(),
            password=passwordEntry.get(),
            encryption=encryptionLabels[encryptionBox.get()],
        )
        proxy = ProxySettings(
            enabled=proxyEnabledVar.get(),
            url=proxyEntry.get().strip(),
        )
        try:
            manager.saveConfig(smtp, proxy)
        except (OSError, ValueError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=window)
            return
        messagebox.showinfo("保存成功", "配置已保存。", parent=window)
        window.destroy()
        if onSaved is not None:
            onSaved()

    tk.Button(buttonBar, text="保存", command=save).pack(side=tk.LEFT, padx=10)
    tk.Button(buttonBar, text="取消", command=window.destroy).pack(side=tk.LEFT, padx=10)
    parent.wait_window(window)
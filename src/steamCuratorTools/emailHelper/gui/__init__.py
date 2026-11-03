"""Tkinter GUI for the email helper.

Imports of :mod:`tkinter` are delayed until :func:`main` is called so the
headless parts of the package remain importable on CI machines without Tk.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from .app import run
    except ImportError as exc:
        print(
            "无法启动邮件助手 GUI："
            f"{exc}\n"
            "请确认已安装 Tk（Linux 通常为 python3-tk），并安装 GUI 依赖："
            'pip install -e ".[gui]"',
            file=sys.stderr,
        )
        return 2
    return run(argv)


__all__ = ["main"]
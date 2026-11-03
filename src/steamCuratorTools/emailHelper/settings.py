"""Persistent SMTP and proxy settings for the email helper."""

from __future__ import annotations

import contextlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

encryptionModes = ("ssl", "starttls", "none")
defaultSmtpPort = 465
defaultEncryption = "ssl"

_emailPattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


@dataclass(slots=True)
class SmtpSettings:
    host: str = ""
    port: int = defaultSmtpPort
    username: str = ""
    password: str = ""
    encryption: str = defaultEncryption

    @property
    def isComplete(self) -> bool:
        return bool(self.host and self.username and self.password and 1 <= self.port <= 65535)

    def problem(self) -> str | None:
        """Return a human-readable problem, or ``None`` when usable."""
        if not self.host.strip():
            return "SMTP 主机不能为空。"
        if not 1 <= self.port <= 65535:
            return "SMTP 端口必须在 1-65535 之间。"
        if not self.username.strip():
            return "发件邮箱地址不能为空。"
        if not self.password:
            return "SMTP 授权码/密码不能为空。"
        if self.encryption not in encryptionModes:
            return f"不支持加密方式: {self.encryption!r}（可选 ssl/starttls/none）。"
        return None


@dataclass(slots=True)
class ProxySettings:
    enabled: bool = False
    url: str = ""


@dataclass(slots=True)
class EmailConfig:
    smtp: SmtpSettings
    proxy: ProxySettings


def inferEncryption(port: int, useTls: Any = True) -> str:
    """Map legacy ``use_tls`` values onto an explicit encryption mode.

    The old implementation used ``use_tls=False`` for STARTTLS, so that
    behaviour is preserved when reading old config files.
    """
    if useTls is False:
        return "starttls"
    if port == 465:
        return "ssl"
    return "starttls"


def isValidEmail(value: str) -> bool:
    return _emailPattern.match(value.strip()) is not None


def _asInt(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def emailConfigFromDict(data: dict[str, Any]) -> EmailConfig:
    smtpData = data.get("smtp")
    if not isinstance(smtpData, dict):
        smtpData = {}
    proxyData = data.get("proxy")
    if not isinstance(proxyData, dict):
        proxyData = {}

    port = _asInt(smtpData.get("port"), defaultSmtpPort)
    encryption = str(smtpData.get("encryption") or "").strip().lower()
    if encryption not in encryptionModes:
        encryption = inferEncryption(port, smtpData.get("use_tls", True))

    return EmailConfig(
        smtp=SmtpSettings(
            host=str(smtpData.get("host") or "").strip(),
            port=port,
            username=str(smtpData.get("username") or "").strip(),
            password=str(smtpData.get("password") or ""),
            encryption=encryption,
        ),
        proxy=ProxySettings(
            enabled=bool(proxyData.get("enabled", False)),
            url=str(proxyData.get("url") or "").strip(),
        ),
    )


def emailConfigToDict(config: EmailConfig) -> dict[str, Any]:
    return {
        "smtp": {
            "host": config.smtp.host,
            "port": config.smtp.port,
            "username": config.smtp.username,
            "password": config.smtp.password,
            "encryption": config.smtp.encryption,
        },
        "proxy": {
            "enabled": config.proxy.enabled,
            "url": config.proxy.url,
        },
    }


def loadEmailConfig(path: Path) -> EmailConfig:
    """Load settings, returning an empty config when the file is absent/invalid."""
    if not path.exists():
        return emailConfigFromDict({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return emailConfigFromDict({})
    if not isinstance(data, dict):
        return emailConfigFromDict({})
    return emailConfigFromDict(data)


def saveEmailConfig(path: Path, config: EmailConfig) -> None:
    """Atomically write settings; the file contains a credential, so lock it down."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(emailConfigToDict(config), ensure_ascii=False, indent=4) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
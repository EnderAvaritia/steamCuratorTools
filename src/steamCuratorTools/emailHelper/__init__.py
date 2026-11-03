"""Publisher outreach email helper (GUI plus reusable core)."""

from __future__ import annotations

from .manager import EmailContent, EmailManager
from .settings import EmailConfig, ProxySettings, SmtpSettings, isValidEmail

__all__ = [
    "EmailConfig",
    "EmailContent",
    "EmailManager",
    "ProxySettings",
    "SmtpSettings",
    "isValidEmail",
]
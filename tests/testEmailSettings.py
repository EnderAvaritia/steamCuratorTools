from __future__ import annotations

import json
from pathlib import Path

from steamCuratorTools.emailHelper.settings import (
    EmailConfig,
    ProxySettings,
    SmtpSettings,
    emailConfigFromDict,
    inferEncryption,
    loadEmailConfig,
    saveEmailConfig,
)


def testInferEncryptionFromLegacyUseTls() -> None:
    assert inferEncryption(465, True) == "ssl"
    assert inferEncryption(587, True) == "starttls"
    assert inferEncryption(25, True) == "starttls"
    assert inferEncryption(465, False) == "starttls"


def testExplicitEncryptionWinsOverLegacyFlag() -> None:
    config = emailConfigFromDict(
        {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "a@example.com",
                "password": "secret",
                "encryption": "none",
                "use_tls": True,
            }
        }
    )
    assert config.smtp.encryption == "none"
    assert config.smtp.isComplete


def testLoadLegacyConfigAndRoundTrip(tmp_path: Path) -> None:
    path = tmp_path / "email_config.json"
    path.write_text(
        json.dumps(
            {
                "smtp": {
                    "host": "smtp.qq.com",
                    "port": 465,
                    "username": "a@qq.com",
                    "password": "code",
                    "use_tls": True,
                },
                "proxy": {"enabled": True, "url": "http://127.0.0.1:7890"},
            }
        ),
        encoding="utf-8",
    )
    loaded = loadEmailConfig(path)
    assert loaded.smtp.encryption == "ssl"
    assert loaded.proxy.enabled
    assert loaded.proxy.url == "http://127.0.0.1:7890"

    saveEmailConfig(path, loaded)
    again = loadEmailConfig(path)
    assert again == loaded
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["smtp"]["encryption"] == "ssl"
    assert "use_tls" not in payload["smtp"]


def testLoadInvalidConfigFallsBackToEmpty(tmp_path: Path) -> None:
    path = tmp_path / "email_config.json"
    path.write_text("{not json", encoding="utf-8")
    config = loadEmailConfig(path)
    assert config.smtp.host == ""
    assert config.smtp.port == 465
    assert not config.proxy.enabled

    missing = loadEmailConfig(tmp_path / "missing.json")
    assert isinstance(missing, EmailConfig)
    assert not missing.smtp.isComplete


def testSmtpProblems() -> None:
    assert SmtpSettings().problem() is not None
    assert SmtpSettings(host="h", port=0, username="a@b.com", password="x").problem()
    assert SmtpSettings(host="h", port=465, username="a@b.com", password="x").problem() is None
    assert (
        SmtpSettings(
            host="h", port=465, username="a@b.com", password="x", encryption="nope"
        ).problem()
        is not None
    )


def testSaveConfigRejectsInvalidProxy(tmp_path: Path) -> None:
    from steamCuratorTools.emailHelper.manager import EmailManager

    manager = EmailManager(baseDir=tmp_path)
    try:
        manager.saveConfig(
            SmtpSettings(host="h", port=465, username="a@b.com", password="x"),
            ProxySettings(enabled=True, url="ftp://127.0.0.1:21"),
        )
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("invalid proxy should be rejected")
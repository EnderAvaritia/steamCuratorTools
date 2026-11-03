from __future__ import annotations

import smtplib
from email import message_from_string, policy
from email.header import decode_header
from pathlib import Path
from typing import Any

import pytest

from steamCuratorTools.emailHelper import manager as managerModule
from steamCuratorTools.emailHelper.manager import EmailManager
from steamCuratorTools.emailHelper.settings import ProxySettings, SmtpSettings


def makeManager(tmp_path: Path, **smtpOverrides: Any) -> EmailManager:
    manager = EmailManager(baseDir=tmp_path)
    smtpValues: dict[str, Any] = {
        "host": "smtp.example.com",
        "port": 465,
        "username": "sender@example.com",
        "password": "secret",
        "encryption": "ssl",
    }
    smtpValues.update(smtpOverrides)
    manager.saveConfig(SmtpSettings(**smtpValues), ProxySettings())
    return manager


class FakeSslServer:
    instances: list[FakeSslServer] = []

    def __init__(self, host: str, port: int, timeout: float, context: Any = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.events: list[str] = ["connect"]
        self.sentFrom = ""
        self.recipients: list[str] = []
        self.message = ""
        self.quitCalled = False
        FakeSslServer.instances.append(self)

    def login(self, username: str, password: str) -> None:
        self.events.append(f"login:{username}")

    def sendmail(self, mailFrom: str, recipients: list[str], message: str) -> None:
        self.sentFrom = mailFrom
        self.recipients = list(recipients)
        self.message = message
        self.events.append("sendmail")

    def quit(self) -> None:
        self.quitCalled = True
        self.events.append("quit")

    def close(self) -> None:
        self.events.append("close")


class FakePlainServer:
    instances: list[FakePlainServer] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.events: list[str] = ["connect"]
        self.sentFrom = ""
        self.recipients: list[str] = []
        self.message = ""
        FakePlainServer.instances.append(self)

    def ehlo(self) -> None:
        self.events.append("ehlo")

    def starttls(self, context: Any = None) -> None:
        self.events.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.events.append(f"login:{username}")

    def sendmail(self, mailFrom: str, recipients: list[str], message: str) -> None:
        self.sentFrom = mailFrom
        self.recipients = list(recipients)
        self.message = message
        self.events.append("sendmail")

    def quit(self) -> None:
        self.events.append("quit")

    def close(self) -> None:
        self.events.append("close")


def decodeHeader(value: str) -> str:
    parts = decode_header(value)
    return "".join(
        part.decode(encoding or "utf-8") if isinstance(part, bytes) else part
        for part, encoding in parts
    )


def testManagerSeedsTemplatesAndPublisherCsv(tmp_path: Path) -> None:
    manager = EmailManager(baseDir=tmp_path)
    assert (tmp_path / "email_templates" / "subject.txt").exists()
    assert (tmp_path / "publishers.csv").exists()
    assert "合作" in manager.getTemplate("subject")
    with pytest.raises(ValueError):
        manager.getTemplate("unknown")


def testBuildContentRendersTemplatesAndSender(tmp_path: Path) -> None:
    manager = makeManager(tmp_path, encryption="ssl")
    content = manager.buildContent(
        toEmail="press@example.org",
        gameName="Demo Game",
        publisherName="Demo Studio",
        appid="12345",
        steamUrl="https://store.steampowered.com/app/12345/",
    )
    assert "Demo Game" in content.subject
    assert "12345" in content.subject
    assert "Demo Studio" in content.body
    assert "https://store.steampowered.com/app/12345/" in content.body
    assert content.fromAddress == "sender@example.com"
    assert content.fromEmail == "ETC <sender@example.com>"


def testSaveTemplateIsUsedByBuildContent(tmp_path: Path) -> None:
    manager = makeManager(tmp_path)
    manager.saveTemplate("subject", "Hi {publisher_name}")
    manager.saveTemplate("body", "Game={game_name}; URL={steam_url}")
    content = manager.buildContent("a@b.com", "G", "P", "1", "u")
    assert content.subject == "Hi P"
    assert content.body == "Game=G; URL=u"


def testSendEmailBuildsProperFromHeader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = makeManager(tmp_path)
    FakeSslServer.instances.clear()
    monkeypatch.setattr(managerModule.smtplib, "SMTP_SSL", FakeSslServer)
    ok, message = manager.sendEmail(
        "press@example.org", "主题", "正文", "测试发件人"
    )
    assert ok, message
    server = FakeSslServer.instances[-1]
    assert server.host == "smtp.example.com"
    assert server.port == 465
    assert server.sentFrom == "sender@example.com"
    assert server.recipients == ["press@example.org"]
    assert server.events[:2] == ["connect", "login:sender@example.com"]
    assert server.quitCalled

    parsed = message_from_string(server.message, policy=policy.default)
    assert "sender@example.com" in parsed["From"]
    assert "测试发件人" in decodeHeader(parsed["From"])
    assert parsed["To"] == "press@example.org"
    assert parsed["Subject"] == "主题"
    assert parsed["Date"]
    assert "正文" in parsed.get_content()


def testSendEmailSupportsMultipleRecipients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = makeManager(tmp_path)
    FakeSslServer.instances.clear()
    monkeypatch.setattr(managerModule.smtplib, "SMTP_SSL", FakeSslServer)
    ok, _ = manager.sendEmail(
        "a@example.com; b@example.com", "Hi", "Body", "ETC"
    )
    assert ok
    server = FakeSslServer.instances[-1]
    assert server.recipients == ["a@example.com", "b@example.com"]
    parsed = message_from_string(server.message, policy=policy.default)
    assert "a@example.com" in parsed["To"]
    assert "b@example.com" in parsed["To"]


def testSendEmailStartTlsMode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = makeManager(tmp_path, port=587, encryption="starttls")
    FakePlainServer.instances.clear()
    monkeypatch.setattr(managerModule.smtplib, "SMTP", FakePlainServer)
    ok, _ = manager.sendEmail("a@example.com", "Hi", "Body", "ETC")
    assert ok
    server = FakePlainServer.instances[-1]
    assert server.events[0] == "connect"
    assert "starttls" in server.events
    assert server.events.count("ehlo") >= 2
    assert "sendmail" in server.events


def testSendEmailPlainModeSkipsTls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = makeManager(tmp_path, port=25, encryption="none")
    FakePlainServer.instances.clear()
    monkeypatch.setattr(managerModule.smtplib, "SMTP", FakePlainServer)
    ok, _ = manager.sendEmail("a@example.com", "Hi", "Body", "ETC")
    assert ok
    server = FakePlainServer.instances[-1]
    assert "starttls" not in server.events


def testSendEmailRejectsIncompleteConfig(tmp_path: Path) -> None:
    manager = EmailManager(baseDir=tmp_path)
    ok, message = manager.sendEmail("a@example.com", "Hi", "Body", "ETC")
    assert not ok
    assert "SMTP" in message


def testSendEmailRejectsInvalidInputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = makeManager(tmp_path)
    monkeypatch.setattr(managerModule.smtplib, "SMTP_SSL", FakeSslServer)

    assert not manager.sendEmail("bad", "Hi", "Body", "ETC")[0]
    assert not manager.sendEmail("a@example.com", "", "Body", "ETC")[0]
    assert not manager.sendEmail("a@example.com", "Hi", "", "ETC")[0]


def testSendEmailMapsAuthErrorToFriendlyMessage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AuthFailServer(FakeSslServer):
        def login(self, username: str, password: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    manager = makeManager(tmp_path)
    monkeypatch.setattr(managerModule.smtplib, "SMTP_SSL", AuthFailServer)
    ok, message = manager.sendEmail("a@example.com", "Hi", "Body", "ETC")
    assert not ok
    assert "授权码" in message


def testProxySettingsNormalization(tmp_path: Path) -> None:
    manager = EmailManager(baseDir=tmp_path)
    manager.saveConfig(
        SmtpSettings(host="h", port=465, username="a@b.com", password="x"),
        ProxySettings(enabled=True, url="127.0.0.1:7890"),
    )
    assert manager.requestsProxies() == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    manager.saveConfig(
        SmtpSettings(host="h", port=465, username="a@b.com", password="x"),
        ProxySettings(enabled=False, url=""),
    )
    assert manager.requestsProxies() == {}
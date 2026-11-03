"""Email configuration, template rendering, SMTP delivery, and publisher lookup."""

from __future__ import annotations

import contextlib
import logging
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses
from pathlib import Path

from ..errors import ConfigError
from ..http import ensureSocksSupport, normalizeProxy
from .publishers import (
    ensurePublisherCsv,
    lookupPublisherEmail,
    upsertPublisherEmail,
)
from .settings import (
    EmailConfig,
    ProxySettings,
    SmtpSettings,
    isValidEmail,
    loadEmailConfig,
    saveEmailConfig,
)
from .templates import defaultTemplates, renderTemplate, templateKinds

defaultConfigName = "email_config.json"
defaultTemplatesDir = "email_templates"
defaultPublishersName = "publishers.csv"
defaultLogName = "app.log"


@dataclass(slots=True)
class EmailContent:
    subject: str
    toEmail: str
    fromEmail: str
    fromAddress: str
    fromDisplay: str
    body: str


class EmailManager:
    def __init__(
        self,
        baseDir: str | Path | None = None,
        configPath: str | Path | None = None,
        templatesDir: str | Path | None = None,
        publishersPath: str | Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.baseDir = Path(baseDir or Path.cwd()).expanduser().resolve()
        self.configPath = Path(configPath) if configPath else self.baseDir / defaultConfigName
        self.templatesDir = (
            Path(templatesDir) if templatesDir else self.baseDir / defaultTemplatesDir
        )
        self.publishersPath = (
            Path(publishersPath) if publishersPath else self.baseDir / defaultPublishersName
        )
        self.logPath = self.baseDir / defaultLogName
        self.logger = logger or logging.getLogger(f"{__name__}.EmailManager")
        self.config: EmailConfig = loadEmailConfig(self.configPath)
        self._ensureTemplates()
        ensurePublisherCsv(self.publishersPath)

    # ---- settings -----------------------------------------------------
    def reloadConfig(self) -> EmailConfig:
        self.config = loadEmailConfig(self.configPath)
        return self.config

    def saveConfig(self, smtp: SmtpSettings, proxy: ProxySettings) -> None:
        problem = smtp.problem()
        if problem:
            raise ValueError(problem)

        proxyUrl = proxy.url.strip()
        if proxy.enabled:
            if not proxyUrl:
                raise ValueError("启用代理时必须填写代理地址。")
            proxyUrl = normalizeProxy(proxyUrl)
            ensureSocksSupport([proxyUrl])
        normalized = EmailConfig(
            smtp=SmtpSettings(
                host=smtp.host.strip(),
                port=smtp.port,
                username=smtp.username.strip(),
                password=smtp.password,
                encryption=smtp.encryption,
            ),
            proxy=ProxySettings(enabled=proxy.enabled, url=proxyUrl),
        )
        saveEmailConfig(self.configPath, normalized)
        self.config = normalized
        self.logger.info("邮件配置已保存: %s", self.configPath)

    def requestsProxies(self) -> dict[str, str]:
        proxy = self.config.proxy
        if not proxy.enabled or not proxy.url:
            return {}
        try:
            url = normalizeProxy(proxy.url)
            ensureSocksSupport([url])
        except ConfigError as exc:
            self.logger.warning("代理配置无效，已退回直连: %s", exc)
            return {}
        return {"http": url, "https": url}

    # ---- templates ----------------------------------------------------
    def _ensureTemplates(self) -> None:
        self.templatesDir.mkdir(parents=True, exist_ok=True)
        for kind, content in defaultTemplates.items():
            path = self.templatesDir / f"{kind}.txt"
            if path.exists():
                continue
            path.write_text(content, encoding="utf-8")

    def _templatePath(self, kind: str) -> Path:
        if kind not in templateKinds:
            raise ValueError(f"未知模板类型: {kind!r}")
        return self.templatesDir / f"{kind}.txt"

    def getTemplate(self, kind: str) -> str:
        path = self._templatePath(kind)
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            self.logger.warning("读取模板失败，使用内置默认值: %s", path)
            return defaultTemplates[kind]

    def saveTemplate(self, kind: str, content: str) -> None:
        path = self._templatePath(kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.logger.info("模板已保存: %s", path)

    # ---- content / sending -------------------------------------------
    def buildContent(
        self,
        toEmail: str,
        gameName: str,
        publisherName: str,
        appid: str,
        steamUrl: str,
    ) -> EmailContent:
        values: Mapping[str, object] = {
            "game_name": gameName,
            "publisher_name": publisherName,
            "appid": appid,
            "steam_url": steamUrl,
        }
        subject = renderTemplate(self.getTemplate("subject"), values).strip()
        body = renderTemplate(self.getTemplate("body"), values)
        fromDisplay = renderTemplate(self.getTemplate("from"), values).strip()
        fromAddress = self.config.smtp.username.strip()
        fromEmail = formataddr((fromDisplay, fromAddress)) if fromAddress else fromDisplay
        return EmailContent(
            subject=subject,
            toEmail=toEmail.strip(),
            fromEmail=fromEmail,
            fromAddress=fromAddress,
            fromDisplay=fromDisplay,
            body=body,
        )

    def sendEmail(
        self,
        toEmail: str,
        subject: str,
        body: str,
        fromDisplay: str | None = None,
    ) -> tuple[bool, str]:
        settings = self.config.smtp
        problem = settings.problem()
        if problem:
            return False, problem

        recipients = [
            address
            for _, address in getaddresses([toEmail.replace(";", ",")])
            if address and isValidEmail(address)
        ]
        if not recipients:
            return False, "收件人邮箱地址无效。"
        if not isValidEmail(settings.username):
            return False, "发件邮箱地址无效，请检查 SMTP 配置。"
        if not subject.strip():
            return False, "邮件主题不能为空。"
        if not body.strip():
            return False, "邮件正文不能为空。"

        display = (
            fromDisplay if fromDisplay is not None else self.getTemplate("from")
        ).strip()
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = Header(subject, "utf-8")
        message["From"] = formataddr((display, settings.username))
        message["To"] = ", ".join(formataddr(("", address)) for address in recipients)
        message["Date"] = formatdate(localtime=True)

        context = ssl.create_default_context()
        server: smtplib.SMTP | None = None
        try:
            if settings.encryption == "ssl":
                server = smtplib.SMTP_SSL(
                    settings.host, settings.port, timeout=30, context=context
                )
            else:
                server = smtplib.SMTP(settings.host, settings.port, timeout=30)
                if settings.encryption == "starttls":
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()

            server.login(settings.username, settings.password)
            server.sendmail(settings.username, recipients, message.as_string())
            self.logger.info("邮件已发送: %s", ", ".join(recipients))
            return True, "邮件发送成功！"
        except smtplib.SMTPAuthenticationError:
            self.logger.error("SMTP 登录失败，请检查邮箱地址与授权码。")
            return False, "SMTP 登录失败，请检查邮箱地址与授权码。"
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            self.logger.exception("邮件发送失败: %s", exc)
            return False, f"邮件发送失败: {exc}"
        finally:
            if server is not None:
                with contextlib.suppress(Exception):
                    server.quit()
                with contextlib.suppress(Exception):
                    server.close()

    # ---- publisher CSV ------------------------------------------------
    def _publisherPath(self, csvPath: str | Path | None) -> Path:
        if csvPath is None:
            return self.publishersPath
        return Path(csvPath).expanduser()

    def lookupPublisherEmail(
        self, publisherName: str, csvPath: str | Path | None = None
    ) -> str | None:
        path = self._publisherPath(csvPath)
        try:
            if not path.exists():
                ensurePublisherCsv(path)
            return lookupPublisherEmail(publisherName, path)
        except OSError:
            self.logger.exception("读取发行商 CSV 失败: %s", path)
            return None

    def savePublisherEmail(
        self, publisherName: str, email: str, csvPath: str | Path | None = None
    ) -> bool:
        path = self._publisherPath(csvPath)
        try:
            return upsertPublisherEmail(publisherName, email, path)
        except (OSError, ValueError):
            self.logger.exception("保存发行商邮箱失败: %s", path)
            return False
# email_manager.py
import json
import os
import re
import csv
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import logging

logger = logging.getLogger(__name__)

class EmailManager:
    def __init__(self):
        self.templates_dir = "email_templates"
        self.config_file = "email_config.json"
        self.email_config = {}

        logger.debug("EmailManager 实例初始化。")
        self._ensure_templates_exist()
        self._load_email_config()

    def _ensure_templates_exist(self):
        if not os.path.exists(self.templates_dir):
            logger.info(f"创建模板目录: {self.templates_dir}")
            os.makedirs(self.templates_dir)

        default_templates = {
            "subject": "关于您的游戏 {game_name} ({appid}) 的合作咨询",
            "body": "尊敬的 {publisher_name} 团队，\n\n我们对您的游戏 {game_name} 非常感兴趣，并希望探讨合作的可能性。\n\n以下是我们对该游戏的评价和建议：\n{steam_url}\n\n期待您的回复！",
            "from": "Steam 合作咨询"
        }

        for template_type, default_content in default_templates.items():
            template_path = os.path.join(self.templates_dir, f"{template_type}.txt")
            if not os.path.exists(template_path):
                logger.info(f"创建默认模板: {template_path}")
                with open(template_path, "w", encoding="utf-8") as f:
                    f.write(default_content)

    def get_template_content(self, template_type: str) -> str:
        template_path = os.path.join(self.templates_dir, f"{template_type}.txt")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.error(f"模板文件未找到: {template_path}")
            return ""
        except Exception as e:
            logger.exception(f"读取模板文件失败: {template_path}")
            return ""

    def save_template_content(self, template_type: str, content: str) -> bool:
        template_path = os.path.join(self.templates_dir, f"{template_type}.txt")
        try:
            with open(template_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"模板已保存: {template_path}")
            return True
        except Exception as e:
            logger.exception(f"保存模板失败: {template_path}")
            return False

    def _load_email_config(self):
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                self.email_config = json.load(f)
            logger.info(f"邮件配置已加载: {self.config_file}")
        except FileNotFoundError:
            logger.warning(f"配置文件未找到: {self.config_file}，使用默认配置。")
            self.email_config = {}
        except json.JSONDecodeError:
            logger.error(f"JSON解码错误: {self.config_file}，请检查文件格式。")
            self.email_config = {}
        except Exception as e:
            logger.exception(f"加载邮件配置失败: {self.config_file}")
            self.email_config = {}

    def save_email_config(self, config: dict) -> bool:
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            logger.info(f"邮件配置已保存: {self.config_file}")
            return True
        except Exception as e:
            logger.exception(f"保存邮件配置失败: {self.config_file}")
            return False

    def construct_email_content(self, to_email: str, game_name: str, publisher_name: str, appid: str, steam_url: str) -> dict:
        """
        构造邮件内容，包括主题、发件人显示名称和正文。
        """
        subject_template = self.get_template_content("subject")
        body_template = self.get_template_content("body")
        from_email_display_template = self.get_template_content("from")

        # 替换占位符
        subject = subject_template.format(game_name=game_name, publisher_name=publisher_name, appid=appid)
        body = body_template.format(game_name=game_name, publisher_name=publisher_name, appid=appid, steam_url=steam_url)
        from_email_display = from_email_display_template.format(game_name=game_name, publisher_name=publisher_name, appid=appid)

        # 获取发件人邮箱地址（从配置中读取）
        smtp_username = self.email_config.get("smtp", {}).get("username", "")
        if not smtp_username:
            logger.warning("SMTP配置中未设置发件人邮箱地址（用户名）。")

        # 组合发件人显示名称和邮箱地址
        formatted_from_email = f"{from_email_display} <{smtp_username}>"

        return {
            "subject": subject,
            "to_email": to_email,
            "from_email": formatted_from_email,
            "body": body
        }

    def send_email(self, to_email: str, subject: str, body: str, from_email_display: str) -> tuple[bool, str]:
        """
        发送邮件。
        from_email_display: 包含显示名称和邮箱地址的字符串，例如 "显示名称 <邮箱地址>"
        """
        smtp_config = self.email_config.get("smtp", {})
        smtp_host = smtp_config.get("host")
        smtp_port = smtp_config.get("port")
        smtp_username = smtp_config.get("username")
        smtp_password = smtp_config.get("password")
        use_tls = smtp_config.get("use_tls", True)

        if not all([smtp_host, smtp_port, smtp_username, smtp_password]):
            logger.error("SMTP配置不完整，请检查配置。")
            return False, "SMTP配置不完整，请检查配置。"

        try:
            # 解析发件人显示名称和邮箱地址
            match = re.match(r"^(.*?) <(.*?)>$", from_email_display)
            if match:
                display_name = match.group(1).strip()
                from_email = match.group(2).strip()
            else:
                display_name = from_email_display # 如果格式不匹配，则直接使用整个字符串作为显示名称
                from_email = smtp_username # 并使用配置中的邮箱地址

            msg = MIMEText(body, 'plain', 'utf-8')
            msg['From'] = Header(display_name, 'utf-8')
            msg['To'] = to_email
            msg['Subject'] = Header(subject, 'utf-8')

            server = smtplib.SMTP_SSL(smtp_host, smtp_port) if use_tls else smtplib.SMTP(smtp_host, smtp_port)
            if use_tls:
                server.connect(smtp_host, smtp_port) # 显式调用 connect
            else:
                server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, [to_email], msg.as_string())
            server.quit()

            logger.info(f"邮件发送成功，收件人: {to_email}")
            return True, "邮件发送成功！"

        except Exception as e:
            logger.exception(f"邮件发送失败，收件人: {to_email}")
            return False, str(e)
            
    def get_email(self, game_name: str, publisher_name: str, csv_path: str) -> str:
        """
        从 CSV 文件中查找发行商的邮箱地址。
        """
        try:
            with open(csv_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row['Publisher'].strip() == publisher_name.strip():
                        logger.info(f"找到 {game_name} (发行商: {publisher_name}) 的邮箱地址: {row['Email']}")
                        return row['Email'].strip()
                logger.warning(f"未找到 {game_name} (发行商: {publisher_name}) 的邮箱地址")
                return None
        except FileNotFoundError:
            logger.error(f"CSV 文件未找到: {csv_path}")
            return None
        except Exception as e:
            logger.exception(f"查找邮箱地址时发生错误: {e}")
            return None

# 示例用法 (仅用于测试此模块)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    email_manager = EmailManager()

    # 示例：构造邮件内容
    email_content = email_manager.construct_email_content(
        to_email="test@example.com",
        game_name="My Game",
        publisher_name="My Publisher",
        appid="123456",
        steam_url="https://store.steampowered.com/app/123456/My_Game/"
    )
    print("构造的邮件内容:", email_content)

    # 示例：发送邮件 (需要配置 email_config.json)
    # success, message = email_manager.send_email(
    #     to_email="test@example.com",
    #     subject=email_content["subject"],
    #     body=email_content["body"],
    #     from_email_display=email_content["from_email"]
    # )
    # if success:
    #     print("邮件发送成功！")
    # else:
    #     print("邮件发送失败:", message)

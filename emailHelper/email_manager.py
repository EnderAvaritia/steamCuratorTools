# email_manager.py
import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import csv
import logging

logger = logging.getLogger(__name__)

class EmailManager:
    def __init__(self):
        self.templates_dir = "email_templates"
        self.config_file = "email_config.json"
        self.publisher_emails = {}
        self.email_config = {}
        self.last_match_type = None

        logger.debug("EmailManager 实例初始化。")
        self._ensure_templates_exist()
        self._load_email_config()

    def _ensure_templates_exist(self):
        logger.info(f"检查邮件模板目录: {self.templates_dir}")
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir)
            logger.info(f"已创建邮件模板目录: {self.templates_dir}")

        default_templates = {
            "subject": "合作机会：关于您的游戏 {game_name}",
            # 默认发件人模板只包含显示名称 (nickname)
            "from_nickname": "您的名称", 
            "body": """尊敬的 {publisher_name}，

您好！

我是一名独立游戏开发者/发行商，对贵公司在Steam上发行的游戏《{game_name}》非常感兴趣。这款游戏（AppID: {appid}）在Steam上表现出色，其独特的玩法/艺术风格/故事（请在此处添加具体赞美）给我留下了深刻印象。

我目前正在开发一款名为 [您的游戏名称] 的游戏，它是一款 [游戏类型] 拥有 [核心玩法特点] 和 [独特卖点]。我相信这款游戏与贵公司的发行理念/游戏组合非常契合，并能为贵公司的产品线带来新的活力。

您可以在这里查看更多关于我的游戏的信息：
[您的游戏链接，例如Steam商店页面、预告片、Demo链接等]

我非常希望能有机会与您探讨潜在的合作机会，例如发行、市场推广或其他形式的合作。

期待您的回复。

此致，
[您的姓名/公司名称]
[您的联系方式/邮箱]
[您的网站/社交媒体链接]

Steam URL(s) for reference:
{steam_url}
"""
        }

        for name, content in default_templates.items():
            # 注意：from_nickname 模板文件名为 from_nickname_template.txt
            filepath = os.path.join(self.templates_dir, f"{name}_template.txt")
            if not os.path.exists(filepath):
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                logger.info(f"已创建默认模板文件: {filepath}")
            else:
                logger.debug(f"模板文件已存在: {filepath}")

    def get_template_content(self, template_type: str) -> str:
        # 调整这里以匹配新的 from_nickname 模板文件名
        if template_type == "from": # GUI仍然会请求 "from" 类型，但我们实际读取 "from_nickname"
            filepath = os.path.join(self.templates_dir, "from_nickname_template.txt")
        else:
            filepath = os.path.join(self.templates_dir, f"{template_type}_template.txt")
        
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                logger.debug(f"已读取模板 '{template_type}' 内容。")
                return content
        logger.warning(f"模板文件不存在: {filepath}")
        return ""

    def save_template_content(self, template_type: str, content: str) -> bool:
        # 调整这里以匹配新的 from_nickname 模板文件名
        if template_type == "from": # GUI仍然会请求 "from" 类型，但我们实际保存 "from_nickname"
            filepath = os.path.join(self.templates_dir, "from_nickname_template.txt")
        else:
            filepath = os.path.join(self.templates_dir, f"{template_type}_template.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"模板 '{template_type}' 已保存到: {filepath}")
            return True
        except Exception as e:
            logger.error(f"保存模板 '{template_type}' 失败: {e}")
            return False

    def _load_email_config(self):
        """加载所有邮件相关配置 (仅SMTP)"""
        logger.info(f"尝试加载邮件配置: {self.config_file}")
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self.email_config = json.load(f)
                logger.info("邮件配置加载成功。")
                logger.debug(f"加载的邮件配置: {self.email_config}")
            except json.JSONDecodeError as e:
                logger.error(f"加载邮件配置失败，JSON格式错误: {e}")
                self.email_config = {}
            except Exception as e:
                logger.error(f"加载邮件配置失败: {e}")
                self.email_config = {}
        else:
            logger.warning(f"邮件配置文件不存在: {self.config_file}")
            self.email_config = {}
        
        # 确保配置字典有默认的smtp键
        self.email_config.setdefault("smtp", {})

    def save_email_config(self, config: dict) -> bool:
        """保存所有邮件相关配置 (仅SMTP)"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            self.email_config = config
            logger.info(f"邮件配置已保存到: {self.config_file}")
            logger.debug(f"保存的邮件配置: {self.email_config}")
            return True
        except Exception as e:
            logger.error(f"保存邮件配置失败: {e}")
            return False

    def load_publisher_emails_from_csv(self, filepath: str) -> bool:
        self.publisher_emails = {}
        logger.info(f"尝试从CSV文件加载发行商邮箱: {filepath}")
        if not os.path.exists(filepath):
            logger.error(f"CSV文件不存在: {filepath}")
            return False
        try:
            with open(filepath, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader) # 跳过标题行
                if "Publisher" not in header or "Email" not in header:
                    logger.error("CSV文件缺少 'Publisher' 或 'Email' 列。")
                    return False
                
                publisher_col_idx = header.index("Publisher")
                email_col_idx = header.index("Email")

                for row_num, row in enumerate(reader, start=2): # 从第2行开始计数
                    if len(row) > max(publisher_col_idx, email_col_idx):
                        publisher = row[publisher_col_idx].strip()
                        email = row[email_col_idx].strip()
                        if publisher and email:
                            self.publisher_emails[publisher.lower()] = (publisher, email)
                        else:
                            logger.warning(f"CSV文件第 {row_num} 行数据不完整或为空，已跳过: {row}")
                    else:
                        logger.warning(f"CSV文件第 {row_num} 行格式不正确，列数不足，已跳过: {row}")
            logger.info(f"已从CSV文件加载 {len(self.publisher_emails)} 条发行商邮箱记录。")
            return True
        except Exception as e:
            logger.exception(f"加载发行商邮箱CSV失败: {e}")
            return False

    def get_email_by_publisher_name(self, steam_publisher_name: str) -> tuple[str, str]:
        """
        根据Steam上获取的发行商名称，模糊匹配CSV中的邮箱。
        返回 (匹配到的CSV中的发行商名称, 邮箱) 或 (None, None)
        """
        self.last_match_type = None
        steam_name_lower = steam_publisher_name.lower()
        logger.info(f"尝试匹配发行商邮箱，Steam名称: '{steam_publisher_name}'")

        # 1. 精确匹配
        if steam_name_lower in self.publisher_emails:
            self.last_match_type = "exact"
            matched_name, email = self.publisher_emails[steam_name_lower]
            logger.info(f"精确匹配成功: '{matched_name}' -> '{email}'")
            return matched_name, email

        # 2. Steam名称包含CSV名称
        for csv_name_lower, (original_csv_name, email) in self.publisher_emails.items():
            if csv_name_lower in steam_name_lower:
                self.last_match_type = "steam_contains_csv"
                logger.info(f"Steam名称包含CSV名称匹配成功: '{original_csv_name}' (CSV) in '{steam_publisher_name}' (Steam) -> '{email}'")
                return original_csv_name, email

        # 3. CSV名称包含Steam名称
        for csv_name_lower, (original_csv_name, email) in self.publisher_emails.items():
            if steam_name_lower in csv_name_lower:
                self.last_match_type = "csv_contains_steam"
                logger.info(f"CSV名称包含Steam名称匹配成功: '{steam_publisher_name}' (Steam) in '{original_csv_name}' (CSV) -> '{email}'")
                return original_csv_name, email
        
        # 4. 正则表达式模糊匹配
        clean_steam_name = re.sub(r'[^a-z0-9]', '', steam_name_lower)
        for csv_name_lower, (original_csv_name, email) in self.publisher_emails.items():
            clean_csv_name = re.sub(r'[^a-z0-9]', '', csv_name_lower)
            if clean_csv_name in clean_steam_name or clean_steam_name in clean_csv_name:
                self.last_match_type = "fuzzy"
                logger.info(f"模糊匹配成功 (清理后): '{original_csv_name}' (CSV) vs '{steam_publisher_name}' (Steam) -> '{email}'")
                return original_csv_name, email

        logger.warning(f"未找到发行商 '{steam_publisher_name}' 的匹配邮箱。")
        return None, None

    def construct_email_content(self, to_email: str, game_name: str, publisher_name: str, appid: str, steam_url: str) -> dict:
        logger.info(f"构造邮件内容，收件人: {to_email}, 游戏: {game_name}, 发行商: {publisher_name}")
        subject_template = self.get_template_content("subject")
        # 从模板获取发件人显示名称 (nickname)
        from_nickname = self.get_template_content("from") # 这里的 "from" 实际读取的是 from_nickname_template.txt
        body_template = self.get_template_content("body")

        formatted_subject = subject_template.format(
            publisher_name=publisher_name,
            game_name=game_name
        )
        formatted_body = body_template.format(
            publisher_name=publisher_name,
            game_name=game_name,
            appid=appid,
            steam_url=steam_url
        )
        logger.debug(f"构造邮件主题: {formatted_subject}")
        logger.debug(f"构造邮件发件人显示名称 (来自模板): {from_nickname}")

        # 获取实际发件人邮箱地址 (SMTP用户名)
        smtp_username = self.email_config.get("smtp", {}).get("username", "")
        # 组合显示名称和实际发件人邮箱地址，用于GUI显示
        display_from_email = f"{from_nickname} <{smtp_username}>" if from_nickname and smtp_username else smtp_username

        return {
            "to_email": to_email,
            "subject": formatted_subject,
            "from_email": display_from_email, # 这个是用于GUI显示的完整From头部
            "body": formatted_body
        }

    def send_email(self, to_email: str, subject: str, body: str, from_email_display: str) -> tuple[bool, str]:
        logger.info(f"尝试发送邮件至: {to_email}, 主题: {subject}")
        
        smtp_config = self.email_config.get("smtp", {})
        if not smtp_config:
            logger.error("SMTP配置未加载或不完整。")
            return False, "SMTP配置未加载或不完整。请先配置SMTP服务器。"

        host = smtp_config.get("host")
        port = smtp_config.get("port")
        username = smtp_config.get("username") # SMTP认证的用户名，即实际发件邮箱
        password = smtp_config.get("password") # **这里是授权码**
        use_tls = smtp_config.get("use_tls", True) # 默认使用TLS

        if not all([host, port, username, password]):
            logger.error(f"SMTP配置不完整。主机: {host}, 端口: {port}, 用户名: {username}, 密码: {'*' * len(password) if password else 'None'}")
            return False, "SMTP配置不完整。请检查主机、端口、用户名和授权码。"

        from_email_address = username # 实际用于SMTP认证和发送的邮箱地址
        logger.debug(f"实际发件人邮箱 (SMTP用户名): {from_email_address}")
        logger.debug(f"邮件正文内容:\n{body}") # 打印发送内容用于调试

        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['To'] = Header(to_email, 'utf-8')

        # --- 核心修改点：直接从模板获取显示名称，并与实际发件邮箱地址拼接 ---
        display_name = self.get_template_content("from") # 直接从 from_nickname_template.txt 读取显示名称
        
        # 如果模板中没有设置显示名称，则使用邮箱地址的前缀作为默认显示名称
        if not display_name and from_email_address:
            display_name = from_email_address.split('@')[0]
            logger.warning(f"发件人显示名称模板为空，将使用邮箱前缀 '{display_name}' 作为显示名称。")
        
        # 构造最终的 From 头部字符串，强制使用实际发件人邮箱地址和模板中的显示名称
        # 关键：使用 Header().encode() 来确保非ASCII字符被正确编码为字符串
        if display_name:
            encoded_display_name = Header(display_name, 'utf-8').encode()
            final_from_header_string = f"{encoded_display_name} <{from_email_address}>"
        else:
            final_from_header_string = f"<{from_email_address}>"
        
        # 直接将编码后的字符串赋值给 msg['From']
        msg['From'] = final_from_header_string
        logger.debug(f"邮件From头部 (实际发送): {final_from_header_string}")
        # --- 核心修改点结束 ---

        server = None
        try:
            if port == 465 and use_tls: # 端口465通常是隐式SSL
                logger.info(f"连接SMTP服务器 (SMTP_SSL): {host}:{port}")
                server = smtplib.SMTP_SSL(host, port, timeout=15) # 增加超时设置
            else: # 其他端口，如587，使用STARTTLS
                logger.info(f"连接SMTP服务器 (SMTP): {host}:{port}, 使用TLS: {use_tls}")
                server = smtplib.SMTP(host, port, timeout=15) # 增加超时设置
                if use_tls:
                    server.starttls()
                    logger.debug("已启动TLS加密。")
            
            logger.info(f"尝试登录SMTP服务器，用户: {username}")
            server.login(username, password) # 使用授权码登录
            logger.info("SMTP登录成功。")
            server.sendmail(from_email_address, to_email, msg.as_string())
            logger.info(f"邮件成功发送至 {to_email}。")
            return True, "邮件发送成功！"
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP认证失败。请检查用户名和授权码是否正确。")
            return False, "SMTP认证失败。请检查用户名和授权码是否正确。"
        except smtplib.SMTPConnectError as e:
            logger.error(f"SMTP连接失败。请检查主机和端口设置，或网络连接/防火墙。错误: {e}")
            return False, f"SMTP连接失败。请检查主机和端口设置，或网络连接/防火墙。错误: {e}"
        except smtplib.SMTPException as e:
            logger.exception(f"SMTP发送邮件时发生错误: {e}")
            return False, f"SMTP发送邮件时发生未知错误: {e}"
        except Exception as e:
            logger.exception(f"发送邮件时发生未知错误: {e}")
            return False, f"发送邮件时发生未知错误: {e}"
        finally:
            if server:
                try:
                    server.quit() # 确保关闭连接
                    logger.debug("SMTP连接已关闭。")
                except Exception as e:
                    logger.warning(f"关闭SMTP连接时发生错误: {e}")

# 示例用法 (仅用于测试此模块)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    manager = EmailManager()

    # 示例：保存配置 (仅SMTP)
    test_config = {
        "smtp": {
            "host": "smtp.qq.com",
            "port": 465,
            "username": "your_qq_email@qq.com", # 替换为你的QQ邮箱
            "password": "your_smtp_auth_code", # 替换为你的SMTP授权码
            "use_tls": True
        }
    }
    manager.save_email_config(test_config)
    print("\n--- 测试邮件发送 ---")
    # 替换为实际的收件人邮箱
    success, msg = manager.send_email("test_recipient@example.com", "测试邮件主题", "这是一封测试邮件正文。", "这个参数现在不重要了") 
    print(f"发送结果: {success}, 消息: {msg}")


# ui/input_frame.py
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import os
import pyperclip
import threading
import logging
import requests
import re
from lxml import html  # 添加这一行


DEFAULT_CSV_FILENAME = "publishers.csv"

class InputFrame(tk.LabelFrame):
    def __init__(self, parent, app):
        super().__init__(parent, text="输入信息", padx=5, pady=5)
        self.app = app
        self.parent = parent
        self._create_widgets()

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=0) 
        self.grid_columnconfigure(1, weight=1) 
        self.grid_columnconfigure(2, weight=0) 

        tk.Label(self, text="Steam URL(s):").grid(row=0, column=0, sticky="nw", pady=2, padx=2)
        self.url_entry = scrolledtext.ScrolledText(self, wrap=tk.WORD, width=50, height=4)
        self.url_entry.grid(row=0, column=1, padx=2, pady=2, sticky="ew") 
        self.url_entry.insert(tk.END, "https://steamcommunity.com/id/EnderAvaritia/recommended/2875610?tscn=1751003141\n")
        self.url_entry.insert(tk.END, "https://store.steampowered.com/app/2875610/Alice_Publication_Game/")

        self.paste_button = tk.Button(self, text="粘贴", command=self._paste_from_clipboard)
        self.paste_button.grid(row=0, column=2, padx=2, pady=2, sticky="n")

        tk.Label(self, text="发行商邮箱CSV:").grid(row=1, column=0, sticky="w", pady=2, padx=2)
        self.csv_path_entry = tk.Entry(self, width=50) 
        self.csv_path_entry.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        self.csv_path_entry.insert(0, DEFAULT_CSV_FILENAME) 
        
        self.browse_csv_button = tk.Button(self, text="选择CSV", command=self._browse_csv_file)
        self.browse_csv_button.grid(row=1, column=2, padx=2, pady=2)

        template_buttons_container = tk.Frame(self)
        template_buttons_container.grid(row=2, column=0, columnspan=3, pady=2, sticky="ew") 

        tk.Button(template_buttons_container, text="编辑主题", 
                  command=lambda: self._edit_template_window("subject", "编辑邮件主题范本")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(template_buttons_container, text="编辑发件人", 
                  command=lambda: self._edit_template_window("from", "编辑发件人显示名称 (Nickname)")).pack(side=tk.LEFT, padx=2, pady=2) # 更改提示
        tk.Button(template_buttons_container, text="编辑正文", 
                  command=lambda: self._edit_template_window("body", "编辑邮件正文范本")).pack(side=tk.LEFT, padx=2, pady=2)
        
        action_status_frame = tk.Frame(self)
        action_status_frame.grid(row=3, column=0, columnspan=3, pady=5, sticky="ew") 
        
        action_status_frame.grid_columnconfigure(0, weight=0) 
        action_status_frame.grid_columnconfigure(1, weight=0) 
        action_status_frame.grid_columnconfigure(2, weight=1) 

        self.email_config_button = tk.Button(action_status_frame, text="配置邮件服务", 
                  command=self._configure_email_window)
        self.email_config_button.grid(row=0, column=0, padx=2, pady=2, sticky="w") 

        self.process_button = tk.Button(action_status_frame, text="处理URL并生成邮件", command=self._start_process_url_thread)
        self.process_button.grid(row=0, column=1, padx=2, pady=2, sticky="w") 

        self.status_label = tk.Label(action_status_frame, text="", fg="black", wraplength=400, justify="left")
        self.status_label.grid(row=0, column=2, padx=2, pady=2, sticky="ew") 

    def _paste_from_clipboard(self):
        """从剪贴板读取内容并粘贴到URL输入框。"""
        self.app._update_status("正在尝试从剪贴板粘贴...", "info")
        logger = logging.getLogger(__name__)
        logger.debug("尝试从剪贴板粘贴内容。")
        try:
            clipboard_content = pyperclip.paste()
            self.url_entry.delete(1.0, tk.END)
            self.url_entry.insert(tk.END, clipboard_content)
            self.app._update_status("剪贴板内容已粘贴。", "success")
            logger.info("剪贴板内容已成功粘贴。")
        except pyperclip.PyperclipException as e:
            self.app._update_status(f"剪贴板错误：无法读取剪贴板内容。请确保您已复制文本，并且系统允许访问剪贴板。\n错误: {e}", "error")
            logger = logging.getLogger(__name__)
            logger.error(f"剪贴板粘贴失败: {e}")
        except Exception as e:
            self.app._update_status(f"粘贴时发生未知错误: {e}", "error")
            logger = logging.getLogger(__name__)
            logger.exception("粘贴时发生未知错误。")

    def _browse_csv_file(self):
        self.app._update_status("正在选择CSV文件...", "info")
        logger = logging.getLogger(__name__)
        logger.debug("打开文件选择对话框。")
        filepath = filedialog.askopenfilename(
            title="选择发行商邮箱CSV文件",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            self.csv_path_entry.delete(0, tk.END)
            self.csv_path_entry.insert(0, filepath)
            self.app._update_status(f"已选择CSV文件: {os.path.basename(filepath)}", "success")
            logger.info(f"已选择CSV文件: {filepath}")
        else:
            self.app._update_status("未选择CSV文件。", "warning")
            logger.warning("用户取消了CSV文件选择。")

    def _edit_template_window(self, template_type: str, title: str):
        logger = logging.getLogger(__name__)
        logger.info(f"打开编辑模板窗口: {title}")
        template_window = tk.Toplevel(self)
        template_window.title(title)
        template_window.geometry("600x500")
        template_window.transient(self)
        template_window.grab_set()

        info_text = ""
        if template_type == "body":
            info_text = "请使用 {publisher_name}, {game_name}, {appid}, {steam_url} 作为占位符。\n{steam_url} 将显示所有输入的Steam URL。"
        elif template_type == "subject":
            info_text = "请使用 {publisher_name}, {game_name} 作为占位符。"
        elif template_type == "from": # 针对发件人显示名称的特殊提示
            info_text = "请在此处输入您的发件人显示名称 (Nickname)。\n实际发件邮箱地址将强制使用您在“配置邮件服务”中设置的邮箱。"
        
        tk.Label(template_window, text=info_text, fg="blue", wraplength=580, justify="left").pack(pady=5, padx=10)

        template_text_area = scrolledtext.ScrolledText(template_window, wrap=tk.WORD, width=70, height=20, font=("Courier New", 10))
        template_text_area.pack(padx=10, pady=10, fill="both", expand=True)
        
        template_text_area.insert(tk.END, self.app.email_manager.get_template_content(template_type))

        def save_template():
            new_content = template_text_area.get(1.0, tk.END).strip()
            if self.app.email_manager.save_template_content(template_type, new_content):
                messagebox.showinfo("保存成功", f"{title}已保存！")
                logger.info(f"模板 '{template_type}' 已保存。")
                # 保存模板后，重新处理URL以更新邮件内容
                self._start_process_url_thread()
                template_window.destroy()
            else:
                messagebox.showerror("保存失败", f"保存{title}时发生错误。")
                logger = logging.getLogger(__name__)
                logger.error(f"模板 '{template_type}' 保存失败。")

        def cancel_edit():
            logger = logging.getLogger(__name__)
            logger.info(f"取消编辑模板: {title}")
            template_window.destroy()

        button_frame = tk.Frame(template_window)
        button_frame.pack(pady=10)

        save_button = tk.Button(button_frame, text="保存", command=save_template)
        save_button.pack(side=tk.LEFT, padx=10)

        cancel_button = tk.Button(button_frame, text="取消", command=cancel_edit)
        cancel_button.pack(side=tk.RIGHT, padx=10)

        self.app.wait_window(template_window)

    def _configure_email_window(self):
        logger = logging.getLogger(__name__)
        logger.info("打开邮件服务配置窗口。")
        config_window = tk.Toplevel(self)
        config_window.title("配置邮件服务 (SMTP)") # 标题已修改
        config_window.geometry("500x350") # 窗口大小已调整，因为移除了IMAP Tab
        config_window.transient(self)
        config_window.grab_set()

        notebook = ttk.Notebook(config_window)
        notebook.pack(expand=True, fill="both", padx=10, pady=10)

        # --- SMTP 配置 Tab ---
        smtp_frame = ttk.Frame(notebook)
        notebook.add(smtp_frame, text="SMTP (发送邮件)")

        current_smtp_config = self.app.email_manager.email_config.get("smtp", {})

        tk.Label(smtp_frame, text="SMTP 主机:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        smtp_host_entry = tk.Entry(smtp_frame, width=40)
        smtp_host_entry.grid(row=0, column=1, padx=5, pady=5)
        smtp_host_entry.insert(0, current_smtp_config.get("host", "smtp.qq.com"))

        tk.Label(smtp_frame, text="端口:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        smtp_port_entry = tk.Entry(smtp_frame, width=40)
        smtp_port_entry.grid(row=1, column=1, padx=5, pady=5)
        smtp_port_entry.insert(0, str(current_smtp_config.get("port", 465)))

        tk.Label(smtp_frame, text="用户名 (发件邮箱地址):").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        smtp_username_entry = tk.Entry(smtp_frame, width=40)
        smtp_username_entry.grid(row=2, column=1, padx=5, pady=5)
        smtp_username_entry.insert(0, current_smtp_config.get("username", ""))

        tk.Label(smtp_frame, text="授权码 (非邮箱密码):").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        smtp_password_entry = tk.Entry(smtp_frame, width=40, show="*")
        smtp_password_entry.grid(row=3, column=1, padx=5, pady=5)
        smtp_password_entry.insert(0, current_smtp_config.get("password", ""))

        smtp_use_tls_var = tk.BooleanVar(value=current_smtp_config.get("use_tls", True))
        tk.Checkbutton(smtp_frame, text="使用TLS/SSL加密 (推荐)", variable=smtp_use_tls_var).grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=5)
        tk.Label(smtp_frame, text="端口465通常使用SSL，端口587通常使用STARTTLS。", fg="gray").grid(row=5, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        def save_email_config():
            new_smtp_config = {
                "host": smtp_host_entry.get().strip(),
                "port": int(smtp_port_entry.get().strip()),
                "username": smtp_username_entry.get().strip(),
                "password": smtp_password_entry.get().strip(),
                "use_tls": smtp_use_tls_var.get()
            }
            
            full_config = {
                "smtp": new_smtp_config,
            }

            if self.app.email_manager.save_email_config(full_config):
                messagebox.showinfo("保存成功", "邮件服务配置已保存！")
                logger.info("邮件服务配置已保存。")
                # 保存配置后，重新处理URL以更新邮件内容（特别是发件人显示）
                self._start_process_url_thread()
                config_window.destroy()
            else:
                messagebox.showerror("保存失败", "保存邮件服务配置时发生错误。")
                logger = logging.getLogger(__name__)
                logger.error("邮件服务配置保存失败。")

        def cancel_config():
            logger = logging.getLogger(__name__)
            logger.info("取消邮件服务配置。")
            config_window.destroy()

        button_frame = tk.Frame(config_window)
        button_frame.pack(pady=10)

        save_button = tk.Button(button_frame, text="保存", command=save_email_config)
        save_button.pack(side=tk.LEFT, padx=10)

        cancel_button = tk.Button(button_frame, text="取消", command=cancel_config)
        cancel_button.pack(side=tk.RIGHT, padx=10)

        self.app.wait_window(config_window)

    def _start_process_url_thread(self):
        """在单独的线程中启动URL处理逻辑，避免GUI卡死。"""
        self.app._set_buttons_state("disabled")
        self.app._update_status("正在后台处理URL并获取游戏信息，请稍候...", "info")
        logger = logging.getLogger(__name__)
        logger.info("启动URL处理线程。")
        thread = threading.Thread(target=self._run_process_url_logic)
        thread.start()

    def _run_process_url_logic(self):
        """实际执行URL处理和邮件构造的逻辑，在单独线程中运行。"""
        logger = logging.getLogger(__name__)  # 添加这一行
        try:
            self.app._clear_output_fields()
            
            steam_urls_raw = self.url_entry.get(1.0, tk.END).strip()
            csv_path = self.csv_path_entry.get().strip()

            if not steam_urls_raw:
                self.app.after(0, lambda: self.app._update_status("输入错误：请输入Steam URL(s)。", "warning"))
                return
            if not csv_path:
                self.app.after(0, lambda: self.app._update_status("输入错误：请选择或输入发行商邮箱CSV文件路径。", "warning"))
                return

            urls = [url.strip() for url in steam_urls_raw.split('\n') if url.strip()]
            if not urls:
                self.app.after(0, lambda: self.app._update_status("输入错误：未检测到有效的Steam URL。", "warning"))
                return

            extracted_appids = []
            for url in urls:
                appid = self.app.extractor.extract_appid_from_url(url)
                if not appid:
                    self.app.after(0, lambda url=url: self.app._update_status(f"AppID提取失败：无法从URL '{url}' 中提取AppID，请检查URL格式。", "error"))
                    return
                extracted_appids.append(appid)
            
            first_appid = extracted_appids[0]
            for appid in extracted_appids:
                if appid != first_appid:
                    self.app.after(0, lambda first=first_appid, current=appid: self.app._update_status(f"AppID不一致：检测到多个不同的AppID ({first} 和 {current} 等)。请确保所有输入的URL都指向同一个游戏。", "error"))
                    return
            
            common_appid = first_appid

            self.app.after(0, lambda: self.app.info_frame.appid_label.config(text=common_appid))

            game_info = self.app.extractor.get_game_info_from_appid(common_appid)
            if not game_info:
                self.app.after(0, lambda: self.app._update_status("游戏信息获取失败：无法从Steam商店页面获取游戏名和发行商名，请检查AppID或网络连接。", "error"))
                return
            
            game_name = game_info.get("game_name", "未知游戏名")
            steam_publisher_name = game_info.get("publisher_name", "未知发行商") 

            self.app.after(0, lambda: self.app.info_frame.game_name_label.config(text=game_name))
            
            # 保存游戏名和发行商名，以便在修改邮箱地址时使用
            self.app.game_name = game_name
            self.app.steam_publisher_name = steam_publisher_name
            
            publisher_email = self.app.email_manager.get_email(game_name, steam_publisher_name, csv_path)

            display_publisher_name = steam_publisher_name
            
            if publisher_email:
                self.app.after(0, lambda: self.app.info_frame.publisher_email_label.config(text=publisher_email, fg="green"))
                self.app.after(0, lambda dpn=display_publisher_name: self.app.info_frame.publisher_name_label.config(text=display_publisher_name, fg="blue"))
                self.app.after(0, lambda dpn=display_publisher_name: self.app._update_status(f"已找到发行商 '{dpn}' 的邮箱。", "success"))
            else:
                self.app.after(0, lambda: self.app.info_frame.publisher_email_label.config(text="未找到该发行商的邮箱", fg="red"))
                self.app.after(0, lambda sp_name=steam_publisher_name: self.app._update_status(f"未在CSV中找到发行商 '{sp_name}' 的邮箱地址。", "warning"))
                self.app.after(0, lambda dpn=display_publisher_name: self.app.info_frame.publisher_name_label.config(text=f"{dpn} (未匹配到邮箱)", fg="red"))
                publisher_email = "未找到邮箱"

                # 如果找不到邮箱，则发送请求到 Steam 帮助页面
                help_url = f"https://help.steampowered.com/zh-cn/wizard/HelpWithGameTechnicalIssue?appid={common_appid}"
                try:
                    response = requests.get(help_url)
                    response.raise_for_status()

                    # 使用 lxml 解析 HTML
                    tree = html.fromstring(response.text)

                    # 使用 XPath 提取包含邮箱地址的文本
                    email_text = tree.xpath('string(//div[@class="help_official_support_row"]/text())')

                    # 使用正则表达式提取邮箱地址
                    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email_text)

                    if match:
                        extracted_email = match.group(0)
                        self.app.after(0, lambda email=extracted_email: self.app.info_frame.publisher_email_label.config(text=email, fg="purple"))  # 使用紫色显示提取的邮箱
                        self.app.after(0, lambda email=extracted_email: self.app._update_status(f"未找到邮箱，但从 Steam 帮助页面提取到邮箱地址: {email}", "success"))
                        logger.info(f"从 Steam 帮助页面提取到邮箱地址: {extracted_email}")
                        publisher_email = extracted_email  # 更新 publisher_email 变量
                    else:
                        self.app.after(0, lambda: self.app._update_status("未找到邮箱，且无法从 Steam 帮助页面提取邮箱地址。", "warning"))
                        logger.warning("未找到邮箱，且无法从 Steam 帮助页面提取邮箱地址。")

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 429:
                        self.app.after(0, lambda: self.app._update_status(f"未找到邮箱，向 Steam 帮助页面发送请求时遇到速率限制 (AppID: {common_appid})。请稍后重试。", "warning"))
                        logger.warning(f"向 Steam 帮助页面发送请求时遇到速率限制 (AppID: {common_appid})。状态码: {e.response.status_code}")
                        time.sleep(60)
                    else:
                        self.app.after(0, lambda: self.app._update_status(f"未找到邮箱，但向 Steam 帮助页面发送请求失败 (AppID: {common_appid})，HTTP 错误: {e}", "error"))
                        logger.error(f"向 Steam 帮助页面发送请求失败 (AppID: {common_appid})，HTTP 错误: {e}")
                except requests.exceptions.RequestException as e:
                    self.app.after(0, lambda: self.app._update_status(f"未找到邮箱，且向 Steam 帮助页面发送请求时发生错误 (AppID: {common_appid}): {e}", "error"))
                    logger.exception(f"向 Steam 帮助页面发送请求时发生错误 (AppID: {common_appid}): {e}")
                except Exception as e:
                    self.app.after(0, lambda e=e: self.app._update_status(f"处理 Steam 帮助页面响应时发生错误: {e}", "error"))
                    logger.exception(f"处理 Steam 帮助页面响应时发生错误: {e}")

            steam_urls_for_template = "\n".join(urls)

            email_parts = self.app.email_manager.construct_email_content(
                to_email=publisher_email,
                game_name=game_name,
                publisher_name=display_publisher_name, 
                appid=common_appid,
                steam_url=steam_urls_for_template
            )
            
            self.app.after(0, lambda: self.app.email_frame.email_subject_label.config(text=email_parts['subject']))
            self.app.after(0, lambda: self.app.email_frame.email_to_label.config(text=email_parts['to_email']))
            self.app.after(0, lambda: self.app.email_frame.email_from_label.config(text=email_parts['from_email'])) # 这里显示的是组合后的完整From头部

            self.app.after(0, self.app.email_frame.email_text_area.delete, 1.0, tk.END)
            self.app.after(0, self.app.email_frame.email_text_area.insert, tk.END, email_parts['body'])

            if self.app.input_frame.status_label.cget("fg") not in ["red", "orange"]:
                self.app.after(0, lambda: self.app._update_status("信息已获取并邮件已构造，请检查界面。", "success"))

        except Exception as e:
            self.app.after(0, lambda e=e: self.app._update_status(f"处理URL时发生意外错误: {e}", "error"))
            logger.exception("处理URL逻辑时发生未捕获的异常。")
        finally:
            self.app.after(0, lambda: self.app._set_buttons_state("normal"))
            logger.info("URL处理线程结束。")

    def _clear_input_fields(self):
        self.url_entry.delete(1.0, tk.END)
        self.url_entry.insert(tk.END, "https://steamcommunity.com/id/EnderAvaritia/recommended/2875610?tscn=1751003141\n")
        self.url_entry.insert(tk.END, "https://store.steampowered.com/app/2875610/Alice_Publication_Game/")
        
        self.csv_path_entry.delete(0, tk.END)
        self.csv_path_entry.insert(0, DEFAULT_CSV_FILENAME)

# ui/button_frame.py
import tkinter as tk
import requests
import logging

class ButtonFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.parent = parent
        self._create_widgets()

    def _create_widgets(self):
        self.send_email_button = tk.Button(self, text="发送邮件", command=self._start_send_email_thread)
        self.send_email_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = tk.Button(self, text="清空所有", command=self._clear_fields)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        self.exit_button = tk.Button(self, text="退出", command=self.app.quit)
        self.exit_button.pack(side=tk.RIGHT, padx=5)

    def _start_send_email_thread(self):
        """在单独的线程中启动邮件发送逻辑，避免GUI卡死。"""
        self.app._set_buttons_state("disabled")
        self.app._update_status("正在后台发送邮件，请稍候...", "info")
        logger = logging.getLogger(__name__)
        logger.info("启动邮件发送线程。")
        thread = threading.Thread(target=self._run_send_email_logic)
        thread.start()

    def _run_send_email_logic(self):
        """实际执行邮件发送的逻辑，在单独线程中运行。"""
        to_email = self.app.email_frame.email_to_label.cget("text")
        subject = self.app.email_frame.email_subject_label.cget("text")
        # 这里的 from_email_display 已经是组合后的 "显示名称 <邮箱地址>" 格式
        from_email_display = self.app.email_frame.email_from_label.cget("text") 
        body = self.app.email_frame.email_text_area.get(1.0, tk.END).strip()

        try:
            if not to_email or to_email == "未找到邮箱":
                self.app.after(0, lambda: self.app._update_status("发送失败：收件人邮箱地址无效。", "error"))
                return
            if not subject:
                self.app.after(0, lambda: self.app._update_status("发送失败：邮件主题不能为空。", "error"))
                return
            # 检查SMTP配置中的用户名（实际发件邮箱）
            if not self.app.email_manager.email_config.get("smtp", {}).get("username"):
                self.app.after(0, lambda: self.app._update_status("发送失败：请先在“配置邮件服务”中设置您的发件邮箱地址。", "error"))
                return

            # 从SMTP配置中获取发件邮箱地址
            from_email_address = self.app.email_manager.email_config["smtp"]["username"]

            # 使用 EmailManager 发送邮件
            if self.app.email_manager.send_email(to_email, subject, body, from_email_address, from_email_display):
                self.app.after(0, lambda: self.app._update_status(f"邮件已成功发送至 {to_email}！", "success"))
                logger = logging.getLogger(__name__)
                logger.info(f"邮件已成功发送至 {to_email}。")
            else:
                self.app.after(0, lambda: self.app._update_status("发送失败：请检查您的邮件服务配置和网络连接。", "error"))
                logger = logging.getLogger(__name__)
                logger.error("邮件发送失败。")

        except Exception as e:
            self.app.after(0, lambda e=e: self.app._update_status(f"发送邮件时发生意外错误: {e}", "error"))
            logger = logging.getLogger(__name__)
            logger.exception("发送邮件时发生未捕获的异常。")
        finally:
            self.app.after(0, lambda: self.app._set_buttons_state("normal"))
            logger = logging.getLogger(__name__)
            logger.info("邮件发送线程结束。")

    def _clear_fields(self):
        self.app._clear_fields()

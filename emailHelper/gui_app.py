# gui_app.py
import tkinter as tk
import requests
import logging
import os

from ui.input_frame import InputFrame
from ui.info_frame import InfoFrame
from ui.email_frame import EmailFrame
from ui.button_frame import ButtonFrame

from steam_info_extractor import SteamInfoExtractor
from email_manager import EmailManager

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

log_file_path = "app.log"
file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

DEFAULT_CSV_FILENAME = "publishers.csv"

class SteamEmailApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Steam 发行商邮件助手")
        self.geometry("800x700")

        self.extractor = SteamInfoExtractor()
        self.email_manager = EmailManager()

        self._create_widgets()
        self._update_status("准备就绪，请输入Steam URL。", "info")
        logger.info("应用程序启动。")

        # 保存游戏名和发行商名，以便在修改邮箱地址时使用
        self.game_name = ""
        self.steam_publisher_name = ""

    def _create_widgets(self):
        self.input_frame = InputFrame(self, self)
        self.info_frame = InfoFrame(self, self)
        self.email_frame = EmailFrame(self, self)
        self.button_frame = ButtonFrame(self, self)

        self.input_frame.pack(pady=5, padx=5, fill="x")
        self.info_frame.pack(pady=5, padx=5, fill="x")
        self.email_frame.pack(pady=5, padx=5, fill="both", expand=True)
        self.button_frame.pack(pady=5)

    def _set_buttons_state(self, state: str):
        """设置主要操作按钮的状态 (normal/disabled)"""
        self.input_frame.process_button.config(state=state)
        self.button_frame.send_email_button.config(state=state)
        self.input_frame.browse_csv_button.config(state=state)
        self.input_frame.paste_button.config(state=state)
        self.input_frame.email_config_button.config(state=state)
        self.button_frame.clear_button.config(state=state)
        self.info_frame.edit_publisher_name_button.config(state=state)
        self.info_frame.edit_publisher_email_button.config(state=state)
        logger.debug(f"按钮状态设置为: {state}")

    def _update_status(self, message: str, message_type: str = "info"):
        """
        更新状态栏信息。
        message_type: "info", "warning", "error", "success"
        """
        color = "black"
        if message_type == "error":
            color = "red"
            logger.error(message)
        elif message_type == "warning":
            color = "orange"
            logger.warning(message)
        elif message_type == "success":
            color = "green"
            logger.info(message)
        else: # info
            logger.info(message)
        
        self.input_frame.status_label.config(text=message, fg=color)
        self.update_idletasks()

    # 以下方法移动到对应的 Frame 类中，只保留调用
    def _paste_from_clipboard(self):
        self.input_frame._paste_from_clipboard()

    def _browse_csv_file(self):
        self.input_frame._browse_csv_file()

    def _edit_template_window(self, template_type: str, title: str):
        self.input_frame._edit_template_window(template_type, title)

    def _configure_email_window(self):
        self.input_frame._configure_email_window()

    def _start_process_url_thread(self):
        self.input_frame._start_process_url_thread()

    def _run_process_url_logic(self):
        self.input_frame._run_process_url_logic()

    def _start_send_email_thread(self):
        self.button_frame._start_send_email_thread()

    def _run_send_email_logic(self):
        self.button_frame._run_send_email_logic()

    def _clear_output_fields(self):
        self.info_frame._clear_output_fields()
        self.email_frame._clear_email_fields()

    def _clear_fields(self):
        self.input_frame._clear_input_fields()
        self._clear_output_fields()
        self._update_status("所有字段已清空，准备就绪。", "info")
        logger.info("所有输入和输出字段已清空。")

    def _edit_publisher_name(self):
        self.info_frame._edit_publisher_name()

    def _edit_publisher_email(self):
        self.info_frame._edit_publisher_email()

if __name__ == "__main__":
    if not os.path.exists(DEFAULT_CSV_FILENAME):
        try:
            with open(DEFAULT_CSV_FILENAME, "w", encoding="utf-8", newline="") as f:
                f.write("Publisher,Email\n")
                f.write("Valve,contact@valvesoftware.com\n")
                f.write("CD Projekt Red,pr@cdprojektred.com\n")
                f.write("Ubisoft,press@ubisoft.com\n")
                f.write("Paradox Interactive,press@paradoxplaza.com\n")
                f.write("EnderAvaritia,ender.avaritia@example.com\n")
                f.write("Alice Publication,alice.pub@example.com\n")
                f.write("Eternal Alice Media,eternal.alice@example.com\n")
            logger.info(f"已创建默认CSV文件: {DEFAULT_CSV_FILENAME}")
        except Exception as e:
            logger.error(f"创建默认CSV文件失败: {e}")
    else:
        logger.info(f"默认CSV文件 '{DEFAULT_CSV_FILENAME}' 已存在。")

    app = SteamEmailApp()
    app.mainloop()
    logger.info("应用程序退出。")

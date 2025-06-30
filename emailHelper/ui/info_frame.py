# ui/info_frame.py
import tkinter as tk
from tkinter import simpledialog, messagebox
import logging
import csv  # 导入 csv 模块
import os

class InfoFrame(tk.LabelFrame):
    def __init__(self, parent, app):
        super().__init__(parent, text="游戏与发行商信息", padx=5, pady=5)
        self.app = app
        self.parent = parent
        self._create_widgets()
        self.app_id_var = tk.StringVar()  # 初始化 app_id_var
        self.game_name_var = tk.StringVar()  # 初始化 game_name_var
        self.publisher_email_var = tk.StringVar()  # 初始化 publisher_email_var

    def _create_widgets(self):
        tk.Label(self, text="AppID:").grid(row=0, column=0, sticky="w", pady=1, padx=2)
        self.appid_label = tk.Label(self, text="", fg="blue")
        self.appid_label.grid(row=0, column=1, sticky="w", pady=1, padx=2)

        tk.Label(self, text="游戏名:").grid(row=1, column=0, sticky="w", pady=1, padx=2)
        self.game_name_label = tk.Label(self, text="", fg="blue")
        self.game_name_label.grid(row=1, column=1, sticky="w", pady=1, padx=2)

        tk.Label(self, text="发行商名:").grid(row=2, column=0, sticky="w", pady=1, padx=2)
        self.publisher_name_label = tk.Label(self, text="", fg="blue")
        self.publisher_name_label.grid(row=2, column=1, sticky="w", pady=1, padx=2)

        tk.Label(self, text="发行商邮箱:").grid(row=3, column=0, sticky="w", pady=1, padx=2)
        self.publisher_email_label = tk.Label(self, text="", fg="green", font=("Arial", 10, "bold"))
        self.publisher_email_label.grid(row=3, column=1, sticky="w", pady=1, padx=2)

        # --- 添加修改发行商名和邮箱的按钮 ---
        edit_buttons_frame = tk.Frame(self)
        edit_buttons_frame.grid(row=4, column=0, columnspan=2, pady=5, padx=2, sticky="ew")

        self.edit_publisher_name_button = tk.Button(edit_buttons_frame, text="修改发行商名", command=self._edit_publisher_name)
        self.edit_publisher_name_button.pack(side=tk.LEFT, padx=5)

        self.edit_publisher_email_button = tk.Button(edit_buttons_frame, text="修改发行商邮箱", command=self._edit_publisher_email)
        self.edit_publisher_email_button.pack(side=tk.LEFT, padx=5)
        
        self.save_button = tk.Button(edit_buttons_frame, text="保存", command=self._save_to_csv)
        self.save_button.pack(side=tk.LEFT, padx=5)

 
    def _clear_output_fields(self):
        """清除所有输出字段的内容。"""
        self.appid_label.config(text="")
        self.game_name_label.config(text="")
        self.publisher_name_label.config(text="")
        self.publisher_email_label.config(text="")

    def _edit_publisher_name(self):
        """弹出对话框修改发行商名称。"""
        logger = logging.getLogger(__name__)
        new_name = simpledialog.askstring("修改发行商名称", "请输入新的发行商名称:",
                                            initialvalue=self.publisher_name_label.cget("text"))
        if new_name:
            self.publisher_name_label.config(text=new_name)
            self.app._update_status(f"发行商名称已修改为: {new_name}", "info")
            logger.info(f"发行商名称已修改为: {new_name}")

    def _edit_publisher_email(self):
        dialog = tk.Toplevel(self)
        dialog.title("编辑发行商邮箱")

        # 获取当前邮箱地址
        current_email = self.publisher_email_var.get()

        # 创建标签和输入框
        tk.Label(dialog, text="新的邮箱地址:").grid(row=0, column=0, padx=5, pady=5)
        email_entry = tk.Entry(dialog)
        email_entry.insert(0, current_email)
        email_entry.grid(row=0, column=1, padx=5, pady=5)

        def confirm_email():
            """确认修改邮箱地址。"""
            new_email = email_entry.get()
            # 在这里添加验证逻辑，例如检查邮箱格式是否正确
            if not self._validate_email(new_email):
                messagebox.showerror("错误", "邮箱地址格式不正确！")
                return

            # 更新邮箱地址
            self.publisher_email_var.set(new_email)
            dialog.destroy()

        def cancel_email():
            """取消修改邮箱地址。"""
            dialog.destroy()

        # 添加确定和取消按钮
        confirm_button = tk.Button(dialog, text="确定", command=confirm_email)
        confirm_button.grid(row=1, column=0, padx=5, pady=5)

        cancel_button = tk.Button(dialog, text="取消", command=cancel_email)
        cancel_button.grid(row=1, column=1, padx=5, pady=5)

        # 邮箱验证函数 (需要自己实现)
    def _validate_email(self, email):
        """验证邮箱地址格式是否正确。"""
        # 使用正则表达式或其他方法进行验证
        import re
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(pattern, email) is not None
        def save_email():
            """保存邮箱地址到CSV文件。"""
            new_email = email_entry.get().strip()
            if not new_email:
                messagebox.showerror("错误", "邮箱地址不能为空。")
                return

            csv_path = self.app.input_frame.csv_path_entry.get().strip()
            if not csv_path:
                messagebox.showerror("错误", "请先选择或输入CSV文件路径。")
                return

            game_name = self.game_name_label.cget("text")
            publisher_name = self.publisher_name_label.cget("text")

            try:
                # 读取现有的 CSV 数据
                data = []
                header = None
                with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.reader(csvfile)
                    header = next(reader)  # 读取标题行
                    for row in reader:
                        data.append(row)

                # 查找要更新的行
                updated = False
                for row in data:
                    if len(row) >= 3 and row[0] == game_name and row[1] == publisher_name:
                        row[2] = new_email  # 更新邮箱地址
                        updated = True
                        break

                # 如果没有找到匹配的行，则添加新行
                if not updated:
                    data.append([game_name, publisher_name, new_email])

                # 写回 CSV 文件
                with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(header)  # 写入标题行
                    writer.writerows(data)

                self.publisher_email_label.config(text=new_email)
                self.app._update_status(f"发行商邮箱已修改为: {new_email} 并已保存到 CSV 文件。", "info")
                logger.info(f"发行商邮箱已修改为: {new_email} 并已保存到 CSV 文件。")
                dialog.destroy()  # 关闭对话框

            except Exception as e:
                messagebox.showerror("错误", f"保存CSV文件时发生错误: {e}")
                logger.exception(f"保存CSV文件时发生错误: {e}")

    def _save_to_csv(self):
        """将数据保存到 CSV 文件。"""
        # 获取所有需要保存的数据
        app_id = self.app_id_var.get()
        game_name = self.game_name_var.get()
        publisher_email = self.publisher_email_var.get()
        # ... 获取其他需要保存的数据

        # 构建 CSV 行
        data = [app_id, game_name, publisher_email, ...]  # 确保顺序与 CSV 文件中的列顺序一致

        # 写入 CSV 文件
        try:
            with open("data.csv", "a", newline="", encoding="utf-8") as csvfile:  # 使用追加模式 "a"
                writer = csv.writer(csvfile)
                writer.writerow(data)
            messagebox.showinfo("成功", "数据已成功保存到 CSV 文件！")
        except Exception as e:
            messagebox.showerror("错误", f"保存到 CSV 文件时发生错误：{e}")
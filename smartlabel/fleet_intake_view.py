"""Non-modal Fleet staging dialog; background work remains owned by the app."""
import webbrowser

import customtkinter as ctk

from .fleet_intake import fleet_inbox_url, list_staged
from .ui_layout import center_dialog


class FleetIntakeView(ctk.CTkToplevel):
    def __init__(self, app, project, root):
        super().__init__(app)
        self.app, self.project, self.root = app, project, root
        self.title("Nhận dữ liệu từ Fleet · Vùng chờ")
        center_dialog(self, app, 850, 600)
        self.protocol("WM_DELETE_WINDOW", self.close)
        ctk.CTkLabel(self, text=f"Project đích: {project.name}", font=("Segoe UI", 18, "bold")).pack(padx=20, pady=(20, 8))
        identity = ctk.CTkEntry(self, width=550)
        identity.insert(0, project.id)
        identity.configure(state="readonly")
        identity.pack(padx=20, pady=8)
        ctk.CTkLabel(self, text="1. Mở Fleet, chọn đợt đã duyệt cho phát triển model và cấp mã nhập đúng project.\n"
                    "2. Dán mã tại đây. Mã hết hạn sau tối đa 5 phút; không chia sẻ mã.\n"
                    "Sau khi nhận, dùng Mở để gán nhãn trong nguồn Khách đóng góp.\n"
                    "Duyệt nhãn chưa cho phép dùng train/export.\n"
                    "Đóng cửa sổ này không hủy lượt đang xử lý. Hạn lưu trên Fleet vẫn áp dụng.",
                    justify="left", wraplength=720).pack(padx=20, pady=8)
        ctk.CTkButton(self, text="Mở hộp thư Fleet", command=lambda: webbrowser.open(fleet_inbox_url(project.id))).pack(pady=8)
        self.code = ctk.CTkEntry(self, width=650, placeholder_text="FleetImportV1.…", show="•")
        self.code.pack(padx=20, pady=8)
        self.submit = ctk.CTkButton(self, text="Nhận vào vùng chờ project này", command=self.start)
        self.submit.pack(pady=8)
        self.review_button = ctk.CTkButton(self, text="Mở đợt đã nhập để gán nhãn", command=self.open_review)
        self.review_button.pack(pady=4)
        self.message = ctk.CTkLabel(self, text="", wraplength=720, justify="left")
        self.message.pack(padx=20, pady=8)
        self.records = ctk.CTkTextbox(self, height=130, wrap="word")
        self.records.pack(fill="both", expand=True, padx=20, pady=8)
        ctk.CTkButton(self, text="Đóng", command=self.close).pack(pady=(8, 20))
        self.refresh()

    def refresh(self):
        try:
            rows = list_staged(self.root, self.project.id)
            value = "\n".join(f"{row['contributionId']} · {row['fileCount']} ảnh · {'Điện thoại' if row['source'] == 'phone' else 'Camera Hydro'} · chờ duyệt nhãn" for row in rows)
            value = value or "Chưa có đợt hoàn tất tại vùng chờ project này."
        except Exception:
            value = "Chưa đọc được vùng chờ; kiểm tra project và bộ nhận."
        self.records.configure(state="normal")
        self.records.delete("1.0", "end")
        self.records.insert("1.0", value + "\nDanh sách tại máy không thay thế việc kiểm tra quyền hiện tại trên Fleet.")
        self.records.configure(state="disabled")

    def start(self):
        code = self.code.get()
        if self.app._start_fleet_intake(self.project, code, self):
            self.code.delete(0, "end")
            self.submit.configure(state="disabled")
            self.message.configure(text="Đang kiểm tra quyền và lưu ảnh…")

    def finished(self, message):
        if not self.winfo_exists():
            return
        self.submit.configure(state="normal")
        self.review_button.configure(state="normal")
        self.message.configure(text=message)
        self.refresh()

    def open_review(self):
        if self.app._start_fleet_review(self.project, self.code.get(), self):
            self.code.delete(0, "end")
            self.submit.configure(state="disabled")
            self.review_button.configure(state="disabled")
            self.message.configure(text="Đang xác minh quyền và ảnh; nhãn cũ được giữ nguyên…")

    def close(self):
        self.code.delete(0, "end")
        self.destroy()  # No grab_set: closing cannot leave an invisible mouse-blocking modal.

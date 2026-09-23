"""Non-modal Fleet staging dialog; background work remains owned by the app."""
import webbrowser

import customtkinter as ctk
from .ui_layout import StudioToplevel

from .fleet_intake import fleet_inbox_url, list_staged
from .ui_layout import setup_dialog, dialog_header, dialog_section, dialog_footer, wrapped_label, MUTED


class FleetIntakeView(StudioToplevel):
    def __init__(self, app, project, root):
        super().__init__(app)
        self.app, self.project, self.root = app, project, root
        self.title("Nhận dữ liệu từ Fleet · Vùng chờ")
        footer = dialog_footer(self)
        ctk.CTkButton(footer, text="Đóng", width=100, height=36, fg_color="#294153", command=self.close).pack(side="right")
        wrapped_label(footer, "Đóng cửa sổ không hủy lượt đang xử lý.", color=MUTED).pack(side="left", fill="x", expand=True, padx=(0, 16))
        dialog_header(self, "Nhận dữ liệu từ Fleet", "Nhận vào vùng chờ → kiểm tra nguồn → gán nhãn")
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        destination = dialog_section(body, "Project đích", project.name)
        identity = ctk.CTkEntry(destination, height=34)
        identity.insert(0, project.id)
        identity.configure(state="readonly")
        identity.pack(fill="x")
        intake = dialog_section(body, "01  ·  Cấp mã và nhận ảnh",
            "Mở Fleet, chọn đợt đã duyệt cho phát triển model và cấp mã nhập đúng project. Mã hết hạn sau tối đa 5 phút; không chia sẻ mã.")
        ctk.CTkButton(intake, text="Mở hộp thư Fleet ↗", height=34, fg_color="#294153",
            command=lambda: webbrowser.open(fleet_inbox_url(project.id))).pack(anchor="w", pady=(0, 10))
        self.code = ctk.CTkEntry(intake, height=38, placeholder_text="Dán mã FleetImportV1.…", show="•")
        self.code.pack(fill="x", pady=(0, 10))
        self.submit = ctk.CTkButton(intake, text="Nhận vào vùng chờ project này", height=36, command=self.start)
        self.submit.pack(anchor="e")
        review = dialog_section(body, "02  ·  Dữ liệu tại máy",
            "Mở để gán nhãn trong nguồn Khách đóng góp. Duyệt nhãn chưa cho phép dùng train/export; hạn lưu và quyền hiện tại trên Fleet vẫn áp dụng.")
        self.records = ctk.CTkTextbox(review, height=130, wrap="word", font=("Segoe UI", 13), fg_color="#0b151f", corner_radius=8)
        self.records.pack(fill="x", pady=(0, 10))
        actions = ctk.CTkFrame(review, fg_color="transparent")
        actions.pack(fill="x"); actions.grid_columnconfigure((0, 1), weight=1, uniform="review")
        self.review_button = ctk.CTkButton(actions, text="Mở để gán nhãn", height=36, command=self.open_review)
        self.review_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.preflight_button = ctk.CTkButton(actions, text="Kiểm tra trước dataset", height=36, fg_color="#294153", command=self.preflight)
        self.preflight_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.message = wrapped_label(body, "")
        self.message.pack(fill="x", padx=12, pady=4)
        self.refresh()
        setup_dialog(self, app, 850, 770, close=self.close, modal=False)

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
        self.preflight_button.configure(state="normal")
        self.message.configure(text=message)
        self.refresh()

    def open_review(self):
        if self.app._start_fleet_review(self.project, self.code.get(), self):
            self.code.delete(0, "end")
            self.submit.configure(state="disabled")
            self.review_button.configure(state="disabled")
            self.message.configure(text="Đang xác minh quyền và ảnh; nhãn cũ được giữ nguyên…")

    def preflight(self):
        if self.app._start_fleet_review(self.project, self.code.get(), self, preflight=True):
            self.code.delete(0, "end")
            for button in (self.submit, self.review_button, self.preflight_button):
                button.configure(state="disabled")
            self.message.configure(text="Đang kiểm tra nguồn, nhãn và ảnh trùng trong project; không tạo dataset hoặc train…")

    def close(self):
        self.code.delete(0, "end")
        self.destroy()  # No grab_set: closing cannot leave an invisible mouse-blocking modal.

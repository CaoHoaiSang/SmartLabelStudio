"""Project trash presentation; recovery still uses the existing ProjectStore."""
import customtkinter as ctk
from .ui_layout import (StudioToplevel, setup_dialog, dialog_header, dialog_footer,
                        wrapped_label, PANEL, BORDER, MUTED, SURFACE)


class ProjectTrashDialog(StudioToplevel):
    def __init__(self, parent, projects, on_restore):
        super().__init__(parent)
        self.title("Dự án đã xóa · Khôi phục")
        self.on_restore = on_restore
        footer = dialog_footer(self)
        ctk.CTkButton(footer, text="Đóng", width=100, command=self.destroy,
                      fg_color="#294153").pack(side="right")
        dialog_header(self, "DỰ ÁN ĐÃ XÓA", "Khôi phục dự án cùng ảnh và nhãn đã lưu. Không tạo dự án bản sao.")
        content = ctk.CTkScrollableFrame(self, fg_color=SURFACE)
        content.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.restore_buttons = []
        if not projects:
            wrapped_label(content, "Thùng rác trống · Chưa có dự án cần khôi phục.", color=MUTED).pack(fill="x", padx=8, pady=16)
        for project in projects:
            row = ctk.CTkFrame(content, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=12)
            row.pack(fill="x", pady=(0, 8))
            row.grid_columnconfigure(0, weight=1)
            wrapped_label(row, project.name, size=15, bold=True).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
            wrapped_label(row, f"{len(project.images):,} ảnh · Giữ nguyên nhãn và cấu hình", color=MUTED).grid(
                row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
            button = ctk.CTkButton(row, text="Khôi phục", width=112, fg_color="#256481",
                                  command=lambda p=project: self.on_restore(p))
            button.grid(row=0, column=1, rowspan=2, padx=(8, 16), pady=12)
            self.restore_buttons.append(button)
        setup_dialog(self, parent, 760, min(600, max(320, 200 + 94 * len(projects))))

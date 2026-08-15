from __future__ import annotations

import tkinter as tk

import customtkinter as ctk


class DatasetVersionDialog(ctk.CTkToplevel):
    """Modal dialog that distinguishes an empty name from cancellation."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.result: str | None = None
        self.name_var = tk.StringVar(value="")

        self.title("Tạo phiên bản dataset")
        self.geometry("520x230")
        self.resizable(False, False)
        self.configure(fg_color="#081019")
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._create())

        panel = ctk.CTkFrame(
            self,
            corner_radius=14,
            fg_color="#142333",
            border_width=1,
            border_color="#263b50",
        )
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            panel,
            text="TẠO PHIÊN BẢN BẤT BIẾN",
            font=("Segoe UI Semibold", 18),
            text_color="#22b9ee",
        ).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(
            panel,
            text="Nhập tên để dễ nhận biết, hoặc để trống để hệ thống tự đặt tên theo thời gian.",
            wraplength=455,
            justify="left",
            text_color="#9bb0c0",
        ).pack(anchor="w", padx=18, pady=(0, 10))

        self.name_entry = ctk.CTkEntry(
            panel,
            height=38,
            textvariable=self.name_var,
            placeholder_text="Ví dụ: chai_v2_sua_nhan",
        )
        self.name_entry.pack(fill="x", padx=18)

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(16, 14))
        ctk.CTkButton(
            actions,
            text="HỦY",
            width=110,
            fg_color="#415466",
            hover_color="#52697d",
            command=self._cancel,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            actions,
            text="TẠO",
            width=120,
            fg_color="#2aa866",
            hover_color="#35bf77",
            command=self._create,
        ).pack(side="right")

        self.after(80, self._focus_and_center)

    def _focus_and_center(self) -> None:
        if not self.winfo_exists():
            return
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
        self.name_entry.focus_set()

    def _create(self) -> None:
        self.result = self.name_var.get().strip()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def ask_dataset_version_name(parent) -> str | None:
    """Return a name (possibly empty) only when the user presses Create."""

    dialog = DatasetVersionDialog(parent)
    parent.wait_window(dialog)
    return dialog.result

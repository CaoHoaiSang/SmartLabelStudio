from __future__ import annotations

from typing import Callable
import tkinter as tk
from . import studio_dialogs as messagebox

import customtkinter as ctk

from .dataset_manager import DatasetManager
from .models import Project
from .benchmark_contract import cycle_rows
from .ui_layout import setup_dialog, dialog_header, dialog_footer, wrapped_label, MUTED


class SplitManagerDialog(ctk.CTkToplevel):
    """Inspect and deliberately move whole capture groups between splits."""

    FILTERS = {"Tất cả": "", "Train": "train", "Validation": "val", "Test": "test"}

    def __init__(
        self,
        parent,
        manager: DatasetManager,
        project: Project,
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.project = project
        self.on_changed = on_changed
        self.rows: list[dict] = []
        self.title("Quản lý Train / Validation / Test theo capture group")
        actions = dialog_footer(self)
        dialog_header(self, "Phân tập theo nhóm ảnh", "Cả nhóm luôn di chuyển cùng nhau để tránh ảnh liên quan lọt sang nhiều tập.")

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(header, text="Lọc theo tập", text_color=MUTED).pack(side="left", padx=(0, 12))
        self.filter_menu = ctk.CTkOptionMenu(
            header,
            values=list(self.FILTERS),
            width=150,
            command=lambda _value: self._refresh(),
        )
        self.filter_menu.set("Tất cả")
        self.filter_menu.pack(side="left")
        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=14)
        self.cycle_choices = {f"{i+1}. {row['title']}": row['key'] for i, row in enumerate(cycle_rows(project))}
        self.cycle_menu = ctk.CTkOptionMenu(filters, values=["Tất cả vụ", *self.cycle_choices],
                                          command=lambda _: self._refresh(), width=200)
        ctk.CTkButton(filters, text="Chọn các nhóm đang lọc", command=lambda: self.listbox.select_set(0, tk.END)).pack(side="right")
        self.cycle_menu.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self.listbox = tk.Listbox(
            self,
            bg="#091119",
            fg="#e7f3fb",
            selectbackground="#217fa9",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#263b50",
            font=("Consolas", 11),
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        self.listbox.pack(fill="both", expand=True, padx=14, pady=6)
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self._show_selected())

        self.detail = wrapped_label(self, "Chọn một nhóm để xem.", color=MUTED)
        self.detail.pack(fill="x", padx=14, pady=(2, 6))
        actions.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="actions")
        for index, (text, color, command) in enumerate((
                ("→ TRAIN", "#217fa9", lambda: self._move("train")),
                ("→ VALIDATION", "#7655b5", lambda: self._move("val")),
                ("→ TEST", "#a94747", lambda: self._move("test")),
                ("Đóng", "#415466", self.destroy))):
            ctk.CTkButton(actions, text=text, width=1, height=36, fg_color=color, command=command).grid(row=0, column=index, sticky="ew", padx=3)
        self._refresh()
        setup_dialog(self, parent, 980, 720)

    def _refresh(self) -> None:
        wanted = self.FILTERS.get(self.filter_menu.get(), "")
        cycle = self.cycle_choices.get(self.cycle_menu.get())
        self.rows = [row for row in self.manager.split_group_rows(self.project)
                     if (not wanted or row["split"] == wanted) and (not cycle or cycle in row["cycles"])]
        self.listbox.delete(0, tk.END)
        for row in self.rows:
            self.listbox.insert(
                tk.END,
                f"[{row['split'].upper():5}] {row['images']} ảnh · {row['sources']} · {', '.join(row['dates']) or 'Chưa rõ ngày'} · {row['group']}",
            )
        self.detail.configure(text=f"Đang hiển thị {len(self.rows)} capture group.")

    def _selected(self) -> dict | None:
        selected = self.listbox.curselection()
        return self.rows[selected[0]] if selected and selected[0] < len(self.rows) else None

    def _show_selected(self) -> None:
        row = self._selected()
        if row:
            self.detail.configure(
                text=f"{row['group']} · {row['images']} ảnh · {row['reviewed']} đã duyệt · {row['annotations']} nhãn · tập {row['split']}",
                text_color="#e7f3fb",
            )

    def _move(self, target: str) -> None:
        rows = [self.rows[i] for i in self.listbox.curselection() if i < len(self.rows)]
        if not rows:
            messagebox.showinfo("Chưa chọn nhóm", "Hãy chọn một capture group trước.", parent=self)
            return
        if all(row["split"] == target for row in rows):
            return
        if not messagebox.askyesno(
            "Đổi tập của capture group?",
            f"Chuyển {len(rows)} nhóm / {sum(row['images'] for row in rows)} ảnh → {target.upper()}?\n\n"
            + "\n".join(sorted({row['sources'] for row in rows})) + "\n\n"
            "Việc đổi Validation/Test có thể làm kết quả không còn so sánh trực tiếp với model đã train trước đó.",
            parent=self,
        ):
            return
        self.manager.set_groups_split(self.project, [row["group"] for row in rows], target)
        self.on_changed()
        self._refresh()

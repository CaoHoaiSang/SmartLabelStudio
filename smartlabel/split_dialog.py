from __future__ import annotations

from typing import Callable
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .dataset_manager import DatasetManager
from .models import Project
from .benchmark_contract import cycle_rows


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
        self.geometry("920x650")
        self.minsize(760, 520)
        self.transient(parent)
        self.grab_set()

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(
            header,
            text="Mỗi dòng là một capture group; toàn bộ frame trong nhóm luôn di chuyển cùng nhau.",
            text_color="#8fa6b8",
        ).pack(side="left")
        self.filter_menu = ctk.CTkOptionMenu(
            header,
            values=list(self.FILTERS),
            width=150,
            command=lambda _value: self._refresh(),
        )
        self.filter_menu.set("Tất cả")
        self.filter_menu.pack(side="right")
        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=14)
        self.cycle_choices = {f"{i+1}. {row['title']}": row['key'] for i, row in enumerate(cycle_rows(project))}
        self.cycle_menu = ctk.CTkOptionMenu(filters, values=["Tất cả vụ", *self.cycle_choices],
                                          command=lambda _: self._refresh(), width=530)
        self.cycle_menu.pack(side="left")
        ctk.CTkButton(filters, text="Chọn các nhóm đang lọc", command=lambda: self.listbox.select_set(0, tk.END)).pack(side="right")

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

        self.detail = ctk.CTkLabel(self, text="Chọn một nhóm để xem.", anchor="w", text_color="#8fa6b8")
        self.detail.pack(fill="x", padx=14, pady=(2, 6))
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(actions, text="→ TRAIN", width=150, fg_color="#217fa9", command=lambda: self._move("train")).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="→ VALIDATION", width=170, fg_color="#7655b5", command=lambda: self._move("val")).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="→ TEST", width=150, fg_color="#a94747", command=lambda: self._move("test")).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="Đóng", width=120, fg_color="#415466", command=self.destroy).pack(side="right", padx=3)
        self._refresh()

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

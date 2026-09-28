from __future__ import annotations

from typing import Callable
import tkinter as tk
from . import studio_dialogs as messagebox

import customtkinter as ctk
from .ui_layout import StudioToplevel

from .dataset_manager import DatasetManager
from .models import Project
from .benchmark_contract import cycle_rows
from .ui_layout import setup_dialog, dialog_header, dialog_footer, wrapped_label, MUTED, PANEL
from .split_health import SplitConflictError, coverage_lines


class SplitManagerDialog(StudioToplevel):
    """Inspect and deliberately move whole capture groups between splits."""

    FILTERS = {"Tất cả": "", "Chỉ nhóm xung đột": "conflict", "Train": "train", "Validation": "val", "Test": "test"}

    def __init__(
        self,
        parent,
        manager: DatasetManager,
        project: Project,
        on_changed: Callable[[], None],
        *, problems_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.project = project
        self.on_changed = on_changed
        self.rows: list[dict] = []
        self.title("Quản lý Train / Validation / Test theo capture group")
        actions = dialog_footer(self)
        dialog_header(self, "Phân tập theo nhóm ảnh", "Cả nhóm luôn di chuyển cùng nhau để tránh ảnh liên quan lọt sang nhiều tập.")
        health_card = ctk.CTkFrame(self, fg_color=PANEL)
        health_card.pack(fill="x", padx=14, pady=(0, 6))
        self.health_label = wrapped_label(health_card, "", color=MUTED)
        self.health_label.pack(fill="x", padx=12, pady=8)
        self.repair_button = ctk.CTkButton(health_card, text="Đưa nhóm xung đột về TRAIN",
                                         command=self._repair, height=34, fg_color="#256481")
        self.coverage = ctk.CTkTextbox(self, height=116, font=("Segoe UI", 13), fg_color=PANEL)
        if project.metadata.get("template") == "Hydroponic Slot Condition":
            self.coverage.pack(fill="x", padx=14, pady=(0, 4))

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(header, text="Lọc theo tập", text_color=MUTED).pack(side="left", padx=(0, 12))
        self.filter_menu = ctk.CTkOptionMenu(
            header,
            values=list(self.FILTERS),
            width=185,
            command=lambda _value: self._refresh(),
        )
        self.filter_menu.set("Chỉ nhóm xung đột" if problems_only else "Tất cả")
        self.filter_menu.pack(side="left")
        filters = header
        self.cycle_choices = {f"{i+1}. {row['title']}": row['key'] for i, row in enumerate(cycle_rows(project))}
        self.cycle_menu = ctk.CTkOptionMenu(filters, values=["Tất cả vụ", *self.cycle_choices],
                                          command=lambda _: self._refresh(), width=200)
        ctk.CTkButton(filters, text="Chọn nhóm đang lọc", width=146, command=lambda: self.listbox.select_set(0, tk.END)).pack(side="right")
        self.cycle_menu.pack(side="left", fill="x", expand=True, padx=12)

        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=14, pady=6)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            list_frame,
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
        vertical = ctk.CTkScrollbar(list_frame, command=self.listbox.yview)
        horizontal = ctk.CTkScrollbar(list_frame, orientation="horizontal", command=self.listbox.xview)
        self.listbox.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
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
        self.revision = self.manager.split_revision(self.project)
        self.health = {"parents": {}, "conflicts": {}, "coverage": []}
        self.repair_button.pack_forget()
        try:
            self.health = self.manager.split_health(self.project)
            conflicts = self.health["conflicts"]
            if conflicts:
                count = sum(len(ids) for ids in conflicts.values())
                text = (f"CẦN XỬ LÝ · {count} ảnh bổ trợ có ảnh gốc ở VAL/TEST ({len(conflicts)} nhóm). "
                        "Đưa nhóm nguồn về TRAIN để giữ các biến thể; không xóa ảnh hay nhãn. "
                        "Hoặc tắt dùng train các biến thể tại GÁN NHÃN → Bổ trợ nếu muốn giữ nhóm ở VAL/TEST.")
                self.repair_button.pack(anchor="w", padx=12, pady=(0, 10))
            else:
                text = ("Không có xung đột ảnh gốc / bổ trợ. Ảnh thêm vào nhóm cũ giữ tập của nhóm; "
                        "nhóm mới vào TRAIN để không tự đổi bộ đánh giá. Chọn vụ và nhóm để bổ sung VAL/TEST có chủ đích.")
            self.health_label.configure(text=text, text_color="#f0bf72" if conflicts else MUTED)
        except (ValueError, OSError) as exc:
            self.health_label.configure(text=str(exc), text_color="#f499a5")
        self.coverage.configure(state="normal")
        self.coverage.delete("1.0", "end")
        self.coverage.insert("1.0", "\n".join(self.health["coverage"]) or "Phân tập theo nhóm; kiểm tra nhãn trước khi train.")
        self.coverage.configure(state="disabled")
        wanted = self.FILTERS.get(self.filter_menu.get(), "")
        cycle = self.cycle_choices.get(self.cycle_menu.get())
        try:
            group_rows = self.manager.split_group_rows(self.project)
        except (ValueError, OSError):
            group_rows = []
        self.rows = [row for row in group_rows
                     if (not wanted or row["split"] == wanted or
                         (wanted == "conflict" and row["group"] in self.health["conflicts"]))
                     and (not cycle or cycle in row["cycles"])]
        self.listbox.delete(0, tk.END)
        for row in self.rows:
            self.listbox.insert(
                tk.END,
                ("⚠ " if row["group"] in self.health["conflicts"] else "") +
                f"[{row['split'].upper():5}] {row['images']} ảnh · {row['sources']} · {row['group']} · {', '.join(row['dates']) or 'Chưa rõ ngày'}",
            )
        self.detail.configure(text=f"Đang hiển thị {len(self.rows)} capture group.")

    def _selected(self) -> dict | None:
        selected = self.listbox.curselection()
        return self.rows[selected[0]] if selected and selected[0] < len(self.rows) else None

    def _show_selected(self) -> None:
        row = self._selected()
        if row:
            info = f"{row['group']} · {row['images']} ảnh · {row['reviewed']} đã duyệt · tập {row['split'].upper()}"
            if row.get("label_counts"):
                info += (f"\n{len(self.health['parents'].get(row['group'], []))} biến thể đang dùng TRAIN liên quan nhóm này.\n"
                         + "Đã duyệt Có/Không: " + row["label_counts"])
            else:
                info += f" · {row['annotations']} nhãn"
            self.detail.configure(
                text=info,
                text_color="#e7f3fb",
            )

    def _move(self, target: str) -> None:
        rows = [self.rows[i] for i in self.listbox.curselection() if i < len(self.rows)]
        if not rows:
            messagebox.showinfo("Chưa chọn nhóm", "Hãy chọn một capture group trước.", parent=self)
            return
        if all(row["split"] == target for row in rows):
            return
        if target != "train":
            conflicts = {r["group"]: self.health["parents"][r["group"]] for r in rows
                         if r["group"] in self.health["parents"]}
            if conflicts:
                messagebox.showwarning("Chưa thể chuyển nhóm", str(SplitConflictError(conflicts)), parent=self)
                return
        if not messagebox.askyesno(
            "Đổi tập của capture group?",
            f"Chuyển {len(rows)} nhóm / {sum(row['images'] for row in rows)} ảnh → {target.upper()}?\n\n"
            + "\n".join(sorted({row['sources'] for row in rows})) + "\n\n"
            + self._move_coverage([row["group"] for row in rows], target) + "\n\n"
            "Việc đổi Validation/Test có thể làm kết quả không còn so sánh trực tiếp với model đã train trước đó.",
            parent=self,
        ):
            return
        self._apply_move([row["group"] for row in rows], target)

    def _move_coverage(self, keys, target):
        assignment = self.manager.ensure_split_assignment(self.project, persist=False)["groups"]
        assignment.update({key: target for key in keys})
        return "DỰ KIẾN SAU KHI CHUYỂN\n" + "\n".join(coverage_lines(self.project, assignment))

    def _apply_move(self, keys, target):
        try:
            self.manager.set_groups_split(self.project, keys, target, expected_revision=self.revision)
            self.on_changed()
        except (ValueError, KeyError, OSError) as exc:
            messagebox.showerror("Chưa đổi phân tập", str(exc), parent=self)
        self._refresh()

    def _repair(self):
        keys = list(self.health["conflicts"])
        if not keys:
            return
        rows = [r for r in self.manager.split_group_rows(self.project) if r["group"] in keys]
        if messagebox.askokcancel("Đưa ảnh gốc về TRAIN?",
                f"Chuyển đúng {len(keys)} nhóm / {sum(r['images'] for r in rows)} ảnh gốc về TRAIN.\n"
                + "\n".join(keys[:8]) + "\n\n"
                + self._move_coverage(keys, "train") + "\n\n"
                "Giữ nguyên ảnh, nhãn, các biến thể và mọi nhóm khác. VAL/TEST sẽ giảm số ảnh tương ứng; "
                "bản phân tập trước được lưu ở split_assignment.previous.json.\n"
                "Không dùng bộ TEST đã thay đổi để tuyên bố độc lập với model cũ đã học các ảnh đó.", parent=self):
            self._apply_move(keys, "train")

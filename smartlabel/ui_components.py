from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog
from typing import Callable
import re
import unicodedata

import customtkinter as ctk
from PIL import Image

from .models import LabelClass, Project


class ThumbnailList(ctk.CTkScrollableFrame):
    """Scrollable image browser with thumbnails, soft status badges and selection."""

    STATUS_STYLE = {
        "unlabeled": ("CHƯA NHÃN", "#52677a", "#ffffff"),
        "draft": ("NHÁP", "#e5a22f", "#211604"),
        "reviewed": ("ĐÃ DUYỆT", "#22ad70", "#ffffff"),
        "rejected": ("TỪ CHỐI", "#dc505b", "#ffffff"),
    }

    def __init__(
        self,
        parent,
        command: Callable[[int], None],
        delete_command: Callable[[object], None] | None = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="#0b141d", corner_radius=9, **kwargs)
        self.command = command
        self.delete_command = delete_command
        self.rows: list[dict] = []
        self.selected_index = -1
        self.selected_key = None
        self._row_by_key: dict[object, dict] = {}
        self._thumbnail_cache: dict[str, ctk.CTkImage] = {}

    def set_items(self, items: list[dict]) -> None:
        """Reconcile visible rows without rebuilding thumbnail widgets.

        Status changes and filters are frequent. Keeping one row per image avoids
        reopening images and recreating hundreds of Tk widgets on every click.
        """
        previous_key = self.selected_key
        previous_keys = [row["key"] for row in self.rows]
        desired_keys = [item["key"] for item in items]
        visible_rows: list[dict] = []
        for item in items:
            key = item["key"]
            row = self._row_by_key.get(key)
            if row is None:
                row = self._create_item(item)
                self._row_by_key[key] = row
            else:
                self._configure_item(row, item)
            visible_rows.append(row)
        if desired_keys != previous_keys:
            desired = set(desired_keys)
            # Pagination supplies only the current page. Destroy rows and
            # thumbnails outside it so browsing a large video never grows the
            # Tk widget/image cache to thousands of items.
            for key, row in list(self._row_by_key.items()):
                if key not in desired:
                    row["frame"].destroy()
                    self._row_by_key.pop(key, None)
                    self._thumbnail_cache.pop(row.get("path", ""), None)
            # Existing visible rows already keep project order. Insert newly
            # visible rows immediately before the next desired row.
            anchor = None
            for row in reversed(visible_rows):
                frame = row["frame"]
                if not frame.winfo_manager():
                    options = {"fill": "x", "padx": 3, "pady": 4}
                    if anchor is not None:
                        options["before"] = anchor
                    frame.pack(**options)
                anchor = frame
        self.rows = visible_rows
        self.selected_index = -1
        self.selected_key = None
        if previous_key is not None:
            restored = next((index for index, row in enumerate(self.rows) if row["key"] == previous_key), -1)
            if restored >= 0:
                self.selected_index = restored
                self.selected_key = previous_key
                self._style_selected(self.rows[restored], True)

    def _thumbnail(self, image_path: str):
        thumbnail = self._thumbnail_cache.get(image_path)
        if thumbnail is not None:
            return thumbnail
        try:
            with Image.open(image_path) as source:
                preview = source.convert("RGB")
                preview.thumbnail((78, 62), Image.Resampling.LANCZOS)
            thumbnail = ctk.CTkImage(light_image=preview, dark_image=preview, size=preview.size)
            self._thumbnail_cache[image_path] = thumbnail
            return thumbnail
        except Exception:
            return None

    def _create_item(self, item: dict) -> dict:
        status = item.get("status", "unlabeled")
        badge_text, badge_bg, badge_fg = self.STATUS_STYLE.get(status, self.STATUS_STYLE["unlabeled"])
        row = ctk.CTkFrame(
            self,
            height=82,
            corner_radius=10,
            fg_color="#111f2c",
            border_width=1,
            border_color="#22394c",
            cursor="hand2",
        )
        row.pack_propagate(False)
        image_path = str(item["path"])
        thumbnail = self._thumbnail(image_path)
        thumb_label = ctk.CTkLabel(row, text="" if thumbnail else "Không có ảnh", image=thumbnail, width=84, height=68, fg_color="#091119", corner_radius=7)
        thumb_label.pack(side="left", padx=7, pady=7)
        center = ctk.CTkFrame(row, fg_color="transparent")
        center.pack(side="left", fill="both", expand=True, padx=(2, 4), pady=7)
        display_name = item.get("display_name") or item.get("name", "")
        name_label = ctk.CTkLabel(center, text=display_name, anchor="w", justify="left", wraplength=150, font=("Segoe UI Semibold", 10), text_color="#dbeaf4")
        name_label.pack(fill="x", anchor="w")
        info_label = ctk.CTkLabel(center, text=f"{item.get('count', 0)} nhãn", anchor="w", font=("Segoe UI", 9), text_color="#7f96a8")
        info_label.pack(fill="x", anchor="w", pady=(2, 0))
        actions = ctk.CTkFrame(row, width=76, fg_color="transparent")
        actions.pack(side="right", fill="y", padx=(2, 7), pady=5)
        delete_button = ctk.CTkButton(
            actions,
            text="×",
            width=28,
            height=23,
            corner_radius=8,
            fg_color="#81363d",
            hover_color="#c44d57",
            font=("Segoe UI Semibold", 14),
            command=lambda key=item["key"]: self._delete_key(key),
        )
        delete_button.pack(anchor="e", pady=(0, 4))
        badge = ctk.CTkLabel(actions, text=badge_text, width=72, height=24, corner_radius=12, fg_color=badge_bg, text_color=badge_fg, font=("Segoe UI Semibold", 8))
        badge.pack(anchor="e")
        ToolTip(delete_button, "Xóa ảnh này cùng toàn bộ nhãn và thuộc tính liên quan.")
        data = {
            "key": item["key"],
            "frame": row,
            "labels": (thumb_label, center, name_label, info_label, actions, badge),
            "thumb": thumb_label,
            "name": name_label,
            "info": info_label,
            "badge": badge,
            "delete": delete_button,
            "status": status,
            "count": item.get("count", 0),
            "display_name": display_name,
            "path": image_path,
        }
        for widget in (row, thumb_label, center, name_label, info_label, actions, badge):
            widget.bind("<Button-1>", lambda _event, key=item["key"]: self._select_key(key), add="+")
        return data

    def _configure_item(self, row: dict, item: dict) -> None:
        status = item.get("status", "unlabeled")
        badge_text, badge_bg, badge_fg = self.STATUS_STYLE.get(status, self.STATUS_STYLE["unlabeled"])
        display_name = item.get("display_name") or item.get("name", "")
        count = item.get("count", 0)
        if display_name != row["display_name"]:
            row["name"].configure(text=display_name)
            row["display_name"] = display_name
        if count != row["count"]:
            row["info"].configure(text=f"{count} nhãn")
            row["count"] = count
        if status != row["status"]:
            row["badge"].configure(text=badge_text, fg_color=badge_bg, text_color=badge_fg)
            row["status"] = status
        image_path = str(item["path"])
        if image_path != row["path"]:
            thumbnail = self._thumbnail(image_path)
            row["thumb"].configure(image=thumbnail, text="" if thumbnail else "Không có ảnh")
            row["path"] = image_path

    def _select_key(self, key) -> None:
        index = next((i for i, row in enumerate(self.rows) if row["key"] == key), -1)
        if index >= 0:
            self.select(index, notify=True, focus=True)

    def _delete_key(self, key) -> None:
        """Select the row first, then ask the owner to confirm its deletion."""
        index = next((i for i, row in enumerate(self.rows) if row["key"] == key), -1)
        if index < 0:
            return
        self.select(index, notify=True, focus=True)
        if self.delete_command:
            self.delete_command(key)

    @staticmethod
    def _style_selected(row: dict, selected: bool) -> None:
        row["frame"].configure(
            fg_color="#193246" if selected else "#111f2c",
            border_width=2 if selected else 1,
            border_color="#29bce8" if selected else "#22394c",
        )

    def select(self, index: int, *, notify: bool = False, focus: bool = False) -> None:
        if not (0 <= index < len(self.rows)):
            return
        if self.selected_key in self._row_by_key:
            self._style_selected(self._row_by_key[self.selected_key], False)
        self.selected_index = index
        current = self.rows[index]
        self.selected_key = current["key"]
        self._style_selected(current, True)
        self.see(index)
        if focus:
            current["frame"].focus_set()
        if notify:
            self.command(index)

    def see(self, index: int) -> None:
        if not (0 <= index < len(self.rows)):
            return
        self.update_idletasks()
        row = self.rows[index]["frame"]
        content_height = max(self.winfo_height(), self._parent_canvas.bbox("all")[3] if self._parent_canvas.bbox("all") else 1)
        viewport_height = max(self._parent_canvas.winfo_height(), 1)
        top = self._parent_canvas.canvasy(0)
        bottom = top + viewport_height
        row_top, row_bottom = row.winfo_y(), row.winfo_y() + row.winfo_height()
        if row_top < top:
            self._parent_canvas.yview_moveto(max(0.0, row_top / content_height))
        elif row_bottom > bottom:
            target = max(0.0, (row_bottom - viewport_height) / content_height)
            self._parent_canvas.yview_moveto(min(1.0, target))

    def curselection(self) -> tuple[int, ...]:
        return (self.selected_index,) if self.selected_index >= 0 else ()

    def update_item(self, index: int, *, status: str, count: int) -> None:
        if not (0 <= index < len(self.rows)):
            return
        badge_text, badge_bg, badge_fg = self.STATUS_STYLE.get(status, self.STATUS_STYLE["unlabeled"])
        row = self.rows[index]
        row["status"] = status
        row["count"] = count
        row["info"].configure(text=f"{count} nhãn")
        row["badge"].configure(text=badge_text, fg_color=badge_bg, text_color=badge_fg)


class ToolTip:
    """Small delayed tooltip that works with Tk and CustomTkinter widgets."""

    def __init__(self, widget, text: str, delay_ms: int = 500):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.after_id = None
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self.after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def _show(self):
        if self.window or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.window,
            text=self.text,
            justify="left",
            background="#eaf5fc",
            foreground="#132433",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
            font=("Segoe UI", 9),
            wraplength=360,
        )
        label.pack()

    def _hide(self, _event=None):
        self._cancel()
        if self.window:
            self.window.destroy()
            self.window = None


class ProjectSettingsDialog(ctk.CTkToplevel):
    PALETTE = ["#21c7ff", "#74e35c", "#ffb547", "#f55d76", "#ad8cff", "#42d9c8"]
    ATTRIBUTE_TITLES = {
        "condition": "Tình trạng",
        "occlusion": "Che khuất",
        "cap": "Nắp chai",
    }
    ROLE_LABELS = {
        "metadata": "Chỉ metadata",
        "classification": "Nhãn Classification hai giai đoạn",
        "pass_fail": "Điều kiện OK/NG",
    }
    NO_DEFAULT = "— Không mặc định —"

    def __init__(self, parent, project: Project, on_save: Callable[[], None]):
        super().__init__(parent)
        self.project = project
        self.on_save = on_save
        self.title("Quản lý Class và thuộc tính")
        self.geometry("900x680")
        self.minsize(760, 560)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color="#0b151f")
        self.class_rows: list[dict] = []
        self.attribute_groups: dict[str, dict] = {}

        ctk.CTkLabel(
            self,
            text="QUẢN LÝ NHÃN DỰ ÁN",
            font=("Segoe UI Semibold", 20),
            text_color="#22b9ee",
        ).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(
            self,
            text="Class mô tả loại vật; nhóm thuộc tính có thể lưu metadata hoặc train thành classifier giai đoạn hai.",
            text_color="#8298aa",
        ).pack(anchor="w", padx=20, pady=(0, 10))

        tabs = ctk.CTkTabview(self, fg_color="#101b27", corner_radius=12)
        tabs.pack(fill="both", expand=True, padx=18, pady=8)
        tabs.add("CLASS")
        tabs.add("THUỘC TÍNH")
        self._build_classes(tabs.tab("CLASS"))
        self._build_attributes(tabs.tab("THUỘC TÍNH"))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=18, pady=(4, 16))
        cancel_button = ctk.CTkButton(footer, text="Hủy", width=110, fg_color="#415466", command=self.destroy)
        cancel_button.pack(side="right", padx=5)
        ToolTip(cancel_button, "Đóng cửa sổ và không áp dụng thay đổi.")
        save_button = ctk.CTkButton(footer, text="LƯU THAY ĐỔI", width=170, fg_color="#2b906d", command=self._save)
        save_button.pack(side="right", padx=5)
        ToolTip(save_button, "Kiểm tra và lưu toàn bộ Class, màu cùng các lựa chọn thuộc tính.")

    def _build_classes(self, parent):
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=8, pady=8)
        add_button = ctk.CTkButton(toolbar, text="+ Thêm Class", width=130, command=self._add_class)
        add_button.pack(side="left")
        ToolTip(add_button, "Tạo một Class mới với ID ổn định và màu mặc định.")
        ctk.CTkLabel(toolbar, text="Không thể xóa Class đang được nhãn sử dụng.", text_color="#8298aa").pack(side="left", padx=12)
        self.class_container = ctk.CTkScrollableFrame(parent, fg_color="#0c1721", corner_radius=10)
        self.class_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        header = ctk.CTkFrame(self.class_container, fg_color="transparent")
        header.pack(fill="x", pady=(2, 6))
        for text, width in (("ID", 50), ("Màu", 70), ("Tên Class", 420), ("Số nhãn", 90), ("", 80)):
            ctk.CTkLabel(header, text=text, width=width, anchor="w", text_color="#8298aa").pack(side="left", padx=4)
        for item in sorted(self.project.classes, key=lambda value: value.id):
            self._append_class_row(item.id, item.name, item.color)

    def _append_class_row(self, class_id: int, name: str, color: str):
        row = ctk.CTkFrame(self.class_container, fg_color="#142333", corner_radius=8)
        row.pack(fill="x", pady=3)
        name_var = tk.StringVar(value=name)
        color_var = tk.StringVar(value=color)
        count = sum(1 for image in self.project.images for ann in image.annotations if ann.class_id == class_id)
        ctk.CTkLabel(row, text=str(class_id), width=50, anchor="w").pack(side="left", padx=4, pady=6)
        color_button = ctk.CTkButton(row, text="", width=54, height=28, fg_color=color, hover_color=color)
        color_button.pack(side="left", padx=8)
        color_button.configure(command=lambda: self._choose_color(color_var, color_button))
        ToolTip(color_button, "Mở bảng màu để chọn màu overlay cho Class này.")
        ctk.CTkEntry(row, width=420, textvariable=name_var).pack(side="left", padx=4, pady=6)
        ctk.CTkLabel(row, text=str(count), width=90, anchor="w").pack(side="left", padx=4)
        delete = ctk.CTkButton(row, text="Xóa", width=70, fg_color="#a94747")
        delete.pack(side="left", padx=4)
        data = {"id": class_id, "name": name_var, "color": color_var, "frame": row, "count": count}
        delete.configure(command=lambda: self._delete_class_row(data))
        ToolTip(delete, "Xóa Class nếu chưa có nhãn nào đang sử dụng.")
        self.class_rows.append(data)

    def _add_class(self):
        next_id = max((row["id"] for row in self.class_rows), default=-1) + 1
        self._append_class_row(next_id, f"Class_{next_id}", self.PALETTE[next_id % len(self.PALETTE)])
        self.class_container._parent_canvas.yview_moveto(1.0)

    def _delete_class_row(self, row):
        if row["count"]:
            messagebox.showwarning("Không thể xóa", f"Class ID {row['id']} đang được {row['count']} nhãn sử dụng.", parent=self)
            return
        if any(other["id"] > row["id"] for other in self.class_rows):
            messagebox.showwarning(
                "Giữ Class ID liên tục",
                "Chỉ có thể xóa Class cuối danh sách. Hãy xóa từ ID lớn nhất xuống để không làm sai ánh xạ model/dataset.",
                parent=self,
            )
            return
        row["frame"].destroy()
        self.class_rows.remove(row)

    @staticmethod
    def _choose_color(variable: tk.StringVar, button):
        selected = colorchooser.askcolor(variable.get(), title="Chọn màu Class")
        if selected and selected[1]:
            variable.set(selected[1])
            button.configure(fg_color=selected[1], hover_color=selected[1])

    def _build_attributes(self, parent):
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=8, pady=8)
        add_group = ctk.CTkButton(toolbar, text="+ Thêm nhóm thuộc tính", width=180, command=self._add_attribute_group)
        add_group.pack(side="left")
        ToolTip(add_group, "Tạo nhóm tùy chọn mới, ví dụ: Tình trạng, Màu sắc, Nắp chai hoặc Mức che khuất.")
        ctk.CTkLabel(
            toolbar,
            text="* Bắt buộc được kiểm tra khi Duyệt. Mỗi nhóm Classification được train thành một model riêng.",
            text_color="#8298aa",
        ).pack(side="left", padx=12)
        self.attribute_container = ctk.CTkScrollableFrame(parent, fg_color="#0c1721", corner_radius=10)
        self.attribute_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        schema = dict(self.project.attribute_schema)
        settings = dict(getattr(self.project, "attribute_settings", {}) or {})
        if not schema:
            schema = {
                "condition": ["nguyen_ven", "bep_nhe", "can_dep", "vo_nat"],
                "occlusion": ["none", "partial", "heavy"],
                "cap": ["co_nap", "mat_nap", "khong_xac_dinh"],
            }
        legacy_defaults = {"occlusion": "none", "cap": "khong_xac_dinh"}
        for key, values in schema.items():
            config = dict(settings.get(key, {}))
            config.setdefault("title", self.ATTRIBUTE_TITLES.get(key, key.replace("_", " ").title()))
            config.setdefault("default", legacy_defaults.get(key, ""))
            config.setdefault("required", False)
            config.setdefault("role", "metadata")
            self._append_attribute_group(key, values, config)

    @staticmethod
    def _slug(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.replace("Đ", "D").replace("đ", "d"))
        ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
        return slug or "thuoc_tinh"

    def _add_attribute_group(self):
        title = simpledialog.askstring("Thêm nhóm thuộc tính", "Tên nhóm (ví dụ: Tình trạng chai):", parent=self)
        if not title or not title.strip():
            return
        base = self._slug(title)
        key = base
        index = 2
        while key in self.attribute_groups:
            key = f"{base}_{index}"
            index += 1
        self._append_attribute_group(
            key,
            ["chua_xac_dinh"],
            {"title": title.strip(), "default": "", "required": False, "role": "metadata"},
        )
        self.attribute_container._parent_canvas.yview_moveto(1.0)

    def _append_attribute_group(self, key: str, values: list[str], config: dict):
        group = ctk.CTkFrame(self.attribute_container, fg_color="#142333", corner_radius=10)
        group.pack(fill="x", padx=4, pady=7)
        top = ctk.CTkFrame(group, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))
        title_var = tk.StringVar(value=str(config.get("title") or self.ATTRIBUTE_TITLES.get(key, key)))
        ctk.CTkLabel(top, text="Tên nhóm", width=75, anchor="w", text_color="#8298aa").pack(side="left")
        ctk.CTkEntry(top, textvariable=title_var, width=300).pack(side="left", padx=4)
        ctk.CTkLabel(top, text=f"Mã: {key}", text_color="#61798d", font=("Consolas", 10)).pack(side="left", padx=8)
        delete_group = ctk.CTkButton(top, text="Xóa nhóm", width=90, fg_color="#a94747", command=lambda: self._delete_attribute_group(key))
        delete_group.pack(side="right")
        ToolTip(delete_group, "Xóa toàn bộ nhóm nếu chưa có nhãn nào sử dụng nhóm này.")

        controls = ctk.CTkFrame(group, fg_color="transparent")
        controls.pack(fill="x", padx=10, pady=4)
        default_var = tk.StringVar(value=str(config.get("default") or self.NO_DEFAULT))
        required_var = tk.BooleanVar(value=bool(config.get("required", False)))
        role_code = str(config.get("role", "metadata"))
        role_var = tk.StringVar(value=self.ROLE_LABELS.get(role_code, self.ROLE_LABELS["metadata"]))
        ctk.CTkLabel(controls, text="Mặc định", text_color="#8298aa").pack(side="left")
        default_menu = ctk.CTkOptionMenu(controls, width=175, values=[self.NO_DEFAULT], variable=default_var)
        default_menu.pack(side="left", padx=(5, 12))
        required = ctk.CTkCheckBox(controls, text="Bắt buộc", variable=required_var, checkbox_width=19, checkbox_height=19)
        required.pack(side="left", padx=(0, 12))
        ToolTip(required, "Nếu bật, mọi nhãn phải có giá trị của nhóm này trước khi ảnh được Duyệt.")
        ctk.CTkLabel(controls, text="Mục đích", text_color="#8298aa").pack(side="left")
        role_menu = ctk.CTkOptionMenu(controls, width=210, values=list(self.ROLE_LABELS.values()), variable=role_var)
        role_menu.pack(side="left", padx=5)
        ToolTip(role_menu, "Nhóm này có thể export crop và train thành classifier riêng sau model Detection/SEG.")

        option_header = ctk.CTkFrame(group, fg_color="transparent")
        option_header.pack(fill="x", padx=10, pady=(5, 0))
        ctk.CTkLabel(option_header, text="CÁC GIÁ TRỊ", font=("Segoe UI Semibold", 11), text_color="#22b9ee").pack(side="left")
        add_button = ctk.CTkButton(option_header, text="+ Thêm lựa chọn", width=130, command=lambda: self._add_attribute_option(key))
        add_button.pack(side="right")
        ToolTip(add_button, f"Thêm một giá trị mới cho nhóm {title_var.get()}.")
        options = ctk.CTkFrame(group, fg_color="transparent")
        options.pack(fill="x", padx=10, pady=(2, 10))
        self.attribute_groups[key] = {
            "frame": group,
            "title": title_var,
            "default": default_var,
            "default_menu": default_menu,
            "required": required_var,
            "role": role_var,
            "options": options,
            "rows": [],
        }
        for value in values:
            self._append_attribute_row(key, options, value)
        self._refresh_default_menu(key)

    def _append_attribute_row(self, key: str, parent, value: str):
        row = ctk.CTkFrame(parent, fg_color="#0c1721", corner_radius=7)
        row.pack(fill="x", pady=3)
        variable = tk.StringVar(value=value)
        ctk.CTkEntry(row, textvariable=variable, width=520).pack(side="left", padx=8, pady=5)
        delete = ctk.CTkButton(row, text="Xóa", width=70, fg_color="#a94747")
        delete.pack(side="right", padx=8, pady=5)
        data = {"value": variable, "frame": row}
        delete.configure(command=lambda: self._delete_attribute_row(key, data))
        ToolTip(delete, "Xóa lựa chọn này nếu chưa có nhãn nào đang sử dụng.")
        self.attribute_groups[key]["rows"].append(data)
        variable.trace_add("write", lambda *_args, attr=key: self._refresh_default_menu(attr))

    def _add_attribute_option(self, key: str):
        group = self.attribute_groups[key]
        value = simpledialog.askstring("Thêm lựa chọn", f"Giá trị mới cho {group['title'].get()}:", parent=self)
        if value and value.strip():
            self._append_attribute_row(key, group["options"], value.strip())
            self._refresh_default_menu(key)

    def _refresh_default_menu(self, key: str):
        group = self.attribute_groups.get(key)
        if not group:
            return
        values = [row["value"].get().strip() for row in group["rows"] if row["value"].get().strip()]
        choices = [self.NO_DEFAULT, *dict.fromkeys(values)]
        group["default_menu"].configure(values=choices)
        if group["default"].get() not in choices:
            group["default"].set(self.NO_DEFAULT)

    def _delete_attribute_row(self, key: str, row):
        value = row["value"].get().strip()
        used = sum(1 for image in self.project.images for ann in image.annotations if ann.attributes.get(key) == value)
        if used:
            messagebox.showwarning("Không thể xóa", f"Giá trị “{value}” đang được {used} nhãn sử dụng.", parent=self)
            return
        row["frame"].destroy()
        self.attribute_groups[key]["rows"].remove(row)
        self._refresh_default_menu(key)

    def _delete_attribute_group(self, key: str):
        used = sum(1 for image in self.project.images for ann in image.annotations if key in ann.attributes)
        if used:
            messagebox.showwarning(
                "Không thể xóa",
                f"Nhóm “{self.attribute_groups[key]['title'].get()}” đang được {used} nhãn sử dụng.",
                parent=self,
            )
            return
        group = self.attribute_groups.pop(key)
        group["frame"].destroy()

    def _save(self):
        names = [row["name"].get().strip() for row in self.class_rows]
        if not names or any(not value for value in names):
            messagebox.showerror("Thiếu tên", "Mọi Class phải có tên.", parent=self)
            return
        if len({value.lower() for value in names}) != len(names):
            messagebox.showerror("Trùng tên", "Tên Class không được trùng nhau.", parent=self)
            return
        schema = {}
        attribute_settings = {}
        titles = []
        for key, group in self.attribute_groups.items():
            title = group["title"].get().strip()
            if not title:
                messagebox.showerror("Thiếu tên nhóm", f"Nhóm mã {key} chưa có tên hiển thị.", parent=self)
                return
            titles.append(title.lower())
            rows = group["rows"]
            values = [row["value"].get().strip() for row in rows if row["value"].get().strip()]
            if not values:
                messagebox.showerror("Thiếu lựa chọn", f"{title} phải có ít nhất một giá trị.", parent=self)
                return
            if len(set(values)) != len(values):
                messagebox.showerror("Trùng lựa chọn", f"{title} có giá trị trùng.", parent=self)
                return
            default = group["default"].get()
            default = "" if default == self.NO_DEFAULT else default
            if default and default not in values:
                messagebox.showerror("Mặc định không hợp lệ", f"Giá trị mặc định của {title} không còn trong danh sách.", parent=self)
                return
            role_label = group["role"].get()
            role = next((code for code, label in self.ROLE_LABELS.items() if label == role_label), "metadata")
            schema[key] = values
            attribute_settings[key] = {
                "title": title,
                "default": default,
                "required": bool(group["required"].get()),
                "role": role,
            }
        if len(set(titles)) != len(titles):
            messagebox.showerror("Trùng tên nhóm", "Tên nhóm thuộc tính không được trùng nhau.", parent=self)
            return
        self.project.classes = [
            LabelClass(row["id"], row["name"].get().strip(), row["color"].get())
            for row in sorted(self.class_rows, key=lambda value: value["id"])
        ]
        self.project.attribute_schema = schema
        self.project.attribute_settings = attribute_settings
        self.on_save()
        self.destroy()

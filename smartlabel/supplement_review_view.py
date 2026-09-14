"""Hydro supplement gallery, isolated from the capture annotation canvas."""
from copy import deepcopy
import gc
from queue import Queue, Empty
from threading import Thread
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from .hydro_labels import model_attributes, presented_display_values
from .supplement_review import load_review, preview_path, review_state, save_review

STAGES = {"small": "Cây nhỏ", "medium": "Cây vừa", "large": "Trưởng thành"}
ALL = "Tất cả"


class SupplementPreview(tk.Canvas):
    def __init__(self, master):
        super().__init__(master, bg="#091119", highlightthickness=0)
        self.source = self.photo = None
        self.factor, self.offset = 1.0, (0, 0)
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<MouseWheel>", lambda e: self.zoom(1.2 if e.delta > 0 else 1 / 1.2))
        self.bind("<ButtonPress-1>", self.start_pan)
        self.bind("<B1-Motion>", self.pan)

    def show(self, path=None):
        self.source = None
        if path:
            with Image.open(path) as im:
                self.source = im.convert("RGB")
        self.fit()

    def fit(self):
        self.factor, self.offset = 1.0, (0, 0)
        self.draw()

    def zoom(self, factor):
        self.factor = max(1, min(6, self.factor * factor))
        self.draw()

    def start_pan(self, event):
        self.focus_set()
        self.origin = (event.x - self.offset[0], event.y - self.offset[1])

    def pan(self, event):
        self.offset = (event.x - self.origin[0], event.y - self.origin[1])
        self.draw()

    def draw(self):
        self.delete("all")
        if self.source is None:
            self.photo = None
            return
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        scale = min(w / self.source.width, h / self.source.height) * self.factor
        # Crop the visible source rectangle before resizing, including at high
        # zoom, so memory use stays bounded by the viewport rather than zoom².
        dw, dh = self.source.width * scale, self.source.height * scale
        x, y = (w - dw) / 2 + self.offset[0], (h - dh) / 2 + self.offset[1]
        box = (max(0, -x / scale), max(0, -y / scale),
               min(self.source.width, (w - x) / scale), min(self.source.height, (h - y) / scale))
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        crop = self.source.crop(box)
        size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        self.photo = ImageTk.PhotoImage(crop.resize(size, Image.Resampling.LANCZOS), master=self)
        self.create_image(max(0, x), max(0, y), image=self.photo, anchor="nw")


class SupplementReviewView(ctk.CTkFrame):
    PAGE_SIZE = 24

    def __init__(self, master, app, colors):
        super().__init__(master, fg_color="transparent")
        self.app, self.colors = app, colors
        self.project = self.data = self.revision = self.selected = None
        self.rows, self.filtered, self.form = [], [], {}
        self.page, self.busy = 0, False
        self.results = Queue()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.banner = ctk.CTkLabel(self, text="", anchor="w", text_color=colors["muted"])
        self.banner.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 7))
        left = ctk.CTkFrame(self, fg_color=colors["panel2"], width=250)
        left.grid(row=1, column=0, sticky="ns", padx=(0, 8))
        ctk.CTkLabel(left, text="ẢNH BỔ TRỢ", text_color=colors["accent"],
                     font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=12, pady=8)
        self.status_filter = self.menu(left, [ALL, "Đang dùng train", "Chờ duyệt", "Từ chối", "Đã duyệt · tạm tắt"])
        self.batch_filter = self.menu(left, ["Tất cả đợt"])
        self.stage_filter = self.menu(left, ["Mọi tuổi cây", *STAGES.values()])
        self.attribute_filter = self.menu(left, ["Mọi nhãn"])
        self.counter = ctk.CTkLabel(left, text="", text_color=colors["muted"], font=("Segoe UI", 11))
        self.counter.pack(pady=(3, 0))
        pager = ctk.CTkFrame(left, fg_color="transparent")
        pager.pack(fill="x", padx=10, pady=5)
        self.prev_page = app._button(pager, "◀", lambda: self.change_page(-1), width=42, color="#415466")
        self.prev_page.pack(side="left")
        self.page_label = ctk.CTkLabel(pager, text="", width=116)
        self.page_label.pack(side="left")
        self.next_page = app._button(pager, "▶", lambda: self.change_page(1), width=42, color="#415466")
        self.next_page.pack(side="left")
        self.list_frame = ctk.CTkScrollableFrame(left, width=220, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        self.reload_button = app._button(left, "Tải lại danh sách", self.reload, width=224, color="#415466")
        self.reload_button.pack(padx=10, pady=(0, 10))

        center = ctk.CTkFrame(self, fg_color="#091119", corner_radius=12)
        center.grid(row=1, column=1, sticky="nsew")
        self.image_title = ctk.CTkLabel(center, text="Chọn ảnh bổ trợ", anchor="w", font=("Segoe UI Semibold", 13))
        self.image_title.pack(fill="x", padx=12, pady=8)
        self.preview = SupplementPreview(center)
        self.preview.pack(fill="both", expand=True, padx=8, pady=4)
        nav = ctk.CTkFrame(center, fg_color="transparent")
        nav.pack(fill="x", padx=10, pady=8)
        self.previous = app._button(nav, "◀ Trước", lambda: self.navigate(-1), width=85, color="#415466")
        self.previous.pack(side="left", padx=2)
        self.next = app._button(nav, "Sau ▶", lambda: self.navigate(1), width=85, color="#415466")
        self.next.pack(side="right", padx=2)
        app._button(nav, "Vừa ảnh", self.preview.fit, width=80, color="#415466").pack()

        self.details = ctk.CTkScrollableFrame(self, width=268, fg_color=colors["panel2"])
        self.details.grid(row=1, column=2, sticky="ns", padx=(8, 0))
        self.status = self.label(self.details, "", colors["good"], bold=True)
        self.meta = self.label(self.details, "", colors["muted"])
        self.label(self.details, "NHÃN DÙNG TRAIN", colors["accent"], bold=True)
        self.form_frame = ctk.CTkFrame(self.details, fg_color="transparent")
        self.form_frame.pack(fill="x", padx=8)
        self.label(self.details, "Chọn nhãn đúng rồi nhấn Duyệt & dùng train. Chỉ lưu vào lần xuất dataset tiếp theo.", colors["muted"])
        self.approve = app._button(self.details, "Duyệt & dùng train", lambda: self.save("reviewed"), width=240, color="#237a57")
        self.approve.pack(fill="x", padx=8, pady=(8, 4))
        self.reject = app._button(self.details, "Từ chối ảnh", lambda: self.save("rejected"), width=240, color="#804550")
        self.reject.pack(fill="x", padx=8, pady=4)
        self.draft = app._button(self.details, "Chuyển về chờ duyệt", lambda: self.save("draft"), width=240, color="#415466")
        self.draft.pack(fill="x", padx=8, pady=4)
        self.feedback = self.label(self.details, "", colors["muted"])
        self.label(self.details, "NGUỒN & LẦN DUYỆT", colors["accent"], bold=True)
        self.provenance = self.label(self.details, "", colors["muted"])
        self.set_project(None)

    def label(self, parent, text, color, bold=False):
        widget = ctk.CTkLabel(parent, text=text, text_color=color, justify="left", anchor="w", wraplength=238,
                              font=("Segoe UI Semibold" if bold else "Segoe UI", 13 if bold else 12))
        widget.pack(fill="x", padx=10, pady=5)
        return widget

    def menu(self, parent, values):
        widget = ctk.CTkOptionMenu(parent, values=values, width=224, command=self.apply_filters)
        widget.pack(padx=10, pady=(0, 6))
        return widget

    def set_project(self, project):
        if self.project is project and project is not None:
            return
        self.project = project
        self.data = self.revision = self.selected = None
        self.rows, self.filtered, self.form = [], [], {}
        self.page = 0
        self.batch_map, self.attribute_map = {}, {}
        for widget, value in ((self.status_filter, ALL), (self.batch_filter, "Tất cả đợt"),
                              (self.stage_filter, "Mọi tuổi cây"), (self.attribute_filter, "Mọi nhãn")):
            widget.set(value)
        self.render_list()
        self.show_row(None)
        self.banner.configure(text="Ảnh bổ trợ được lưu riêng; không thêm lại ảnh gốc vào dự án.")

    def allow_leave(self):
        if self.busy:
            return False
        if self.selected and self.values() != self.selected.get("attributes", {}):
            if not messagebox.askyesno("Nhãn chưa lưu", "Bỏ thay đổi nhãn chưa duyệt để chuyển ảnh hoặc tải lại?", parent=self):
                return False
            for key, (menu, choices) in self.form.items():
                original = self.selected["attributes"][key]
                menu.set(next((caption for caption, value in choices.items() if value == original), original))
        return True

    def reload(self):
        if not self.allow_leave():
            return
        try:
            self.data, self.revision = load_review(self.app.store, self.project)
            self.rows = self.data["images"] if self.data else []
            self.batch_map = {f"Đợt {i + 1} · {sum(r.get('batchId', '') == key for r in self.rows)} ảnh": key
                              for i, key in enumerate(dict.fromkeys(r.get("batchId", "") for r in self.rows))}
            self.batch_filter.configure(values=["Tất cả đợt", *self.batch_map])
            if self.batch_filter.get() not in self.batch_map:
                self.batch_filter.set("Tất cả đợt")
            self.attribute_map = {f"{a['displayName']} · {caption}": (a["id"], value)
                                  for a in model_attributes(self.project) for value, caption in presented_display_values(a).items()
                                  if any(r.get("attributes", {}).get(a["id"]) == value for r in self.rows)} if self.project else {}
            self.attribute_filter.configure(values=["Mọi nhãn", *self.attribute_map])
            if self.attribute_filter.get() not in self.attribute_map:
                self.attribute_filter.set("Mọi nhãn")
            self.selected = None
            self.apply_filters()
            self.banner.configure(text=f"{len(self.rows)} ảnh bổ trợ · {sum(r.get('enabled') is True for r in self.rows)} đang bật train"
                                  "  •  Không dùng cho VAL / TEST; không thêm ảnh gốc.")
            self.feedback.configure(text="")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.rows, self.filtered = [], []
            self.data = self.revision = None
            self.render_list()
            self.show_row(None)
            self.banner.configure(text=f"Chưa đọc được ảnh bổ trợ: {exc}")

    def apply_filters(self, _value=None):
        if self.busy:
            return
        if not self.allow_leave():
            for menu, value in zip((self.status_filter, self.batch_filter, self.stage_filter, self.attribute_filter), self.filter_selection):
                menu.set(value)
            return
        self.filter_selection = tuple(menu.get() for menu in (self.status_filter, self.batch_filter, self.stage_filter, self.attribute_filter))
        state, batch, stage = self.status_filter.get(), self.batch_map.get(self.batch_filter.get()), self.stage_filter.get()
        attr = self.attribute_map.get(self.attribute_filter.get())
        self.filtered = [r for r in self.rows if (state == ALL or review_state(r) == state)
                         and (batch is None or r.get("batchId", "") == batch)
                         and (stage == "Mọi tuổi cây" or STAGES.get(r.get("growthStage")) == stage)
                         and (attr is None or r.get("attributes", {}).get(attr[0]) == attr[1])]
        self.page = 0
        self.render_list()
        self.show_row(self.filtered[0] if self.filtered else None)

    def render_list(self):
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        self.thumbnails, self.list_buttons = [], {}
        page_rows = self.filtered[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        for row in page_rows:
            photo = None
            try:
                with Image.open(preview_path(self.app.store, self.project, row)) as im:
                    thumb = im.convert("RGB")
                    thumb.thumbnail((56, 56))
                    photo = ctk.CTkImage(thumb, size=thumb.size)
                    self.thumbnails.append(photo)
            except (OSError, ValueError):
                pass
            index = self.rows.index(row) + 1
            button = ctk.CTkButton(self.list_frame, text=f"Ảnh {index:03d} · {STAGES.get(row.get('growthStage'), 'Bổ trợ')}\n{review_state(row)}",
                image=photo, anchor="w", height=66, font=("Segoe UI", 11), fg_color="#1c3042", hover_color="#294a62",
                command=lambda r=row: self.select(r))
            button.pack(fill="x", pady=3)
            self.list_buttons[row["id"]] = button
        pages = max(1, (len(self.filtered) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.counter.configure(text=f"{len(self.filtered)} / {len(self.rows)} ảnh")
        self.page_label.configure(text=f"Trang {self.page + 1} / {pages}")
        self.app._set_button_enabled(self.prev_page, not self.busy and self.page > 0)
        self.app._set_button_enabled(self.next_page, not self.busy and self.page + 1 < pages)
        if not page_rows:
            ctk.CTkLabel(self.list_frame, text="Chưa có ảnh phù hợp.", text_color=self.colors["muted"]).pack(pady=20)

    def change_page(self, delta):
        if not self.allow_leave():
            return
        pages = max(1, (len(self.filtered) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = max(0, min(pages - 1, self.page + delta))
        self.render_list()
        self.show_row(next(iter(self.filtered[self.page * self.PAGE_SIZE:]), None))

    def select(self, row):
        if self.allow_leave():
            self.show_row(row)

    def navigate(self, delta):
        if not self.selected or not self.allow_leave():
            return
        index = self.filtered.index(self.selected) + delta
        if 0 <= index < len(self.filtered):
            self.page = index // self.PAGE_SIZE
            self.render_list()
            self.show_row(self.filtered[index])

    def show_row(self, row):
        self.selected = row
        self.form = {}
        for widget in self.form_frame.winfo_children():
            widget.destroy()
        self.preview.show()
        for key, button in self.list_buttons.items():
            button.configure(fg_color="#275273" if row and row["id"] == key else "#1c3042")
        color = (self.colors["bad"] if row and row.get("reviewStatus") == "rejected"
                 else self.colors["good"] if row and row.get("enabled") is True else self.colors["warn"])
        self.status.configure(text=review_state(row) if row else "Chưa chọn ảnh", text_color=color)
        self.meta.configure(text="")
        self.provenance.configure(text="")
        self.feedback.configure(text="")
        self.image_title.configure(text=f"Ảnh {self.rows.index(row) + 1:03d} · Chỉ ảnh bổ trợ" if row else "Chọn ảnh bổ trợ")
        self.preview_ok = False
        if row:
            try:
                self.preview.show(preview_path(self.app.store, self.project, row))
                self.preview_ok = True
            except (OSError, ValueError) as exc:
                self.feedback.configure(text=str(exc), text_color=self.colors["warn"])
            self.meta.configure(text=f"{'Ảnh tổng hợp' if row.get('kind') == 'synthetic' else 'Nguồn ngoài'} · Chỉ TRAIN\n"
                                f"{STAGES.get(row.get('growthStage'), 'Chưa ghi tuổi cây')}"
                                + (f" · {row['ageDays']} ngày" if row.get('ageDays') is not None else ""))
            attrs = {a["id"]: a for a in model_attributes(self.project)}
            for key, value in row.get("attributes", {}).items():
                attr = attrs.get(key)
                captions = presented_display_values(attr) if attr else {value: value}
                choices = {caption: raw for raw, caption in captions.items()}
                self.label(self.form_frame, attr["displayName"] if attr else key, self.colors["text"], bold=True)
                menu = ctk.CTkOptionMenu(self.form_frame, values=list(choices), width=234)
                menu.set(captions.get(value, str(value)))
                menu.pack(fill="x", pady=(0, 6))
                self.form[key] = (menu, choices)
            source = row.get("provenance", {})
            self.provenance.configure(text=f"Mã: {row['id']}\nĐợt: {row.get('batchId', 'Ban đầu')}\n"
                f"Cách tạo: {source.get('method', source.get('author', 'Chưa ghi'))}\n"
                f"Nguồn: {source.get('parentImageId', source.get('url', 'Chưa ghi'))}\n\n"
                f"Người duyệt: {row.get('reviewedBy', 'Chưa duyệt')}\n"
                f"{row.get('reviewNote', '')}")
        self.update_controls()

    def values(self):
        return {key: choices.get(menu.get(), menu.get()) for key, (menu, choices) in self.form.items()}

    def update_controls(self):
        valid = self.selected is not None and not self.busy
        for button in (self.approve, self.reject, self.draft):
            self.app._set_button_enabled(button, valid and (button != self.approve or self.preview_ok))
        self.app._set_button_enabled(self.previous, valid and self.filtered.index(self.selected) > 0)
        self.app._set_button_enabled(self.next, valid and self.filtered.index(self.selected) + 1 < len(self.filtered))
        self.app._set_button_enabled(self.reload_button, not self.busy)
        for menu in (self.status_filter, self.batch_filter, self.stage_filter, self.attribute_filter,
                     *(pair[0] for pair in self.form.values())):
            menu.configure(state="disabled" if self.busy else "normal")

    def save(self, decision):
        if self.busy or not self.selected or self.project is not self.app.project or not self.app._can_change_project():
            return
        project = deepcopy(self.project)
        assignments = self.app.datasets.ensure_split_assignment(project, persist=False)["groups"]
        identifier, revision, attributes = self.selected["id"], self.revision, self.values()
        self.busy = self.app.supplement_review_running = True
        self.grab_set()
        self.update_controls()
        self.feedback.configure(text="Đang kiểm tra nguồn và lưu kết quả duyệt…", text_color=self.colors["muted"])
        # Destroyed Tk/CTkImage cycles must be collected on the UI thread,
        # before the validator's allocations can trigger a background collect.
        gc.collect()

        def worker():
            try:
                self.results.put((save_review(self.app.store, project, assignments, identifier, decision, revision,
                                              attributes=attributes), None))
            except Exception as exc:
                self.results.put((None, str(exc)))
        try:
            Thread(target=worker, daemon=True).start()
        except Exception as exc:
            self.results.put((None, str(exc)))
        self.after(80, self.finish_save)

    def finish_save(self):
        try:
            result, error = self.results.get_nowait()
        except Empty:
            self.after(80, self.finish_save)
            return
        self.busy = self.app.supplement_review_running = False
        self.grab_release()
        if error:
            self.feedback.configure(text=f"Chưa lưu: {error}", text_color=self.colors["warn"])
            self.update_controls()
            return
        selected_id = self.selected["id"]
        self.data, self.revision = result
        self.rows = self.data["images"]
        self.selected = None
        self.apply_filters()
        row = next((r for r in self.filtered if r["id"] == selected_id), None)
        if row:
            self.page = self.filtered.index(row) // self.PAGE_SIZE
            self.render_list()
            self.show_row(row)
        self.banner.configure(text=f"{len(self.rows)} ảnh bổ trợ · {sum(r.get('enabled') is True for r in self.rows)} đang bật train"
                              "  •  Không dùng cho VAL / TEST; không thêm ảnh gốc.")
        self.feedback.configure(text="Đã lưu kết quả duyệt.", text_color=self.colors["good"])
        self.app._refresh_project_statistics()

"""Sidecar adapter for the SAME labeling widgets used by captured images.

Supplement records never enter project.images. Only this adapter writes their
labels, through the revision-checked sidecar API.
"""
from copy import deepcopy
import gc
from pathlib import Path
from queue import Queue, Empty
from threading import Thread
from tkinter import messagebox

from . import image_filters
from .hydro_labels import display_values, enforce_presence
from .models import ImageRecord
from .supplement_review import load_review, preview_path, save_review
from .training_supplements import review_attributes
from .ui_components import IMAGE_REVIEW_STATUS_STYLE

STATUSES = ["Tất cả", "Chưa gán nhãn", "Bản nháp", "Đã duyệt", "Từ chối"]


class SupplementReviewView:
    def __init__(self, app, colors):
        self.app, self.colors = app, colors
        self.project = self.data = self.revision = self.selected = None
        self.rows, self.filtered, self.page_rows = [], [], []
        self.page = 0
        self.busy = self.active = self.rendering = self.preview_ok = False
        self.results = Queue()
        self.capture_view = None
        self.filter_selection = ("Tất cả", image_filters.ALL, image_filters.ANY)

    @property
    def preview(self):
        return self.app.canvas

    @property
    def form(self):
        return {k: (w, self.app.attribute_display_to_value[k]) for k, w in self.app.attribute_widgets.items()}

    def set_project(self, project):
        if self.project is project:
            return
        self.project = project
        self.data = self.revision = self.selected = None
        self.rows, self.filtered, self.page_rows = [], [], []
        self.page = 0
        self.filter_selection = ("Tất cả", image_filters.ALL, image_filters.ANY)

    def filter_widgets(self):
        return self.app.image_filter, self.app.label_filter_field, self.app.label_filter_value

    def set_filters(self, selection):
        for widget, value in zip(self.filter_widgets(), selection):
            widget.set(value)
        self.app._refresh_label_filters()

    def activate(self):
        self.set_project(self.app.project)
        if not self.active:
            self.capture_view = (tuple(w.get() for w in self.filter_widgets()), self.app.image_page)
        self.active = True
        self.app.image_filter.configure(values=[*STATUSES, "Đã lưu trữ"])
        self.set_filters(self.filter_selection)
        self.preview.read_only = True
        self.preview.set_mode("select")
        self.app.sam_click_request_version += 1
        self.reload()
        self.preview.focus_set()

    def deactivate(self, *, render=True):
        if not self.active:
            return
        self.filter_selection = tuple(w.get() for w in self.filter_widgets())
        self.active = False
        self.preview.read_only = False
        self.app.image_filter.configure(values=STATUSES)
        for widget in self.app.attribute_widgets.values():
            widget.configure(state="normal")
        if self.capture_view:
            selection, self.app.image_page = self.capture_view
            self.set_filters(selection)
        if render:
            self.app._refresh_image_list()
            if self.app.current_index >= 0:
                self.app._load_current_image()
            else:
                self.app._clear_current_image()

    def values(self):
        return {k: v for k, (w, choices) in self.form.items() if (v := choices.get(w.get(), w.get())) != ""}

    def allow_leave(self):
        if self.busy:
            return False
        if not self.active or not self.selected:
            return True
        if (self.values() != review_attributes(self.project, self.selected)
                or self.app.other_abnormal_var.get() != self.selected.get("otherAbnormal", "")):
            if not messagebox.askyesno("Nhãn chưa lưu", "Bỏ thay đổi chưa lưu để chuyển ảnh hoặc tải lại?", parent=self.app):
                return False
            self.sync_details()
        return True

    def reload(self):
        if not self.allow_leave():
            return
        selected_id = self.selected.get("id") if self.selected else None
        try:
            self.data, self.revision = load_review(self.app.store, self.project)
            self.rows = self.data["images"] if self.data else []
            self.selected = None
            self.refresh_list()
            self.show_row(next((r for r in self.filtered if r["id"] == selected_id), self.filtered[0] if self.filtered else None))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.rows, self.filtered = [], []
            self.data = self.revision = None
            self.render_list()
            self.show_row(None)
            self.app._set_status(f"Chưa đọc được ảnh bổ trợ: {exc}", self.colors["warn"])

    def record_for(self, row):
        values = review_attributes(self.project, row)
        if not isinstance(values, dict):
            raise ValueError("Thuộc tính ảnh bổ trợ không hợp lệ; cần kiểm tra manifest.")
        status = row.get("reviewStatus", "draft")
        if row.get("archived"):
            status = "rejected"
        elif status != "rejected" and (status != "reviewed" or not row.get("enabled")):
            status = "draft" if values else "unlabeled"
        return ImageRecord(id=row["id"], file_name=Path(row.get("file", "")).name,
                           width=0, height=0, attributes=values, review_status=status, asset_role="slot")

    def refresh_list(self):
        self.app._refresh_label_filters()
        archived = self.app.image_filter.get() == "Đã lưu trữ"
        self.filtered = [r for r in self.rows if bool(r.get("archived")) == archived
                         and self.app._image_matches_filters(self.record_for(r))]
        self.render_list()

    def apply_filters(self, _value=None):
        if not self.allow_leave():
            self.set_filters(self.filter_selection)
            return
        self.filter_selection = tuple(w.get() for w in self.filter_widgets())
        self.page = 0
        self.refresh_list()
        self.show_row(self.filtered[0] if self.filtered else None)

    def render_list(self):
        size = self.app.image_page_size
        pages = max(1, (len(self.filtered) + size - 1) // size)
        self.page = min(max(0, self.page), pages - 1)
        self.page_rows = self.filtered[self.page * size:(self.page + 1) * size]
        items = []
        for row in self.page_rows:
            try:
                path = preview_path(self.app.store, self.project, row)
            except (OSError, ValueError):
                path = Path("__missing_supplement_preview__")
            record = self.record_for(row)
            items.append({"key": f"supplement:{row['id']}", "name": record.file_name, "path": path,
                          "status": record.review_status, "count": len(record.attributes),
                          "delete_tooltip": "Lưu trữ ảnh bổ trợ; giữ ảnh, nhãn và lịch sử."})
        self.app.image_list.set_items(items)
        start = self.page * size
        shown = f"{start + 1}–{start + len(items)}" if items else "0"
        self.app.image_page_label.configure(text=f"{shown}/{len(self.filtered)} · trang {self.page + 1}/{pages}")
        self.app._set_button_enabled(self.app.image_page_previous_button, not self.busy and self.page > 0)
        self.app._set_button_enabled(self.app.image_page_next_button, not self.busy and self.page + 1 < pages)

    def change_page(self, delta):
        if self.allow_leave():
            self.page += delta
            self.render_list()
            self.show_row(self.page_rows[0] if self.page_rows else None)

    def select_index(self, index):
        if 0 <= index < len(self.page_rows):
            self.select(self.page_rows[index])

    def select(self, row):
        if self.allow_leave():
            self.show_row(row)
        elif self.selected in self.page_rows:
            self.app.image_list.select(self.page_rows.index(self.selected))

    def navigate(self, delta):
        if self.filtered and self.allow_leave():
            current = self.filtered.index(self.selected) if self.selected in self.filtered else (-1 if delta > 0 else 0)
            self.show_row(self.filtered[(current + delta) % len(self.filtered)])

    def show_row(self, row):
        self.selected, self.preview_ok, self.rendering = row, False, True
        try:
            self.preview.clear_image()
            self.app.selected_annotation_id = None
            if row:
                path = preview_path(self.app.store, self.project, row)
                self.preview.load(self.project, self.record_for(row), str(path))
                self.preview_ok = True
                self.app.current_image_label.configure(text=f"Bổ trợ · {self.rows.index(row) + 1}/{len(self.rows)}"
                    f" · {path.name} · {self.preview.image.width}×{self.preview.image.height} · Chỉ TRAIN")
                if row in self.filtered:
                    self.page = self.filtered.index(row) // self.app.image_page_size
                    self.render_list()
                    self.app.image_list.select(self.page_rows.index(row), focus=True)
            else:
                self.app.current_image_label.configure(text="Không có ảnh bổ trợ trong bộ lọc này")
        except (OSError, ValueError) as exc:
            self.app.current_image_label.configure(text=f"Không mở được ảnh bổ trợ: {exc}")
        finally:
            self.rendering = False
        self.sync_details()

    def sync_details(self):
        if not self.active or self.rendering:
            return
        values = review_attributes(self.project, self.selected) if self.selected else {}
        for key, widget in self.app.attribute_widgets.items():
            value = values.get(key, "")
            widget.set(display_values(self.project, key).get(value, value) if value else "— Chưa gán —")
        self.app.other_abnormal_var.set(self.selected.get("otherAbnormal", "") if self.selected else "")
        self.update_controls()

    def attribute_changed(self, key, value):
        if self.busy or not self.selected:
            return
        values = self.values()
        if value:
            values[key] = value
        else:
            values.pop(key, None)
        enforce_presence(self.project, values)
        for attr, widget in self.app.attribute_widgets.items():
            raw = values.get(attr, "")
            widget.set(display_values(self.project, attr).get(raw, raw) if raw else "— Chưa gán —")
        self.save("draft", save_draft_labels=True)

    def update_controls(self):
        row = self.selected
        status = self.record_for(row).review_status if row else "unlabeled"
        style = IMAGE_REVIEW_STATUS_STYLE[status]
        self.app.image_status_frame.configure(fg_color=style["background"], border_color=style["border"])
        title = "ĐÃ LƯU TRỮ" if row and row.get("archived") else style["full_label"]
        self.app.image_status_label.configure(text=title if row else "CHƯA CHỌN ẢNH", text_color=style["text"], fg_color=style["background"])
        valid = bool(row) and not self.busy
        for button, enabled in ((self.app.approve_image_button, valid and self.preview_ok),
                                (self.app.unapprove_image_button, valid and status == "reviewed"),
                                (self.app.reject_image_button, valid and status != "rejected"),
                                (self.app.restore_image_button, valid and status == "rejected")):
            self.app._set_button_enabled(button, enabled)
        for widget in (*self.filter_widgets(), *self.app.attribute_widgets.values()):
            widget.configure(state="disabled" if self.busy or (widget in self.app.attribute_widgets.values() and not row) else "normal")
        if not self.busy:
            self.app._refresh_label_filters()

    def archive(self, identifier=None):
        row = next((r for r in self.rows if f"supplement:{r['id']}" == identifier), self.selected)
        if row is not None and self.allow_leave() and messagebox.askyesno("Lưu trữ ảnh bổ trợ",
                "Ẩn ảnh khỏi danh sách làm việc và train? Ảnh, nhãn và lịch sử vẫn được giữ.", parent=self.app):
            self.show_row(row)
            self.save("archived")

    def save(self, decision, *, save_draft_labels=False, advance=False):
        if self.busy or not self.selected or self.project is not self.app.project or not self.app._can_change_project():
            return
        project = deepcopy(self.project)
        assignments = self.app.datasets.ensure_split_assignment(project, persist=False)["groups"]
        identifier, revision, attributes = self.selected["id"], self.revision, self.values()
        note = self.app.other_abnormal_var.get()
        self.next_id = identifier
        if advance and self.selected in self.filtered and len(self.filtered) > 1:
            self.next_id = self.filtered[(self.filtered.index(self.selected) + 1) % len(self.filtered)]["id"]
        self.busy = self.app.supplement_review_running = True
        self.update_controls()
        self.app._set_status("Đang lưu nhãn bổ trợ…")
        gc.collect()

        def worker():
            try:
                result = save_review(self.app.store, project, assignments, identifier, decision, revision,
                                     attributes=attributes, save_draft_labels=save_draft_labels, other_abnormal=note)
                self.results.put((result, None))
            except Exception as exc:
                self.results.put((None, str(exc)))
        try:
            Thread(target=worker, daemon=True).start()
        except Exception as exc:
            self.results.put((None, str(exc)))
        self.app.after(80, self.finish_save)

    def finish_save(self):
        try:
            result, error = self.results.get_nowait()
        except Empty:
            self.app.after(80, self.finish_save)
            return
        self.busy = self.app.supplement_review_running = False
        if error:
            self.app._set_status(f"Chưa lưu: {error}", self.colors["warn"])
            self.update_controls()
            return
        self.data, self.revision = result
        self.rows = self.data["images"]
        self.refresh_list()
        self.show_row(next((r for r in self.filtered if r["id"] == self.next_id), self.filtered[0] if self.filtered else None))
        self.app._set_status("Đã lưu nhãn bổ trợ." + ("" if self.selected and self.selected.get("enabled") else " Duyệt ảnh để dùng train."), self.colors["good"])
        self.app._refresh_project_statistics()

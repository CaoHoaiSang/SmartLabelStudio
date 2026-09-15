"""Sidecar adapter for the SAME labeling widgets used by captured images.

Supplement records never enter project.images. Only this adapter writes their
labels, through the revision-checked sidecar API.
"""
from copy import copy, deepcopy
import gc
from pathlib import Path
from queue import Queue, Empty
from threading import Event, Thread
from tkinter import messagebox

from . import image_filters
from .hydro_labels import display_values, enforce_presence
from .models import ImageRecord
from .supplement_review import form_attributes, load_review, preview_path, save_review
from .training_supplements import ReviewPixelCache, review_attributes
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
        self.preview_cache = {}
        self.list_dirty = True
        self.pixel_cache = ReviewPixelCache()
        self.warm_stop = Event()
        self.warm_started = False

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
        self.preview_cache.clear()
        self.warm_stop.set()
        self.warm_stop = Event()
        self.warm_started = False
        self.pixel_cache = ReviewPixelCache()
        self.list_dirty = True

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
        self.app.label_reload_button.pack(padx=10, pady=(0, 8))
        self.app.image_filter.configure(values=[*STATUSES, "Đã lưu trữ"])
        self.set_filters(self.filter_selection)
        self.preview.read_only = True
        self.preview.set_mode("select")
        self.app.sam_click_request_version += 1
        # The caller already checked the previous source. Widgets still contain
        # capture labels here, so comparing them to the last supplement is wrong.
        self.reload(check_unsaved=False)
        self.warm_review_pixels()
        self.preview.focus_set()

    def warm_review_pixels(self):
        if self.warm_started or not self.project:
            return
        self.warm_started = True
        paths = [self.app.store.image_path(self.project, r) for r in self.project.images]
        cache, stop = self.pixel_cache, self.warm_stop
        # Background work captures paths/cache only, never Tk widgets or live labels.
        gc.collect()
        def worker():
            for path in paths:
                if stop.is_set():
                    return
                try:
                    cache.fingerprint(path)
                except (OSError, ValueError):
                    pass  # Approval will report invalid/missing files; warmup never approves.
        try:
            Thread(target=worker, daemon=True).start()
        except RuntimeError:
            self.warm_started = False  # Optional preparation; approval can compute without it.

    def deactivate(self, *, render=True):
        if not self.active:
            return
        self.filter_selection = tuple(w.get() for w in self.filter_widgets())
        self.active = False
        self.app.label_reload_button.pack_forget()
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
        if (self.values() != form_attributes(self.project, self.selected)
                or self.app.other_abnormal_var.get() != self.selected.get("otherAbnormal", "")):
            if not messagebox.askyesno("Nhãn chưa lưu", "Bỏ thay đổi chưa lưu để chuyển ảnh hoặc tải lại?", parent=self.app):
                return False
            self.sync_details()
        return True

    def reload(self, *, check_unsaved=True):
        if check_unsaved and not self.allow_leave():
            return
        selected_id = self.selected.get("id") if self.selected else None
        try:
            data, revision = load_review(self.app.store, self.project)
            if check_unsaved or revision != self.revision:
                self.preview_cache.clear()
            self.data, self.revision = data, revision
            self.rows = self.data["images"] if self.data else []
            self.selected = None
            self.refresh_list(render=False)
            self.show_row(next((r for r in self.filtered if r["id"] == selected_id), self.filtered[0] if self.filtered else None))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.rows, self.filtered = [], []
            self.data = self.revision = None
            self.render_list()
            self.show_row(None)
            self.app._set_status(f"Chưa đọc được ảnh bổ trợ: {exc}", self.colors["warn"])

    def record_for(self, row):
        values = form_attributes(self.project, row)
        if not isinstance(values, dict):
            raise ValueError("Thuộc tính ảnh bổ trợ không hợp lệ; cần kiểm tra manifest.")
        status = row.get("reviewStatus", "draft")
        if row.get("archived"):
            status = "rejected"
        elif status != "rejected" and (status != "reviewed" or not row.get("enabled")
                                      or values != review_attributes(self.project, row)):
            status = "draft" if values else "unlabeled"
        return ImageRecord(id=row["id"], file_name=Path(row.get("file", "")).name,
                           width=0, height=0, attributes=values, review_status=status, asset_role="slot")

    def refresh_list(self, *, render=True):
        self.app._refresh_label_filters()
        archived = self.app.image_filter.get() == "Đã lưu trữ"
        self.filtered = [r for r in self.rows if bool(r.get("archived")) == archived
                         and self.app._image_matches_filters(self.record_for(r))]
        self.list_dirty = True
        if render:
            self.render_list()

    def apply_filters(self, _value=None):
        if not self.allow_leave():
            self.set_filters(self.filter_selection)
            return
        self.filter_selection = tuple(w.get() for w in self.filter_widgets())
        self.page = 0
        self.refresh_list(render=False)
        self.show_row(self.filtered[0] if self.filtered else None)

    def render_list(self):
        size = self.app.image_page_size
        pages = max(1, (len(self.filtered) + size - 1) // size)
        self.page = min(max(0, self.page), pages - 1)
        self.page_rows = self.filtered[self.page * size:(self.page + 1) * size]
        items = []
        for row in self.page_rows:
            try:
                path = preview_path(self.app.store, self.project, row, cache=self.preview_cache)
            except (OSError, ValueError):
                path = Path("__missing_supplement_preview__")
            record = self.record_for(row)
            items.append({"key": f"supplement:{row['id']}", "name": record.file_name, "path": path,
                          "status": record.review_status, "count": len(record.attributes),
                          "delete_tooltip": "Lưu trữ ảnh bổ trợ; giữ ảnh, nhãn và lịch sử."})
        self.app.image_list.set_items(items)
        self.list_dirty = False
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
        if not self.allow_leave():
            return
        if self.filtered:
            if self.selected in self.filtered:
                row = self.filtered[(self.filtered.index(self.selected) + delta) % len(self.filtered)]
            else:
                positions = {r['id']: i for i, r in enumerate(self.rows)}
                index = positions.get(self.selected['id'], -1) if self.selected else -1
                following = [r for r in self.filtered if positions[r['id']] > index]
                preceding = [r for r in self.filtered if positions[r['id']] < index]
                row = (following[0] if following else self.filtered[0]) if delta > 0 else (preceding[-1] if preceding else self.filtered[-1])
            self.show_row(row)
        else:
            self.show_row(None)

    def show_row(self, row):
        previous = self.selected
        self.selected, self.preview_ok, self.rendering = row, False, True
        self.app._label_feedback()
        try:
            self.app.selected_annotation_id = None
            if row in self.filtered:
                page = self.filtered.index(row) // self.app.image_page_size
                self.list_dirty = self.list_dirty or page != self.page
                self.page = page
            if self.list_dirty:
                self.render_list()
            if row:
                path = preview_path(self.app.store, self.project, row, cache=self.preview_cache)
                signature = (path, path.stat().st_mtime_ns, path.stat().st_size, row.get("sha256"))
                same_image = (previous and previous['id'] == row['id'] and self.preview.image is not None
                              and self.preview.record and self.preview.record.id == row['id']
                              and getattr(self, 'loaded_preview_signature', None) == signature)
                if not same_image:
                    self.preview.load(self.project, self.record_for(row), str(path))
                else:
                    self.preview.record = self.record_for(row)
                self.loaded_preview_signature = signature
                self.preview_ok = True
                source = [r for r in self.rows if bool(r.get('archived')) == bool(row.get('archived'))]
                self.app.image_position_label.configure(text=f"{source.index(row) + 1} / {len(source)}")
                self.app.current_image_label.configure(text=f"Bổ trợ · {path.name}"
                    f" · {self.preview.image.width}×{self.preview.image.height} · Chỉ TRAIN")
                if row in self.filtered:
                    self.app.image_list.select(self.page_rows.index(row), focus=True)
                else:
                    self.app.image_list.clear_selection()
            else:
                self.preview.clear_image()
                self.app.image_position_label.configure(text="0 / 0")
                self.app.current_image_label.configure(text="Không có ảnh bổ trợ trong bộ lọc này")
        except (OSError, ValueError) as exc:
            self.preview.clear_image()
            self.app.image_position_label.configure(text="0 / 0")
            self.app.current_image_label.configure(text=f"Không mở được ảnh bổ trợ: {exc}")
        finally:
            self.rendering = False
        self.sync_details()

    def sync_details(self):
        if not self.active or self.rendering:
            return
        values = form_attributes(self.project, self.selected) if self.selected else {}
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
        if values.get(key, "") != value:
            self.app._label_feedback("Cần chọn Có cây trước khi gán tình trạng lá. Khi chưa xác nhận có cây, tình trạng là Không áp dụng.", warning=True)

    def update_controls(self):
        row = self.selected
        status = self.record_for(row).review_status if row else "unlabeled"
        style = IMAGE_REVIEW_STATUS_STYLE[status]
        self.app.image_status_frame.configure(fg_color=style["background"], border_color=style["border"])
        title = "ĐÃ LƯU TRỮ" if row and row.get("archived") else style["full_label"]
        self.app.image_status_label.configure(text=title if row else "CHƯA CHỌN ẢNH", text_color=style["text"], fg_color=style["background"])
        valid = bool(row) and not self.busy
        for button, enabled in ((self.app.approve_image_button, valid and self.preview_ok and status != "reviewed"),
                                (self.app.unapprove_image_button, valid and status == "reviewed"),
                                (self.app.reject_image_button, valid and status != "rejected"),
                                (self.app.restore_image_button, valid and status == "rejected")):
            self.app._set_button_enabled(button, enabled)
        for widget in (*self.filter_widgets(), *self.app.attribute_widgets.values()):
            widget.configure(state="disabled" if self.busy or (widget in self.app.attribute_widgets.values() and not row) else "normal")
        self.app._set_button_enabled(self.app.label_reload_button, not self.busy)
        self.app.approve_image_button.configure(text="Đang kiểm tra…" if self.busy and getattr(self, 'saving_decision', '') == 'reviewed'
                                                else "Duyệt & tiếp")

    def archive(self, identifier=None):
        row = next((r for r in self.rows if f"supplement:{r['id']}" == identifier), self.selected)
        if row is not None and self.allow_leave() and messagebox.askyesno("Lưu trữ ảnh bổ trợ",
                "Ẩn ảnh khỏi danh sách làm việc và train? Ảnh, nhãn và lịch sử vẫn được giữ.", parent=self.app):
            self.show_row(row)
            self.save("archived")

    def save(self, decision, *, save_draft_labels=False, advance=False):
        if self.busy or not self.selected or self.project is not self.app.project or not self.app._can_change_project():
            return
        if (decision == "reviewed" and self.record_for(self.selected).review_status == "reviewed"
                and self.values() == form_attributes(self.project, self.selected)
                and self.app.other_abnormal_var.get() == self.selected.get("otherAbnormal", "")):
            return
        # Draft writes need schema/settings only. Full evidence belongs to approval.
        project = copy(self.project)
        if decision != "reviewed":
            project.images = []
        project = deepcopy(project)
        assignments = self.app.datasets.ensure_split_assignment(project, persist=False)["groups"] if decision == "reviewed" else {}
        identifier, revision, attributes = self.selected["id"], self.revision, self.values()
        note = self.app.other_abnormal_var.get()
        self.next_id = identifier
        if advance and self.filtered:
            if self.selected in self.filtered:
                self.next_id = self.filtered[(self.filtered.index(self.selected) + 1) % len(self.filtered)]["id"]
            else:
                positions = {r['id']: i for i, r in enumerate(self.rows)}
                index = positions.get(identifier, -1)
                self.next_id = next((r['id'] for r in self.filtered if positions[r['id']] > index), self.filtered[0]['id'])
        self.busy = self.app.supplement_review_running = True
        self.saving_decision = decision
        self.keep_edited_row = decision == "draft" and save_draft_labels and not advance
        self.update_controls()
        self.app._set_status("Đang kiểm tra ảnh và nguồn trước khi duyệt…" if decision == "reviewed" else "Đang lưu nhãn bổ trợ…")
        self.app._label_feedback("Đang kiểm tra ảnh và nguồn trước khi duyệt…" if decision == "reviewed" else "Đang lưu nhãn…")
        gc.collect()

        def worker():
            try:
                result = save_review(self.app.store, project, assignments, identifier, decision, revision,
                                     attributes=attributes, save_draft_labels=save_draft_labels, other_abnormal=note,
                                     pixel_cache=self.pixel_cache)
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
            self.app._label_feedback(f"Chưa lưu: {error}", warning=True)
            self.update_controls()
            return
        self.data, self.revision = result
        self.rows = self.data["images"]
        self.refresh_list(render=False)
        candidates = self.rows if self.keep_edited_row else self.filtered
        self.show_row(next((r for r in candidates if r["id"] == self.next_id), self.filtered[0] if self.filtered else None))
        if self.keep_edited_row:
            self.app._label_feedback("Đã lưu nhãn. Duyệt lại ảnh sau khi sửa." if self.selected in self.filtered else
                "Đã lưu. Ảnh này không còn thuộc bộ lọc; bạn có thể sửa tiếp hoặc chọn Ảnh sau.")
        self.app._set_status("Đã lưu nhãn bổ trợ." + ("" if self.selected and self.selected.get("enabled") else " Duyệt ảnh để dùng train."), self.colors["good"])
        self.app._request_project_statistics()

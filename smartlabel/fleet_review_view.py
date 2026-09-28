"""Fleet adapter for the existing canvas, attribute fields, filters and review buttons."""
from queue import Queue, Empty
from threading import Thread
import time

from .models import ImageRecord
from .fleet_review import FleetReviewBusy
from .fleet_source import qualification, source_caption
from .supplement_review_view import SupplementReviewView


class FleetReviewView(SupplementReviewView):
    saved_caption = "Đã lưu nhãn khách đóng góp; chưa đưa vào dataset/train."
    def __init__(self, app, colors, session):
        super().__init__(app, colors)
        self.session = session
        self.loaded = Queue()
        self.timer = None
        self.expired_pixels = False
        self.retry_at = 0

    @staticmethod
    def _form_attributes(project, row):
        return dict(row.get("attributes", {}))  # No inferred AI labels or configured defaults.

    def warm_review_pixels(self):
        pass  # This source is not admitted to datasets; no need to scan existing projects.

    def _load_review(self, store, project):
        if project.id != self.session.project_id or not self.session.data:
            raise ValueError("Lấy mã cho đúng project và mở đợt ảnh trên Fleet.")
        return self.session.data, self.session.revision

    def _preview_path(self, store, project, row, **kwargs):
        return self.session.preview_path(row)

    def _save_review(self, store, project, assignments, identifier, decision, revision, **kwargs):
        return self.session.save(project, identifier, decision, revision, **kwargs)

    def record_for(self, row):
        return ImageRecord(id=row["id"], file_name=row["file"], width=row.get("width", 0), height=row.get("height", 0),
                           attributes=self._form_attributes(self.project, row), asset_role="slot",
                           review_status=row["reviewStatus"] if row["attributes"] or row["reviewStatus"] == "rejected" else "unlabeled")

    def activate(self):
        super().activate()
        self._schedule()

    def _schedule(self):
        if self.timer is not None:
            self.app.after_cancel(self.timer)
        self.timer = self.app.after(1000, self._tick)

    def _tick(self):
        self.timer = None
        if not self.active:
            return
        if self.session.deadline <= time.monotonic():
            self.expired_pixels = True
            self.preview.clear_image()
            self.preview_ok = False
            self.app.image_list.set_items([])  # Clear thumbnail pixels too.
            self.update_controls()
        if (not self.busy and self.session.data is not None and self.session.deadline > 0
                and time.monotonic() >= self.retry_at and self.session.deadline - time.monotonic() < 10):
            self.reload(check_unsaved=False, automatic=True)
        self._schedule()

    def reload(self, *, check_unsaved=True, automatic=False):
        if self.busy or (check_unsaved and not self.allow_leave()):
            return
        self.busy = self.app.supplement_review_running = True
        self.automatic_refresh = automatic
        self.update_controls()
        session = self.session
        def worker():
            try:
                session.refresh()
                self.loaded.put(None)
            except FleetReviewBusy as exc:
                self.loaded.put(exc)
            except Exception:
                self.loaded.put("Chưa xác minh được quyền. Nhãn cũ được giữ; thử Tải lại hoặc lấy mã mới từ Fleet.")
        try:
            Thread(target=worker, daemon=True).start()
        except Exception:
            self.loaded.put("Chưa khởi động được kiểm tra quyền; hãy thử lại.")
        self.app.after(50, self._finish_reload)

    def _finish_reload(self):
        try:
            error = self.loaded.get_nowait()
        except Empty:
            self.app.after(50, self._finish_reload)
            return
        self.busy = self.app.supplement_review_running = False
        if not self.active or self.project is not self.app.project:
            return
        if isinstance(error, FleetReviewBusy):
            self.retry_at = time.monotonic() + 5
            self.update_controls()
            return
        if error:
            self.preview.clear_image()
            self.rows, self.filtered = [], []
            self.selected = None
            self.render_list()
            self.show_row(None)
            self.app._set_status(error, self.colors["warn"])
            self.session.close()  # No endless retries after logout/expiry/network failure.
        else:
            if self.automatic_refresh and self.revision == self.session.revision and not self.expired_pixels:
                self.update_controls()  # Do not discard a note the operator is currently typing.
            else:
                super().reload(check_unsaved=False)
                self.expired_pixels = False

    def show_row(self, row):
        super().show_row(row)
        if row and self.preview_ok:
            self.app.current_image_label.configure(text=source_caption(row))
            self.app._set_status("Nhãn Fleet được lưu riêng. Duyệt nhãn chưa đưa ảnh vào dataset hoặc train.")

    def sync_delete_controls(self, *, force=False):
        for item in self.app.image_list.rows:
            if str(item["key"]).startswith("supplement:"):
                self.app._set_button_enabled(item["delete"], False)

    def delete(self, identifier=None):
        self.app._set_status("Dùng Từ chối để loại ảnh. Yêu cầu xóa cả đợt được thực hiện trên Fleet.", self.colors["warn"])

    def update_controls(self):
        super().update_controls()
        # Source QA can change without a label revision (e.g. project crop corrected).
        # Update its caption/guard without discarding an operator's unsaved note.
        current = next((row for row in (self.session.data or {}).get("images", [])
                        if self.selected and row["id"] == self.selected["id"]), {})
        if self.selected and qualification(current)["sourceClass"] == "unqualified":
            self.app._set_button_enabled(self.app.approve_image_button, False)
        if current and self.preview_ok:
            self.app.current_image_label.configure(text=source_caption(current))
        if self.session.deadline <= time.monotonic():
            for button in (self.app.approve_image_button, self.app.unapprove_image_button,
                           self.app.reject_image_button, self.app.restore_image_button):
                self.app._set_button_enabled(button, False)
            for widget in self.app.attribute_widgets.values():
                widget.configure(state="disabled")

    def deactivate(self, *, render=True):
        if self.timer is not None:
            self.app.after_cancel(self.timer)
            self.timer = None
        super().deactivate(render=render)

"""Use the existing SmartLabel canvas/forms/navigation for TEST-only sidecars."""
from . import heldout_collection as storage
from .models import ImageRecord
from .supplement_review_view import SupplementReviewView


class HeldoutReviewView(SupplementReviewView):
    saved_caption = "Đã lưu nhãn TEST · dữ liệu vẫn cách ly khỏi TRAIN/VAL."
    _load_review = staticmethod(storage.load_collection)
    _preview_path = staticmethod(storage.preview_path)
    _save_review = staticmethod(storage.save_review)

    @staticmethod
    def _form_attributes(project, row):
        return dict(row.get("attributes", {}))

    def warm_review_pixels(self):
        pass

    def record_for(self, row):
        return ImageRecord(id=row["id"], file_name=f"{row['source']['slotId']} · {row['source']['captureId'][-6:]}",
            width=row["width"], height=row["height"], attributes=dict(row.get("attributes", {})),
            review_status=row["reviewStatus"], asset_role="slot")

    def show_row(self, row):
        super().show_row(row)
        if row and self.preview_ok:
            empty = " · Khai báo rọ trống (chưa phải nhãn)" if row.get("declaredEmpty") else ""
            lot = next((v for v in self.data["lots"] if v["lotId"] == row["source"]["lotId"]), {})
            self.app.current_image_label.configure(text=f"TEST · {lot.get('name', '')} · {row['source']['slotId']} · {row['capturedAt']}{empty}")
            self.app._set_status("Gán nhãn từ ảnh thực tế. Không có cây → dấu hiệu Không áp dụng. Không dùng dữ liệu này để train.")
        elif not row:
            self.app.current_image_label.configure(text="Chưa có ảnh TEST trong bộ lọc · mở DATASET → Thu thập TEST")

    def sync_delete_controls(self, *, force=False):
        for item in self.app.image_list.rows:
            item["delete"].pack_forget()

    def delete(self, identifier=None):
        self.app._label_feedback("Dùng Từ chối để loại ảnh khỏi bộ kiểm định; giữ nguồn và lịch sử duyệt.", warning=True)

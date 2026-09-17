"""Shared project/dataset presentation; statistics follow each task's label scope."""
from collections import Counter
import customtkinter as ctk

from .hydro_labels import model_attributes
from .label_schema import meaning_for
from .supplement_review import load_review
from .training_supplements import review_attributes


def summarize_supplement_rows(project, rows):
    """Return operator-facing counts without changing supplement eligibility."""
    rows = list(rows or [])
    excluded = [row for row in rows if row.get("archived") is True or row.get("reviewStatus") == "rejected"]
    working = [row for row in rows if row not in excluded]
    reviewed = [row for row in working if row.get("reviewStatus") == "reviewed"]
    active = [row for row in reviewed if row.get("enabled") is True]
    pending = len(working) - len(reviewed)
    attributes = []
    for attribute in model_attributes(project):
        counts = Counter(
            meaning_for(attribute, review_attributes(project, row).get(attribute["id"]))
            for row in active
        )
        attributes.append({
            "id": attribute["id"],
            "title": attribute["displayName"],
            "positive": counts.get("positive", 0),
            "negative": counts.get("negative", 0),
        })
    return {
        "total": len(rows),
        "working": len(working),
        "reviewed": len(reviewed),
        "active": len(active),
        "paused": len(reviewed) - len(active),
        "pending": max(0, pending),
        "rejected": len(excluded),
        "legacy_archived": sum(row.get("archived") is True for row in rows),
        "attributes": attributes,
    }


class ProjectOverview(ctk.CTkScrollableFrame):
    def __init__(self, master, colors, *, expanded=False):
        super().__init__(master, fg_color="#0a131c", corner_radius=10)
        self.colors = colors
        self.details_visible = expanded
        self.split_frames = []
        self.wrapped_labels = []
        self.last_width = 0
        # Keep CTkScrollableFrame's scrollregion update when content expands.
        self.bind("<Configure>", self.resize_labels, add="+")

    def label(self, parent, text, *, color=None, size=12, bold=False):
        label = ctk.CTkLabel(parent, text=text, anchor="w", justify="left",
            wraplength=max(180, self.last_width - 64),
            text_color=color or self.colors["text"], font=("Segoe UI Semibold" if bold else "Segoe UI", size))
        label.pack(fill="x", padx=12, pady=3)
        self.wrapped_labels.append(label)
        return label

    def resize_labels(self, event):
        if event.width == self.last_width:
            return
        self.last_width = event.width
        for label in self.wrapped_labels:
            label.configure(wraplength=max(180, event.width - 64))

    def render(self, store, project, summary):
        for widget in self.winfo_children():
            widget.destroy()
        self.split_frames = []
        self.wrapped_labels = []
        muted = self.colors["muted"]
        hydro = "image_attributes" in summary
        self.label(self, project.name, size=20, bold=True)
        self.label(self, "Phân loại từng rọ · Nhãn trực tiếp trên ảnh" if hydro
                   else "Nhãn vật thể · RECT / SEG / OBB / ORI", color=muted)
        if hydro:
            self.label(self, "ẢNH TỪ GIÀN", size=13, color=self.colors["accent"], bold=True)
        totals = ctk.CTkFrame(self, fg_color="transparent")
        totals.pack(fill="x", padx=6, pady=(8, 12))
        totals.grid_columnconfigure((0, 1, 2), weight=1, uniform="counts")
        statuses = summary["statuses"]
        for i, (count, title, color) in enumerate((
                (summary["images"], "Ảnh giàn" if hydro else "Ảnh", self.colors["accent"]),
                (statuses.get("reviewed", 0), "Đã duyệt", self.colors["good"]),
                (summary["images"] - statuses.get("reviewed", 0) - statuses.get("rejected", 0), "Chưa duyệt", self.colors["warn"]))):
            card = ctk.CTkFrame(totals, fg_color=self.colors["panel2"], corner_radius=10)
            card.grid(row=0, column=i, sticky="ew", padx=4)
            self.label(card, f"{count:,}", size=23, color=color, bold=True)
            self.label(card, title, color=muted)
        if statuses.get("rejected"):
            self.label(self, f"Ảnh bị từ chối: {statuses['rejected']}", color=muted)
        if not hydro:
            self.render_geometry(project, summary)
            return
        self.label(self, "THUỘC TÍNH TRÊN ẢNH RỌ", size=13, color=self.colors["accent"], bold=True)
        self.label(self, "Có / Không: số ảnh rọ đã duyệt theo từng thuộc tính.", color=muted)
        rows = summary["image_attributes"]
        for row in rows:
            card = ctk.CTkFrame(self, fg_color=self.colors["panel2"], corner_radius=10)
            card.pack(fill="x", padx=6, pady=5)
            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=12, pady=(8, 4))
            header.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(header, text=row["title"], anchor="w", justify="left", width=1, wraplength=170,
                         font=("Segoe UI Semibold", 14)).grid(row=0, column=0, sticky="ew", padx=(0, 8))
            counts = row["reviewed"]
            for col, (key, caption, color) in enumerate((("positive", "Có", "#69d7bd"), ("negative", "Không", "#9bc7dd")), 1):
                ctk.CTkLabel(header, text=f"{caption}  {counts.get(key, 0):,}", fg_color="#1b3546",
                    corner_radius=6, font=("Segoe UI Semibold", 13), text_color=color).grid(row=0, column=col, padx=(6, 0), ipadx=8, ipady=2)
            details = [f"{caption} {counts[key]}" for key, caption in
                       (("uncertain", "Chưa chắc"), ("not_applicable", "Không áp dụng"), ("missing", "Thiếu nhãn")) if counts.get(key)]
            pending = sum(row["pending"].values())
            if pending:
                details.append(f"Chưa duyệt / bị loại {pending}")
            self.label(card, "   ·   ".join(details) if details else "Các ảnh đã duyệt đều có nhãn Có / Không.", color=muted, size=11)
            splits = ctk.CTkFrame(card, fg_color="#10202d", corner_radius=8)
            splits.grid_columnconfigure((0, 1, 2, 3), weight=1)
            for i, caption in enumerate(("Ảnh đủ điều kiện", "TRAIN", "VAL", "TEST")):
                ctk.CTkLabel(splits, text=caption, font=("Segoe UI", 10), text_color=muted).grid(row=0, column=i, padx=5, pady=(6, 2))
            for line, (meaning, caption) in enumerate((("positive", "Có"), ("negative", "Không")), 1):
                for col, value in enumerate((caption, *(row["splits"][s].get(meaning, 0) for s in ("train", "val", "test")))):
                    ctk.CTkLabel(splits, text=str(value), font=("Segoe UI", 12)).grid(row=line, column=col, padx=5, pady=2)
            self.split_frames.append(splits)
            if self.details_visible:
                splits.pack(fill="x", padx=10, pady=(4, 10))
        self.toggle = ctk.CTkButton(self, text="", command=self.toggle_details, fg_color="#243d51", hover_color="#31526c")
        self.toggle.pack(anchor="w", padx=8, pady=8)
        self.update_toggle()
        self.label(self, "Train / Val / Test chỉ tính ảnh đã duyệt, nhãn Có hoặc Không hợp lệ; tình trạng lá cần xác nhận có cây.", color=muted, size=11)
        missing = [r["title"] for r in rows if any(r["splits"]["test"].get(k, 0) == 0 for k in ("positive", "negative"))]
        if missing:
            self.label(self, "TEST còn thiếu một trong hai nhóm Có / Không: " + ", ".join(missing)
                       + ". Chưa đủ dữ liệu để đánh giá hai nhóm.", color=self.colors["warn"], size=11)
        self.render_supplements(store, project, muted)

    def render_supplements(self, store, project, muted):
        """Render the separate TRAIN-only source after all captured-image facts."""
        supplement = ctk.CTkFrame(self, fg_color="#132b31", corner_radius=10)
        supplement.pack(fill="x", padx=6, pady=(14, 12))
        self.label(supplement, "ẢNH BỔ TRỢ · CHỈ TRAIN", size=13, color="#69d7bd", bold=True)
        try:
            data, _ = load_review(store, project)
            supplement_summary = summarize_supplement_rows(project, data["images"] if data else [])
            supplement_totals = ctk.CTkFrame(supplement, fg_color="transparent")
            supplement_totals.pack(fill="x", padx=6, pady=(4, 6))
            supplement_totals.grid_columnconfigure((0, 1, 2), weight=1, uniform="supplement_counts")
            for column, (count, title, color) in enumerate((
                    (supplement_summary["total"], "Ảnh bổ trợ", self.colors["accent"]),
                    (supplement_summary["reviewed"], "Đã duyệt", self.colors["good"]),
                    (supplement_summary["pending"], "Chưa duyệt", self.colors["warn"]))):
                card = ctk.CTkFrame(supplement_totals, fg_color=self.colors["panel2"], corner_radius=10)
                card.grid(row=0, column=column, sticky="ew", padx=4)
                self.label(card, f"{count:,}", size=22, color=color, bold=True)
                self.label(card, title, color=muted)
            details = [f"Đang dùng train {supplement_summary['active']}"]
            if supplement_summary["paused"]:
                details.append(f"Tạm tắt {supplement_summary['paused']}")
            if supplement_summary["rejected"]:
                details.append(f"Từ chối {supplement_summary['rejected']}")
            self.label(supplement, "   ·   ".join(details), color=muted, size=11)
            for attribute in supplement_summary["attributes"]:
                self.label(
                    supplement,
                    f"{attribute['title']}:  Có {attribute['positive']:,}   ·   Không {attribute['negative']:,}",
                    color="#b9d7e8",
                    size=11,
                )
            self.label(
                supplement,
                "Ảnh bổ trợ đã duyệt chỉ bổ sung TRAIN; không thay ảnh giàn trong VAL / TEST.",
                color=muted,
                size=11,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.label(supplement, f"Cần kiểm tra danh sách bổ trợ: {exc}", color=self.colors["warn"], size=11)

    def render_geometry(self, project, summary):
        self.label(self, f"{summary['annotations']:,} nhãn vật thể", size=18, bold=True)
        self.label(self, "Thống kê nhãn hiện có, gồm cả bản nháp. Trạng thái duyệt ảnh được hiển thị ở trên.", color=self.colors["muted"])
        sections = [("THEO CLASS", summary["classes"]), ("NGUỒN NHÃN", summary["sources"])]
        for key in project.attribute_schema:
            settings = project.attribute_settings.get(key, {})
            scope = settings.get("scope", "annotation_crop")
            records = project.images if scope == "image" else [ann for record in project.images for ann in record.annotations]
            counts = Counter(record.attributes.get(key) or "Chưa gán" for record in records)
            title = settings.get("title") or key
            sections.append((f"{title} · {'trên ảnh' if scope == 'image' else 'trên vật thể'}", counts))
        for title, counts in sections:
            card = ctk.CTkFrame(self, fg_color=self.colors["panel2"], corner_radius=10)
            card.pack(fill="x", padx=6, pady=6)
            self.label(card, title, color=self.colors["accent"], size=13, bold=True)
            if not counts:
                self.label(card, "Chưa có dữ liệu", color=self.colors["muted"])
            for name, count in counts.items():
                self.label(card, f"{name}   ·   {count:,}")

    def update_toggle(self):
        self.toggle.configure(text=("Ẩn" if self.details_visible else "Xem") + " chi tiết Train / Val / Test")

    def toggle_details(self):
        self.details_visible = not self.details_visible
        for frame in self.split_frames:
            if self.details_visible:
                frame.pack(fill="x", padx=10, pady=(4, 10))
            else:
                frame.pack_forget()
        self.update_toggle()

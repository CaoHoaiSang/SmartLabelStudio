"""Readable overview of real slot labels, with supplements shown separately."""
import customtkinter as ctk

from .supplement_review import load_review


class HydroOverview(ctk.CTkScrollableFrame):
    def __init__(self, master, colors, open_supplements):
        super().__init__(master, fg_color="#0a131c", corner_radius=10)
        self.colors, self.open_supplements = colors, open_supplements
        self.details_visible = False
        self.split_frames = []
        self.wrapped_labels = []
        self.last_width = 0
        self.bind("<Configure>", self.resize_labels)

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
        self.label(self, project.name, size=20, bold=True)
        self.label(self, "Phân loại từng rọ · Nhãn trực tiếp trên ảnh", color=muted)
        totals = ctk.CTkFrame(self, fg_color="transparent")
        totals.pack(fill="x", padx=6, pady=(8, 12))
        totals.grid_columnconfigure((0, 1, 2), weight=1, uniform="counts")
        statuses = summary["statuses"]
        for i, (count, title, color) in enumerate((
                (summary["images"], "Ảnh giàn", self.colors["accent"]),
                (statuses.get("reviewed", 0), "Đã duyệt", self.colors["good"]),
                (summary["images"] - statuses.get("reviewed", 0) - statuses.get("rejected", 0), "Chưa duyệt", self.colors["warn"]))):
            card = ctk.CTkFrame(totals, fg_color=self.colors["panel2"], corner_radius=10)
            card.grid(row=0, column=i, sticky="ew", padx=4)
            self.label(card, f"{count:,}", size=23, color=color, bold=True)
            self.label(card, title, color=muted)
        if statuses.get("rejected"):
            self.label(self, f"Ảnh giàn bị từ chối: {statuses['rejected']}", color=muted)
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
        supplement = ctk.CTkFrame(self, fg_color="#132b31", corner_radius=10)
        supplement.pack(fill="x", padx=6, pady=(12, 8))
        self.label(supplement, "ẢNH BỔ TRỢ · CHỈ TRAIN", size=13, color="#69d7bd", bold=True)
        try:
            data, _ = load_review(store, project)
            images = data["images"] if data else []
            active = sum(r.get("enabled") is True for r in images)
            self.label(supplement, f"{len(images)} ảnh bổ trợ   ·   {active} đang bật train")
            self.label(supplement, "Lưu riêng với ảnh giàn. Không cộng vào thống kê Có / Không và VAL / TEST ở trên.", color=muted, size=11)
        except (OSError, ValueError, TypeError) as exc:
            self.label(supplement, f"Cần kiểm tra danh sách bổ trợ: {exc}", color=self.colors["warn"], size=11)
        ctk.CTkButton(supplement, text="Xem & duyệt ảnh bổ trợ →", command=self.open_supplements,
                      fg_color="#27505a", hover_color="#346974").pack(anchor="w", padx=12, pady=(6, 12))

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

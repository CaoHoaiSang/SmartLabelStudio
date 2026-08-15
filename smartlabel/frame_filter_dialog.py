from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import textwrap
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageOps

from .frame_filter import (
    SOURCE_ALL,
    SOURCE_IMPORTED,
    SOURCE_VIDEO,
    FrameDecision,
    FrameFilterSettings,
    analyze_smart_images,
    image_records_for_filter,
)
from .models import Project
from .project_store import ProjectStore
from .ui_components import ToolTip


PREVIEW_SIZE = (430, 320)
PREVIEW_MARGIN = 12
PREVIEW_BACKGROUND = (7, 16, 25)
KEEP_SELECTION_COLOR = "#25664d"
DELETE_SELECTION_COLOR = "#74353d"
NEUTRAL_SELECTION_COLOR = "#1e607c"


def build_contained_preview(source: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Fit a complete image inside the preview frame without cropping."""

    image = ImageOps.exif_transpose(source).convert("RGB")
    inner_width = PREVIEW_SIZE[0] - PREVIEW_MARGIN * 2
    inner_height = PREVIEW_SIZE[1] - PREVIEW_MARGIN * 2
    fitted = ImageOps.contain(image, (inner_width, inner_height), Image.Resampling.LANCZOS)
    left = (PREVIEW_SIZE[0] - fitted.width) // 2
    top = (PREVIEW_SIZE[1] - fitted.height) // 2
    preview = Image.new("RGB", PREVIEW_SIZE, PREVIEW_BACKGROUND)
    preview.paste(fitted, (left, top))
    return preview, (left, top, fitted.width, fitted.height)


class SmartFrameFilterDialog(ctk.CTkToplevel):
    SOURCE_LABELS = {
        "Tất cả ảnh": SOURCE_ALL,
        "Frame video": SOURCE_VIDEO,
        "Ảnh nhập / thư mục": SOURCE_IMPORTED,
    }
    CATEGORY_LABELS = {
        "positive": "NÊN GIỮ",
        "negative_keep": "GIỮ ẢNH NỀN",
        "duplicate": "GẦN TRÙNG",
        "empty": "ẢNH TRỐNG/CẦN KIỂM TRA",
        "uncertain": "CHƯA CHẮC",
        "quality": "CHẤT LƯỢNG KÉM",
    }

    def __init__(self, parent, project: Project, store: ProjectStore, on_deleted):
        super().__init__(parent)
        self.project = project
        self.store = store
        self.store.ensure_import_batches(self.project)
        self.on_deleted = on_deleted
        self.results: list[FrameDecision] = []
        self.result_by_id: dict[str, FrameDecision] = {}
        self.queue: Queue = Queue()
        self.cancel_event = Event()
        self.preview_photo = None
        self.title("Lọc ảnh thông minh")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = min(1450, max(1120, screen_width - 100))
        window_height = min(860, max(700, screen_height - 140))
        self.geometry(f"{window_width}x{window_height}")
        self.minsize(1120, 700)
        self.transient(parent)
        self.configure(fg_color="#081019")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.after(120, self._poll)

    def _build(self):
        title = ctk.CTkLabel(self, text="LỌC ẢNH THÔNG MINH", font=("Segoe UI Semibold", 20), text_color="#22b9ee")
        title.pack(anchor="w", padx=18, pady=(15, 2))
        ctk.CTkLabel(
            self,
            text="Hỗ trợ frame video và ảnh nhập. AI/OpenCV chỉ đề xuất; ảnh đã có nhãn/đã duyệt được bảo vệ mặc định.",
            text_color="#8298aa",
        ).pack(anchor="w", padx=18, pady=(0, 8))

        settings = ctk.CTkFrame(self, corner_radius=10, fg_color="#142333")
        settings.pack(fill="x", padx=18, pady=5)
        self.similarity_var = tk.StringVar(value="99.0")
        self.confidence_var = tk.StringVar(value="0.20")
        self.negative_var = tk.StringVar(value="10")
        self.source_var = tk.StringVar(value="Tất cả ảnh")
        self.include_existing_var = tk.BooleanVar(value=False)
        ctk.CTkLabel(settings, text="Nguồn", text_color="#a9bdcc").pack(side="left", padx=(12, 4), pady=10)
        self.source_menu = ctk.CTkOptionMenu(
            settings,
            values=list(self.SOURCE_LABELS),
            variable=self.source_var,
            width=160,
            command=self._source_changed,
        )
        self.source_menu.pack(side="left", padx=(0, 8), pady=8)
        for label, variable, width in (
            ("Gần trùng (%)", self.similarity_var, 74),
            ("Confidence", self.confidence_var, 64),
            ("Giữ nền (%)", self.negative_var, 58),
        ):
            ctk.CTkLabel(settings, text=label, text_color="#a9bdcc").pack(side="left", padx=(12, 4), pady=10)
            ctk.CTkEntry(settings, width=width, textvariable=variable).pack(side="left", padx=(0, 8), pady=8)
        model_exists = bool(self.project.active_model and Path(self.project.active_model).exists())
        self.use_model = ctk.CTkCheckBox(settings, text="Dùng model", width=125)
        self.use_model.pack(side="left", padx=10)
        if model_exists:
            self.use_model.select()
        else:
            self.use_model.configure(state="disabled")
        self.analyze_button = ctk.CTkButton(settings, text="PHÂN TÍCH", width=130, command=self._start_analysis)
        self.analyze_button.pack(side="right", padx=10, pady=8)
        ToolTip(self.analyze_button, "Phân tích nguồn đã chọn; không thay đổi dữ liệu khi chưa xác nhận xóa.")

        scope_row = ctk.CTkFrame(self, fg_color="transparent")
        scope_row.pack(fill="x", padx=20, pady=(3, 0))
        self.include_existing = ctk.CTkCheckBox(
            scope_row,
            text="Bao gồm ảnh cũ đang có trong dự án",
            variable=self.include_existing_var,
            command=self._source_changed,
            width=285,
        )
        self.include_existing.pack(side="left")
        ToolTip(
            self.include_existing,
            "Tắt: chỉ phân tích ảnh của lượt nhập thành công gần nhất. Bật: quét cả ảnh cũ và ảnh mới trong dự án.",
        )
        ctk.CTkLabel(
            scope_row,
            text="Mặc định chỉ lọc lượt nhập mới nhất để thao tác nhanh trên dự án lớn.",
            text_color="#8298aa",
        ).pack(side="left", padx=14)

        self.status_label = ctk.CTkLabel(self, text="", text_color="#ffb547")
        self.status_label.pack(fill="x", padx=20, pady=4)
        self._source_changed(self.source_var.get())

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=5)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1, minsize=620)
        body.grid_columnconfigure(1, weight=0, minsize=480)
        table_card = ctk.CTkFrame(body, corner_radius=10, fg_color="#101b27")
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.tree_style = ttk.Style(self)
        self.tree_style.theme_use("clam")
        self.tree_style.configure("Frame.Treeview", background="#0b151f", fieldbackground="#0b151f", foreground="#dcecf6", rowheight=48, borderwidth=0)
        self.tree_style.configure("Frame.Treeview.Heading", background="#1c3345", foreground="#dcecf6", relief="flat")
        self.tree_style.map(
            "Frame.Treeview",
            background=[("selected", NEUTRAL_SELECTION_COLOR)],
            foreground=[("selected", "#ffffff")],
        )
        self.tree = ttk.Treeview(
            table_card,
            columns=("action", "source", "category", "name", "detail"),
            show="headings",
            style="Frame.Treeview",
            selectmode="browse",
        )
        self.tree.heading("action", text="THAO TÁC")
        self.tree.heading("source", text="│  NGUỒN")
        self.tree.heading("category", text="│  NHÓM")
        self.tree.heading("name", text="│  TÊN ẢNH")
        self.tree.heading("detail", text="│  LÝ DO")
        self.tree.column("action", width=70, minwidth=70, anchor="center", stretch=False)
        self.tree.column("source", width=145, minwidth=145, anchor="w", stretch=False)
        self.tree.column("category", width=135, minwidth=120, stretch=False)
        self.tree.column("name", width=210, minwidth=170, stretch=False)
        self.tree.column("detail", width=290, minwidth=230, stretch=True)
        scrollbar = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table_card, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        scrollbar.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x", padx=(8, 0))
        self.tree.pack(fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._show_selected)
        self.tree.bind("<Double-1>", self._toggle_selected)
        self.tree.tag_configure("delete", foreground="#ff9ba2", background="#15151d")
        self.tree.tag_configure("keep", foreground="#8ee6b5", background="#0d1920")

        preview_card = ctk.CTkFrame(body, width=480, corner_radius=10, fg_color="#101b27")
        preview_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        preview_card.grid_propagate(False)
        preview_header = ctk.CTkFrame(preview_card, fg_color="transparent")
        preview_header.pack(fill="x", padx=12, pady=(12, 5))
        ctk.CTkLabel(
            preview_header,
            text="XEM TRƯỚC",
            font=("Segoe UI Semibold", 13),
            text_color="#22b9ee",
        ).pack(side="left")
        self.preview_status_label = ctk.CTkLabel(
            preview_header,
            text="CHƯA CHỌN",
            width=105,
            height=25,
            corner_radius=8,
            fg_color="#314252",
            text_color="#d7e3ec",
            font=("Segoe UI Semibold", 10),
        )
        self.preview_status_label.pack(side="right")
        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="Chọn một dòng",
            width=450,
            height=340,
            fg_color="#071019",
            corner_radius=8,
        )
        self.preview_label.pack(padx=12, pady=5)
        self.preview_info = ctk.CTkTextbox(
            preview_card,
            width=450,
            height=165,
            fg_color="#0b151f",
            font=("Consolas", 11),
            wrap="word",
        )
        self.preview_info.pack(fill="both", expand=True, padx=12, pady=8)
        self.preview_info.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=18, pady=(3, 14))
        self.summary_label = ctk.CTkLabel(footer, text="Chưa phân tích", text_color="#a9bdcc")
        self.summary_label.pack(side="left")
        close = ctk.CTkButton(footer, text="Đóng", width=95, fg_color="#415466", command=self._close)
        close.pack(side="right", padx=4)
        self.delete_button = ctk.CTkButton(footer, text="XÓA CÁC ẢNH ĐỀ XUẤT", width=210, fg_color="#a94747", command=self._delete_suggestions, state="disabled")
        self.delete_button.pack(side="right", padx=4)
        ToolTip(self.delete_button, "Chỉ xóa những dòng đang mang trạng thái XÓA sau một lần xác nhận cuối.")

    def _settings(self) -> FrameFilterSettings:
        similarity = float(self.similarity_var.get().replace(",", ".")) / 100.0
        confidence = float(self.confidence_var.get().replace(",", "."))
        negative = int(self.negative_var.get())
        if not 0.90 <= similarity <= 1.0:
            raise ValueError("Ngưỡng gần trùng phải từ 90 đến 100%.")
        if not 0.05 <= confidence <= 0.95:
            raise ValueError("Confidence AI phải từ 0.05 đến 0.95.")
        if not 0 <= negative <= 100:
            raise ValueError("Tỷ lệ giữ ảnh nền phải từ 0 đến 100%.")
        return FrameFilterSettings(similarity, confidence, negative)

    def _start_analysis(self):
        source = self.SOURCE_LABELS.get(self.source_var.get(), SOURCE_ALL)
        records = image_records_for_filter(
            self.project,
            source,
            include_existing=bool(self.include_existing_var.get()),
        )
        if not records:
            detail = (
                "Chưa có ảnh thuộc lượt nhập mới nhất. Hãy nhập ảnh mới hoặc bật “Bao gồm ảnh cũ đang có trong dự án”."
                if not self.include_existing_var.get()
                else "Nguồn đã chọn không có ảnh để phân tích."
            )
            messagebox.showinfo("Không có ảnh", detail, parent=self)
            return
        try:
            settings = self._settings()
        except Exception as exc:
            messagebox.showerror("Thông số chưa hợp lệ", str(exc), parent=self)
            return
        self.cancel_event.clear()
        self.analyze_button.configure(state="disabled", text="ĐANG PHÂN TÍCH…")
        self.source_menu.configure(state="disabled")
        self.include_existing.configure(state="disabled")
        self.delete_button.configure(state="disabled")
        model = self.project.active_model if self.use_model.get() else None

        def progress(done, total, stage):
            self.queue.put(("progress", done, total, stage))

        def worker():
            try:
                results = analyze_smart_images(
                    self.project,
                    self.store,
                    settings,
                    model_path=model,
                    records=records,
                    progress=progress,
                    cancel_event=self.cancel_event,
                )
                self.queue.put(("done", results))
            except Exception as exc:
                self.queue.put(("error", str(exc)))
        Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                event = self.queue.get_nowait()
                if event[0] == "progress":
                    _, done, total, stage = event
                    self.status_label.configure(text=f"{stage}: {done}/{total}")
                elif event[0] == "done":
                    self._populate(event[1])
                    self.analyze_button.configure(state="normal", text="PHÂN TÍCH LẠI")
                    self.source_menu.configure(state="normal")
                    self.include_existing.configure(state="normal")
                elif event[0] == "error":
                    self.analyze_button.configure(state="normal", text="PHÂN TÍCH LẠI")
                    self.source_menu.configure(state="normal")
                    self.include_existing.configure(state="normal")
                    messagebox.showerror("Lọc ảnh lỗi", event[1], parent=self)
        except Empty:
            pass
        if self.winfo_exists():
            self.after(120, self._poll)

    def _populate(self, results: list[FrameDecision]):
        self.results = results
        self.result_by_id = {item.image_id: item for item in results}
        self.tree.delete(*self.tree.get_children())
        for item in results:
            self._insert_or_update(item)
        self._update_summary()
        self.status_label.configure(text="Phân tích xong. Double-click để sửa quyết định trước khi xóa.", text_color="#43d17d")
        self.delete_button.configure(state="normal")

    def _insert_or_update(self, item: FrameDecision):
        source_text = "VIDEO" if item.source_kind == SOURCE_VIDEO else "ẢNH NHẬP"
        if item.protected:
            source_text += "\nBẢO VỆ"
        values = (
            "XÓA" if item.suggested_delete else "GIỮ",
            self._with_column_separator(source_text),
            self._with_column_separator(self.CATEGORY_LABELS.get(item.category, item.category)),
            self._with_column_separator(self._compact_file_name(item.file_name)),
            self._with_column_separator(self._wrap_table_text(item.reason)),
        )
        tags = ("delete",) if item.suggested_delete else ("keep",)
        if self.tree.exists(item.image_id):
            self.tree.item(item.image_id, values=values, tags=tags)
        else:
            self.tree.insert("", "end", iid=item.image_id, values=values, tags=tags)

    @staticmethod
    def _compact_file_name(value: str, limit: int = 34) -> str:
        if len(value) <= limit:
            return value
        tail = max(10, limit // 2 - 2)
        head = limit - tail - 1
        return f"{value[:head]}…{value[-tail:]}"

    @staticmethod
    def _wrap_table_text(value: str, width: int = 42, max_lines: int = 2) -> str:
        lines = textwrap.wrap(value, width=width, break_long_words=True, break_on_hyphens=False)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" .") + "…"
        return "\n".join(lines)

    @staticmethod
    def _with_column_separator(value: str) -> str:
        return "\n".join(f"│  {line}" for line in str(value).splitlines())

    def _toggle_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        item = self.result_by_id[selected[0]]
        item.suggested_delete = not item.suggested_delete
        self._insert_or_update(item)
        self._update_summary()
        self._show_selected()

    def _show_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        item = self.result_by_id[selected[0]]
        self._apply_selection_state(item)
        record = self.project.image_by_id(item.image_id)
        if record is None:
            return
        try:
            with Image.open(self.store.image_path(self.project, record)) as source:
                preview, _content_box = build_contained_preview(source)
            self.preview_photo = ctk.CTkImage(
                light_image=preview,
                dark_image=preview,
                size=PREVIEW_SIZE,
            )
            self.preview_label.configure(image=self.preview_photo, text="")
        except Exception:
            self.preview_photo = None
            self.preview_label.configure(image=None, text="Không đọc được ảnh")
        info = (
            f"Quyết định : {'XÓA' if item.suggested_delete else 'GIỮ'}\n"
            f"Nhóm       : {self.CATEGORY_LABELS.get(item.category, item.category)}\n"
            f"AI thấy    : {item.detection_count} vật\n"
            f"Confidence : {item.confidence:.3f}\n"
            f"Độ giống   : {item.similarity * 100:.2f}%\n"
            f"Foreground : {item.foreground_ratio * 100:.2f}%\n"
            f"Độ nét     : {item.sharpness:.1f}\n"
            f"Độ sáng    : {item.brightness:.1f}/255\n"
            f"Nguồn      : {'Frame video' if item.source_kind == SOURCE_VIDEO else 'Ảnh nhập'}\n"
            f"Bảo vệ     : {'Có nhãn/đã duyệt' if item.protected else 'Không'}\n\n{item.reason}"
        )
        self.preview_info.configure(state="normal")
        self.preview_info.delete("1.0", tk.END)
        self.preview_info.insert("1.0", info)
        self.preview_info.configure(state="disabled")

    def _apply_selection_state(self, item: FrameDecision) -> None:
        if item.suggested_delete:
            color = DELETE_SELECTION_COLOR
            badge_text = "SẼ XÓA"
        else:
            color = KEEP_SELECTION_COLOR
            badge_text = "ĐANG GIỮ"
        self.tree_style.map(
            "Frame.Treeview",
            background=[("selected", color)],
            foreground=[("selected", "#ffffff")],
        )
        self.preview_status_label.configure(text=badge_text, fg_color=color, text_color="#ffffff")

    def _update_summary(self):
        delete_count = sum(item.suggested_delete for item in self.results)
        protected = sum(item.protected for item in self.results)
        self.summary_label.configure(
            text=f"Tổng {len(self.results)} ảnh · GIỮ {len(self.results) - delete_count} · đề xuất XÓA {delete_count} · bảo vệ {protected}"
        )

    def _delete_suggestions(self):
        ids = {item.image_id for item in self.results if item.suggested_delete}
        records = [record for record in self.project.images if record.id in ids]
        if not records:
            messagebox.showinfo("Không có ảnh cần xóa", "Không có dòng nào đang mang trạng thái XÓA.", parent=self)
            return
        annotations = sum(len(record.annotations) for record in records)
        if not messagebox.askyesno(
            "Xác nhận lọc ảnh",
            f"Xóa {len(records)} ảnh và {annotations} nhãn liên quan khỏi dự án?\n\n"
            "Ảnh/video nguồn ban đầu và Dataset đã export không bị thay đổi. "
            "Có thể double-click từng dòng để đổi quyết định trước khi tiếp tục.",
            parent=self,
        ):
            return
        try:
            removed_images, removed_annotations = self.store.delete_images(self.project, records)
        except Exception as exc:
            messagebox.showerror("Không xóa được ảnh", str(exc), parent=self)
            return
        self.on_deleted(removed_images, removed_annotations)
        messagebox.showinfo("Đã lọc ảnh", f"Đã xóa {removed_images} ảnh và {removed_annotations} nhãn liên quan.", parent=self)
        self.destroy()

    def _source_changed(self, _value=None):
        source = self.SOURCE_LABELS.get(self.source_var.get(), SOURCE_ALL)
        include_existing = bool(self.include_existing_var.get())
        count = len(image_records_for_filter(self.project, source, include_existing=include_existing))
        self.results = []
        self.result_by_id = {}
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "delete_button"):
            self.delete_button.configure(state="disabled")
        if hasattr(self, "summary_label"):
            self.summary_label.configure(text="Chưa phân tích")
        if hasattr(self, "preview_label"):
            self.preview_photo = None
            self.preview_label.configure(image=None, text="Chọn một dòng")
            self.preview_status_label.configure(text="CHƯA CHỌN", fg_color="#314252", text_color="#d7e3ec")
            self.tree_style.map(
                "Frame.Treeview",
                background=[("selected", NEUTRAL_SELECTION_COLOR)],
                foreground=[("selected", "#ffffff")],
            )
            self.preview_info.configure(state="normal")
            self.preview_info.delete("1.0", tk.END)
            self.preview_info.configure(state="disabled")
        if not include_existing and not self.project.last_import_batch:
            text = "Dự án cũ chưa có mã lượt nhập mới. Hãy nhập thêm ảnh hoặc bật “Bao gồm ảnh cũ”."
        else:
            scope = "toàn bộ dự án" if include_existing else "lượt nhập mới nhất"
            text = f"Nguồn “{self.source_var.get()}” · {scope}: {count} ảnh sẵn sàng phân tích."
        self.status_label.configure(text=text, text_color="#ffb547")

    def _close(self):
        self.cancel_event.set()
        self.destroy()

from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from datetime import datetime
import json
import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from .annotation_canvas import AnnotationCanvas
from .auto_label import Sam2Adapter, auto_label_project, mask_to_geometry
from .dataset_manager import DatasetManager
from .deployment import build_vision_bundle_manifest, classifier_manifest_entry, write_classifier_pt_bundle
from .evaluation import evaluate_yolo_model
from .hardware import inspect_hardware
from .frame_filter_dialog import SmartFrameFilterDialog
from .model_export import RknnExportConfig, RknnExportJob, diagnose_rknn_environment
from .models import Annotation, Project
from .project_store import ProjectStore
from .quality import inspect_project
from .split_dialog import SplitManagerDialog
from .training import TrainingConfig, TrainingJob
from .ui_components import ProjectSettingsDialog, ThumbnailList, ToolTip
from .version_dialog import ask_dataset_version_name


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = APP_ROOT / "workspace"
DEMO_IMAGES = Path(r"D:\DeltaX\Tai Lieu Demo\Phan Loai Chai Nhua\Data\images")
DEMO_MODEL = Path(r"D:\DeltaX\Tai Lieu Demo\Phan Loai Chai Nhua\Model\best.pt")
SAM2_SMALL_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_small.pt"

COLORS = {
    "bg": "#081019",
    "panel": "#101b27",
    "panel2": "#142333",
    "border": "#263b50",
    "text": "#e7f3fb",
    "muted": "#8298aa",
    "accent": "#22b9ee",
    "good": "#43d17d",
    "warn": "#ffb547",
    "bad": "#f26464",
}

ATTRIBUTE_DISPLAY = {
    "condition": {
        "nguyen_ven": "Nguyên vẹn",
        "bep_nhe": "Bẹp nhẹ",
        "can_dep": "Cán dẹp",
        "vo_nat": "Vỡ nát",
    },
    "occlusion": {"none": "Không che", "partial": "Che một phần", "heavy": "Che nhiều"},
    "cap": {"co_nap": "Có nắp", "mat_nap": "Mất nắp", "khong_xac_dinh": "Chưa rõ"},
}

SPLIT_STRATEGY_LABELS = {
    "Phát triển · Khóa Train/Val/Test": DatasetManager.STRATEGY_LOCKED,
    "Final · Train + Val, giữ Test": DatasetManager.STRATEGY_FINAL_KEEP_TEST,
    "Final · Train 100% dữ liệu": DatasetManager.STRATEGY_TRAIN_ALL,
}


class SmartLabelApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("DeltaX Smart Label Studio — AI-assisted Annotation")
        self.geometry("1500x900")
        self.minsize(1180, 720)
        self.configure(fg_color=COLORS["bg"])

        self.store = ProjectStore(WORKSPACE)
        self.datasets = DatasetManager(self.store)
        self.settings_path = WORKSPACE / "settings.json"
        self.app_settings = self._load_app_settings()
        self.project: Project | None = None
        self.current_index = -1
        self.image_page_size = 50
        self.image_page = 0
        self.paged_images = []
        self.selected_annotation_id: str | None = None
        self.last_selected_by_image: dict[str, str] = {}
        self.model_path = tk.StringVar(value=str(DEMO_MODEL) if DEMO_MODEL.exists() else "")
        self.event_queue: Queue[tuple[str, object]] = Queue()
        self.cancel_event = Event()
        self.training_job: TrainingJob | None = None
        self.running_training_task = ""
        self.running_classification_key = ""
        self.classification_batch_vars: dict[str, tk.BooleanVar] = {}
        self.batch_training_queue: list[tuple[str, Path]] = []
        self.batch_training_results: dict[str, Path] = {}
        self.batch_training_options: dict[str, object] = {}
        self.batch_training_total = 0
        self.batch_training_active = False
        self.batch_training_cancelled = False
        self.pending_training_note = ""
        self.last_localization_task = "detect"
        self.model_export_job: RknnExportJob | None = None
        self.running_rknn_task = ""
        self.running_rknn_attribute_key = ""
        self.rknn_batch_queue: list[tuple[str, Path]] = []
        self.rknn_batch_output_dir: Path | None = None
        self.rknn_batch_total = 0
        self.rknn_batch_completed = 0
        self.rknn_batch_active = False
        self.rknn_batch_cancelled = False
        self.deploy_model_path = tk.StringVar(value="")
        self.evaluation_model_path = tk.StringVar(value="")
        self.evaluation_data_path = tk.StringVar(value="")
        self.evaluation_split = tk.StringVar(value="test")
        self.evaluation_running = False
        self.train_split_strategy = tk.StringVar(value=next(iter(SPLIT_STRATEGY_LABELS)))
        self.classification_group_var = tk.StringVar(value="")
        self.sam_adapter: Sam2Adapter | None = None
        self.sam_lock = Lock()
        self.sam_request_versions: dict[str, int] = {}
        self.sam_click_enabled = tk.BooleanVar(value=False)
        self.sam_click_request_version = 0
        self.sam_click_busy = False
        self.sam_checkpoint = tk.StringVar(value=self.app_settings.get("sam_checkpoint", ""))
        self.annotation_geometry = tk.StringVar(value=self.app_settings.get("annotation_geometry", "RECT"))
        # This is a project training-mode switch, not a cosmetic preference.
        # Off: train the normal localization task. On: label/train attributes
        # as a second-stage Classification dataset.
        self.show_attribute_panel = tk.BooleanVar(value=False)
        saved_sam_config = self.app_settings.get("sam_config", "")
        self.sam_config = tk.StringVar(value=saved_sam_config if saved_sam_config in Sam2Adapter.available_configs() else Sam2Adapter.suggest_config())

        self._build_header()
        self._build_tabs()
        self._load_initial_project()
        self.after(100, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- shell ----------
    def _load_app_settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_app_settings(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.app_settings.update({
            "sam_checkpoint": self.sam_checkpoint.get(),
            "sam_config": self.sam_config.get(),
            "annotation_geometry": self.annotation_geometry.get(),
        })
        self.settings_path.write_text(json.dumps(self.app_settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=74, corner_radius=0, fg_color="#0b151f")
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(brand, text="SMART LABEL", font=("Segoe UI Semibold", 22), text_color=COLORS["accent"]).pack(anchor="w")
        ctk.CTkLabel(brand, text="Gán nhãn nhanh hơn với AI, con người giữ quyền quyết định", font=("Segoe UI", 11), text_color=COLORS["muted"]).pack(anchor="w")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right", padx=18)
        self.project_menu = ctk.CTkOptionMenu(actions, width=260, values=["Chưa có dự án"], command=self._switch_project)
        self.project_menu.pack(side="left", padx=6)
        self._button(actions, "Dự án mới", self._new_project, width=110).pack(side="left", padx=6)
        self._button(actions, "Lưu", self.save_project, width=80, color=COLORS["good"]).pack(side="left", padx=6)

    def _build_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(
            self,
            corner_radius=14,
            fg_color=COLORS["panel"],
            segmented_button_fg_color="#101d2a",
            segmented_button_selected_color=COLORS["accent"],
            segmented_button_selected_hover_color="#1aa7d7",
        )
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(8, 14))
        for name in ("DỰ ÁN", "GÁN NHÃN", "AUTO-LABEL", "KIỂM DUYỆT", "DATASET", "TRAIN", "PHẦN CỨNG"):
            self.tabs.add(name)
        self._build_project_tab()
        self._build_label_tab()
        self._build_auto_tab()
        self._build_review_tab()
        self._build_dataset_tab()
        self._build_train_tab()
        self._build_hardware_tab()

    def _button(self, parent, text, command, *, width=130, color=None, tooltip: str | None = None):
        enabled_color = color or "#217fa9"
        hover_color = "#279dcc" if color is None else color
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=36,
            corner_radius=9,
            fg_color=enabled_color,
            hover_color=hover_color,
            text_color=COLORS["text"],
            text_color_disabled="#617181",
            font=("Segoe UI Semibold", 12),
        )
        button._smartlabel_enabled_fg = enabled_color
        button._smartlabel_enabled_hover = hover_color
        ToolTip(button, tooltip or self._tooltip_text(text))
        return button

    @staticmethod
    def _set_button_enabled(button, enabled: bool) -> None:
        if enabled:
            button.configure(
                state="normal",
                fg_color=getattr(button, "_smartlabel_enabled_fg", "#217fa9"),
                hover_color=getattr(button, "_smartlabel_enabled_hover", "#279dcc"),
                border_width=0,
                text_color=COLORS["text"],
            )
        else:
            button.configure(
                state="disabled",
                fg_color="#202a34",
                hover_color="#202a34",
                border_width=1,
                border_color="#344451",
                text_color_disabled="#617181",
            )

    @staticmethod
    def _tooltip_text(text: str) -> str:
        normalized = text.lower()
        hints = (
            ("dự án mới", "Tạo một dự án gán nhãn độc lập."),
            ("lưu", "Lưu ngay class, ảnh, nhãn và trạng thái hiện tại."),
            ("thư mục", "Nhập toàn bộ ảnh trong thư mục và các thư mục con."),
            ("các ảnh", "Chọn một hoặc nhiều file ảnh để nhập."),
            ("video", "Tách frame từ video theo khoảng frame đã chọn."),
            ("lọc frame", "Nhóm ảnh gần trùng, ảnh trống và frame nên giữ; chỉ xóa sau khi người dùng xác nhận."),
            ("demo", "Nhập bộ 126 ảnh chai nhựa dùng để thử nghiệm."),
            ("quản lý", "Thêm/xóa Class, chọn màu và sửa các lựa chọn thuộc tính."),
            ("polygon", "Bấm các điểm quanh vật; double-click để kết thúc polygon."),
            ("box", "Kéo chuột để tạo bounding box quanh vật."),
            ("sam2 từ", "Dùng box đang chọn làm prompt để SAM2 tạo mask."),
            ("sam2 → seg", "Dùng RECT đang chọn làm prompt để SAM2 tạo nhãn Segmentation."),
            ("seg → rect", "Bỏ đường mask và quay nhãn đang chọn về bounding box RECT được giữ lại."),
            ("sam +", "Bấm vào phần vật SAM2 còn thiếu để thêm vùng vào mask."),
            ("sam −", "Bấm vào nền/vật khác để loại vùng bị dính khỏi mask."),
            ("↶", "Hoàn tác thay đổi nhãn gần nhất (Ctrl+Z)."),
            ("↷", "Làm lại thay đổi vừa hoàn tác (Ctrl+Y)."),
            ("xóa nhãn", "Xóa nhãn đang được chọn khỏi ảnh."),
            ("vừa ảnh", "Thu phóng để toàn bộ ảnh vừa trong vùng hiển thị."),
            ("căn giữa", "Đưa ảnh về giữa vùng hiển thị, giữ nguyên mức zoom."),
            ("phóng to", "Phóng to ảnh quanh tâm vùng hiển thị."),
            ("thu nhỏ", "Thu nhỏ ảnh quanh tâm vùng hiển thị."),
            ("ảnh trước", "Mở ảnh liền trước và đồng bộ vùng chọn trong danh sách."),
            ("ảnh sau", "Mở ảnh liền sau và đồng bộ vùng chọn trong danh sách."),
            ("duyệt ảnh", "Đánh dấu ảnh và mọi nhãn hiện tại đã được kiểm tra."),
            ("bỏ duyệt", "Đưa ảnh đã duyệt về bản nháp để sửa lại."),
            ("từ chối", "Loại ảnh khỏi dataset mặc định nhưng không xóa ảnh/nhãn."),
            ("khôi phục", "Bỏ trạng thái từ chối và đưa ảnh về bản nháp."),
            ("auto-label", "Chạy model YOLO tạo nhãn đề xuất cho nhiều ảnh."),
            ("dừng", "Yêu cầu dừng tác vụ đang chạy sau bước an toàn hiện tại."),
            ("export", "Xuất dataset theo định dạng đã chọn."),
            ("train", "Chạy huấn luyện trong tiến trình riêng để không khóa giao diện."),
            ("đánh giá", "Đánh giá model trên dataset và hiển thị các chỉ số."),
            ("quét", "Kiểm tra lại trạng thái runtime hoặc dữ liệu."),
            ("mở ảnh", "Mở ảnh của dòng đang chọn trong trang GÁN NHÃN."),
        )
        return next((hint for key, hint in hints if key in normalized), f"Thực hiện chức năng “{text}”.")

    def _card(self, parent, title: str):
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color=COLORS["panel2"], border_width=1, border_color=COLORS["border"])
        ctk.CTkLabel(card, text=title, font=("Segoe UI Semibold", 14), text_color=COLORS["accent"]).pack(anchor="w", padx=14, pady=(12, 6))
        return card

    # ---------- project ----------
    def _build_project_tab(self) -> None:
        tab = self.tabs.tab("DỰ ÁN")
        left = self._card(tab, "DỮ LIỆU DỰ ÁN")
        left.pack(side="left", fill="y", padx=(8, 5), pady=8)
        self._button(left, "Nhập thư mục ảnh", self._import_folder, width=220).pack(padx=14, pady=6)
        self._button(left, "Nhập các ảnh", self._import_files, width=220).pack(padx=14, pady=6)
        self._button(left, "Tách frame từ video", self._import_video, width=220).pack(padx=14, pady=6)
        self._button(
            left,
            "Lọc ảnh thông minh",
            self._open_frame_filter,
            width=220,
            color="#6d56a4",
            tooltip="Lọc gần trùng, ảnh nền và ảnh chất lượng kém cho cả frame video lẫn ảnh nhập/thư mục.",
        ).pack(padx=14, pady=6)
        self._button(left, "Nạp demo 126 ảnh chai", self._import_demo, width=220, color="#2b906d").pack(padx=14, pady=6)
        self._button(left, "Quản lý Class & thuộc tính", self._edit_classes, width=220).pack(padx=14, pady=6)
        ctk.CTkLabel(left, text="Ảnh được sao chép vào workspace\nđể dự án không phụ thuộc thư mục nguồn.", text_color=COLORS["muted"], justify="left").pack(padx=14, pady=14)

        center = self._card(tab, "TỔNG QUAN")
        center.pack(side="left", fill="both", expand=True, padx=5, pady=8)
        self.project_summary = ctk.CTkTextbox(center, font=("Consolas", 14), fg_color="#0a131c", corner_radius=10)
        self.project_summary.pack(fill="both", expand=True, padx=14, pady=(4, 14))

        right = self._card(tab, "NGUYÊN TẮC")
        right.pack(side="right", fill="y", padx=(5, 8), pady=8)
        guidance = (
            "1. AI chỉ tạo nhãn đề xuất.\n\n"
            "2. Nhãn phải được người dùng kiểm tra.\n\n"
            "3. Chỉ ảnh ĐÃ DUYỆT mới được đưa vào dataset mặc định.\n\n"
            "4. Class là loại chai; biến dạng lưu bằng thuộc tính.\n\n"
            "5. Mỗi lần train dùng một phiên bản dataset bất biến."
        )
        ctk.CTkLabel(right, text=guidance, width=280, wraplength=260, justify="left", anchor="nw", text_color=COLORS["text"]).pack(padx=14, pady=10)

    def _new_project(self) -> None:
        name = simpledialog.askstring("Dự án mới", "Tên dự án:", parent=self)
        if not name:
            return
        project = self.store.create_project(name, classes=["Chai_trong", "Chai_lo", "Chai_xanh_la"])
        project.attribute_schema = {
            "condition": ["nguyen_ven", "bep_nhe", "can_dep", "vo_nat"],
            "occlusion": ["none", "partial", "heavy"],
            "cap": ["co_nap", "mat_nap", "khong_xac_dinh"],
        }
        project.attribute_settings = {
            "condition": {"title": "Tình trạng", "default": "", "required": False, "role": "classification"},
            "occlusion": {"title": "Che khuất", "default": "none", "required": False, "role": "metadata"},
            "cap": {"title": "Nắp chai", "default": "khong_xac_dinh", "required": False, "role": "metadata"},
        }
        self.store.save(project)
        self.project = project
        self.current_index = -1
        self._refresh_everything()

    def _load_initial_project(self) -> None:
        projects = self.store.list_projects()
        if projects:
            self.project = self.store.load(projects[0])
            if self.project.active_model and Path(self.project.active_model).exists():
                self.model_path.set(self.project.active_model)
                if Path(self.project.active_model).suffix.lower() == ".pt":
                    self.deploy_model_path.set(self.project.active_model)
            self._recover_latest_trained_model()
            self._refresh_evaluation_defaults(force=True)
        self._refresh_everything()

    def _recover_latest_trained_model(self) -> None:
        """Recover a completed best.pt if the UI closed before handling train_done."""
        if not self.project:
            return
        best = self._latest_best_pt()
        active = Path(self.project.active_model) if self.project.active_model else None
        if best is None or (active and active.is_file() and active.stat().st_mtime >= best.stat().st_mtime):
            return
        registered = self.store.register_model(best)
        self.project.active_model = str(registered)
        self.model_path.set(str(registered))
        self.deploy_model_path.set(str(best.resolve()))
        self.store.save(self.project)

    def _refresh_project_menu(self) -> None:
        paths = self.store.list_projects()
        values = []
        self.project_lookup = {}
        for path in paths:
            try:
                project = self.store.load(path)
                label = f"{project.name} · {project.id[-6:]}"
                values.append(label)
                self.project_lookup[label] = path
            except Exception:
                continue
        if not values:
            values = ["Chưa có dự án"]
        self.project_menu.configure(values=values)
        if self.project:
            selected = next((label for label in values if self.project.id in str(self.project_lookup.get(label, ""))), values[0])
            self.project_menu.set(selected)

    def _switch_project(self, label: str) -> None:
        path = getattr(self, "project_lookup", {}).get(label)
        if path:
            self.project = self.store.load(path)
            self._recover_latest_trained_model()
            if self.project.active_model and Path(self.project.active_model).exists():
                self.model_path.set(self.project.active_model)
                if Path(self.project.active_model).suffix.lower() == ".pt":
                    self.deploy_model_path.set(self.project.active_model)
            self.current_index = 0 if self.project.images else -1
            self._refresh_evaluation_defaults(force=True)
            self._refresh_everything()

    def save_project(self) -> None:
        if self.project:
            self.store.save(self.project)
            self._set_status("Đã lưu dự án", COLORS["good"])

    def _import_folder(self) -> None:
        folder = filedialog.askdirectory(title="Chọn thư mục ảnh")
        if folder:
            self._run_import([folder])

    def _import_files(self) -> None:
        files = filedialog.askopenfilenames(title="Chọn ảnh", filetypes=[("Ảnh", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp")])
        if files:
            self._run_import(files)

    def _import_demo(self) -> None:
        if not DEMO_IMAGES.exists():
            messagebox.showerror("Không tìm thấy", f"Không tìm thấy dữ liệu demo:\n{DEMO_IMAGES}")
            return
        self._run_import([DEMO_IMAGES])

    def _import_video(self) -> None:
        if not self.project:
            self._new_project()
        if not self.project:
            return
        path = filedialog.askopenfilename(title="Chọn video", filetypes=[("Video", "*.mp4 *.avi *.mov *.mkv")])
        if not path:
            return
        total_frames = 0
        fps = 0.0
        try:
            import cv2
            probe = cv2.VideoCapture(path)
            if probe.isOpened():
                total_frames = int(probe.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = float(probe.get(cv2.CAP_PROP_FPS))
            probe.release()
        except Exception:
            pass
        suggested = max(10, (total_frames + 499) // 500) if total_frames else 10
        duration = f" · khoảng {total_frames / fps:.1f} giây" if total_frames and fps > 0 else ""
        prompt = (
            f"Video có {total_frames:,} frame{duration}.\n"
            f"Lưu mỗi N frame (khuyến nghị N ≥ {suggested}, tương đương tối đa khoảng 500 ảnh):"
            if total_frames
            else "Lưu mỗi N frame:"
        )
        every = simpledialog.askinteger(
            "Tách frame",
            prompt,
            initialvalue=suggested,
            minvalue=1,
            maxvalue=10000,
            parent=self,
        )
        if not every:
            return
        estimated = (total_frames + every - 1) // every if total_frames else 0
        if estimated > 500 and not messagebox.askyesno(
            "Số ảnh rất lớn",
            f"Thiết lập N={every} dự kiến tạo khoảng {estimated:,} ảnh.\n\n"
            "Nhập quá nhiều ảnh sẽ tốn dung lượng và thời gian gán nhãn. "
            f"Khuyến nghị quay lại và chọn N ≥ {suggested}.\n\nVẫn tiếp tục?",
            parent=self,
        ):
            return
        project = self.project
        def worker():
            try:
                result = self.store.import_video(project, path, every, lambda i, n, name: self.event_queue.put(("status", f"Video {i}/{n}: {name}")))
                self.event_queue.put(("import_done", result))
            except Exception as exc:
                self.event_queue.put(("error", str(exc)))
        Thread(target=worker, daemon=True).start()

    def _open_frame_filter(self) -> None:
        if not self.project:
            messagebox.showinfo("Chưa có dự án", "Hãy mở hoặc tạo một dự án trước.", parent=self)
            return
        SmartFrameFilterDialog(self, self.project, self.store, self._after_frame_filter_delete)

    def _after_frame_filter_delete(self, removed_images: int, removed_annotations: int) -> None:
        self.last_selected_by_image = {
            image_id: annotation_id
            for image_id, annotation_id in self.last_selected_by_image.items()
            if self.project and self.project.image_by_id(image_id)
        }
        if self.project and self.project.images:
            self.current_index = min(max(self.current_index, 0), len(self.project.images) - 1)
        else:
            self.current_index = -1
        self.image_page = 0
        self._refresh_everything()
        self._set_status(
            f"Lọc ảnh: đã xóa {removed_images} ảnh và {removed_annotations} nhãn",
            COLORS["good"],
        )

    def _run_import(self, paths) -> None:
        if not self.project:
            self._new_project()
        if not self.project:
            return
        self._set_status("Đang nhập ảnh…")
        def worker():
            try:
                result = self.store.import_images(self.project, paths, lambda i, n, name: self.event_queue.put(("status", f"Nhập {i}/{n}: {name}")))
                self.event_queue.put(("import_done", result))
            except Exception as exc:
                self.event_queue.put(("error", str(exc)))
        Thread(target=worker, daemon=True).start()

    def _edit_classes(self) -> None:
        if not self.project:
            return
        ProjectSettingsDialog(self, self.project, self._save_project_settings)

    def _save_project_settings(self) -> None:
        self.save_project()
        self._refresh_label_choices()
        self._refresh_everything(keep_image=True)

    # ---------- labeling ----------
    def _build_label_tab(self) -> None:
        tab = self.tabs.tab("GÁN NHÃN")
        geometry_bar = ctk.CTkFrame(tab, height=44, corner_radius=10, fg_color="#0d1924")
        geometry_bar.pack(fill="x", padx=8, pady=(8, 3))
        ctk.CTkLabel(geometry_bar, text="LOẠI NHÃN", text_color=COLORS["muted"], font=("Segoe UI Semibold", 11)).pack(side="left", padx=(12, 8))
        self.geometry_selector = ctk.CTkSegmentedButton(
            geometry_bar,
            values=["RECT", "SEG", "OBB", "ORI"],
            variable=self.annotation_geometry,
            command=self._geometry_changed,
            width=310,
        )
        self.geometry_selector.pack(side="left", padx=4, pady=6)
        self.to_obb_button = self._button(geometry_bar, "SEG/RECT → OBB", self._convert_selected_to_obb, width=145, color="#48657a", tooltip="Tạo OBB quay sát vật từ polygon SEG; nếu chưa có SEG thì dùng RECT.")
        self.to_obb_button.pack(side="left", padx=5, pady=4)
        self.orientation_button = self._button(geometry_bar, "Đặt hướng ORI", self._start_orientation, width=125, color="#8a6631", tooltip="Chọn vật rồi bấm điểm chỉ hướng đầu/nắp; tâm mũi tên lấy từ tâm RECT.")
        self.orientation_button.pack(side="left", padx=5, pady=4)
        ctk.CTkLabel(geometry_bar, text="OBB: góc 180° · ORI: hướng đầu–đuôi 360°", text_color="#7890a3", font=("Segoe UI", 10)).pack(side="left", padx=8)

        toolbar = ctk.CTkFrame(tab, height=48, corner_radius=10, fg_color=COLORS["panel2"])
        toolbar.pack(fill="x", padx=8, pady=(3, 5))
        self._button(toolbar, "Chọn", lambda: self._set_tool("select"), width=75).pack(side="left", padx=(8, 3), pady=6)
        self._button(toolbar, "Vẽ RECT", lambda: self._set_geometry_and_tool("RECT", "box"), width=82).pack(side="left", padx=3, pady=6)
        self._button(toolbar, "Vẽ SEG", lambda: self._set_geometry_and_tool("SEG", "polygon"), width=82).pack(side="left", padx=3, pady=6)
        self.sam_click_switch = ctk.CTkSwitch(
            toolbar,
            text="SAM ON",
            variable=self.sam_click_enabled,
            command=self._toggle_sam_click,
            width=92,
            progress_color="#7655b5",
            button_color="#d5c4ff",
            button_hover_color="#ffffff",
            text_color=COLORS["text"],
            font=("Segoe UI Semibold", 11),
        )
        self.sam_click_switch.pack(side="left", padx=5, pady=6)
        ToolTip(self.sam_click_switch, "Bật rồi bấm một điểm lên vật để SAM2 tự tạo RECT, SEG hoặc OBB mà không cần model YOLO.")
        self._button(toolbar, "SAM2 → SEG", self._sam_refine_selected, width=105, color="#7655b5", tooltip="Dùng RECT đang chọn làm prompt để SAM2 tạo biên SEG.").pack(side="left", padx=3, pady=6)
        self.to_rect_button = self._button(toolbar, "SEG → RECT", self._convert_selected_to_bbox, width=100, color="#48657a")
        self.to_rect_button.pack(side="left", padx=3, pady=6)
        self._button(toolbar, "SAM +", lambda: self._set_tool("sam_positive"), width=65, color="#278c61").pack(side="left", padx=3, pady=6)
        self._button(toolbar, "SAM −", lambda: self._set_tool("sam_negative"), width=65, color="#a94747").pack(side="left", padx=3, pady=6)
        self._button(toolbar, "↶", lambda: self.canvas.undo(), width=42).pack(side="left", padx=3, pady=6)
        self._button(toolbar, "↷", lambda: self.canvas.redo(), width=42).pack(side="left", padx=3, pady=6)
        self._button(toolbar, "Xóa nhãn", self._delete_annotation, width=90, color="#a94747").pack(side="left", padx=3, pady=6)
        # With pack(side="right"), the first widget is placed furthest right.
        # Keep the natural reading order: Ảnh trước on the left, Ảnh sau on the right.
        self._button(toolbar, "Ảnh sau ▶", self._next_image, width=100).pack(side="right", padx=(3, 8), pady=6)
        self._button(toolbar, "◀ Ảnh trước", self._previous_image, width=100).pack(side="right", padx=3, pady=6)

        body = ctk.CTkFrame(tab, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        left = self._card(body, "DANH SÁCH ẢNH")
        left.pack(side="left", fill="y", padx=(0, 5))
        self.image_filter = ctk.CTkOptionMenu(left, width=260, values=["Tất cả", "Chưa gán nhãn", "Bản nháp", "Đã duyệt", "Từ chối"], command=self._change_image_filter)
        self.image_filter.pack(padx=10, pady=6)
        page_row = ctk.CTkFrame(left, fg_color="transparent")
        page_row.pack(fill="x", padx=8, pady=(0, 3))
        self.image_page_previous_button = self._button(
            page_row,
            "◀",
            lambda: self._change_image_page(-1),
            width=42,
            color="#415466",
            tooltip="Trang ảnh trước. Mỗi trang chỉ nạp một số thumbnail để ứng dụng không bị treo.",
        )
        self.image_page_previous_button.pack(side="left")
        self.image_page_label = ctk.CTkLabel(
            page_row,
            text="0 ảnh",
            width=174,
            text_color=COLORS["muted"],
            font=("Segoe UI Semibold", 10),
        )
        self.image_page_label.pack(side="left", padx=3)
        self.image_page_next_button = self._button(
            page_row,
            "▶",
            lambda: self._change_image_page(1),
            width=42,
            color="#415466",
            tooltip="Trang ảnh tiếp theo.",
        )
        self.image_page_next_button.pack(side="right")
        self.image_list = ThumbnailList(
            left,
            command=self._on_thumbnail_selected,
            delete_command=self._delete_image_from_thumbnail,
            width=286,
        )
        self.image_list.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        center = ctk.CTkFrame(body, corner_radius=12, fg_color="#091119", border_width=1, border_color=COLORS["border"])
        center.pack(side="left", fill="both", expand=True, padx=5)
        self.current_image_label = ctk.CTkLabel(
            center,
            text="Chưa chọn ảnh",
            height=32,
            anchor="w",
            font=("Segoe UI Semibold", 12),
            text_color=COLORS["accent"],
        )
        self.current_image_label.pack(fill="x", padx=10, pady=(4, 0))
        self.canvas = AnnotationCanvas(center, self._annotation_changed, self._annotation_selected, self._sam_prompt_added, self._view_changed)
        self.canvas.set_geometry_mode(self.annotation_geometry.get().lower())
        self.canvas.pack(fill="both", expand=True, padx=5, pady=5)
        zoom_panel = ctk.CTkFrame(center, corner_radius=12, fg_color="#122331", border_width=1, border_color="#31516a")
        zoom_panel.place(relx=1.0, rely=1.0, x=-18, y=-18, anchor="se")
        self._button(zoom_panel, "−", lambda: self.canvas.zoom(1 / 1.2), width=36, tooltip="Thu nhỏ ảnh quanh tâm vùng hiển thị.").pack(side="left", padx=(5, 2), pady=5)
        self.zoom_percent_label = ctk.CTkLabel(zoom_panel, text="100%", width=54, text_color=COLORS["text"], font=("Segoe UI Semibold", 11))
        self.zoom_percent_label.pack(side="left", padx=2)
        self._button(zoom_panel, "+", lambda: self.canvas.zoom(1.2), width=36, tooltip="Phóng to ảnh quanh tâm vùng hiển thị.").pack(side="left", padx=2, pady=5)
        self._button(zoom_panel, "Vừa", lambda: self.canvas.fit_image(), width=50, tooltip="Thu phóng để toàn bộ ảnh vừa vùng xem.").pack(side="left", padx=2, pady=5)
        self._button(zoom_panel, "⌾", lambda: self.canvas.center_image(), width=38, tooltip="Căn ảnh vào giữa nhưng giữ nguyên phần trăm zoom.").pack(side="left", padx=(2, 5), pady=5)

        right = ctk.CTkScrollableFrame(
            body,
            width=280,
            label_text="CHI TIẾT NHÃN",
            corner_radius=12,
            fg_color=COLORS["panel2"],
            border_width=1,
            border_color=COLORS["border"],
            label_fg_color=COLORS["panel2"],
            label_text_color=COLORS["accent"],
        )
        right.pack(side="right", fill="y", padx=(5, 0))
        self.image_status_frame = ctk.CTkFrame(
            right,
            corner_radius=12,
            fg_color="#243342",
            border_width=1,
            border_color="#3a5368",
        )
        self.image_status_frame.pack(fill="x", padx=12, pady=(2, 10))
        self.image_status_label = ctk.CTkLabel(
            self.image_status_frame,
            text="Ảnh: chưa chọn",
            fg_color="#243342",
            corner_radius=12,
            height=40,
            font=("Segoe UI Semibold", 12),
            text_color=COLORS["muted"],
        )
        self.image_status_label.pack(fill="x", padx=1, pady=1)
        ctk.CTkLabel(right, text="CLASS · chọn nhanh", text_color=COLORS["muted"]).pack(anchor="w", padx=12)
        self.class_search_var = tk.StringVar()
        self.class_search_var.trace_add("write", lambda *_args: self._refresh_label_choices())
        self.class_search_entry = ctk.CTkEntry(right, width=240, textvariable=self.class_search_var, placeholder_text="Tìm class…")
        self.class_search_entry.pack(padx=12, pady=(3, 5))
        self.class_choices = ctk.CTkFrame(right, width=240, fg_color="transparent")
        self.class_choices.pack(fill="x", padx=12, pady=(0, 10))
        self.class_buttons: dict[int, ctk.CTkButton] = {}

        self.show_attribute_checkbox = ctk.CTkCheckBox(
            right,
            text="Bật Classification thuộc tính",
            variable=self.show_attribute_panel,
            command=self._toggle_attribute_panel,
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=5,
            fg_color=COLORS["accent"],
            hover_color="#1aa7d7",
        )
        self.show_attribute_checkbox.pack(anchor="w", padx=12, pady=(2, 7))
        ToolTip(
            self.show_attribute_checkbox,
            "Tắt: train Detection/SEG/OBB/ORI để định vị vật. Bật: hiện thuộc tính và chuyển luồng Dataset/Train sang Classification hai giai đoạn.",
        )
        self.attribute_panel = ctk.CTkFrame(right, fg_color="#0f1c28", corner_radius=10)
        self.attribute_widgets: dict[str, ctk.CTkOptionMenu] = {}
        self.attribute_display_to_value: dict[str, dict[str, str]] = {}
        self._rebuild_attribute_panel()
        self._apply_attribute_panel_visibility()

        self.annotation_info = ctk.CTkTextbox(right, width=260, height=125, fg_color="#0a131c", corner_radius=9)
        self.annotation_info.pack(padx=12, pady=8)
        self.approve_switch = ctk.CTkSwitch(right, text="Nhãn đang chọn đã kiểm tra", command=self._toggle_annotation_approved)
        self.approve_switch.pack(anchor="w", padx=12, pady=6)
        ToolTip(
            self.approve_switch,
            "Đánh dấu riêng nhãn đang chọn đã được người kiểm tra. Trạng thái này được lưu; nút Duyệt ảnh sẽ đánh dấu toàn bộ nhãn trong ảnh.",
        )
        review_actions = ctk.CTkFrame(right, fg_color="transparent")
        review_actions.pack(fill="x", padx=12, pady=(12, 3))
        self.approve_image_button = self._button(review_actions, "Duyệt & tiếp", self._approve_image_next, width=112, color=COLORS["good"])
        self.approve_image_button.pack(side="left", padx=(0, 4))
        self.unapprove_image_button = self._button(review_actions, "Bỏ duyệt", self._unapprove_image, width=112, color="#8b6a2f")
        self.unapprove_image_button.pack(side="right", padx=(4, 0))
        reject_actions = ctk.CTkFrame(right, fg_color="transparent")
        reject_actions.pack(fill="x", padx=12, pady=3)
        self.reject_image_button = self._button(reject_actions, "Từ chối", self._reject_image, width=112, color="#a94747")
        self.reject_image_button.pack(side="left", padx=(0, 4))
        self.restore_image_button = self._button(reject_actions, "Khôi phục", self._restore_image, width=112, color="#415466")
        self.restore_image_button.pack(side="right", padx=(4, 0))
        ctk.CTkLabel(
            right,
            text="RECT: kéo 8 điểm để đổi kích thước · kéo trong hộp để di chuyển\n"
                 "SAM ON: chọn Class rồi bấm vật · SEG: double-click kết thúc polygon\n"
                 "Vùng trống: kéo ảnh · giữ Space/con lăn giữa để pan",
            justify="left", wraplength=240, text_color=COLORS["muted"],
        ).pack(anchor="w", padx=12, pady=14)

    def _geometry_changed(self, value: str) -> None:
        normalized = value.lower()
        if normalized not in {"rect", "seg", "obb", "ori"}:
            return
        self.annotation_geometry.set(value.upper())
        if hasattr(self, "canvas"):
            self.canvas.set_geometry_mode(normalized)
            self.canvas.set_mode("sam_click" if self.sam_click_enabled.get() else "select")
        self._save_app_settings()
        self._annotation_selected(self.selected_annotation_id)
        self._set_status(f"Hiển thị/chỉnh nhãn {value.upper()}")

    def _set_geometry_and_tool(self, geometry: str, tool: str) -> None:
        self.geometry_selector.set(geometry)
        self._geometry_changed(geometry)
        self._set_tool(tool)

    def _start_orientation(self) -> None:
        if not self._selected_annotation():
            messagebox.showinfo("Chưa chọn vật", "Hãy chọn một RECT/SEG/OBB trước, sau đó đặt hướng ORI.")
            return
        self.geometry_selector.set("ORI")
        self._geometry_changed("ORI")
        self.canvas.set_mode("orientation")
        self._set_status("ORI: bấm điểm chỉ về phía đầu/nắp của vật")

    def _convert_selected_to_obb(self) -> None:
        ann = self._selected_annotation()
        if not ann or len(ann.bbox) != 4:
            messagebox.showinfo("Chưa chọn vật", "Hãy chọn một nhãn RECT hoặc SEG trước.")
            return
        self.canvas.checkpoint()
        if len(ann.points) >= 3:
            import cv2
            import numpy as np
            rect = cv2.minAreaRect(np.asarray(ann.points, dtype=np.float32))
            ann.obb = [[float(x), float(y)] for x, y in cv2.boxPoints(rect)]
        else:
            x, y, w, h = ann.bbox
            ann.obb = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        ann.kind = "obb"
        ann.source = "manual"
        ann.confidence = None
        ann.approved = False
        self._annotation_changed()
        self.geometry_selector.set("OBB")
        self._geometry_changed("OBB")
        self.canvas.redraw()
        self._annotation_selected(ann.id)

    def _set_tool(self, tool: str) -> None:
        self.canvas.set_mode(tool)
        self._set_status(f"Công cụ: {tool}")

    def _toggle_sam_click(self) -> None:
        """Enable point-only SAM labeling without requiring a seed box."""
        if self.sam_click_enabled.get():
            checkpoint_value = self.sam_checkpoint.get().strip()
            checkpoint = Path(checkpoint_value) if checkpoint_value else None
            if checkpoint is None or not checkpoint.is_file() or checkpoint.suffix.lower() not in {".pt", ".pth"}:
                self.sam_click_enabled.set(False)
                messagebox.showinfo(
                    "Thiếu checkpoint SAM2",
                    "Hãy vào trang AUTO-LABEL, tải hoặc chọn đúng checkpoint SAM2 .pt/.pth rồi bật lại SAM ON.",
                )
                return
            self.canvas.clear_prompts()
            self.canvas.set_mode("sam_click")
            self._set_status("SAM ON · chọn Class rồi bấm một điểm vào vật")
        else:
            self.sam_click_request_version += 1
            self.sam_click_busy = False
            self.canvas.clear_prompts()
            self.canvas.set_mode("select")
            self._set_status("Đã tắt SAM ON")

    def _view_changed(self, scale: float) -> None:
        if hasattr(self, "zoom_percent_label"):
            self.zoom_percent_label.configure(text=f"{round(scale * 100)}%")

    def _change_image_filter(self, _value: str | None = None) -> None:
        self.image_page = 0
        self._refresh_image_list()

    def _change_image_page(self, delta: int) -> None:
        total_pages = max(1, (len(getattr(self, "filtered_images", [])) + self.image_page_size - 1) // self.image_page_size)
        target = min(max(self.image_page + delta, 0), total_pages - 1)
        if target == self.image_page:
            return
        self.image_page = target
        self._refresh_image_list()
        if self.project and self.paged_images:
            record = self.paged_images[0]
            self.current_index = self.project.images.index(record)
            self._load_current_image()

    def _refresh_image_list(self) -> None:
        self.filtered_images = []
        if not self.project:
            self.paged_images = []
            self.image_list.set_items([])
            if hasattr(self, "image_page_label"):
                self.image_page_label.configure(text="0 ảnh")
            return
        mapping = {"Chưa gán nhãn": "unlabeled", "Bản nháp": "draft", "Đã duyệt": "reviewed", "Từ chối": "rejected"}
        status = mapping.get(self.image_filter.get())
        for record in self.project.images:
            if status and record.review_status != status:
                continue
            self.filtered_images.append(record)
        total = len(self.filtered_images)
        total_pages = max(1, (total + self.image_page_size - 1) // self.image_page_size)
        self.image_page = min(max(self.image_page, 0), total_pages - 1)
        start = self.image_page * self.image_page_size
        end = min(start + self.image_page_size, total)
        self.paged_images = self.filtered_images[start:end]
        items = []
        for record in self.paged_images:
            display_name = record.file_name
            prefix, separator, remainder = display_name.partition("_")
            if separator and len(prefix) == 10 and all(char in "0123456789abcdef" for char in prefix.lower()):
                display_name = remainder
            items.append({
                "key": record.id,
                "name": record.file_name,
                "display_name": display_name,
                "path": self.store.image_path(self.project, record),
                "status": record.review_status,
                "count": len(record.annotations),
            })
        self.image_list.set_items(items)
        if hasattr(self, "image_page_label"):
            shown = f"{start + 1}–{end}" if total else "0"
            self.image_page_label.configure(text=f"{shown}/{total} · trang {self.image_page + 1}/{total_pages}")
            self._set_button_enabled(self.image_page_previous_button, self.image_page > 0)
            self._set_button_enabled(self.image_page_next_button, self.image_page + 1 < total_pages)

    def _on_thumbnail_selected(self, index: int) -> None:
        if not self.project or not (0 <= index < len(self.paged_images)):
            return
        record = self.paged_images[index]
        self.current_index = self.project.images.index(record)
        self._load_current_image()

    def _load_current_image(self) -> None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            return
        # A point-only SAM result must never land on an image selected later.
        self.sam_click_request_version += 1
        self.sam_click_busy = False
        record = self.project.images[self.current_index]
        self.canvas.load(self.project, record, str(self.store.image_path(self.project, record)))
        self.current_image_label.configure(
            text=f"{self.current_index + 1}/{len(self.project.images)}  ·  {record.file_name}  ·  {record.width}×{record.height}"
        )
        remembered = self.last_selected_by_image.get(record.id)
        selected_id = remembered if remembered and any(ann.id == remembered for ann in record.annotations) else (record.annotations[0].id if record.annotations else None)
        self.canvas.selected_id = selected_id
        self._annotation_selected(selected_id)
        if self.sam_click_enabled.get():
            self.canvas.set_mode("sam_click")
        self.canvas.redraw()
        self._sync_image_list_to_current(focus=True)
        self._update_image_status_controls()
        self._set_status(f"Ảnh {self.current_index + 1}/{len(self.project.images)} · {record.width}×{record.height}")

    def _sync_image_list_to_current(self, focus: bool = False) -> None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            return
        record = self.project.images[self.current_index]
        if record not in getattr(self, "filtered_images", []):
            self.image_filter.set("Tất cả")
            self.image_page = 0
            self._refresh_image_list()
        if record in self.filtered_images:
            filtered_index = self.filtered_images.index(record)
            target_page = filtered_index // self.image_page_size
            if target_page != self.image_page:
                self.image_page = target_page
                self._refresh_image_list()
            local_index = filtered_index - self.image_page * self.image_page_size
            self.image_list.select(local_index, focus=focus)

    def _previous_image(self) -> None:
        if self.project and self.project.images:
            self.current_index = (self.current_index - 1) % len(self.project.images)
            self._load_current_image()

    def _next_image(self) -> None:
        if self.project and self.project.images:
            self.current_index = (self.current_index + 1) % len(self.project.images)
            self._load_current_image()

    def _delete_image_from_thumbnail(self, image_id: object) -> None:
        if not self.project:
            return
        record = self.project.image_by_id(str(image_id))
        if record is None:
            return
        self.current_index = self.project.images.index(record)
        self._delete_current_image()

    def _delete_current_image(self) -> None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            messagebox.showinfo("Chưa chọn ảnh", "Hãy chọn một ảnh cần xóa trước.")
            return

        record = self.project.images[self.current_index]
        annotation_count = len(record.annotations)
        source_note = ""
        if record.source_path:
            source_note = "\n\nẢnh nguồn ban đầu sẽ không bị xóa."
        confirmed = messagebox.askyesno(
            "Xóa ảnh khỏi dự án",
            f"Xóa “{record.file_name}”?\n\n"
            f"Ảnh này có {annotation_count} nhãn. Toàn bộ tọa độ RECT/SEG/OBB/ORI, "
            "thuộc tính và trạng thái duyệt của ảnh sẽ bị xóa."
            f"{source_note}\n\nCác Dataset đã export trước đó là snapshot nên không bị thay đổi.\n"
            "Thao tác này không thể hoàn tác trong dự án.",
            parent=self,
        )
        if not confirmed:
            return

        old_global_index = self.current_index
        filtered = list(getattr(self, "filtered_images", []))
        filtered_index = filtered.index(record) if record in filtered else -1
        next_record = None
        if filtered_index >= 0 and len(filtered) > 1:
            next_record = filtered[min(filtered_index + 1, len(filtered) - 1)]
            if next_record is record:
                next_record = filtered[filtered_index - 1]

        try:
            removed_annotations = self.store.delete_image(self.project, record)
        except Exception as exc:
            messagebox.showerror("Không xóa được ảnh", str(exc), parent=self)
            return

        self.last_selected_by_image.pop(record.id, None)
        self.selected_annotation_id = None
        self.image_page = 0

        if self.project.images:
            if next_record in self.project.images:
                self.current_index = self.project.images.index(next_record)
            else:
                self.image_filter.set("Tất cả")
                self.current_index = min(old_global_index, len(self.project.images) - 1)
            self._refresh_image_list()
            self._load_current_image()
        else:
            self.current_index = -1
            self.filtered_images = []
            self.paged_images = []
            self._refresh_image_list()
            self.canvas.clear_image()
            self.current_image_label.configure(text="Chưa có ảnh trong dự án")
            self._annotation_selected(None)
            self.image_status_frame.configure(fg_color="#243342", border_color="#3a5368")
            self.image_status_label.configure(text="○  CHƯA CÓ ẢNH", text_color="#a7bac9", fg_color="#243342")
            for button in (
                self.approve_image_button,
                self.unapprove_image_button,
                self.reject_image_button,
                self.restore_image_button,
            ):
                self._set_button_enabled(button, False)

        self._set_status(
            f"Đã xóa 1 ảnh và {removed_annotations} nhãn liên quan · còn {len(self.project.images)} ảnh",
            COLORS["good"],
        )
        self._refresh_project_statistics()

    def _selected_annotation(self) -> Annotation | None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)) or not self.selected_annotation_id:
            return None
        return next((ann for ann in self.project.images[self.current_index].annotations if ann.id == self.selected_annotation_id), None)

    @staticmethod
    def _legacy_attribute_title(key: str) -> str:
        return {
            "condition": "Tình trạng",
            "occlusion": "Che khuất",
            "cap": "Nắp chai",
        }.get(key, key.replace("_", " ").strip().title())

    def _attribute_config(self, key: str) -> dict:
        if not self.project:
            return {"title": self._legacy_attribute_title(key), "default": "", "required": False, "role": "metadata"}
        saved = self.project.attribute_settings.get(key, {})
        values = self.project.attribute_schema.get(key, [])
        default = str(saved.get("default", ""))
        return {
            "title": str(saved.get("title") or self._legacy_attribute_title(key)),
            "default": default if default in values else "",
            "required": bool(saved.get("required", False)),
            "role": str(saved.get("role", "metadata")),
        }

    def _attribute_defaults(self) -> dict[str, str]:
        if not self.project:
            return {}
        defaults = {}
        for key in self.project.attribute_schema:
            value = self._attribute_config(key)["default"]
            if value:
                defaults[key] = value
        return defaults

    def _rebuild_attribute_panel(self) -> None:
        if not hasattr(self, "attribute_panel"):
            return
        for child in self.attribute_panel.winfo_children():
            child.destroy()
        self.attribute_widgets = {}
        self.attribute_display_to_value = {}
        if not self.project or not self.project.attribute_schema:
            ctk.CTkLabel(
                self.attribute_panel,
                text="Chưa có nhóm thuộc tính.\nTạo tại Dự án → Quản lý Class & thuộc tính.",
                justify="left",
                wraplength=220,
                text_color=COLORS["muted"],
            ).pack(anchor="w", padx=10, pady=10)
            return
        role_names = {
            "metadata": "Metadata",
            "classification": "Classification hai giai đoạn",
            "pass_fail": "Điều kiện OK/NG",
        }
        for key, raw_values in self.project.attribute_schema.items():
            config = self._attribute_config(key)
            heading = f"{config['title'].upper()}{'  *' if config['required'] else ''}"
            ctk.CTkLabel(self.attribute_panel, text=heading, text_color=COLORS["muted"]).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(
                self.attribute_panel,
                text=role_names.get(config["role"], config["role"]),
                text_color="#61798d",
                font=("Segoe UI", 9),
            ).pack(anchor="w", padx=10, pady=(0, 2))
            display_values = [ATTRIBUTE_DISPLAY.get(key, {}).get(value, value) for value in raw_values]
            choices = ["— Chưa gán —", *display_values]
            self.attribute_display_to_value[key] = {
                **dict(zip(display_values, raw_values)),
                "— Chưa gán —": "",
            }
            widget = ctk.CTkOptionMenu(
                self.attribute_panel,
                width=220,
                values=choices,
                command=lambda value, attr=key: self._attribute_changed(attr, value),
            )
            widget.set("— Chưa gán —")
            widget.pack(fill="x", padx=10, pady=(1, 7))
            self.attribute_widgets[key] = widget
        if hasattr(self, "canvas"):
            self.canvas.set_default_attributes(self._attribute_defaults())

    def _apply_attribute_panel_visibility(self) -> None:
        if not hasattr(self, "attribute_panel"):
            return
        if self.show_attribute_panel.get():
            if not self.attribute_panel.winfo_manager():
                pack_options = {"fill": "x", "padx": 12, "pady": (0, 8)}
                # Re-packing a hidden widget normally sends it to the bottom.
                # Keep attributes directly below the Classification switch.
                if hasattr(self, "annotation_info"):
                    pack_options["before"] = self.annotation_info
                self.attribute_panel.pack(**pack_options)
        else:
            self.attribute_panel.pack_forget()

    def _toggle_attribute_panel(self) -> None:
        if self.project:
            self.project.attribute_classification_enabled = bool(self.show_attribute_panel.get())
            self.store.save(self.project)
        if hasattr(self, "train_task_menu"):
            if self.show_attribute_panel.get():
                current_task = self.train_task_menu.get()
                if current_task in {"detect", "segment", "obb", "pose"}:
                    self.last_localization_task = current_task
                self.train_task_menu.set("classify")
            elif self.train_task_menu.get() == "classify":
                self.train_task_menu.set(self.last_localization_task)
        if hasattr(self, "classification_mode_label"):
            self._refresh_classification_controls()
        self._apply_attribute_panel_visibility()
        self._annotation_selected(self.selected_annotation_id)
        mode = "Classification thuộc tính" if self.show_attribute_panel.get() else "Định vị bình thường cho Radxa"
        self._set_status(f"Chế độ: {mode}")

    def _refresh_classification_controls(self) -> None:
        self.classification_group_lookup = {}
        labels = []
        if self.project:
            ordered_keys = sorted(
                self.project.attribute_schema,
                key=lambda key: self._attribute_config(key)["role"] != "classification",
            )
            for key in ordered_keys:
                config = self._attribute_config(key)
                suffix = " · Classification" if config["role"] == "classification" else ""
                label = f"{config['title']} · {key}{suffix}"
                labels.append(label)
                self.classification_group_lookup[label] = key
        if not labels:
            labels = ["Chưa có nhóm thuộc tính"]
        current = self.classification_group_var.get()
        if current not in labels:
            self.classification_group_var.set(labels[0])
        for name in ("dataset_classification_group_menu", "train_classification_group_menu"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(values=labels)
        self._rebuild_batch_group_choices()
        enabled = bool(self.project and self.project.attribute_classification_enabled)
        if hasattr(self, "train_task_menu"):
            if enabled:
                self.train_task_menu.configure(values=["classify"])
                self.train_task_menu.set("classify")
            else:
                self.train_task_menu.configure(values=["detect", "segment", "obb", "pose"])
                if self.train_task_menu.get() == "classify":
                    self.train_task_menu.set(self.last_localization_task or "detect")
        if hasattr(self, "classification_mode_label"):
            if enabled:
                self.classification_mode_label.configure(
                    text="ĐANG BẬT · các nhóm tick bên dưới dùng chung cho Dataset, Train và xuất RKNN.",
                    text_color=COLORS["warn"],
                )
            else:
                self.classification_mode_label.configure(
                    text="ĐANG TẮT · train model định vị bình thường để xuất RKNN cho Radxa.",
                    text_color=COLORS["good"],
                )
        self._apply_classification_mode_visibility(enabled)

    def _apply_classification_mode_visibility(self, enabled: bool) -> None:
        dataset_section = getattr(self, "dataset_classification_section", None)
        if dataset_section is not None:
            if enabled and not dataset_section.winfo_manager():
                options = {"fill": "x", "padx": 10, "pady": (10, 5)}
                if hasattr(self, "dataset_coco_button"):
                    options["before"] = self.dataset_coco_button
                dataset_section.pack(**options)
            elif not enabled:
                dataset_section.pack_forget()

        train_section = getattr(self, "train_classification_section", None)
        if train_section is not None:
            if enabled and not train_section.winfo_manager():
                options = {"fill": "x", "padx": 14, "pady": (5, 4)}
                if hasattr(self, "task_model_button"):
                    options["before"] = self.task_model_button
                train_section.pack(**options)
            elif not enabled:
                train_section.pack_forget()

        start_button = getattr(self, "train_start_button", None)
        if start_button is not None:
            start_button.configure(
                text="TRAIN CÁC NHÓM ĐÃ TICK" if enabled else "BẮT ĐẦU TRAIN",
                fg_color="#7655b5" if enabled else COLORS["good"],
                hover_color="#6646a4" if enabled else "#35b66c",
            )

        help_label = getattr(self, "deploy_help_label", None)
        if help_label is not None:
            help_label.configure(
                text=(
                    "Xuất lần lượt các classifier đã tick sang RKNN, sau đó tạo gói triển khai cùng model định vị."
                    if enabled
                    else "Xuất model Detection/SEG định vị để nạp vào Vision AI Setting hiện tại."
                )
            )

        source_row = getattr(self, "deploy_source_row", None)
        single_export = getattr(self, "deploy_export_button", None)
        batch_export = getattr(self, "batch_rknn_export_button", None)
        bundle_export = getattr(self, "bundle_export_button", None)
        stop_button = getattr(self, "deploy_stop_button", None)
        if source_row is not None:
            if enabled:
                source_row.pack_forget()
            elif not source_row.winfo_manager():
                source_row.pack(fill="x", padx=14, pady=3, before=self.deploy_action_row)
        if single_export is not None:
            if enabled:
                single_export.pack_forget()
            elif not single_export.winfo_manager():
                single_export.pack(side="left", padx=3, before=stop_button)
        for button in (batch_export, bundle_export):
            if button is None:
                continue
            if enabled and not button.winfo_manager():
                button.pack(side="left", padx=3, before=stop_button)
            elif not enabled:
                button.pack_forget()

    def _rebuild_batch_group_choices(self) -> None:
        frames = [
            frame
            for frame in (
                getattr(self, "dataset_classification_multi_frame", None),
                getattr(self, "train_classification_multi_frame", None),
            )
            if frame is not None
        ]
        if not frames:
            return
        previous = {key: variable.get() for key, variable in self.classification_batch_vars.items()}
        for frame in frames:
            for child in frame.winfo_children():
                child.destroy()
        self.classification_batch_vars = {}
        if not self.project or not self.project.attribute_schema:
            for frame in frames:
                ctk.CTkLabel(frame, text="Chưa có nhóm thuộc tính", text_color=COLORS["muted"]).pack(
                    anchor="w", padx=10, pady=8
                )
            return
        for key in self.project.attribute_schema:
            config = self._attribute_config(key)
            variable = tk.BooleanVar(value=previous.get(key, config["role"] == "classification"))
            self.classification_batch_vars[key] = variable
            suffix = " · Classification" if config["role"] == "classification" else ""
            for frame in frames:
                checkbox = ctk.CTkCheckBox(
                    frame,
                    text=f"{config['title']}{suffix}",
                    variable=variable,
                    command=lambda attr=key: self._classification_group_checked(attr),
                    checkbox_width=19,
                    checkbox_height=19,
                    corner_radius=5,
                    fg_color=COLORS["accent"],
                    hover_color="#1aa7d7",
                )
                checkbox.pack(anchor="w", padx=10, pady=5)
                ToolTip(checkbox, f"Dùng cùng lựa chọn này tại Dataset, Train và xuất RKNN cho nhóm {config['title']}.")

    def _classification_group_checked(self, key: str) -> None:
        if self.classification_batch_vars.get(key) and self.classification_batch_vars[key].get():
            for label, mapped_key in self.classification_group_lookup.items():
                if mapped_key == key:
                    self.classification_group_var.set(label)
                    break

    def _set_batch_group_selection(self, selected: bool) -> None:
        for variable in self.classification_batch_vars.values():
            variable.set(selected)

    def _selected_batch_classification_keys(self) -> list[str]:
        if not self.project:
            return []
        return [
            key
            for key in self.project.attribute_schema
            if key in self.classification_batch_vars and self.classification_batch_vars[key].get()
        ]

    def _missing_required_attributes(self, record) -> list[str]:
        if not self.project:
            return []
        missing = []
        for index, ann in enumerate(record.annotations, start=1):
            for key, values in self.project.attribute_schema.items():
                config = self._attribute_config(key)
                if config["required"] and ann.attributes.get(key) not in values:
                    missing.append(f"Nhãn {index}: {config['title']}")
        return missing

    def _annotation_selected(self, annotation_id: str | None) -> None:
        self.selected_annotation_id = annotation_id
        if annotation_id and self.project and 0 <= self.current_index < len(self.project.images):
            self.last_selected_by_image[self.project.images[self.current_index].id] = annotation_id
        ann = self._selected_annotation()
        self.annotation_info.configure(state="normal")
        self.annotation_info.delete("1.0", tk.END)
        if ann and self.project:
            class_info = self.project.class_by_id(ann.class_id)
            self._highlight_class(ann.class_id)
            for key, widget in self.attribute_widgets.items():
                values = self.project.attribute_schema.get(key, [])
                value = ann.attributes.get(key, "")
                if value in values:
                    widget.set(ATTRIBUTE_DISPLAY.get(key, {}).get(value, value))
                else:
                    widget.set("— Chưa gán —")
            if ann.approved:
                self.approve_switch.select()
            else:
                self.approve_switch.deselect()
            self.approve_switch.configure(state="normal")
            available = ["RECT"]
            if len(ann.points) >= 3:
                available.append("SEG")
            if len(ann.obb) == 4:
                available.append("OBB")
            if len(ann.orientation) == 2:
                available.append("ORI")
            self.annotation_info.insert("1.0", f"ID: {ann.id}\nNguồn: {ann.source}\nConfidence: {ann.confidence if ann.confidence is not None else '-'}\nCó dữ liệu: {' · '.join(available)}\nBox: {[round(v, 1) for v in ann.bbox]}")
            self._set_button_enabled(self.to_rect_button, bool(ann.points))
            self._set_button_enabled(self.to_obb_button, True)
            self._set_button_enabled(self.orientation_button, True)
        else:
            for widget in getattr(self, "attribute_widgets", {}).values():
                widget.set("— Chưa gán —")
            self.approve_switch.deselect()
            self.approve_switch.configure(state="disabled")
            self._highlight_class(self.canvas.active_class_id if hasattr(self, "canvas") else -1)
            self.annotation_info.insert("1.0", "Chọn một nhãn để xem và sửa.")
            self._set_button_enabled(self.to_rect_button, False)
            self._set_button_enabled(self.to_obb_button, False)
            self._set_button_enabled(self.orientation_button, False)
        self.annotation_info.configure(state="disabled")

    def _annotation_changed(self) -> None:
        record = None
        if self.project and 0 <= self.current_index < len(self.project.images):
            record = self.project.images[self.current_index]
            if record.review_status == "reviewed":
                record.review_status = "draft"
        self.save_project()
        if record is not None:
            self._update_record_thumbnail(record)
        self._sync_image_list_to_current()
        self._update_image_status_controls()

    def _delete_annotation(self) -> None:
        self.canvas.delete_selected()

    def _convert_selected_to_bbox(self) -> None:
        """Discard a selected SEG outline while preserving its original RECT."""
        ann = self._selected_annotation()
        if not ann:
            messagebox.showinfo("Chưa chọn nhãn", "Hãy chọn một nhãn SEG trước.")
            return
        if not ann.points:
            messagebox.showinfo("Nhãn đang là RECT", "Nhãn đang chọn đã là bounding box RECT.")
            return
        self.canvas.checkpoint()
        ann.kind = "bbox"
        ann.points = []
        ann.source = "manual"
        ann.confidence = None
        ann.approved = False
        self.canvas.clear_prompts()
        self._annotation_changed()
        self.geometry_selector.set("RECT")
        self._geometry_changed("RECT")
        self.canvas.redraw()
        self._annotation_selected(ann.id)

    def _class_changed(self, class_id: int) -> None:
        if not self.project:
            return
        self.canvas.active_class_id = class_id
        self._highlight_class(class_id)
        ann = self._selected_annotation()
        if ann:
            self.canvas.checkpoint()
            ann.class_id = class_id
            ann.source = "manual"
            ann.confidence = None
            ann.approved = False
            self._annotation_changed()
            self.canvas.redraw()

    def _refresh_label_choices(self) -> None:
        if not self.project or not hasattr(self, "class_choices"):
            return
        for child in self.class_choices.winfo_children():
            child.destroy()
        self.class_buttons = {}
        query = self.class_search_var.get().strip().lower()
        items = [item for item in sorted(self.project.classes, key=lambda item: item.id) if not query or query in item.name.lower() or query == str(item.id)]
        if not items:
            ctk.CTkLabel(self.class_choices, text="Không tìm thấy Class", text_color=COLORS["muted"]).pack(anchor="w")
        for item in items:
            button = ctk.CTkButton(
                self.class_choices,
                text=f"●  {item.id}: {item.name}",
                anchor="w",
                height=30,
                corner_radius=7,
                fg_color="#0c1721",
                hover_color="#21374a",
                text_color=item.color,
                command=lambda class_id=item.id: self._class_changed(class_id),
            )
            button.pack(fill="x", pady=2)
            ToolTip(button, f"Chọn Class {item.name} cho nhãn đang chọn hoặc nhãn sẽ vẽ tiếp theo.")
            self.class_buttons[item.id] = button
        ann = self._selected_annotation()
        self._highlight_class(ann.class_id if ann else self.canvas.active_class_id)

    def _highlight_class(self, class_id: int) -> None:
        for item_id, button in getattr(self, "class_buttons", {}).items():
            button.configure(fg_color="#23475c" if item_id == class_id else "#0c1721")

    def _attribute_changed(self, key: str, value: str) -> None:
        value = getattr(self, "attribute_display_to_value", {}).get(key, {}).get(value, value)
        ann = self._selected_annotation()
        if ann:
            self.canvas.checkpoint()
            if value:
                ann.attributes[key] = value
            else:
                ann.attributes.pop(key, None)
            ann.source = "manual" if ann.source != "manual" else ann.source
            ann.confidence = None if ann.source == "manual" else ann.confidence
            ann.approved = False
            self._annotation_changed()

    def _toggle_annotation_approved(self) -> None:
        ann = self._selected_annotation()
        if ann:
            if self.approve_switch.get() and self.project:
                missing = []
                for key, values in self.project.attribute_schema.items():
                    config = self._attribute_config(key)
                    if config["required"] and ann.attributes.get(key) not in values:
                        missing.append(config["title"])
                if missing:
                    self.approve_switch.deselect()
                    messagebox.showwarning(
                        "Thiếu thuộc tính bắt buộc",
                        "Nhãn chưa thể được xác nhận vì còn thiếu: " + ", ".join(missing),
                    )
                    return
            self.canvas.checkpoint()
            ann.approved = bool(self.approve_switch.get())
            self._annotation_changed()

    def _approve_image_next(self) -> None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            return
        record = self.project.images[self.current_index]
        missing = self._missing_required_attributes(record)
        if missing:
            preview = "\n".join(f"• {item}" for item in missing[:12])
            if len(missing) > 12:
                preview += f"\n• … và {len(missing) - 12} mục khác"
            messagebox.showwarning(
                "Thiếu thuộc tính bắt buộc",
                "Chưa thể duyệt ảnh vì một số nhãn thiếu thuộc tính:\n\n" + preview,
            )
            return
        for ann in record.annotations:
            ann.approved = True
        record.review_status = "reviewed"
        self.save_project()
        self._update_record_thumbnail(record)
        self._next_image()

    def _unapprove_image(self) -> None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            return
        record = self.project.images[self.current_index]
        for ann in record.annotations:
            ann.approved = False
        record.review_status = "draft" if record.annotations else "unlabeled"
        self.save_project()
        self._update_record_thumbnail(record)
        self._sync_image_list_to_current()
        self._annotation_selected(self.selected_annotation_id)
        self._update_image_status_controls()

    def _reject_image(self) -> None:
        if self.project and 0 <= self.current_index < len(self.project.images):
            record = self.project.images[self.current_index]
            record.review_status = "rejected"
            self.save_project()
            self._update_record_thumbnail(record)
            self._sync_image_list_to_current()
            self._update_image_status_controls()

    def _restore_image(self) -> None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            return
        record = self.project.images[self.current_index]
        record.review_status = "reviewed" if record.annotations and all(ann.approved for ann in record.annotations) else ("draft" if record.annotations else "unlabeled")
        self.save_project()
        self._update_record_thumbnail(record)
        self._sync_image_list_to_current()
        self._update_image_status_controls()

    def _update_image_status_controls(self) -> None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            return
        status = self.project.images[self.current_index].review_status
        labels = {
            "unlabeled": ("○  CHƯA GÁN NHÃN", "#a7bac9", "#243342", "#3a5368"),
            "draft": ("●  BẢN NHÁP · CẦN KIỂM TRA", "#ffd080", "#40351f", "#6b572d"),
            "reviewed": ("✓  ĐÃ DUYỆT", "#69e0a0", "#19372c", "#2d684f"),
            "rejected": ("×  ĐÃ TỪ CHỐI", "#ff8f96", "#402427", "#733b42"),
        }
        text, color, background, border = labels.get(status, (status, COLORS["muted"], "#243342", "#3a5368"))
        self.image_status_frame.configure(fg_color=background, border_color=border)
        self.image_status_label.configure(text=text, text_color=color, fg_color=background)
        self._set_button_enabled(self.approve_image_button, status != "reviewed")
        self._set_button_enabled(self.unapprove_image_button, status == "reviewed")
        self._set_button_enabled(self.reject_image_button, status != "rejected")
        self._set_button_enabled(self.restore_image_button, status == "rejected")

    def _update_record_thumbnail(self, record) -> None:
        """Update one visible row; only reconcile rows when filter membership changes."""
        filter_status = {"Chưa gán nhãn": "unlabeled", "Bản nháp": "draft", "Đã duyệt": "reviewed", "Từ chối": "rejected"}.get(self.image_filter.get())
        belongs = filter_status is None or record.review_status == filter_status
        was_filtered = record in getattr(self, "filtered_images", [])
        if belongs != was_filtered:
            self._refresh_image_list()
        elif record in getattr(self, "paged_images", []):
            index = self.paged_images.index(record)
            self.image_list.update_item(index, status=record.review_status, count=len(record.annotations))
        self._refresh_project_statistics()

    # ---------- auto label ----------
    def _build_auto_tab(self) -> None:
        tab = self.tabs.tab("AUTO-LABEL")
        settings = self._card(tab, "MODEL PHÁT HIỆN")
        settings.pack(side="left", fill="y", padx=(8, 5), pady=8)
        self.model_entry = ctk.CTkEntry(settings, width=330, textvariable=self.model_path)
        self.model_entry.pack(padx=14, pady=5)
        self.active_model_status_label = ctk.CTkLabel(
            settings,
            text="Chưa có model Auto-Label đang hoạt động",
            width=320,
            wraplength=315,
            justify="left",
            anchor="w",
            text_color=COLORS["muted"],
            font=("Segoe UI Semibold", 10),
        )
        self.active_model_status_label.pack(anchor="w", padx=14, pady=(0, 4))
        self._button(
            settings,
            "Chọn model PC · .pt / .onnx",
            self._choose_model,
            width=330,
            tooltip="Chọn model chạy Auto-Label trên PC. RKNN dành cho NPU Rockchip/Radxa nên không chọn tại đây.",
        ).pack(padx=14, pady=5)
        ctk.CTkLabel(
            settings,
            text=".pt/.onnx: Auto-Label trên PC  ·  .rknn: triển khai trên Radxa",
            wraplength=320,
            justify="left",
            text_color="#8fa6b8",
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=14, pady=(0, 4))
        ctk.CTkLabel(settings, text="Thiết bị", text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=(12, 2))
        self.device_menu = ctk.CTkOptionMenu(settings, width=330, values=["auto", "cpu", "cuda"])
        self.device_menu.pack(padx=14, pady=4)
        ctk.CTkLabel(settings, text="Confidence", text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=(12, 2))
        self.confidence_slider = ctk.CTkSlider(settings, from_=0.05, to=0.95, number_of_steps=90, command=self._confidence_changed)
        self.confidence_slider.set(0.25)
        self.confidence_slider.pack(padx=14, pady=4)
        self.confidence_label = ctk.CTkLabel(settings, text="0.25")
        self.confidence_label.pack()
        self.unlabeled_switch = ctk.CTkSwitch(settings, text="Chỉ ảnh chưa có nhãn")
        self.unlabeled_switch.select()
        self.unlabeled_switch.pack(anchor="w", padx=14, pady=(14, 4))
        self.replace_switch = ctk.CTkSwitch(settings, text="Thay dự đoán AI cũ")
        self.replace_switch.select()
        self.replace_switch.pack(anchor="w", padx=14, pady=4)
        self._button(settings, "CHẠY AUTO-LABEL", self._start_auto_label, width=330, color=COLORS["good"]).pack(padx=14, pady=(18, 5))
        self._button(settings, "Dừng", self._stop_auto_label, width=330, color="#a94747").pack(padx=14, pady=5)

        sam = self._card(tab, "SAM2 · BOX → MASK")
        sam.pack(side="left", fill="y", padx=5, pady=8)
        ctk.CTkLabel(sam, text="Checkpoint SAM2 / SAM2.1", text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=(4, 2))
        ctk.CTkEntry(sam, width=300, textvariable=self.sam_checkpoint).pack(padx=14, pady=4)
        self._button(sam, "Chọn checkpoint", self._choose_sam_checkpoint, width=300).pack(padx=14, pady=4)
        self._button(sam, "Tải SAM2 Small tương thích", self._download_sam2_small, width=300, color="#2b906d", tooltip="Tải checkpoint SAM2 Hiera Small chính thức của Meta vào workspace; file khá lớn.").pack(padx=14, pady=4)
        ctk.CTkLabel(sam, text="Config tìm thấy trong package", text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=(10, 2))
        available_configs = Sam2Adapter.available_configs()
        self.sam_config_menu = ctk.CTkOptionMenu(
            sam,
            width=300,
            variable=self.sam_config,
            values=available_configs or ["Chưa cài SAM2"],
            command=self._sam_config_changed,
        )
        self.sam_config_menu.pack(padx=14, pady=4)
        self._button(sam, "Kiểm tra cấu hình SAM2", self._diagnose_sam2, width=300, color="#415466").pack(padx=14, pady=4)
        self.sam_status_label = ctk.CTkLabel(sam, text="", width=300, wraplength=285, justify="left", text_color=COLORS["muted"])
        self.sam_status_label.pack(anchor="w", padx=14, pady=4)
        ctk.CTkLabel(
            sam,
            text="Dự án mới chưa có model:\n1. Chọn checkpoint SAM2.\n2. Qua GÁN NHÃN, chọn Class và RECT/SEG/OBB.\n3. Bật SAM ON rồi bấm một điểm lên từng vật.\n\nTinh chỉnh nhãn có sẵn:\nChọn nhãn → SAM2 → SEG → dùng SAM +/−.\nORI cần bấm thêm hướng đầu/nắp.\n\nCPU vẫn chạy được nhưng chậm. RTX 4060 Ti\nsẽ dùng CUDA khi PyTorch CUDA sẵn sàng.",
            width=300,
            wraplength=285,
            justify="left",
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=14, pady=12)

        content = self._card(tab, "TIẾN TRÌNH")
        content.pack(side="left", fill="both", expand=True, padx=(5, 8), pady=8)
        self.auto_progress = ctk.CTkProgressBar(content)
        self.auto_progress.set(0)
        self.auto_progress.pack(fill="x", padx=14, pady=8)
        self.auto_log = ctk.CTkTextbox(content, fg_color="#091119", font=("Consolas", 12), corner_radius=10)
        self.auto_log.pack(fill="both", expand=True, padx=14, pady=(4, 14))

    def _choose_model(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn model Auto-Label chạy trên PC",
            filetypes=[
                ("Model PC được hỗ trợ", "*.pt *.onnx"),
                ("PyTorch model", "*.pt"),
                ("ONNX model", "*.onnx"),
            ],
        )
        if path:
            registered = self.store.register_model(path)
            self.model_path.set(str(registered))
            if self.project:
                self.project.active_model = str(registered)
                self.save_project()
                self._refresh_active_model_status()

    def _refresh_active_model_status(self) -> None:
        if not hasattr(self, "active_model_status_label"):
            return
        path = Path(self.project.active_model) if self.project and self.project.active_model else None
        if path and path.is_file():
            updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            self.active_model_status_label.configure(
                text=f"✓ ĐANG DÙNG: {path.name}\nCập nhật: {updated}",
                text_color=COLORS["good"],
            )
        else:
            self.active_model_status_label.configure(
                text="Chưa có model Auto-Label đang hoạt động",
                text_color=COLORS["bad"],
            )

    def _choose_sam_checkpoint(self) -> None:
        path = filedialog.askopenfilename(title="Chọn SAM2 checkpoint", filetypes=[("Checkpoint", "*.pt *.pth")])
        if path:
            self.sam_checkpoint.set(path)
            self.sam_adapter = None
            checkpoint_name = Path(path).name.lower()
            configs = Sam2Adapter.available_configs()
            size_tokens = ("hiera_s", "hiera_t", "hiera_l", "hiera_b+")
            token = next((value for value in size_tokens if value in checkpoint_name), None)
            matches = [value for value in configs if token and token in value]
            if "sam2.1" in checkpoint_name:
                matches = [value for value in matches if "sam2.1" in value]
            if matches:
                self.sam_config.set(matches[0])
            self._save_app_settings()
            self._diagnose_sam2()

    def _download_sam2_small(self) -> None:
        target = self.store.models_dir / "sam2_hiera_small.pt"
        if target.is_file():
            self.sam_checkpoint.set(str(target))
            if "sam2_hiera_s.yaml" in Sam2Adapter.available_configs():
                self.sam_config.set("sam2_hiera_s.yaml")
            self._save_app_settings()
            self._diagnose_sam2()
            return
        if not messagebox.askyesno("Tải checkpoint SAM2", "Checkpoint SAM2 Small khoảng 176 MB. Tải từ máy chủ chính thức của Meta vào workspace?", parent=self):
            return
        self.sam_status_label.configure(text="Đang tải checkpoint SAM2…", text_color=COLORS["warn"])
        def worker():
            import urllib.request
            temp = target.with_suffix(".pt.download")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(SAM2_SMALL_URL, timeout=30) as response, temp.open("wb") as output:
                    total = int(response.headers.get("Content-Length", 0))
                    received = 0
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        received += len(block)
                        self.event_queue.put(("sam_download_progress", (received, total)))
                if temp.stat().st_size < 10 * 1024 * 1024:
                    raise RuntimeError("File checkpoint tải về quá nhỏ hoặc không hợp lệ.")
                temp.replace(target)
                self.event_queue.put(("sam_download_done", str(target)))
            except Exception as exc:
                if temp.exists():
                    temp.unlink()
                self.event_queue.put(("error", f"Tải SAM2 thất bại: {exc}"))
        Thread(target=worker, daemon=True).start()

    def _sam_config_changed(self, _value: str) -> None:
        self.sam_adapter = None
        self._save_app_settings()
        self._diagnose_sam2()

    def _diagnose_sam2(self) -> None:
        configs = Sam2Adapter.available_configs()
        checkpoint_value = self.sam_checkpoint.get().strip()
        checkpoint = Path(checkpoint_value) if checkpoint_value else None
        if not configs:
            text, color = "Chưa cài package SAM2.", COLORS["bad"]
        elif checkpoint is None or not checkpoint.is_file() or checkpoint.suffix.lower() not in {".pt", ".pth"}:
            text, color = f"Đã tìm thấy {len(configs)} config; hãy chọn đúng file checkpoint .pt/.pth.", COLORS["warn"]
        else:
            try:
                resolved = Sam2Adapter.resolve_config(self.sam_config.get(), checkpoint)
                text, color = f"Sẵn sàng · {resolved}", COLORS["good"]
            except Exception as exc:
                text, color = str(exc), COLORS["bad"]
        if hasattr(self, "sam_status_label"):
            self.sam_status_label.configure(text=text, text_color=color)

    def _sam_refine_selected(self) -> None:
        self._run_sam_refine(use_prompts=False)

    def _sam_prompt_added(self, _x: float, _y: float, _label: int) -> None:
        if self.canvas.mode == "sam_click":
            self._run_sam_click_create(_x, _y)
        else:
            self._run_sam_refine(use_prompts=True)

    def _annotation_at_point(self, x: float, y: float) -> Annotation | None:
        if not self.project or not (0 <= self.current_index < len(self.project.images)):
            return None
        candidates = []
        for ann in self.project.images[self.current_index].annotations:
            if len(ann.bbox) != 4:
                continue
            bx, by, width, height = ann.bbox
            if bx <= x <= bx + width and by <= y <= by + height:
                candidates.append((width * height, ann))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def _run_sam_click_create(self, x: float, y: float) -> None:
        """Use one positive point to create the first annotation in a project."""
        if not self.sam_click_enabled.get() or not self.project or self.current_index < 0:
            return
        if self.sam_click_busy:
            self.canvas.clear_prompts()
            self._set_status("SAM2 đang xử lý điểm trước · vui lòng chờ")
            return

        existing = self._annotation_at_point(x, y)
        if existing is not None:
            self.canvas.clear_prompts()
            self.canvas.selected_id = existing.id
            self._annotation_selected(existing.id)
            self.canvas.redraw()
            self._set_status("Vật này đã có nhãn · đã chọn nhãn để tránh tạo trùng")
            return

        checkpoint_value = self.sam_checkpoint.get().strip()
        checkpoint = Path(checkpoint_value) if checkpoint_value else None
        if checkpoint is None or not checkpoint.is_file() or checkpoint.suffix.lower() not in {".pt", ".pth"}:
            self.sam_click_enabled.set(False)
            self._toggle_sam_click()
            return

        record = self.project.images[self.current_index]
        image_path = self.store.image_path(self.project, record)
        image_id = record.id
        class_id = int(self.canvas.active_class_id)
        geometry = self.annotation_geometry.get().strip().lower()
        default_attributes = dict(self.canvas.default_attributes)
        self.sam_click_request_version += 1
        request_version = self.sam_click_request_version
        self.sam_click_busy = True
        self._set_status("SAM2 đang phân tích điểm đã chọn…")

        def worker():
            try:
                import cv2

                image = cv2.imread(str(image_path))
                if image is None:
                    raise RuntimeError(f"Không đọc được ảnh: {image_path.name}")
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                with self.sam_lock:
                    if self.sam_adapter is None:
                        self.sam_adapter = Sam2Adapter(checkpoint, self.sam_config.get(), device="auto")
                    self.sam_adapter.set_image(rgb, str(image_path))
                    mask, score = self.sam_adapter.mask_from_points([[x, y]], [1])
                geometry_data = mask_to_geometry(mask, anchor_point=(x, y))
                self.event_queue.put((
                    "sam_click_done",
                    (image_id, request_version, class_id, geometry, default_attributes, geometry_data, score),
                ))
            except Exception as exc:
                self.event_queue.put(("sam_click_error", (request_version, str(exc))))

        Thread(target=worker, daemon=True).start()

    def _run_sam_refine(self, use_prompts: bool) -> None:
        ann = self._selected_annotation()
        if not ann or len(ann.bbox) != 4 or not self.project or self.current_index < 0:
            messagebox.showwarning("Chưa chọn box", "Hãy chọn một bounding box trước.")
            return
        checkpoint_value = self.sam_checkpoint.get().strip()
        checkpoint = Path(checkpoint_value) if checkpoint_value else None
        if checkpoint is None or not checkpoint.is_file() or checkpoint.suffix.lower() not in {".pt", ".pth"}:
            messagebox.showinfo("Thiếu checkpoint SAM2", "Hãy vào trang AUTO-LABEL và chọn đúng một file checkpoint .pt hoặc .pth. Không chọn thư mục và không để trống.")
            return
        record = self.project.images[self.current_index]
        image_path = self.store.image_path(self.project, record)
        ann_id = ann.id
        request_version = self.sam_request_versions.get(ann_id, 0) + 1
        self.sam_request_versions[ann_id] = request_version
        bbox = list(ann.bbox)
        prompt_snapshot = list(self.canvas.prompt_points)
        self._set_status("SAM2 đang tạo mask…")
        def worker():
            try:
                import cv2
                rgb = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
                with self.sam_lock:
                    if self.sam_adapter is None:
                        self.sam_adapter = Sam2Adapter(checkpoint, self.sam_config.get(), device="auto")
                    self.sam_adapter.set_image(rgb, str(image_path))
                    x, y, w, h = bbox
                    if use_prompts and prompt_snapshot:
                        prompts = [[px, py] for px, py, _ in prompt_snapshot]
                        labels = [label for _, _, label in prompt_snapshot]
                        mask, score = self.sam_adapter.mask_from_prompts([x, y, x + w, y + h], prompts, labels)
                    else:
                        mask, score = self.sam_adapter.mask_from_box([x, y, x + w, y + h])
                binary = (mask.astype("uint8") * 255)
                contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not contours:
                    raise RuntimeError("SAM2 không tạo được contour")
                contour = max(contours, key=cv2.contourArea)
                epsilon = max(1.0, 0.002 * cv2.arcLength(contour, True))
                contour = cv2.approxPolyDP(contour, epsilon, True)
                points = [[float(p[0][0]), float(p[0][1])] for p in contour]
                self.event_queue.put(("sam_done", (record.id, ann_id, request_version, points, score)))
            except Exception as exc:
                self.event_queue.put(("error", f"SAM2: {exc}"))
        Thread(target=worker, daemon=True).start()

    def _confidence_changed(self, value) -> None:
        self.confidence_label.configure(text=f"{float(value):.2f}")

    def _start_auto_label(self) -> None:
        if not self.project or not self.project.images:
            messagebox.showwarning("Thiếu dữ liệu", "Hãy tạo dự án và nhập ảnh trước.")
            return
        if not Path(self.model_path.get()).exists():
            messagebox.showerror("Thiếu model", "Hãy chọn model YOLO .pt hợp lệ.")
            return
        self.cancel_event.clear()
        self.auto_log.delete("1.0", tk.END)
        project = self.project
        def progress(index, total, name):
            self.event_queue.put(("auto_progress", (index, total, name)))
        def worker():
            try:
                stats = auto_label_project(
                    self.store,
                    project,
                    self.model_path.get(),
                    confidence=float(self.confidence_slider.get()),
                    device=self.device_menu.get(),
                    unlabeled_only=bool(self.unlabeled_switch.get()),
                    replace_predictions=bool(self.replace_switch.get()),
                    progress=progress,
                    cancel_event=self.cancel_event,
                )
                self.event_queue.put(("auto_done", stats))
            except Exception as exc:
                self.event_queue.put(("error", str(exc)))
        Thread(target=worker, daemon=True).start()

    def _stop_auto_label(self) -> None:
        self.cancel_event.set()
        self._append_log(self.auto_log, "Đang yêu cầu dừng sau ảnh hiện tại…")

    # ---------- review ----------
    def _build_review_tab(self) -> None:
        tab = self.tabs.tab("KIỂM DUYỆT")
        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.pack(fill="x", padx=8, pady=8)
        self._button(controls, "Quét lỗi nhãn", self._run_quality_check, width=150).pack(side="left")
        self._button(controls, "Ảnh AI chưa chắc", self._build_active_learning_queue, width=160, color="#7655b5").pack(side="left", padx=8)
        self._button(controls, "Mở ảnh đang chọn", self._open_issue, width=160).pack(side="left", padx=8)
        ctk.CTkLabel(controls, text="AI không tự duyệt nhãn; lỗi phải được xử lý trước khi đóng băng dataset.", text_color=COLORS["muted"]).pack(side="left", padx=12)
        self.review_list = tk.Listbox(tab, bg="#091119", fg=COLORS["text"], selectbackground="#217fa9", borderwidth=0, highlightthickness=0, font=("Consolas", 11))
        self.review_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.quality_issues = []

    def _run_quality_check(self) -> None:
        self.review_list.delete(0, tk.END)
        if not self.project:
            return
        self.quality_issues = inspect_project(self.project)
        for issue in self.quality_issues:
            record = self.project.image_by_id(issue.image_id)
            self.review_list.insert(tk.END, f"[{issue.severity.upper():7}] {record.file_name if record else issue.image_id} · {issue.message}")
        if not self.quality_issues:
            self.review_list.insert(tk.END, "✓ Không phát hiện lỗi cấu trúc nhãn.")

    def _build_active_learning_queue(self) -> None:
        from .quality import QualityIssue
        self.review_list.delete(0, tk.END)
        self.quality_issues = []
        if not self.project:
            return
        ranked = []
        class_frequency = {item.id: 0 for item in self.project.classes}
        for record in self.project.images:
            for ann in record.annotations:
                class_frequency[ann.class_id] = class_frequency.get(ann.class_id, 0) + 1
        max_frequency = max(class_frequency.values(), default=1)
        for record in self.project.images:
            if record.review_status == "reviewed":
                continue
            ai = [ann for ann in record.annotations if ann.source != "manual"]
            if not ai:
                priority = 1.5
                reason = "AI không tìm thấy vật"
            else:
                lowest = min((ann.confidence if ann.confidence is not None else 0.0) for ann in ai)
                rare_bonus = max((max_frequency - class_frequency.get(ann.class_id, 0)) / max(max_frequency, 1) for ann in ai)
                priority = (1.0 - lowest) + 0.35 * rare_bonus
                reason = f"confidence thấp nhất {lowest:.2f}" + (" · class hiếm" if rare_bonus > 0.5 else "")
            ranked.append((priority, record, reason))
        for priority, record, reason in sorted(ranked, key=lambda item: item[0], reverse=True):
            issue = QualityIssue(record.id, "", "review", reason)
            self.quality_issues.append(issue)
            self.review_list.insert(tk.END, f"[{priority:4.2f}] {record.file_name} · {reason}")

    def _open_issue(self) -> None:
        selected = self.review_list.curselection()
        if not selected or not self.project or selected[0] >= len(self.quality_issues):
            return
        issue = self.quality_issues[selected[0]]
        record = self.project.image_by_id(issue.image_id)
        if record:
            self.current_index = self.project.images.index(record)
            self.tabs.set("GÁN NHÃN")
            self._load_current_image()

    # ---------- dataset ----------
    def _build_dataset_tab(self) -> None:
        tab = self.tabs.tab("DATASET")
        controls = self._card(tab, "EXPORT DATASET · ẢNH + TỌA ĐỘ NHÃN")
        controls.pack(side="left", fill="y", padx=(8, 5), pady=8)
        ctk.CTkLabel(
            controls,
            text="Nút Train đã tự export dataset. Trang này dùng\nđể kiểm tra hoặc export thủ công khi cần.",
            justify="left", text_color=COLORS["warn"],
        ).pack(anchor="w", padx=14, pady=(0, 8))
        self._button(
            controls,
            "Tạo phiên bản bất biến",
            self._create_version,
            width=260,
            color=COLORS["good"],
            tooltip=(
                "Lưu manifest, nhãn, cách chia tập và mã kiểm tra ảnh tại thời điểm hiện tại để đối chiếu. "
                "Train vẫn tự export trạng thái mới nhất của dự án khi bấm Bắt đầu Train."
            ),
        ).pack(padx=14, pady=6)
        self._button(controls, "Export thủ công RECT · Detection", lambda: self._export_yolo("detect"), width=260).pack(padx=14, pady=5)
        self._button(controls, "Export thủ công SEG · Segmentation", lambda: self._export_yolo("segment"), width=260).pack(padx=14, pady=5)
        self._button(controls, "Export thủ công OBB · Rotated Box", lambda: self._export_yolo("obb"), width=260).pack(padx=14, pady=5)
        self._button(controls, "Export thủ công ORI · Pose 2 điểm", lambda: self._export_yolo("pose"), width=260).pack(padx=14, pady=5)
        self.dataset_classification_section = ctk.CTkFrame(
            controls,
            fg_color="#0c1823",
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.dataset_classification_section.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            self.dataset_classification_section,
            text="THUỘC TÍNH CLASSIFICATION ĐÃ TICK",
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.dataset_classification_multi_frame = ctk.CTkFrame(
            self.dataset_classification_section,
            fg_color="transparent",
        )
        self.dataset_classification_multi_frame.pack(fill="x", padx=2, pady=2)
        dataset_select_row = ctk.CTkFrame(self.dataset_classification_section, fg_color="transparent")
        dataset_select_row.pack(fill="x", padx=8, pady=(2, 4))
        self._button(dataset_select_row, "Chọn tất cả", lambda: self._set_batch_group_selection(True), width=112, color="#48657a").pack(side="left", padx=(0, 3))
        self._button(dataset_select_row, "Bỏ chọn", lambda: self._set_batch_group_selection(False), width=112, color="#415466").pack(side="right", padx=(3, 0))
        self._button(
            self.dataset_classification_section,
            "EXPORT CROP CÁC NHÓM ĐÃ TICK",
            self._export_selected_classification_groups,
            width=238,
            color="#7655b5",
            tooltip="Cắt từng vật theo RECT cho tất cả nhóm đã tick và tạo dataset Classification riêng cho từng nhóm.",
        ).pack(padx=8, pady=(3, 8))
        self.dataset_coco_button = self._button(controls, "Export COCO JSON", self._export_coco, width=260)
        self.dataset_coco_button.pack(padx=14, pady=6)
        self.reviewed_only_switch = ctk.CTkSwitch(controls, text="Chỉ ảnh đã duyệt")
        self.reviewed_only_switch.select()
        self.reviewed_only_switch.pack(anchor="w", padx=14, pady=12)
        ctk.CTkLabel(controls, text="Split theo capture group để tránh\nframe gần nhau lọt vào cả train và test.", justify="left", text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=8)

        dataset_right = ctk.CTkFrame(tab, fg_color="transparent")
        dataset_right.pack(side="left", fill="both", expand=True, padx=(5, 8), pady=8)
        split_card = self._card(dataset_right, "PHÂN TẬP CỐ ĐỊNH THEO CAPTURE GROUP")
        split_card.pack(fill="x", pady=(0, 6))
        self.dataset_split_status_label = ctk.CTkLabel(
            split_card,
            text="Chưa khởi tạo phân tập",
            justify="left",
            anchor="w",
            text_color=COLORS["muted"],
            font=("Consolas", 11),
        )
        self.dataset_split_status_label.pack(fill="x", padx=14, pady=(2, 6))
        split_actions = ctk.CTkFrame(split_card, fg_color="transparent")
        split_actions.pack(fill="x", padx=14, pady=(0, 10))
        self._button(
            split_actions,
            "KHÓA / CẬP NHẬT ẢNH MỚI",
            self._lock_split_assignment,
            width=235,
            color=COLORS["good"],
            tooltip="Giữ nguyên tập của ảnh cũ; capture group mới được đưa vào Train.",
        ).pack(side="left", padx=(0, 6))
        self._button(
            split_actions,
            "PHÂN LẠI 70/15/15",
            self._rebalance_split_assignment,
            width=190,
            color="#a94747",
            tooltip="Viết lại toàn bộ Train/Val/Test. Chỉ dùng khi chủ động tạo Benchmark mới.",
        ).pack(side="left", padx=(0, 6))
        self._button(
            split_actions,
            "XEM / CHUYỂN NHÓM",
            self._open_split_manager,
            width=190,
            color="#48657a",
            tooltip="Xem capture group trong từng tập và chủ động chuyển cả nhóm sang Train, Validation hoặc Test.",
        ).pack(side="left")

        info = self._card(dataset_right, "THỐNG KÊ DATASET")
        info.pack(fill="both", expand=True, pady=(6, 0))
        self.dataset_info = ctk.CTkTextbox(info, fg_color="#091119", font=("Consolas", 13), corner_radius=10)
        self.dataset_info.pack(fill="both", expand=True, padx=14, pady=(4, 14))

    def _refresh_split_status(self) -> None:
        if not self.project or not hasattr(self, "dataset_split_status_label"):
            return
        summary = self.datasets.split_summary(self.project)
        counts = summary["counts"]
        group_counts = summary["group_counts"]
        text = (
            f"ĐÃ KHÓA · Train {counts['train']} ảnh/{group_counts['train']} nhóm · "
            f"Val {counts['val']} ảnh/{group_counts['val']} nhóm · "
            f"Test {counts['test']} ảnh/{group_counts['test']} nhóm\n"
            "Ảnh/capture group mới → Train · ảnh cũ không tự đổi tập"
        )
        self.dataset_split_status_label.configure(text=text, text_color=COLORS["good"])

    def _lock_split_assignment(self) -> None:
        if not self.project:
            return
        self.datasets.ensure_split_assignment(self.project)
        self._refresh_split_status()
        messagebox.showinfo(
            "Đã khóa phân tập",
            "Train/Validation/Test của các capture group hiện tại đã được giữ cố định.\n\n"
            "Ảnh mới sẽ vào Train; ảnh cũ không tự chuyển tập khi export hoặc train lại.",
            parent=self,
        )

    def _open_split_manager(self) -> None:
        if not self.project:
            return
        SplitManagerDialog(self, self.datasets, self.project, self._refresh_split_status)

    def _rebalance_split_assignment(self) -> None:
        if not self.project:
            return
        confirmed = messagebox.askyesno(
            "Tạo Benchmark mới?",
            "Thao tác này sẽ phân lại TOÀN BỘ capture group theo gần 70/15/15.\n\n"
            "Model cũ có thể đã học những ảnh chuyển sang Test mới, vì vậy không được dùng Test mới để tuyên bố "
            "kết quả khách quan cho model cũ. Chỉ tiếp tục nếu bạn muốn tạo chu kỳ Benchmark mới.",
            parent=self,
        )
        if not confirmed:
            return
        self.datasets.ensure_split_assignment(self.project, force_rebalance=True)
        self._refresh_split_status()
        messagebox.showinfo("Đã tạo phân tập mới", "Phân tập mới đã được khóa. Hãy train model mới từ đầu chu kỳ này.", parent=self)

    def _selected_split_strategy(self) -> str:
        return SPLIT_STRATEGY_LABELS.get(
            self.train_split_strategy.get(),
            DatasetManager.STRATEGY_LOCKED,
        )

    def _confirm_split_strategy(self) -> bool:
        strategy = self._selected_split_strategy()
        if strategy == DatasetManager.STRATEGY_LOCKED:
            return True
        if strategy == DatasetManager.STRATEGY_FINAL_KEEP_TEST:
            return messagebox.askyesno(
                "Train Final bằng Train + Validation?",
                "Validation sẽ được gộp vào Train; Test vẫn được giữ độc lập.\n\n"
                "Không chạy validation/early stopping trong lần này, vì vậy Patience bị bỏ qua. "
                "Hãy dùng số Epoch gần epoch tốt nhất của lần phát triển trước.",
                parent=self,
            )
        answer = simpledialog.askstring(
            "Xác nhận Train 100%",
            "Model sẽ học cả Train, Validation và Test. Dataset này sẽ KHÔNG còn tập đánh giá độc lập.\n\n"
            "Nhập TRAIN ALL để tiếp tục:",
            parent=self,
        )
        return bool(answer and answer.strip().upper() == "TRAIN ALL")

    def _create_version(self) -> None:
        if not self.project:
            return
        name = ask_dataset_version_name(self)
        if name is None:
            return
        try:
            path = self.datasets.create_version(self.project, name)
            messagebox.showinfo("Đã tạo", f"Đã đóng băng metadata tại:\n{path}")
        except Exception as exc:
            messagebox.showerror("Không tạo được", str(exc))

    def _export_yolo(self, task: str) -> None:
        if not self.project:
            return
        if not self._confirm_split_strategy():
            return
        split_strategy = self._selected_split_strategy()
        try:
            path = self.datasets.export_yolo(
                self.project,
                task=task,
                reviewed_only=bool(self.reviewed_only_switch.get()),
                split_strategy=split_strategy,
            )
            self.last_yolo_export = path
            self.train_data_entry.delete(0, tk.END)
            self.train_data_entry.insert(0, str(path / "data.yaml"))
            if hasattr(self, "train_task_menu"):
                self.train_task_menu.set(task)
            if self.project.attribute_classification_enabled:
                self.show_attribute_panel.set(False)
                self._toggle_attribute_panel()
                self.train_task_menu.set(task)
            metadata = json.loads((path / "export.json").read_text(encoding="utf-8"))
            messagebox.showinfo(
                "Export hoàn tất",
                f"Task: {task}\nNhãn đã xuất: {metadata.get('exported_annotations', 0)}\n"
                f"Chiến lược: {metadata.get('split_strategy')} · {metadata.get('counts')}\n"
                f"Nhãn thiếu hình học phù hợp: {metadata.get('skipped_annotations', 0)}\n{path}",
            )
        except Exception as exc:
            messagebox.showerror("Export lỗi", str(exc))

    def _selected_classification_key(self) -> str:
        return getattr(self, "classification_group_lookup", {}).get(self.classification_group_var.get(), "")

    def _export_classification(self) -> None:
        if not self.project:
            return
        key = self._selected_classification_key()
        if not key:
            messagebox.showerror("Chưa chọn thuộc tính", "Hãy tạo/chọn một nhóm thuộc tính để train Classification.")
            return
        if not self._confirm_split_strategy():
            return
        try:
            path = self.datasets.export_classification(
                self.project,
                key,
                reviewed_only=bool(self.reviewed_only_switch.get()),
                split_strategy=self._selected_split_strategy(),
            )
            self.train_data_entry.delete(0, tk.END)
            self.train_data_entry.insert(0, str(path))
            self.show_attribute_panel.set(True)
            self._toggle_attribute_panel()
            self.train_task_menu.set("classify")
            metadata = json.loads((path / "export.json").read_text(encoding="utf-8"))
            messagebox.showinfo(
                "Export Classification hoàn tất",
                f"Nhóm: {metadata.get('attribute_title', key)}\n"
                f"Crop đã xuất: {metadata.get('exported_crops', 0)}\n"
                f"Thiếu thuộc tính: {metadata.get('skipped_missing_attribute', 0)}\n{path}",
            )
        except Exception as exc:
            messagebox.showerror("Export Classification lỗi", str(exc))

    def _export_selected_classification_groups(self) -> None:
        if not self.project:
            return
        keys = self._selected_batch_classification_keys()
        if not keys:
            messagebox.showerror("Chưa chọn thuộc tính", "Hãy tick ít nhất một nhóm thuộc tính Classification.")
            return
        if not self._confirm_split_strategy():
            return
        split_strategy = self._selected_split_strategy()
        reviewed_only = bool(self.reviewed_only_switch.get())
        completed: list[tuple[str, Path, int]] = []
        errors: list[str] = []
        for key in keys:
            title = self._attribute_config(key)["title"]
            try:
                path = self.datasets.export_classification(
                    self.project,
                    key,
                    reviewed_only=reviewed_only,
                    split_strategy=split_strategy,
                )
                metadata = json.loads((path / "export.json").read_text(encoding="utf-8"))
                completed.append((title, path, int(metadata.get("exported_crops", 0))))
            except Exception as exc:
                errors.append(f"{title}: {exc}")
        if completed:
            last_path = completed[-1][1]
            self.train_data_entry.delete(0, tk.END)
            self.train_data_entry.insert(0, str(last_path))
        lines = [f"✓ {title}: {count} crop" for title, _path, count in completed]
        lines.extend(f"✗ {item}" for item in errors)
        if errors:
            messagebox.showwarning("Export nhiều nhóm hoàn tất một phần", "\n".join(lines))
        else:
            messagebox.showinfo("Export nhiều nhóm hoàn tất", "\n".join(lines))

    def _export_coco(self) -> None:
        if not self.project:
            return
        path = self.datasets.export_coco(self.project, reviewed_only=bool(self.reviewed_only_switch.get()))
        messagebox.showinfo("Export hoàn tất", str(path))

    # ---------- train ----------
    def _build_train_tab(self) -> None:
        tab = self.tabs.tab("TRAIN")
        settings_card = self._card(tab, "CẤU HÌNH TRAIN")
        settings_card.pack(side="left", fill="y", padx=(8, 5), pady=8)
        settings = ctk.CTkScrollableFrame(settings_card, width=350, fg_color="transparent", corner_radius=0)
        settings.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        ctk.CTkLabel(settings, text="Task train", text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=(7, 1))
        self.train_task_menu = ctk.CTkOptionMenu(
            settings,
            width=330,
            values=["detect", "segment", "obb", "pose", "classify"],
            command=self._train_task_changed,
        )
        self.train_task_menu.set("detect")
        self.train_task_menu.pack(padx=14, pady=2)
        split_label = ctk.CTkLabel(settings, text="Chiến lược dữ liệu", text_color=COLORS["muted"])
        split_label.pack(anchor="w", padx=14, pady=(8, 1))
        ToolTip(split_label, "Phát triển giữ Test cố định. Hai chế độ Final tận dụng thêm dữ liệu nhưng tắt validation trong lúc train.")
        self.train_split_strategy_menu = ctk.CTkOptionMenu(
            settings,
            width=330,
            variable=self.train_split_strategy,
            values=list(SPLIT_STRATEGY_LABELS),
            command=self._train_split_strategy_changed,
        )
        self.train_split_strategy_menu.pack(padx=14, pady=2)
        self.train_split_help_label = ctk.CTkLabel(
            settings,
            text="Ảnh cũ giữ nguyên tập · ảnh mới mặc định vào Train · có Validation và Test độc lập.",
            width=320,
            wraplength=320,
            justify="left",
            anchor="w",
            text_color="#8fa6b8",
            font=("Segoe UI", 10),
        )
        self.train_split_help_label.pack(anchor="w", padx=14, pady=(1, 5))
        self.train_classification_section = ctk.CTkFrame(
            settings,
            fg_color="#0c1823",
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.train_classification_section.pack(fill="x", padx=14, pady=(5, 4))
        self.classification_mode_label = ctk.CTkLabel(
            self.train_classification_section,
            text="Classification thuộc tính đang bật.",
            width=306,
            wraplength=300,
            justify="left",
            text_color=COLORS["warn"],
            font=("Segoe UI", 10),
        )
        self.classification_mode_label.pack(anchor="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            self.train_classification_section,
            text="Tick một nhóm để train một · tick nhiều để train tuần tự",
            text_color=COLORS["muted"],
            wraplength=300,
            justify="left",
        ).pack(anchor="w", padx=10, pady=(2, 1))
        self.train_classification_multi_frame = ctk.CTkFrame(
            self.train_classification_section,
            width=306,
            fg_color="transparent",
        )
        self.train_classification_multi_frame.pack(fill="x", padx=2, pady=2)
        batch_select_row = ctk.CTkFrame(self.train_classification_section, fg_color="transparent")
        batch_select_row.pack(fill="x", padx=10, pady=(2, 8))
        self._button(
            batch_select_row,
            "Chọn tất cả",
            lambda: self._set_batch_group_selection(True),
            width=140,
            color="#48657a",
        ).pack(side="left", padx=(0, 4))
        self._button(
            batch_select_row,
            "Bỏ chọn",
            lambda: self._set_batch_group_selection(False),
            width=140,
            color="#415466",
        ).pack(side="right", padx=(4, 0))
        self.task_model_button = self._button(settings, "Dùng model khởi tạo phù hợp", self._apply_task_model, width=330, color="#48657a", tooltip="Điền model YOLO11 nano đúng kiến trúc với task RECT/SEG/OBB/ORI/Classification.")
        self.task_model_button.pack(padx=14, pady=4)
        fields = [
            ("Model khởi tạo", "train_model_entry", str(DEMO_MODEL) if DEMO_MODEL.exists() else "yolo11n.pt"),
            ("Dataset tự tạo · hoặc chọn ngoài để đánh giá", "train_data_entry", ""),
            ("Epoch", "epochs_entry", "50"),
            ("Image size", "imgsz_entry", "640"),
            ("Batch", "batch_entry", "8"),
            ("Patience", "patience_entry", "15"),
        ]
        field_help = {
            "epochs_entry": "Số vòng model học toàn bộ tập Train. Bắt đầu 30–50; Final nên dùng gần epoch tốt nhất của lần phát triển.",
            "imgsz_entry": "Kích thước ảnh đưa vào model. Detection/SEG cho Radxa dùng 640; Classification thường dùng 224. Lớn hơn có thể rõ hơn nhưng chậm và tốn RAM/VRAM.",
            "batch_entry": "Số ảnh xử lý trước một lần cập nhật trọng số. CPU thử 4–8; RTX 4060 Ti thử 8–16. Nếu hết RAM/VRAM hãy giảm Batch.",
            "patience_entry": "Số epoch Validation không cải thiện trước khi dừng sớm. Thường 10–20. Bị bỏ qua trong hai chế độ Final không có Validation.",
        }
        for label, name, value in fields:
            label_widget = ctk.CTkLabel(
                settings,
                text=label + ("  ⓘ" if name in field_help else ""),
                text_color=COLORS["muted"],
            )
            label_widget.pack(anchor="w", padx=14, pady=(7, 1))
            if name in field_help:
                ToolTip(label_widget, field_help[name])
            entry = ctk.CTkEntry(settings, width=330)
            entry.insert(0, value)
            entry.pack(padx=14, pady=2)
            setattr(self, name, entry)
            if name == "train_model_entry":
                self._button(
                    settings,
                    "Chọn model khởi tạo .pt…",
                    self._choose_training_model,
                    width=330,
                    color="#48657a",
                    tooltip="Chọn checkpoint .pt để train mới hoặc fine-tune. RKNN là model triển khai nên không dùng làm model khởi tạo.",
                ).pack(padx=14, pady=(4, 1))
            elif name == "train_data_entry":
                self._button(
                    settings,
                    "Chọn dataset…",
                    self._choose_training_data_yaml,
                    width=330,
                    color="#48657a",
                    tooltip="Chọn dataset ngoài chủ yếu để ĐÁNH GIÁ MODEL. Khi bắt đầu train, ứng dụng tự export dữ liệu hiện tại của dự án.",
                ).pack(padx=14, pady=(4, 1))
        ctk.CTkLabel(
            settings,
            text="Bắt đầu Train tự export và điền dataset. Chọn thủ công chỉ cần khi đánh giá một dataset bên ngoài.",
            wraplength=320,
            justify="left",
            text_color="#8fa6b8",
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=14, pady=(1, 3))
        ctk.CTkLabel(settings, text="Thiết bị", text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=(7, 1))
        self.train_device_menu = ctk.CTkOptionMenu(settings, width=330, values=["auto", "cpu", "cuda"])
        self.train_device_menu.pack(padx=14, pady=2)
        self.train_start_button = self._button(
            settings,
            "BẮT ĐẦU TRAIN",
            self._start_training_for_current_mode,
            width=330,
            color=COLORS["good"],
            tooltip="Tự export dataset rồi train. Chế độ thường export theo task định vị; Classification export crop và train các nhóm đã tick.",
        )
        self.train_start_button.pack(padx=14, pady=(16, 5))
        # Alias retained for the batch-state enable/disable code.
        self.batch_train_button = self.train_start_button
        self._button(settings, "Dừng train", self._stop_training, width=330, color="#a94747").pack(padx=14, pady=5)

        right = ctk.CTkFrame(tab, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(5, 8), pady=8)

        deploy_card = self._card(right, "XUẤT RKNN CHO RADXA")
        deploy_card.pack(fill="x", pady=(0, 6))
        self.deploy_help_label = ctk.CTkLabel(
            deploy_card,
            text="Detection/SEG dùng Vision AI Setting hiện tại · Classification được xuất riêng rồi ghép bằng manifest nhiều model",
            wraplength=740,
            justify="left",
            text_color=COLORS["muted"],
        )
        self.deploy_help_label.pack(anchor="w", padx=14, pady=(1, 5))
        self.deploy_source_row = ctk.CTkFrame(deploy_card, fg_color="transparent")
        self.deploy_source_row.pack(fill="x", padx=14, pady=3)
        self.deploy_model_entry = ctk.CTkEntry(self.deploy_source_row, textvariable=self.deploy_model_path)
        self.deploy_model_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(
            self.deploy_source_row,
            "Chọn best.pt…",
            self._choose_deploy_model,
            width=135,
            color="#48657a",
            tooltip="Chọn model Detection, Segmentation hoặc Classification .pt đã train để chuyển sang RKNN cho Radxa.",
        ).pack(side="left")
        self.deploy_action_row = ctk.CTkFrame(deploy_card, fg_color="transparent")
        self.deploy_action_row.pack(fill="x", padx=14, pady=(4, 3))
        self.deploy_export_button = self._button(
            self.deploy_action_row,
            "XUẤT RKNN · RK3588",
            self._export_deployment_model,
            width=260,
            color=COLORS["good"],
            tooltip="Tự nhận biết Detection/SEG/Classification, chuyển best.pt sang RKNN và lưu contract JSON đi kèm.",
        )
        self.deploy_export_button.pack(side="left", padx=3)
        self.batch_rknn_export_button = self._button(
            self.deploy_action_row,
            "XUẤT RKNN CÁC NHÓM ĐÃ TICK",
            self._start_batch_rknn_export,
            width=265,
            color=COLORS["good"],
            tooltip="Chọn thư mục một lần rồi tự chuyển lần lượt toàn bộ classifier .pt đã tick sang RKNN.",
        )
        self.batch_rknn_export_button.pack(side="left", padx=3)
        self.bundle_export_button = self._button(
            self.deploy_action_row,
            "TẠO GÓI TRIỂN KHAI RADXA",
            self._export_deployment_bundle,
            width=235,
            color="#48657a",
            tooltip="Sao chép detector và các classifier RKNN đã xuất vào một thư mục cùng manifest cho Radxa.",
        )
        self.bundle_export_button.pack(side="left", padx=3)
        self.deploy_stop_button = self._button(
            self.deploy_action_row,
            "Dừng xuất RKNN",
            self._stop_rknn_export,
            width=145,
            color="#a94747",
        )
        self.deploy_stop_button.pack(side="left", padx=3)
        self._set_button_enabled(self.deploy_stop_button, False)
        self.deploy_status_label = ctk.CTkLabel(
            deploy_card,
            text="Hỗ trợ RKNN: Detection 9 output · SEG 13 output · Classification 1 output",
            text_color="#8fa6b8",
            font=("Segoe UI", 11),
        )
        self.deploy_status_label.pack(anchor="w", padx=14, pady=(2, 10))

        evaluation_card = self._card(right, "ĐÁNH GIÁ MODEL · VALIDATION / TEST")
        evaluation_card.pack(fill="x", pady=6)
        ctk.CTkLabel(
            evaluation_card,
            text="Model đánh giá và Dataset là hai file riêng. Mặc định dùng best.pt mới nhất trên tập test chưa dùng để cập nhật trọng số.",
            wraplength=900,
            justify="left",
            text_color=COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=14, pady=(1, 5))
        evaluation_model_row = ctk.CTkFrame(evaluation_card, fg_color="transparent")
        evaluation_model_row.pack(fill="x", padx=14, pady=3)
        self.evaluation_model_entry = ctk.CTkEntry(evaluation_model_row, textvariable=self.evaluation_model_path)
        self.evaluation_model_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(
            evaluation_model_row,
            "Chọn model .pt…",
            self._choose_evaluation_model,
            width=155,
            color="#48657a",
            tooltip="Chọn best.pt cần đánh giá. Đây không phải nút chọn Dataset.",
        ).pack(side="left")
        evaluation_data_row = ctk.CTkFrame(evaluation_card, fg_color="transparent")
        evaluation_data_row.pack(fill="x", padx=14, pady=3)
        self.evaluation_data_entry = ctk.CTkEntry(evaluation_data_row, textvariable=self.evaluation_data_path)
        self.evaluation_data_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(
            evaluation_data_row,
            "Chọn Dataset…",
            self._choose_evaluation_dataset,
            width=155,
            color="#48657a",
            tooltip="Detection/SEG/OBB/ORI chọn data.yaml; Classification chọn thư mục dataset. File model được chọn ở hàng phía trên.",
        ).pack(side="left")
        evaluation_action_row = ctk.CTkFrame(evaluation_card, fg_color="transparent")
        evaluation_action_row.pack(fill="x", padx=14, pady=(4, 4))
        ctk.CTkLabel(evaluation_action_row, text="Tập:", text_color=COLORS["muted"]).pack(side="left", padx=(2, 5))
        self.evaluation_split_menu = ctk.CTkOptionMenu(
            evaluation_action_row,
            variable=self.evaluation_split,
            values=["test", "val"],
            width=95,
        )
        self.evaluation_split_menu.pack(side="left", padx=(0, 8))
        self.evaluation_button = self._button(
            evaluation_action_row,
            "ĐÁNH GIÁ MODEL",
            self._evaluate_model,
            width=205,
            color="#7655b5",
            tooltip="Chạy model đã chọn trên tập test hoặc validation và ghi Precision, Recall, mAP cùng kết quả từng Class.",
        )
        self.evaluation_button.pack(side="left", padx=3)
        self.evaluation_status_label = ctk.CTkLabel(
            evaluation_action_row,
            text="Chưa đánh giá",
            text_color="#8fa6b8",
            font=("Segoe UI Semibold", 10),
        )
        self.evaluation_status_label.pack(side="left", padx=10)

        log_card = self._card(right, "NHẬT KÝ TRAIN / XUẤT MODEL")
        log_card.pack(fill="both", expand=True, pady=(6, 0))
        self.train_log = ctk.CTkTextbox(log_card, fg_color="#070d13", font=("Consolas", 11), corner_radius=10)
        self.train_log.pack(fill="both", expand=True, padx=14, pady=(4, 14))

    def _apply_task_model(self) -> None:
        suggestions = {
            "detect": "yolo11n.pt",
            "segment": "yolo11n-seg.pt",
            "obb": "yolo11n-obb.pt",
            "pose": "yolo11n-pose.pt",
            "classify": "yolo11n-cls.pt",
        }
        value = suggestions[self.train_task_menu.get()]
        self.train_model_entry.delete(0, tk.END)
        self.train_model_entry.insert(0, value)
        self._set_status(f"Model gợi ý: {value}")

    def _train_split_strategy_changed(self, _value: str) -> None:
        strategy = self._selected_split_strategy()
        messages = {
            DatasetManager.STRATEGY_LOCKED: (
                "Ảnh cũ giữ nguyên tập · ảnh mới mặc định vào Train · có Validation và Test độc lập.",
                COLORS["good"],
            ),
            DatasetManager.STRATEGY_FINAL_KEEP_TEST: (
                "Gộp Train + Validation để học · giữ Test độc lập · Patience/early stopping không dùng.",
                COLORS["warn"],
            ),
            DatasetManager.STRATEGY_TRAIN_ALL: (
                "Học 100% ảnh · không còn Validation/Test khách quan · cần Benchmark mới để đánh giá.",
                COLORS["bad"],
            ),
        }
        text, color = messages[strategy]
        self.train_split_help_label.configure(text=text, text_color=color)

    def _train_task_changed(self, value: str) -> None:
        enable_classification = value == "classify"
        if not enable_classification:
            self.last_localization_task = value
        if bool(self.show_attribute_panel.get()) != enable_classification:
            self.show_attribute_panel.set(enable_classification)
            self._toggle_attribute_panel()
        self._refresh_classification_controls()
        self.train_task_menu.set(value)
        if hasattr(self, "imgsz_entry"):
            current = self.imgsz_entry.get().strip()
            if enable_classification and current == "640":
                self.imgsz_entry.delete(0, tk.END)
                self.imgsz_entry.insert(0, "224")
            elif not enable_classification and current == "224":
                self.imgsz_entry.delete(0, tk.END)
                self.imgsz_entry.insert(0, "640")

    def _choose_training_model(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn model khởi tạo để train/fine-tune",
            filetypes=[
                ("Ultralytics checkpoint", "*.pt"),
                ("Ultralytics architecture", "*.yaml *.yml"),
                ("Tất cả file", "*.*"),
            ],
        )
        if not path:
            return
        self.train_model_entry.delete(0, tk.END)
        self.train_model_entry.insert(0, path)
        self._set_status(f"Model khởi tạo: {Path(path).name}")

    def _choose_training_data_yaml(self) -> None:
        initial_dir = None
        current = self.train_data_entry.get().strip()
        if current:
            candidate = Path(current)
            initial_dir = str(candidate.parent if candidate.suffix else candidate)
        if self.train_task_menu.get() == "classify":
            path = filedialog.askdirectory(title="Chọn thư mục dataset Classification", initialdir=initial_dir)
        else:
            path = filedialog.askopenfilename(
                title="Chọn cấu hình dataset data.yaml",
                initialdir=initial_dir,
                filetypes=[("YOLO dataset", "*.yaml *.yml"), ("YAML", "*.yaml"), ("Tất cả file", "*.*")],
            )
        if not path:
            return
        self.train_data_entry.delete(0, tk.END)
        self.train_data_entry.insert(0, path)
        self._set_status(f"Đã chọn dataset: {Path(path).name}")

    @staticmethod
    def _dataset_from_model_run(model_path: Path) -> Path | None:
        """Read the exact dataset used by a weights/best.pt training run."""
        args_path = model_path.parent.parent / "args.yaml"
        if not args_path.is_file():
            return None
        try:
            import yaml

            data = yaml.safe_load(args_path.read_text(encoding="utf-8")) or {}
            candidate = Path(str(data.get("data", "")))
            return candidate.resolve() if candidate.exists() else None
        except Exception:
            return None

    @staticmethod
    def _dataset_has_independent_test(data_path: Path | None) -> bool:
        if data_path is None or not data_path.exists():
            return False
        metadata_path = (data_path / "export.json") if data_path.is_dir() else (data_path.parent / "export.json")
        if not metadata_path.is_file():
            return True
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return bool(metadata.get("independent_test", True))
        except (OSError, ValueError, TypeError):
            return True

    def _refresh_evaluation_defaults(self, *, force: bool = False) -> None:
        if not self.project:
            return
        best = self._latest_best_pt()
        current_model = Path(self.evaluation_model_path.get()) if self.evaluation_model_path.get().strip() else None
        if best and (force or current_model is None or not current_model.is_file()):
            self.evaluation_model_path.set(str(best.resolve()))
            current_model = best
        dataset = self._dataset_from_model_run(current_model) if current_model else None
        current_data = Path(self.evaluation_data_path.get()) if self.evaluation_data_path.get().strip() else None
        if self._dataset_has_independent_test(dataset) and (force or current_data is None or not current_data.exists()):
            self.evaluation_data_path.set(str(dataset))
        elif force or current_data is None or not current_data.exists():
            candidates = [
                path for path in (self.store.project_dir(self.project) / "exports").glob("yolo_*/data.yaml")
                if self._dataset_has_independent_test(path)
            ]
            if candidates:
                self.evaluation_data_path.set(str(max(candidates, key=lambda path: path.stat().st_mtime).resolve()))

    def _choose_evaluation_model(self) -> None:
        self._refresh_evaluation_defaults()
        current = Path(self.evaluation_model_path.get()) if self.evaluation_model_path.get().strip() else None
        initial_dir = str(current.parent) if current and current.parent.exists() else str(WORKSPACE / "models")
        path = filedialog.askopenfilename(
            title="Chọn model cần đánh giá",
            initialdir=initial_dir,
            filetypes=[("Ultralytics model", "*.pt *.onnx"), ("PyTorch checkpoint", "*.pt"), ("Tất cả file", "*.*")],
        )
        if not path:
            return
        self.evaluation_model_path.set(path)
        dataset = self._dataset_from_model_run(Path(path))
        if self._dataset_has_independent_test(dataset):
            self.evaluation_data_path.set(str(dataset))
        self._set_status(f"Model đánh giá: {Path(path).name}")

    def _choose_evaluation_dataset(self) -> None:
        self._refresh_evaluation_defaults()
        current = Path(self.evaluation_data_path.get()) if self.evaluation_data_path.get().strip() else None
        initial_dir = str(current.parent if current and current.suffix else current) if current and current.exists() else None
        task = ""
        model_path = Path(self.evaluation_model_path.get()) if self.evaluation_model_path.get().strip() else None
        if model_path and model_path.is_file():
            try:
                from ultralytics import YOLO

                task = str(YOLO(str(model_path)).task)
            except Exception:
                task = ""
        if task == "classify":
            path = filedialog.askdirectory(title="Chọn thư mục Dataset Classification", initialdir=initial_dir)
        else:
            path = filedialog.askopenfilename(
                title="Chọn data.yaml của Dataset đánh giá",
                initialdir=initial_dir,
                filetypes=[("YOLO Dataset", "*.yaml *.yml"), ("Tất cả file", "*.*")],
            )
        if path:
            self.evaluation_data_path.set(path)
            self._set_status(f"Dataset đánh giá: {Path(path).name}")

    def _choose_deploy_model(self) -> None:
        initial_dir = None
        current = self.deploy_model_path.get().strip()
        if current:
            initial_dir = str(Path(current).parent)
        path = filedialog.askopenfilename(
            title="Chọn model .pt đã train",
            initialdir=initial_dir,
            filetypes=[("Ultralytics model", "*.pt"), ("Tất cả file", "*.*")],
        )
        if path:
            self.deploy_model_path.set(path)
            self._set_status(f"Model triển khai: {Path(path).name}")

    def _use_selected_classifier_for_deploy(self) -> None:
        if not self.project:
            return
        key = self._selected_classification_key()
        source = Path(self.project.attribute_models.get(key, "")) if key else Path()
        if not key or not source.is_file():
            messagebox.showerror(
                "Chưa có classifier",
                "Nhóm đang chọn chưa có classifier .pt đã train. Hãy Export crop và train Classification trước.",
            )
            return
        self.deploy_model_path.set(str(source.resolve()))
        self.show_attribute_panel.set(True)
        self._toggle_attribute_panel()
        self.train_task_menu.set("classify")
        self.imgsz_entry.delete(0, tk.END)
        self.imgsz_entry.insert(0, "224")
        self._set_status(f"Classifier triển khai: {self._attribute_config(key)['title']} · {source.name}")

    def _start_batch_rknn_export(self) -> None:
        if not self.project:
            return
        if not self._check_rknn_environment():
            return
        if self.model_export_job and self.model_export_job.thread and self.model_export_job.thread.is_alive():
            messagebox.showerror("Đang xuất RKNN", "Hãy chờ hoặc dừng tác vụ RKNN hiện tại trước.")
            return
        keys = self._selected_batch_classification_keys()
        if not keys:
            messagebox.showerror("Chưa chọn nhóm", "Hãy tick ít nhất một nhóm thuộc tính Classification.")
            return
        queue: list[tuple[str, Path]] = []
        missing: list[str] = []
        for key in keys:
            source = Path(self.project.attribute_models.get(key, ""))
            if source.is_file():
                queue.append((key, source))
            else:
                missing.append(self._attribute_config(key)["title"])
        if missing:
            messagebox.showerror(
                "Thiếu classifier đã train",
                "Các nhóm sau chưa có best.pt:\n" + "\n".join(f"• {title}" for title in missing),
            )
            return
        parent = filedialog.askdirectory(title="Chọn thư mục lưu các classifier RKNN")
        if not parent:
            return
        self.rknn_batch_queue = queue
        self.rknn_batch_output_dir = Path(parent)
        self.rknn_batch_total = len(queue)
        self.rknn_batch_completed = 0
        self.rknn_batch_active = True
        self.rknn_batch_cancelled = False
        self._set_button_enabled(self.batch_rknn_export_button, False)
        self._set_button_enabled(self.bundle_export_button, False)
        self._set_button_enabled(self.deploy_stop_button, True)
        self._append_log(self.train_log, f"\nBẮT ĐẦU XUẤT RKNN HÀNG LOẠT · {len(queue)} CLASSIFIER")
        self._start_next_batch_rknn_export()

    def _start_next_batch_rknn_export(self) -> None:
        if not self.rknn_batch_active or self.rknn_batch_cancelled:
            self._finish_batch_rknn_export(cancelled=True)
            return
        if not self.rknn_batch_queue:
            self._finish_batch_rknn_export()
            return
        key, source = self.rknn_batch_queue.pop(0)
        try:
            from ultralytics import YOLO
            model = YOLO(str(source))
            if model.task != "classify":
                raise ValueError(f"{source.name} không phải model Classification")
            class_count = len(model.names)
        except Exception as exc:
            self._finish_batch_rknn_export(error=str(exc))
            return
        safe_key = "".join(char if char.isalnum() or char in "-_" else "_" for char in key)
        output = self.rknn_batch_output_dir / f"classifier_{safe_key}.rknn"
        self.running_rknn_task = "classify"
        self.running_rknn_attribute_key = key
        title = self._attribute_config(key)["title"]
        self.deploy_status_label.configure(
            text=f"RKNN {self.rknn_batch_completed + 1}/{self.rknn_batch_total} · {title}",
            text_color=COLORS["warn"],
        )
        self.model_export_job = RknnExportJob(
            RknnExportConfig(
                model=source,
                output=output,
                converter_dir=APP_ROOT / "tools" / "rknn_converter",
                image_size=224,
                target="rk3588",
                class_count=class_count,
                task="classify",
            ),
            lambda line: self.event_queue.put(("rknn_line", line)),
            lambda code, path, error: self.event_queue.put(("rknn_done", (code, path, error))),
        )
        self.model_export_job.start()

    def _finish_batch_rknn_export(self, *, cancelled: bool = False, error: str = "") -> None:
        was_active = self.rknn_batch_active
        self.rknn_batch_active = False
        self.rknn_batch_queue = []
        self._set_button_enabled(self.batch_rknn_export_button, True)
        self._set_button_enabled(self.bundle_export_button, True)
        self._set_button_enabled(self.deploy_stop_button, False)
        if not was_active:
            return
        if cancelled or error:
            reason = error or "Đã dừng theo yêu cầu."
            self.deploy_status_label.configure(text="Xuất RKNN hàng loạt chưa hoàn tất", text_color=COLORS["bad"])
            messagebox.showwarning(
                "Xuất RKNN chưa hoàn tất",
                f"{reason}\n\nĐã hoàn thành {self.rknn_batch_completed}/{self.rknn_batch_total} model.",
            )
            return
        self.deploy_status_label.configure(
            text=f"Đã xuất {self.rknn_batch_completed} classifier RKNN",
            text_color=COLORS["good"],
        )
        messagebox.showinfo(
            "Xuất RKNN hàng loạt hoàn tất",
            f"Đã xuất {self.rknn_batch_completed} classifier vào:\n{self.rknn_batch_output_dir}\n\n"
            "Bước tiếp theo: TẠO GÓI TRIỂN KHAI RADXA.",
        )

    @staticmethod
    def _read_rknn_sidecar(path: Path) -> dict:
        sidecar = path.with_suffix(".json")
        try:
            return json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _export_deployment_bundle(self) -> None:
        if not self.project:
            return
        localization = Path(self.project.active_rknn_model) if self.project.active_rknn_model else None
        classifiers = {
            key: Path(path)
            for key, path in self.project.attribute_rknn_models.items()
            if path and Path(path).is_file()
        }
        if localization is None or not localization.is_file():
            messagebox.showerror(
                "Thiếu model định vị RKNN",
                "Hãy xuất model Detection/SEG RKNN trước; gói hai giai đoạn luôn cần model tìm vật.",
            )
            return
        if not classifiers:
            messagebox.showerror(
                "Thiếu classifier RKNN",
                "Hãy chọn từng classifier đã train và xuất ít nhất một model Classification RKNN.",
            )
            return
        parent = filedialog.askdirectory(title="Chọn nơi lưu gói nhiều model cho Radxa")
        if not parent:
            return
        bundle_dir = Path(parent) / f"deltax_vision_bundle_{datetime.now():%Y%m%d_%H%M%S}"
        bundle_dir.mkdir(parents=True, exist_ok=False)

        def copy_model(source: Path, target_name: str) -> tuple[Path, dict]:
            target = bundle_dir / target_name
            shutil.copy2(source, target)
            metadata = self._read_rknn_sidecar(source)
            if metadata:
                (bundle_dir / f"{target.stem}.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            return target, metadata

        localization_target, localization_meta = copy_model(
            localization,
            f"localization_{localization.name}",
        )
        classifier_entries = []
        for key, source in sorted(classifiers.items()):
            safe_key = "".join(char if char.isalnum() or char in "-_" else "_" for char in key)
            target, metadata = copy_model(source, f"classifier_{safe_key}_{source.name}")
            classifier_entries.append(
                classifier_manifest_entry(
                    self.project,
                    attribute_key=key,
                    model_name=target.name,
                    metadata=metadata,
                )
            )
        manifest = build_vision_bundle_manifest(
            self.project,
            localization_model=localization_target.name,
            localization_metadata=localization_meta,
            classifiers=classifier_entries,
        )
        (bundle_dir / "vision_bundle.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        note_source = APP_ROOT / "docs" / "RADXA_CLASSIFICATION_INTEGRATION.md"
        if note_source.is_file():
            shutil.copy2(note_source, bundle_dir / note_source.name)
        messagebox.showinfo(
            "Đã tạo gói triển khai",
            f"Detector/SEG: 1\nClassifier: {len(classifier_entries)}\nManifest: vision_bundle.json\n\n{bundle_dir}",
        )
        self._set_status(f"Đã tạo gói Radxa · {len(classifier_entries)} classifier")

    def _latest_best_pt(self, task: str | None = None) -> Path | None:
        if not self.project:
            return None
        runs_dir = self.store.project_dir(self.project) / "runs"
        pattern = f"candidate_{task}*/weights/best.pt" if task else "candidate*/weights/best.pt"
        candidates = list(runs_dir.glob(pattern))
        if task is None:
            candidates = [path for path in candidates if "classify" not in path.parent.parent.name.lower()]
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None

    def _export_deployment_model(self) -> None:
        if not self.project:
            return
        source_text = self.deploy_model_path.get().strip()
        source = Path(source_text) if source_text else self._latest_best_pt()
        if source is None or not source.is_file() or source.suffix.lower() != ".pt":
            messagebox.showerror("Thiếu best.pt", "Hãy train xong hoặc chọn một file model .pt hợp lệ.")
            return
        self.deploy_model_path.set(str(source.resolve()))

        try:
            from ultralytics import YOLO

            model = YOLO(str(source))
            if model.task not in {"detect", "segment", "classify"}:
                messagebox.showerror(
                    "RKNN chưa tương thích",
                    "Bộ xuất RKNN hiện hỗ trợ Detection, Segmentation và Classification.\n"
                    f"Model đã chọn có task: {model.task}.",
                )
                return
            class_count = len(model.names)
            task = model.task
        except Exception as exc:
            messagebox.showerror("Không đọc được model", str(exc))
            return

        if not self._check_rknn_environment():
            return

        safe_stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in source.stem)
        destination = filedialog.asksaveasfilename(
            title="Lưu model RKNN dùng trên Radxa",
            defaultextension=".rknn",
            initialfile=f"{safe_stem}_{task}_rk3588.rknn",
            filetypes=[("Rockchip RKNN", "*.rknn")],
        )
        if not destination:
            return
        output = Path(destination).with_suffix(".rknn")
        try:
            image_size = int(self.imgsz_entry.get())
        except ValueError:
            messagebox.showerror("Sai image size", "Image size phải là số nguyên, ví dụ 640.")
            return
        if task in {"detect", "segment"} and image_size != 640:
            messagebox.showerror(
                "Image size không tương thích Radxa",
                "RKNNRuntime và bộ giải mã DeltaX hiện tại cố định ở 640×640. Hãy đặt Image size = 640 rồi xuất lại.",
            )
            return
        if task == "classify" and image_size < 32:
            messagebox.showerror("Image size không hợp lệ", "Classification cần Image size tối thiểu 32; khuyến nghị 224.")
            return

        classification_key = ""
        if task == "classify":
            classification_key = self._selected_classification_key()
            if not classification_key:
                messagebox.showerror("Chưa chọn nhóm", "Hãy chọn nhóm thuộc tính tương ứng với classifier này.")
                return
            expected_labels = set(self.project.attribute_schema.get(classification_key, [])) if self.project else set()
            model_labels = {str(value) for value in model.names.values()}
            if expected_labels and model_labels != expected_labels:
                messagebox.showerror(
                    "Sai nhãn Classification",
                    "Label trong classifier không khớp nhóm thuộc tính đang chọn.\n"
                    f"Nhóm: {sorted(expected_labels)}\nModel: {sorted(model_labels)}",
                )
                return

        self._set_button_enabled(self.deploy_export_button, False)
        self._set_button_enabled(self.deploy_stop_button, True)
        task_label = "Classification" if task == "classify" else "SEG" if task == "segment" else "Detection"
        self.deploy_status_label.configure(text=f"Đang chuyển {task_label} PT → RKNN…", text_color=COLORS["warn"])
        self._append_log(
            self.train_log,
            f"\nBẮT ĐẦU XUẤT RKNN {task_label}\nModel: {source}\nĐích: {output}\nClass: {class_count} · image size: {image_size}",
        )
        self.running_rknn_task = task
        self.running_rknn_attribute_key = classification_key
        self.model_export_job = RknnExportJob(
            RknnExportConfig(
                model=source,
                output=output,
                converter_dir=APP_ROOT / "tools" / "rknn_converter",
                image_size=image_size,
                target="rk3588",
                class_count=class_count,
                task=task,
            ),
            lambda line: self.event_queue.put(("rknn_line", line)),
            lambda code, path, error: self.event_queue.put(("rknn_done", (code, path, error))),
        )
        self.model_export_job.start()

    def _stop_rknn_export(self) -> None:
        active = bool(self.model_export_job and self.model_export_job.thread and self.model_export_job.thread.is_alive())
        if not active and not self.rknn_batch_active:
            self.deploy_status_label.configure(text="Không có tiến trình RKNN đang chạy", text_color=COLORS["muted"])
            self._append_log(self.train_log, "DỪNG RKNN: không có tiến trình đang chạy.")
            return
        if self.rknn_batch_active:
            self.rknn_batch_cancelled = True
            self.rknn_batch_queue = []
        if self.model_export_job:
            self.model_export_job.stop()
        self._set_button_enabled(self.deploy_stop_button, False)
        self.deploy_status_label.configure(text="Đang dừng xuất RKNN…", text_color=COLORS["warn"])
        self._append_log(self.train_log, "ĐÃ NHẬN YÊU CẦU DỪNG XUẤT RKNN")

    def _check_rknn_environment(self) -> bool:
        ready, detail = diagnose_rknn_environment()
        self.deploy_status_label.configure(
            text=detail.splitlines()[0],
            text_color=COLORS["good"] if ready else COLORS["bad"],
        )
        self._append_log(self.train_log, f"KIỂM TRA RKNN: {detail}")
        if not ready:
            messagebox.showerror("Môi trường RKNN chưa sẵn sàng", detail, parent=self)
        return ready

    def _start_training_for_current_mode(self) -> None:
        if self.project and self.project.attribute_classification_enabled:
            self._start_batch_classification_training()
        else:
            self._start_localization_training_with_auto_export()

    def _start_localization_training_with_auto_export(self) -> None:
        if not self.project:
            return
        task = self.train_task_menu.get()
        if task not in {"detect", "segment", "obb", "pose"}:
            messagebox.showerror("Task không hợp lệ", "Hãy chọn Detection, SEG, OBB hoặc ORI/Pose.")
            return
        if self.training_job and self.training_job.thread and self.training_job.thread.is_alive():
            messagebox.showerror("Train đang chạy", "Hãy chờ hoặc dừng tác vụ train hiện tại trước.")
            return
        if not self._confirm_split_strategy():
            return
        split_strategy = self._selected_split_strategy()
        try:
            reviewed_only = bool(self.reviewed_only_switch.get()) if hasattr(self, "reviewed_only_switch") else True
            export_dir = self.datasets.export_yolo(
                self.project,
                task=task,
                reviewed_only=reviewed_only,
                split_strategy=split_strategy,
            )
            metadata = json.loads((export_dir / "export.json").read_text(encoding="utf-8"))
            exported_annotations = int(metadata.get("exported_annotations", 0))
            if exported_annotations <= 0:
                review_hint = " Hãy duyệt ảnh có nhãn hoặc tắt “Chỉ ảnh đã duyệt”." if reviewed_only else ""
                raise ValueError(f"Không có nhãn {task} hợp lệ để train.{review_hint}")
            data_yaml = export_dir / "data.yaml"
            self.last_yolo_export = export_dir
            self.train_data_entry.delete(0, tk.END)
            self.train_data_entry.insert(0, str(data_yaml))
            if metadata.get("independent_test"):
                self.evaluation_data_path.set(str(data_yaml))
            self.pending_training_note = (
                f"AUTO EXPORT DATASET · task {task} · {exported_annotations} nhãn\n"
                f"Chiến lược: {split_strategy} · {metadata.get('counts')}\n"
                f"data.yaml: {data_yaml}"
            )
            self._set_status(f"Đã tự export {exported_annotations} nhãn {task} · bắt đầu train")
        except Exception as exc:
            messagebox.showerror("Tự export dataset trước khi train thất bại", str(exc))
            return
        self._start_training()

    def _start_batch_classification_training(self) -> None:
        if not self.project:
            return
        if self.training_job and self.training_job.thread and self.training_job.thread.is_alive():
            messagebox.showerror("Train đang chạy", "Hãy chờ hoặc dừng tác vụ train hiện tại trước.")
            return
        if not self._confirm_split_strategy():
            return
        split_strategy = self._selected_split_strategy()
        keys = self._selected_batch_classification_keys()
        if not keys:
            messagebox.showerror("Chưa chọn nhóm", "Hãy tick ít nhất một nhóm thuộc tính trong phần Train hàng loạt.")
            return
        model_path = self.train_model_entry.get().strip()
        auto_model_selected = False
        try:
            if Path(model_path).is_file():
                from ultralytics import YOLO
                if YOLO(model_path).task != "classify":
                    model_path = "yolo11n-cls.pt"
                    auto_model_selected = True
            elif "-cls" not in Path(model_path).name.lower():
                model_path = "yolo11n-cls.pt"
                auto_model_selected = True
            if self.train_model_entry.get().strip() != model_path:
                self.train_model_entry.delete(0, tk.END)
                self.train_model_entry.insert(0, model_path)
            image_size = int(self.imgsz_entry.get())
            if image_size == 640:
                image_size = 224
                self.imgsz_entry.delete(0, tk.END)
                self.imgsz_entry.insert(0, "224")
            options = {
                "model": model_path,
                "epochs": int(self.epochs_entry.get()),
                "image_size": image_size,
                "batch": int(self.batch_entry.get()),
                "patience": int(self.patience_entry.get()),
                "device": self.train_device_menu.get(),
                "split_strategy": split_strategy,
                "validate": split_strategy == DatasetManager.STRATEGY_LOCKED,
            }
        except ValueError as exc:
            messagebox.showerror("Cấu hình train chưa hợp lệ", str(exc))
            return
        reviewed_only = bool(self.reviewed_only_switch.get()) if hasattr(self, "reviewed_only_switch") else True
        prepared: list[tuple[str, Path]] = []
        problems: list[str] = []
        self.train_log.delete("1.0", tk.END)
        self._append_log(self.train_log, f"CHUẨN BỊ TRAIN HÀNG LOẠT · {len(keys)} NHÓM")
        if auto_model_selected:
            self._append_log(self.train_log, "Đã tự chọn model khởi tạo Classification: yolo11n-cls.pt")
        for key in keys:
            title = self._attribute_config(key)["title"]
            try:
                data_path = self.datasets.export_classification(
                    self.project,
                    key,
                    reviewed_only=reviewed_only,
                    split_strategy=split_strategy,
                )
                metadata = json.loads((data_path / "export.json").read_text(encoding="utf-8"))
                populated = [name for name, count in metadata.get("counts", {}).items() if count]
                if len(populated) < 2:
                    raise ValueError("cần ít nhất hai giá trị thuộc tính có crop")
                prepared.append((key, data_path))
                self._append_log(
                    self.train_log,
                    f"✓ {title}: {metadata.get('exported_crops', 0)} crop · {len(populated)} nhãn",
                )
            except Exception as exc:
                problems.append(f"{title}: {exc}")
        if problems:
            messagebox.showerror(
                "Không thể train hàng loạt",
                "Hãy sửa dữ liệu của các nhóm sau rồi thử lại:\n\n" + "\n".join(problems),
            )
            return
        self.show_attribute_panel.set(True)
        self._toggle_attribute_panel()
        self.train_task_menu.set("classify")
        self.batch_training_queue = prepared
        self.batch_training_results = {}
        self.batch_training_options = options
        self.batch_training_total = len(prepared)
        self.batch_training_active = True
        self.batch_training_cancelled = False
        self._set_button_enabled(self.batch_train_button, False)
        self._append_log(
            self.train_log,
            "\nMỗi nhóm dùng một head/label space riêng. Khi hoàn tất, ứng dụng sẽ tạo một gói ZIP quản lý chung.",
        )
        self._start_next_batch_classification_training()

    def _start_next_batch_classification_training(self) -> None:
        if not self.batch_training_active or self.batch_training_cancelled:
            self._finish_batch_classification_training(cancelled=True)
            return
        if not self.batch_training_queue:
            self._finish_batch_classification_training()
            return
        key, data_path = self.batch_training_queue.pop(0)
        title = self._attribute_config(key)["title"]
        current_number = len(self.batch_training_results) + 1
        for label, mapped_key in self.classification_group_lookup.items():
            if mapped_key == key:
                self.classification_group_var.set(label)
                break
        self.train_data_entry.delete(0, tk.END)
        self.train_data_entry.insert(0, str(data_path))
        safe_key = "".join(char if char.isalnum() or char in "-_" else "_" for char in key)
        options = self.batch_training_options
        config = TrainingConfig(
            model=str(options["model"]),
            data=str(data_path),
            project_dir=str(self.store.project_dir(self.project) / "runs"),
            task="classify",
            run_name=f"candidate_classify_{safe_key}_{options.get('split_strategy', 'locked')}",
            epochs=int(options["epochs"]),
            image_size=int(options["image_size"]),
            batch=int(options["batch"]),
            patience=int(options["patience"]),
            device=str(options["device"]),
            validate=bool(options.get("validate", True)),
        )
        self.running_training_task = "classify"
        self.running_classification_key = key
        self._append_log(
            self.train_log,
            f"\n===== [{current_number}/{self.batch_training_total}] TRAIN {title.upper()} =====",
        )
        self.training_job = TrainingJob(
            config,
            lambda line: self.event_queue.put(("train_line", line)),
            lambda code: self.event_queue.put(("train_done", code)),
        )
        self.training_job.start()

    def _finish_batch_classification_training(self, *, cancelled: bool = False, error: str = "") -> None:
        was_active = self.batch_training_active
        self.batch_training_active = False
        self.batch_training_queue = []
        self._set_button_enabled(self.batch_train_button, True)
        if not was_active:
            return
        if cancelled or error:
            reason = error or "Người dùng đã dừng train."
            self._append_log(self.train_log, f"\nTRAIN HÀNG LOẠT DỪNG · {reason}")
            messagebox.showwarning(
                "Train hàng loạt chưa hoàn tất",
                f"{reason}\n\nCác classifier đã hoàn thành trước đó vẫn được lưu riêng.",
            )
            return
        try:
            bundle_dir = self.store.project_dir(self.project) / "bundles"
            bundle = bundle_dir / f"classification_models_{datetime.now():%Y%m%d_%H%M%S}.zip"
            write_classifier_pt_bundle(self.project, bundle, self.batch_training_results)
            self.project.attribute_model_bundle = str(bundle.resolve())
            self.store.save(self.project)
            self._append_log(
                self.train_log,
                f"\nHOÀN TẤT {len(self.batch_training_results)}/{self.batch_training_total} CLASSIFIER\nGói PT: {bundle}",
            )
            messagebox.showinfo(
                "Train nhiều thuộc tính hoàn tất",
                f"Đã train: {len(self.batch_training_results)} classifier\n"
                f"Đã gom thành một gói quản lý:\n{bundle}\n\n"
                "ZIP không phải một mạng neural duy nhất; mỗi classifier bên trong vẫn có nhãn và output riêng.",
            )
        except Exception as exc:
            self._append_log(self.train_log, f"\nTẠO GÓI CLASSIFIER LỖI: {exc}")
            messagebox.showerror("Không tạo được gói classifier", str(exc))

    def _start_training(self) -> None:
        data_path = Path(self.train_data_entry.get())
        model_path = self.train_model_entry.get().strip()
        if not data_path.exists():
            messagebox.showerror("Thiếu dataset", "Hãy export YOLO rồi chọn data.yaml.")
            return
        if not self.project:
            return
        expected_task = self.train_task_menu.get()
        if expected_task == "classify":
            if not self.project.attribute_classification_enabled:
                messagebox.showerror(
                    "Classification chưa bật",
                    "Hãy tick “Bật Classification thuộc tính” trong trang GÁN NHÃN hoặc chọn task classify lại.",
                )
                return
            classification_key = self._selected_classification_key()
            if not classification_key:
                messagebox.showerror("Chưa chọn nhóm", "Hãy chọn nhóm thuộc tính cần train Classification.")
                return
        else:
            classification_key = ""
        export_metadata: dict = {}
        metadata_path = (data_path / "export.json") if data_path.is_dir() else (data_path.parent / "export.json")
        if metadata_path.is_file():
            try:
                export_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                exported_task = export_metadata.get("task", "detect")
                if exported_task != expected_task:
                    messagebox.showerror("Sai loại dataset", f"Dataset là task {exported_task}, nhưng mục Train đang chọn {expected_task}.")
                    return
                if expected_task == "classify" and export_metadata.get("attribute_key") != classification_key:
                    messagebox.showerror(
                        "Sai nhóm thuộc tính",
                        "Dataset Classification được xuất cho nhóm khác với nhóm đang chọn trong trang Train.",
                    )
                    return
                if expected_task == "classify":
                    populated = [name for name, count in export_metadata.get("counts", {}).items() if count]
                    if len(populated) < 2:
                        messagebox.showerror(
                            "Classification cần ít nhất hai nhãn",
                            "Dataset hiện chỉ có một giá trị thuộc tính có ảnh. Hãy gán và duyệt dữ liệu cho ít nhất hai giá trị.",
                        )
                        return
            except (OSError, json.JSONDecodeError):
                pass
        try:
            if Path(model_path).is_file():
                from ultralytics import YOLO
                model_task = YOLO(model_path).task
                if model_task != expected_task:
                    messagebox.showerror(
                        "Model không đúng task",
                        f"Model đã chọn là {model_task}, nhưng dataset cần {expected_task}.\n"
                        "Hãy nhấn “Dùng model khởi tạo phù hợp” hoặc chọn checkpoint đúng task.",
                    )
                    return
            else:
                lower_name = Path(model_path).name.lower()
                required = {"segment": "-seg", "obb": "-obb", "pose": "-pose", "classify": "-cls"}.get(expected_task)
                if required and required not in lower_name:
                    messagebox.showerror("Model không đúng task", f"Task {expected_task} cần model có hậu tố {required}.pt.")
                    return
        except Exception as exc:
            messagebox.showerror("Không kiểm tra được model", str(exc))
            return
        try:
            epochs = int(self.epochs_entry.get())
            image_size = int(self.imgsz_entry.get())
            batch = int(self.batch_entry.get())
            patience = int(self.patience_entry.get())
            if epochs <= 0 or image_size <= 0 or batch == 0 or patience < 0:
                raise ValueError
            validate = bool(export_metadata.get("validation_enabled", True))
            split_strategy = str(export_metadata.get("split_strategy", DatasetManager.STRATEGY_LOCKED))
            config = TrainingConfig(
                model=model_path,
                data=str(data_path),
                project_dir=str(self.store.project_dir(self.project) / "runs"),
                task=expected_task,
                run_name=f"candidate_{expected_task}_{split_strategy}",
                epochs=epochs,
                image_size=image_size,
                batch=batch,
                patience=patience,
                device=self.train_device_menu.get(),
                validate=validate,
            )
        except ValueError:
            messagebox.showerror(
                "Sai thông số",
                "Epoch và Image size phải > 0; Batch khác 0; Patience phải ≥ 0. Tất cả phải là số nguyên.",
            )
            return
        self.train_log.delete("1.0", tk.END)
        if self.pending_training_note:
            self._append_log(self.train_log, self.pending_training_note)
            self.pending_training_note = ""
        if not config.validate:
            self._append_log(
                self.train_log,
                "CHẾ ĐỘ FINAL: Validation và early stopping đã tắt; Patience không được sử dụng. "
                f"Model sẽ chạy đủ {config.epochs} epoch.",
            )
        self.running_training_task = expected_task
        self.running_classification_key = classification_key
        self.training_job = TrainingJob(
            config,
            lambda line: self.event_queue.put(("train_line", line)),
            lambda code: self.event_queue.put(("train_done", code)),
        )
        self.training_job.start()

    def _stop_training(self) -> None:
        if self.batch_training_active:
            self.batch_training_cancelled = True
            self.batch_training_queue = []
        if self.training_job:
            self.training_job.stop()

    def _activate_latest_trained_model(self) -> Path | None:
        """Register the newest best.pt and make it the Auto-label model."""
        best = self._latest_best_pt()
        if best is None or not self.project:
            return None
        registered = self.store.register_model(best)
        self.deploy_model_path.set(str(best.resolve()))
        self.evaluation_model_path.set(str(best.resolve()))
        dataset = self._dataset_from_model_run(best)
        if self._dataset_has_independent_test(dataset):
            self.evaluation_data_path.set(str(dataset))
        self.model_path.set(str(registered))
        self.project.active_model = str(registered)
        self.store.save(self.project)
        self._append_log(self.train_log, f"Model tốt nhất: {best}\nĐã đưa vào AUTO-LABEL: {registered}")
        self._refresh_active_model_status()
        return registered

    def _activate_latest_classification_model(self) -> Path | None:
        best = self._latest_best_pt("classify")
        key = self.running_classification_key
        if best is None or not self.project or not key:
            return None
        registered = self.store.register_model(best)
        self.project.attribute_models[key] = str(registered)
        self.store.save(self.project)
        title = self._attribute_config(key)["title"]
        self._append_log(
            self.train_log,
            f"Classifier tốt nhất ({title}): {best}\nĐã lưu riêng trong hệ thống: {registered}\n"
            "Model này không thay thế model Detection/SEG dùng để định vị vật.",
        )
        return registered

    def _evaluate_model(self) -> None:
        if not self.project:
            messagebox.showerror("Chưa có dự án", "Hãy mở dự án trước khi đánh giá model.", parent=self)
            return
        if self.evaluation_running:
            messagebox.showinfo("Đang đánh giá", "Hãy chờ lần đánh giá hiện tại hoàn tất.", parent=self)
            return
        self._refresh_evaluation_defaults()
        model_path = Path(self.evaluation_model_path.get().strip())
        data_path = Path(self.evaluation_data_path.get().strip())
        if not model_path.is_file():
            messagebox.showerror("Thiếu model đánh giá", "Hãy chọn best.pt cần đánh giá ở hàng Model.", parent=self)
            return
        if not data_path.exists():
            messagebox.showerror(
                "Thiếu Dataset đánh giá",
                "Detection/SEG/OBB/ORI cần chọn data.yaml; Classification cần chọn thư mục Dataset.",
                parent=self,
            )
            return
        try:
            image_size = int(self.imgsz_entry.get())
        except ValueError:
            messagebox.showerror("Image size không hợp lệ", "Image size phải là số nguyên.", parent=self)
            return
        from .hardware import best_ultralytics_device

        device = best_ultralytics_device(self.train_device_menu.get())
        split = self.evaluation_split.get()
        output_root = self.store.project_dir(self.project) / "runs" / "evaluations"
        self.evaluation_running = True
        self._set_button_enabled(self.evaluation_button, False)
        self.evaluation_status_label.configure(text=f"Đang chạy {split}…", text_color=COLORS["warn"])
        self._append_log(
            self.train_log,
            f"\nBẮT ĐẦU ĐÁNH GIÁ · tập {split}\nModel: {model_path}\nDataset: {data_path}\nThiết bị: {device}",
        )

        def worker():
            try:
                result = evaluate_yolo_model(
                    model_path,
                    data_path,
                    split=split,
                    image_size=image_size,
                    device=device,
                    output_root=output_root,
                )
                self.event_queue.put(("evaluation_done", result))
            except Exception as exc:
                self.event_queue.put(("evaluation_error", str(exc)))

        Thread(target=worker, daemon=True).start()

    def _finish_evaluation(self, result: dict) -> None:
        self.evaluation_running = False
        self._set_button_enabled(self.evaluation_button, True)
        metrics = result.get("metrics", {})
        rating = str(result.get("rating", "Đã hoàn tất"))
        lines = [
            "\nĐÁNH GIÁ HOÀN TẤT",
            f"Task / tập: {result.get('task')} / {result.get('split')}",
            f"Nhận định: {rating}",
        ]
        if "map50_95" in metrics:
            lines.append(
                "Tổng: "
                f"Precision={metrics.get('precision', 0):.3f} · Recall={metrics.get('recall', 0):.3f} · "
                f"mAP50={metrics.get('map50', 0):.3f} · mAP50-95={metrics.get('map50_95', 0):.3f}"
            )
            lines.append("Theo Class:")
            for item in result.get("per_class", []):
                lines.append(
                    f"  {item['class_name']}: P={item['precision']:.3f} · R={item['recall']:.3f} · "
                    f"mAP50={item['map50']:.3f} · mAP50-95={item['map50_95']:.3f}"
                )
            self.evaluation_status_label.configure(
                text=f"mAP50-95 {metrics.get('map50_95', 0):.3f} · Recall {metrics.get('recall', 0):.3f}",
                text_color=COLORS["good"] if metrics.get("map50_95", 0) >= 0.65 and metrics.get("recall", 0) >= 0.80 else COLORS["warn"],
            )
        else:
            lines.append(f"Top-1={metrics.get('top1', 0):.3f} · Top-5={metrics.get('top5', 0):.3f}")
            self.evaluation_status_label.configure(text=f"Top-1 {metrics.get('top1', 0):.3f}", text_color=COLORS["good"])
        speed = result.get("speed_ms", {})
        if speed:
            total = sum(float(speed.get(key, 0)) for key in ("preprocess", "inference", "postprocess"))
            lines.append(f"Thời gian xử lý tham khảo: {total:.1f} ms/ảnh")
        lines.append(f"Báo cáo: {result.get('save_dir')}")
        self._append_log(self.train_log, "\n".join(lines))

    def _fail_evaluation(self, error: str) -> None:
        self.evaluation_running = False
        self._set_button_enabled(self.evaluation_button, True)
        self.evaluation_status_label.configure(text="Đánh giá lỗi", text_color=COLORS["bad"])
        self._append_log(self.train_log, f"ĐÁNH GIÁ LỖI: {error}")
        messagebox.showerror("Đánh giá model bị lỗi", error, parent=self)

    # ---------- hardware ----------
    def _build_hardware_tab(self) -> None:
        tab = self.tabs.tab("PHẦN CỨNG")
        card = self._card(tab, "RUNTIME VÀ THIẾT BỊ")
        card.pack(fill="both", expand=True, padx=8, pady=8)
        self._button(card, "Quét lại phần cứng", self._refresh_hardware, width=180).pack(anchor="w", padx=14, pady=8)
        self.hardware_info = ctk.CTkTextbox(card, fg_color="#091119", font=("Consolas", 13), corner_radius=10)
        self.hardware_info.pack(fill="both", expand=True, padx=14, pady=(4, 14))

    def _refresh_hardware(self) -> None:
        profile = inspect_hardware()
        cuda_text = f"CÓ · {profile.cuda_device}" if profile.cuda_available else "KHÔNG"
        text = (
            f"Python              : {profile.python}\n"
            f"Hệ điều hành        : {profile.os}\n\n"
            f"PyTorch             : {'Có' if profile.torch_available else 'Không'}\n"
            f"CUDA NVIDIA         : {cuda_text}\n"
            f"ONNX Runtime        : {'Có' if profile.onnxruntime_available else 'Không'}\n"
            f"ONNX providers      : {', '.join(profile.onnx_providers) or '-'}\n"
            f"OpenVINO            : {'Có' if profile.openvino_available else 'Không'}\n"
            f"OpenVINO devices    : {', '.join(profile.openvino_devices) or '-'}\n\n"
            "Máy hiện tại không có GPU: chọn auto hoặc cpu.\n"
            "Máy RTX 4060 Ti: cài NVIDIA Driver + PyTorch CUDA, sau đó chọn auto/cuda.\n"
            "NPU không phải yêu cầu của dự án này."
        )
        self.hardware_info.configure(state="normal")
        self.hardware_info.delete("1.0", tk.END)
        self.hardware_info.insert("1.0", text)
        self.hardware_info.configure(state="disabled")

    # ---------- shared refresh/events ----------
    def _refresh_everything(self, keep_image: bool = False) -> None:
        self._refresh_project_menu()
        self._refresh_image_list()
        if self.project:
            self.show_attribute_panel.set(bool(self.project.attribute_classification_enabled))
            class_ids = [item.id for item in sorted(self.project.classes, key=lambda item: item.id)]
            if class_ids and self.canvas.active_class_id not in class_ids:
                self.canvas.active_class_id = class_ids[0]
            self._rebuild_attribute_panel()
            self._apply_attribute_panel_visibility()
            self._refresh_classification_controls()
            self._refresh_label_choices()
            self._refresh_active_model_status()
            if self.project.images:
                if not (0 <= self.current_index < len(self.project.images)):
                    self.current_index = 0
                # A refresh rebuilds the thumbnail widgets, so always restore the
                # active image and its visible selection/focus afterwards.
                self._load_current_image()
            self._refresh_project_statistics()
            self._refresh_split_status()
        else:
            self._replace_text(self.project_summary, "Chưa có dự án. Nhấn Dự án mới để bắt đầu.")
            self._replace_text(self.dataset_info, "Chưa có dữ liệu.")
        self._refresh_hardware()

    def _refresh_project_statistics(self) -> None:
        if not self.project or not hasattr(self, "project_summary") or not hasattr(self, "dataset_info"):
            return
        summary = self.datasets.summary(self.project)
        text = [
            f"Dự án       : {self.project.name}",
            f"ID           : {self.project.id}",
            "Bài toán     : đa hình học · RECT / SEG / OBB / ORI",
            f"Số ảnh       : {summary['images']}",
            f"Số nhãn      : {summary['annotations']}",
            "",
            "TRẠNG THÁI",
        ]
        text.extend(f"  {key:12}: {value}" for key, value in summary["statuses"].items())
        text.append("\nTHEO CLASS")
        text.extend(f"  {key:20}: {value}" for key, value in summary["classes"].items())
        text.append("\nNGUỒN NHÃN")
        text.extend(f"  {key:20}: {value}" for key, value in summary["sources"].items())
        self._replace_text(self.project_summary, "\n".join(text))
        self._replace_text(self.dataset_info, "\n".join(text[3:]))

    @staticmethod
    def _replace_text(widget, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    @staticmethod
    def _append_log(widget, value: str) -> None:
        widget.insert(tk.END, value + "\n")
        widget.see(tk.END)

    def _set_status(self, text: str, color: str | None = None) -> None:
        self.title(f"DeltaX Smart Label Studio — {text}")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "status":
                    self._set_status(str(payload))
                elif kind == "error":
                    messagebox.showerror("Lỗi", str(payload))
                elif kind == "import_done":
                    added, skipped = payload
                    self._refresh_everything()
                    messagebox.showinfo("Nhập hoàn tất", f"Đã thêm: {added}\nBỏ qua ảnh trùng: {skipped}")
                elif kind == "auto_progress":
                    index, total, name = payload
                    self.auto_progress.set(index / max(total, 1))
                    self._append_log(self.auto_log, f"[{index:4}/{total}] {name}")
                elif kind == "auto_done":
                    self._append_log(self.auto_log, f"\nHoàn tất · {payload.processed} ảnh · {payload.detections} vật · task {payload.task} · {payload.elapsed_seconds:.1f}s · {payload.device}")
                    self._refresh_everything(keep_image=True)
                elif kind == "sam_done":
                    image_id, ann_id, request_version, points, score = payload
                    if self.project and self.sam_request_versions.get(ann_id) == request_version:
                        record = self.project.image_by_id(image_id)
                        ann = next((a for a in record.annotations if a.id == ann_id), None) if record else None
                        if ann and record:
                            is_current = 0 <= self.current_index < len(self.project.images) and self.project.images[self.current_index].id == image_id
                            if is_current:
                                self.canvas.checkpoint()
                            ann.kind = "polygon"
                            ann.points = points
                            ann.source = "sam2"
                            ann.confidence = score
                            ann.approved = False
                            if record.review_status == "reviewed":
                                record.review_status = "draft"
                            self.save_project()
                            if is_current:
                                self._refresh_image_list()
                                self._sync_image_list_to_current()
                                self._update_image_status_controls()
                                self.geometry_selector.set("SEG")
                                self._geometry_changed("SEG")
                                self.canvas.redraw()
                                self._annotation_selected(ann.id)
                            config_name = self.sam_adapter.config if self.sam_adapter else self.sam_config.get()
                            self._set_status(f"SAM2 tạo mask · confidence {score:.2f} · {config_name}")
                elif kind == "sam_click_done":
                    image_id, request_version, class_id, geometry, default_attributes, geometry_data, score = payload
                    if request_version == self.sam_click_request_version:
                        self.sam_click_busy = False
                        is_current = (
                            self.project is not None
                            and 0 <= self.current_index < len(self.project.images)
                            and self.project.images[self.current_index].id == image_id
                        )
                        if is_current:
                            record = self.project.images[self.current_index]
                            self.canvas.checkpoint()
                            ann = Annotation.create_box(
                                class_id,
                                geometry_data["bbox"],
                                source="sam2-point",
                                confidence=float(score),
                                model_version=self.sam_config.get(),
                            )
                            ann.attributes.update(default_attributes)
                            if geometry == "seg":
                                ann.kind = "polygon"
                                ann.points = geometry_data["points"]
                            elif geometry == "obb":
                                ann.kind = "obb"
                                ann.points = geometry_data["points"]
                                ann.obb = geometry_data["obb"]
                            elif geometry == "ori":
                                # SAM provides shape, but head/tail is semantic and
                                # must be supplied by one additional user click.
                                ann.kind = "polygon"
                                ann.points = geometry_data["points"]
                            record.annotations.append(ann)
                            record.review_status = "draft"
                            self.canvas.clear_prompts()
                            self.canvas.selected_id = ann.id
                            self._annotation_selected(ann.id)
                            self._annotation_changed()

                            if geometry == "ori":
                                self.sam_click_enabled.set(False)
                                self.geometry_selector.set("ORI")
                                self._geometry_changed("ORI")
                                self.canvas.selected_id = ann.id
                                self._annotation_selected(ann.id)
                                self.canvas.set_mode("orientation")
                                self._set_status("SAM đã tách vật · bấm thêm điểm về phía đầu/nắp để hoàn tất ORI")
                            else:
                                shown_geometry = geometry.upper() if geometry in {"rect", "seg", "obb"} else "RECT"
                                self.geometry_selector.set(shown_geometry)
                                self._geometry_changed(shown_geometry)
                                self.canvas.selected_id = ann.id
                                self._annotation_selected(ann.id)
                                self.canvas.redraw()
                                self._set_status(f"SAM ON đã tạo {shown_geometry} · confidence {score:.2f} · sẵn sàng bấm vật tiếp theo")
                elif kind == "sam_click_error":
                    request_version, error = payload
                    if request_version == self.sam_click_request_version:
                        self.sam_click_busy = False
                        self.canvas.clear_prompts()
                        messagebox.showerror("SAM ON", f"SAM2 không tạo được nhãn từ điểm đã chọn:\n{error}")
                        if self.sam_click_enabled.get():
                            self.canvas.set_mode("sam_click")
                elif kind == "sam_download_progress":
                    received, total = payload
                    percent = round(received * 100 / total) if total else 0
                    self.sam_status_label.configure(text=f"Đang tải SAM2… {percent}% · {received / 1024 / 1024:.1f} MB", text_color=COLORS["warn"])
                elif kind == "sam_download_done":
                    self.sam_checkpoint.set(str(payload))
                    if "sam2_hiera_s.yaml" in Sam2Adapter.available_configs():
                        self.sam_config.set("sam2_hiera_s.yaml")
                    self.sam_adapter = None
                    self._save_app_settings()
                    self._diagnose_sam2()
                elif kind == "train_line":
                    self._append_log(self.train_log, str(payload))
                elif kind == "evaluation_done":
                    self._finish_evaluation(payload)
                elif kind == "evaluation_error":
                    self._fail_evaluation(str(payload))
                elif kind == "train_done":
                    self._append_log(self.train_log, "\nTRAIN THÀNH CÔNG" if payload == 0 else f"\nTRAIN DỪNG/LỖI · mã {payload}")
                    if self.batch_training_active:
                        if payload == 0 and not self.batch_training_cancelled:
                            completed_key = self.running_classification_key
                            registered = self._activate_latest_classification_model()
                            if registered and completed_key:
                                self.batch_training_results[completed_key] = registered
                                self._append_log(
                                    self.train_log,
                                    f"Tiến độ hàng loạt: {len(self.batch_training_results)}/{self.batch_training_total}",
                                )
                                self.after(120, self._start_next_batch_classification_training)
                            else:
                                self._finish_batch_classification_training(
                                    error="Train xong nhưng không tìm thấy best.pt của nhóm hiện tại."
                                )
                        else:
                            reason = "Đã dừng theo yêu cầu." if self.batch_training_cancelled else f"Train lỗi với mã {payload}."
                            self._finish_batch_classification_training(cancelled=self.batch_training_cancelled, error=reason)
                    elif payload == 0:
                        if self.running_training_task == "classify":
                            self._activate_latest_classification_model()
                        else:
                            self._activate_latest_trained_model()
                elif kind == "rknn_line":
                    self._append_log(self.train_log, str(payload))
                elif kind == "rknn_done":
                    code, path, error = payload
                    completed_task = self.running_rknn_task
                    completed_key = self.running_rknn_attribute_key
                    cancelled = bool(self.model_export_job and self.model_export_job.cancel_event.is_set())
                    if self.rknn_batch_active:
                        if code == 0 and path and not self.rknn_batch_cancelled:
                            if self.project and completed_key:
                                self.project.attribute_rknn_models[completed_key] = str(Path(path).resolve())
                                self.store.save(self.project)
                            self.rknn_batch_completed += 1
                            self._append_log(
                                self.train_log,
                                f"RKNN hàng loạt: {self.rknn_batch_completed}/{self.rknn_batch_total} · {Path(path).name}",
                            )
                            self.after(120, self._start_next_batch_rknn_export)
                        else:
                            reason = "Đã dừng theo yêu cầu." if self.rknn_batch_cancelled else str(error or f"Mã lỗi {code}")
                            self._finish_batch_rknn_export(cancelled=self.rknn_batch_cancelled, error=reason)
                    else:
                        self._set_button_enabled(self.deploy_export_button, True)
                        self._set_button_enabled(self.deploy_stop_button, False)
                        if cancelled:
                            self.deploy_status_label.configure(text="Đã dừng xuất RKNN", text_color=COLORS["warn"])
                            self._append_log(self.train_log, "Đã dừng xuất RKNN theo yêu cầu.")
                        elif code == 0 and path:
                            if self.project:
                                if completed_task == "classify" and completed_key:
                                    self.project.attribute_rknn_models[completed_key] = str(Path(path).resolve())
                                elif completed_task in {"detect", "segment"}:
                                    self.project.active_rknn_model = str(Path(path).resolve())
                                self.store.save(self.project)
                            self.deploy_status_label.configure(
                                text=f"RKNN sẵn sàng cho Radxa: {Path(path).name}",
                                text_color=COLORS["good"],
                            )
                            messagebox.showinfo(
                                "Xuất RKNN hoàn tất",
                                f"File dùng cho Radxa đã được lưu tại:\n{path}\n\n"
                                "File RKNN không được thêm vào danh sách Auto-Label.",
                            )
                        else:
                            self.deploy_status_label.configure(text="Xuất RKNN thất bại", text_color=COLORS["bad"])
                            messagebox.showerror("Xuất RKNN lỗi", str(error or f"Mã lỗi {code}"))
                    self.running_rknn_task = ""
                    self.running_rknn_attribute_key = ""
        except Empty:
            pass
        self.after(100, self._drain_events)

    def _on_close(self) -> None:
        if self.project:
            self.store.save(self.project)
        self.cancel_event.set()
        if self.training_job:
            self.training_job.stop()
        if self.model_export_job:
            self.model_export_job.stop()
        self._save_app_settings()
        self.destroy()


def main() -> None:
    SmartLabelApp().mainloop()


if __name__ == "__main__":
    main()

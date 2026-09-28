"""Cancellable training preflight. Workers never access Tk widgets or variables."""
from copy import deepcopy
from pathlib import Path
from threading import Event, Thread
from time import monotonic
import json
import shutil


class PreparationCancelled(Exception):
    pass


class PreparationProgress:
    def __init__(self, emit, cancel_event=None, export_root=None):
        self.emit = emit
        self.cancel_event = cancel_event or Event()
        self.export_root = Path(export_root).resolve() if export_root else None
        self.created = []
        self.last_update = 0.0
        self.last_stage = ""

    def check(self):
        if self.cancel_event.is_set():
            raise PreparationCancelled()

    def report(self, stage, current=None, total=None):
        self.check()
        now = monotonic()
        if stage != self.last_stage or current == total or now - self.last_update >= .25:
            suffix = f" · {current}/{total} ảnh" if current is not None else ""
            self.emit(stage + suffix)
            self.last_update, self.last_stage = now, stage

    def reserve_export(self, path):
        """Only this job's exclusively created children may be removed on failure."""
        self.check()
        path = Path(path).resolve()
        if self.export_root is None or path.parent != self.export_root:
            raise ValueError("Thư mục chuẩn bị dataset nằm ngoài kho export của dự án.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()  # Never take ownership of an existing snapshot.
        self.created.append(path)

    def discard_exports(self):
        for path in self.created:
            try:
                if path.is_symlink() or path.resolve().parent != self.export_root:
                    raise ValueError("Đường dẫn đã đổi; giữ lại để kiểm tra.")
                shutil.rmtree(path)
            except (OSError, ValueError) as exc:
                self.emit(f"Chưa dọn được dataset tạm {path.name}: {exc}")
        self.created.clear()


def inspect_model(model_path, task, *, auto_classification=False):
    if Path(model_path).is_file():
        from ultralytics import YOLO
        actual = YOLO(model_path).task
        if actual == task:
            return model_path
        if auto_classification:
            return "yolo11n-cls.pt"
        raise ValueError(f"Model đã chọn là {actual}, nhưng dataset cần {task}. "
                         "Hãy dùng model khởi tạo phù hợp hoặc checkpoint đúng task.")
    required = {"segment": "-seg", "obb": "-obb", "pose": "-pose", "classify": "-cls"}.get(task)
    if required and required not in Path(model_path).name.lower():
        if auto_classification:
            return "yolo11n-cls.pt"
        raise ValueError(f"Task {task} cần model có hậu tố {required}.pt.")
    return model_path


def prepare_training(datasets, project, request, progress):
    from .split_health import SplitConflictError, classification_training_problem
    from .training_supplements import manifest_path
    from .fleet_boundaries import require_legacy_project

    task, options = request["task"], dict(request["options"])
    progress.report("[1/3] Kiểm tra nguồn ảnh và phân tập")
    require_legacy_project(project, datasets.store)
    health = datasets.split_health(project)
    if health["conflicts"]:
        raise SplitConflictError(health["conflicts"])
    # Resolve new groups once, then detect sidecar edits during the whole batch.
    datasets.ensure_split_assignment(project)
    sidecars = (datasets.split_assignment_path(project), manifest_path(datasets.store, project))
    def revisions():
        return tuple(path.read_bytes() if path.exists() else None for path in sidecars)
    baseline = revisions()
    progress.report("[2/3] Kiểm tra model khởi tạo (chưa chạy epoch)")
    options["model"] = inspect_model(options["model"], task, auto_classification=task == "classify")
    progress.check()
    prepared, problems = [], []
    keys = request["keys"] if task == "classify" else [("", task)]
    for index, (key, title) in enumerate(keys, 1):
        progress.report(f"[3/3] Chuẩn bị {title} · nhóm {index}/{len(keys)}")
        try:
            kwargs = dict(reviewed_only=request["reviewed_only"],
                          split_strategy=options["split_strategy"], progress=progress)
            if task == "classify":
                path = datasets.export_classification(project, key, **kwargs)
            else:
                path = datasets.export_yolo(project, task=task, **kwargs)
            progress.check()
            metadata = json.loads((path / "export.json").read_text(encoding="utf-8"))
            if task == "classify":
                problem = classification_training_problem(metadata)
                if problem:
                    raise ValueError(problem)
                if sum(bool(count) for count in metadata.get("counts", {}).values()) < 2:
                    raise ValueError("Cần ít nhất hai giá trị thuộc tính có crop.")
                progress.report(f"✓ {title}: {metadata.get('exported_crops', 0)} crop "
                                f"· {metadata.get('supplement_count', 0)} ảnh bổ trợ chỉ vào TRAIN")
            elif int(metadata.get("exported_annotations", 0)) <= 0:
                raise ValueError(f"Không có nhãn {task} hợp lệ để train. Hãy gán nhãn và duyệt ảnh.")
            prepared.append((key, path, metadata))
        except PreparationCancelled:
            raise
        except Exception as exc:
            problems.append(f"{title}: {exc}")
        if revisions() != baseline:
            raise ValueError("Phân tập hoặc ảnh bổ trợ đã đổi trong lúc chuẩn bị. "
                             "Chưa chạy train; hãy kiểm tra rồi bắt đầu lại.")
    if problems:
        raise ValueError("Hãy sửa dữ liệu của các nhóm sau rồi thử lại:\n\n" + "\n".join(problems))
    progress.check()
    return {"task": task, "options": options, "prepared": prepared}


class TrainingPreparationJob:
    def __init__(self, project, datasets, request, emit):
        self.source_project = project
        self.project = deepcopy(project)
        self.datasets = datasets
        self.request = deepcopy(request)
        self.emit = emit
        self.cancel_event = Event()
        self.thread = None

    def start(self):
        if self.thread is not None:
            raise RuntimeError("Lượt chuẩn bị này đã được khởi động.")
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel_event.set()

    def _run(self):
        result, error, cancelled = None, None, False
        progress = PreparationProgress(
            lambda text: self.emit("train_prepare_progress", (self, text)), self.cancel_event,
            self.datasets.store.project_dir(self.project) / "exports")
        try:
            result = prepare_training(self.datasets, self.project, self.request, progress)
            progress.check()
        except PreparationCancelled:
            cancelled = True
        except Exception as exc:
            error = exc
        if cancelled or error:
            progress.discard_exports()
            result = None
        self.emit("train_prepare_done", (self, result, error, cancelled))

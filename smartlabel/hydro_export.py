"""One Hydro package workflow, using the existing ONNX and bundle contracts."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import shutil

from .dataset_manager import DatasetManager
from .hydro_labels import model_attributes
from .hydroponic import (RUNTIME_TARGETS, describe_hydro_qa_issue, export_jetson_onnx,
                        hydro_dataset_qa, write_hydro_model_bundle)


class HydroExportCancelled(Exception):
    pass


def build_hydro_package(project, store, output, config, progress, cancel):
    """Build from a snapshot. Neither PTs nor project/split files are modified."""
    project = deepcopy(project)
    output = Path(output).resolve()
    archive = output.with_suffix(".zip")
    if output.exists() or output.is_symlink() or archive.exists() or archive.is_symlink():
        raise FileExistsError("Tên gói đã tồn tại; hãy chọn tên hoặc nơi lưu khác.")

    def checkpoint():
        if cancel.is_set():
            raise HydroExportCancelled()

    checkpoint()
    progress("[1/3] Kiểm tra model và chất lượng dữ liệu…")
    attrs = model_attributes(project)
    models = {attr["id"]: Path(project.attribute_models.get(attr["id"], "")) for attr in attrs}
    missing = [attr["displayName"] for attr in attrs
               if not models[attr["id"]].is_file() or models[attr["id"]].suffix.lower() != ".pt"]
    if missing:
        raise ValueError("Chưa có model đã train cho: " + ", ".join(missing))
    required = {"datasetVersion": "Phiên bản dataset", "sourceCommit": "Source commit",
                "cameraProfileIds": "Camera profile", "geometryProfileIds": "Geometry profile"}
    missing_config = [title for key, title in required.items() if not config.get(key)]
    if missing_config:
        raise ValueError("Cấu hình gói còn thiếu: " + ", ".join(missing_config))
    thresholds = config.get("thresholds", {})
    if set(thresholds) != set(models):
        raise ValueError("Cần ngưỡng đã hiệu chỉnh cho mọi nhóm model.")
    for key, threshold in thresholds.items():
        if not 0 <= float(threshold.get("lowThreshold", -1)) < float(threshold.get("highThreshold", -1)) <= 1:
            raise ValueError(f"Ngưỡng {key} cần thỏa 0 ≤ low < high ≤ 1.")
    runtime, mode = config.get("runtimeTarget"), config.get("deploymentMode")
    if runtime not in RUNTIME_TARGETS or mode not in {"shadow", "operational"}:
        raise ValueError("Runtime hoặc chế độ triển khai không hợp lệ.")
    if runtime == "windows_onnxruntime_cpu" and mode != "shadow":
        raise ValueError("Windows chỉ hỗ trợ chế độ shadow.")
    assignment = DatasetManager(store).ensure_split_assignment(project, persist=False)
    report = hydro_dataset_qa(project, store, assignment)
    errors = [issue for issue in report["issues"] if issue["severity"] == "error"]
    if errors:
        details = list(dict.fromkeys(describe_hydro_qa_issue(issue) for issue in errors))
        raise ValueError(f"Dataset còn {len(errors)} lỗi QA. Hãy mở Kiểm tra Dataset Hydro để xử lý.\n"
                         + "\n".join(details[:5]))
    project.metadata["validationStatus"] = report["validationStatus"]
    if mode == "operational" and report["validationStatus"] != "validated_holdout":
        raise ValueError("Chưa đủ QA holdout cho chế độ operational.")
    checkpoint()
    # Exporter writes beside its PT input. Copy PTs into job-owned staging first.
    with TemporaryDirectory(prefix=".hydro-package-", dir=output.parent) as directory:
        staging = Path(directory)
        onnx = {}
        for index, attr in enumerate(attrs, 1):
            checkpoint()
            key = attr["id"]
            progress(f"[2/3] Chuyển ONNX {index}/{len(attrs)} · {attr['displayName']}…")
            model_dir = staging / f"classifier_{index}"
            model_dir.mkdir()
            source = model_dir / "model.pt"
            shutil.copy2(models[key], source)
            checkpoint()
            onnx[key] = export_jetson_onnx(source, model_dir / "model.onnx", input_size=224, opset=12)
            checkpoint()
        progress("[3/3] Kiểm tra hợp đồng model và đóng gói ZIP…")
        bundle = write_hydro_model_bundle(
            project, staging / "bundle", onnx, config["thresholds"],
            dataset_version=config["datasetVersion"], source_commit=config["sourceCommit"],
            camera_profile_ids=config["cameraProfileIds"], geometry_profile_ids=config["geometryProfileIds"],
            input_size=224, runtime_target=config["runtimeTarget"], deployment_mode=config["deploymentMode"],
        )
        checkpoint()
        # Exclusive destinations: never replace a previous package. On failure,
        # remove only paths created by this job, both under the selected parent.
        made_output = made_archive = False
        try:
            output.mkdir()
            made_output = True
            shutil.copytree(bundle, output, dirs_exist_ok=True)
            with archive.open("xb") as target:
                made_archive = True
                with bundle.with_suffix(".zip").open("rb") as source:
                    shutil.copyfileobj(source, target)
        except Exception:
            if made_archive:
                archive.unlink(missing_ok=True)
            if made_output:
                if output.resolve().parent != output.parent:
                    raise RuntimeError("Đường dẫn gói đã thay đổi; giữ lại để kiểm tra thay vì xóa.")
                shutil.rmtree(output)
            raise
    return {
        "bundle": output, "archive": archive, "validationStatus": report["validationStatus"],
        "onnxModels": {key: str(output / "models" / f"{key}.onnx") for key in models},
    }


class HydroBundleJob:
    def __init__(self, project, store, output, config, emit):
        self.source_project = project
        self.project = deepcopy(project)
        self.store = store
        self.output = output
        self.config = deepcopy(config)
        self.emit = emit
        self.cancel_event = Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Đang tạo gói Hydro.")
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel_event.set()

    def _run(self):
        result, error, cancelled = None, "", False
        try:
            result = build_hydro_package(
                self.project, self.store, self.output, self.config,
                lambda message: self.emit("hydro_export_progress", (self, message)), self.cancel_event,
            )
        except HydroExportCancelled:
            cancelled = True
        except Exception as exc:
            error = str(exc)
        self.emit("hydro_export_done", (self, result, error, cancelled))

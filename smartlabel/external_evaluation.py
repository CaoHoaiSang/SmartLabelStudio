"""Checkpoint-bound external evaluation. TEST never selects thresholds or trains."""
from datetime import datetime, timezone
from pathlib import Path
import math
import re

from .benchmark_contract import (benchmark_root, canonical, cycle_key, digest, file_hash,
    image_identity, inside, read_json, source_identity, validate_benchmark)
from .fleet_boundaries import require_legacy_project, require_legacy_training_data
from .hydro_labels import model_attributes
from .hydro_model_tools import HydroClassifier, binary_metrics
from .label_schema import training_identity


def thresholds_valid(thresholds):
    return (isinstance(thresholds, dict) and set(thresholds) == {"lowThreshold", "highThreshold"}
            and all(type(v) in (int, float) and math.isfinite(v) for v in thresholds.values())
            and 0 <= thresholds["lowThreshold"] < thresholds["highThreshold"] <= 1)


def training_inventory(project, attr, dataset, *, validation_used=True):
    """Read actual checkpoint export, not the project's current split_assignment."""
    dataset = Path(dataset).absolute()
    require_legacy_training_data(dataset)
    metadata = read_json(inside(dataset, "export.json"))
    if (metadata.get("project_id") != project.id or metadata.get("attribute_key") != attr["id"]
            or metadata.get("classification_scope") != "image"
            or training_identity(metadata.get("label_attribute", attr)) != training_identity(attr)):
        raise ValueError("Dataset đã train không khớp project/thuộc tính/checkpoint.")
    # Old exports did not freeze provenance. Recover only exact unique filenames;
    # do not guess a crop from dates, directories or a filename prefix.
    provenance = metadata.get("source_records")
    legacy = provenance is None
    if legacy:
        provenance = [{"fileName": r.file_name, "source": source_identity(r), "originalSha256": r.sha256}
                      for r in project.images]
    by_name = {}
    for row in provenance:
        if row["fileName"] in by_name:
            raise ValueError("Nguồn ảnh train có tên trùng; chưa xác minh được vụ.")
        by_name[row["fileName"]] = row
    supplements = {r.get("exportedFile") for r in metadata.get("training_supplements", [])}
    files, cycles = [], {}
    original_hashes = {r['sha256'] for r in metadata.get("training_supplements", []) if r.get('sha256')}
    splits = ["train"] if (not validation_used and metadata.get("validation_enabled") is False
                           and metadata.get("split_strategy") in {"final_keep_test", "train_all"}) else ["train", "val"]
    for split in splits:
        folder = inside(dataset, split)
        for path in sorted(folder.rglob("*")) if folder.exists() else []:
            if not path.is_file():
                continue
            relative = path.relative_to(dataset).as_posix()
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                raise ValueError("Dataset train có tệp không phải ảnh được hỗ trợ.")
            identity = image_identity(inside(dataset, relative))
            record = by_name.get(path.name)
            if relative not in supplements:
                source = (record or {}).get("source", {})
                if not all(source.get(k) for k in ("siteId", "deviceId", "cropCycleId")):
                    raise ValueError("Thiếu nguồn vụ của ảnh đã train. Khôi phục project/export gốc; không tự khai ảnh đã học thành TEST.")
                cycles[cycle_key(source)] = source
                if record.get("originalSha256"):
                    original_hashes.add(record["originalSha256"])
            files.append({"path": relative, **identity})
    if not any(r["path"].startswith("train/") for r in files):
        raise ValueError("Thiếu ảnh train gốc để kiểm tra độc lập.")
    return {"dataset": str(dataset), "exportSha256": file_hash(dataset / "export.json"),
            "files": files, "cycles": list(cycles.values()), "splits": splits, "originalHashes": sorted(original_hashes),
            "provenanceMode": "legacy_filename_match" if legacy else "export_snapshot"}


def verify_inventory(inventory):
    dataset = Path(inventory["dataset"])
    require_legacy_training_data(dataset)
    if file_hash(inside(dataset, "export.json")) != inventory["exportSha256"]:
        raise ValueError("Bản kê dữ liệu đã train thay đổi sau đánh giá.")
    actual = []
    for split in inventory.get("splits", ["train", "val"]):
        folder = inside(dataset, split)
        for path in sorted(folder.rglob("*")) if folder.exists() else []:
            if path.is_file():
                relative = path.relative_to(dataset).as_posix()
                actual.append({"path": relative, **image_identity(inside(dataset, relative))})
    if actual != inventory["files"]:
        raise ValueError("Dữ liệu đã train đã đổi; cần kiểm tra và đánh giá lại.")


def reject_overlap(manifest, inventory):
    hashes = {r["sha256"] for r in inventory["files"]} | set(inventory.get("originalHashes", []))
    pixels = {r["pixelSha256"] for r in inventory["files"]}
    for row in manifest["records"]:
        if row["sha256"] in hashes or row["pixelSha256"] in pixels:
            raise ValueError("Ảnh TEST trùng byte/pixel với TRAIN hoặc VAL của checkpoint.")
        candidate = row["source"]
        for learned in inventory["cycles"]:
            known_gateways = candidate.get("fleetDeviceId") and learned.get("fleetDeviceId")
            same = cycle_key(candidate) == cycle_key(learned) if known_gateways else candidate["cropCycleId"] == learned["cropCycleId"]
            if same:
                raise ValueError("Vụ TEST trùng vụ đã dùng để train/validation checkpoint. Thiếu namespace Gateway thì chặn bảo thủ theo mã vụ.")


def operating_metrics(samples, thresholds):
    low, high = thresholds["lowThreshold"], thresholds["highThreshold"]
    decided = [(y, p) for y, p in samples if p <= low or p >= high]
    result = binary_metrics(decided, center=high)
    result.update(total=len(samples), uncertain=len(samples) - len(decided),
                  coverage=len(decided) / len(samples),
                  positiveSupport=sum(y == 1 for y, _ in samples), negativeSupport=sum(y == 0 for y, _ in samples))
    result["positiveDetectionRateAll"] = sum(y == 1 and p >= high for y, p in samples) / result["positiveSupport"]
    return result


def evaluate_external(project, store, benchmark_id, thresholds, *, device="cpu", progress=lambda *_: None,
                      cancel=None, independence_confirmed=False, classifier_factory=HydroClassifier):
    require_legacy_project(project, store)
    if independence_confirmed is not True:
        raise ValueError("Cần xác nhận bộ TEST chưa dùng để học/chọn model/ngưỡng, kể cả model cha.")
    root = benchmark_root(store, project, benchmark_id)
    manifest, fingerprint = validate_benchmark(root, project, cancel=cancel)
    if benchmark_id != "benchmark_" + fingerprint:
        raise ValueError("Bộ TEST được quản lý đã thay đổi.")
    attrs = model_attributes(project)
    if set(thresholds) != {a["id"] for a in attrs} or not all(thresholds_valid(v) for v in thresholds.values()):
        raise ValueError("Cần cố định low/high hợp lệ cho mọi model trước khi đánh giá TEST.")
    # Hash before loading/scoring; copied checkpoint per job prevents replacement
    # at the original path from changing a classifier halfway through evaluation.
    from tempfile import TemporaryDirectory
    import shutil
    results = {}
    for attr in attrs:
        path = Path(project.attribute_models.get(attr["id"], ""))
        if not path.is_file() or path.suffix.lower() != ".pt":
            raise ValueError(f"{attr['displayName']}: chưa có checkpoint PT để đánh giá. Chọn model đã train trước.")
    starting_hashes = {a["id"]: file_hash(project.attribute_models[a["id"]]) for a in attrs}
    with TemporaryDirectory(prefix="hydro-evaluation-") as temp:
        for attr in attrs:
            key = attr["id"]
            if cancel and cancel.is_set():
                raise ValueError("Đã hủy đánh giá; chưa tạo bằng chứng.")
            original = Path(project.attribute_models[key])
            if original.suffix.lower() != ".pt":
                raise ValueError("Đánh giá gói Hydro yêu cầu checkpoint PT.")
            checkpoint = Path(temp) / f"{key}.pt"
            shutil.copy2(original, checkpoint)
            if file_hash(checkpoint) != starting_hashes[key]:
                raise ValueError("Checkpoint đổi khi bắt đầu đánh giá.")
            classifier = classifier_factory(attr, checkpoint, device)
            args = getattr(classifier.model, "ckpt", {}).get("train_args", {})
            if not args.get("data"):
                raise ValueError("Checkpoint không lưu nguồn dataset đã train.")
            inventory = training_inventory(project, attr, args["data"], validation_used=args.get("val") is not False)
            reject_overlap(manifest, inventory)
            targets = [r for r in manifest["records"] if r["labels"][key] in {"positive", "negative"}]
            if {r["labels"][key] for r in targets} != {"positive", "negative"}:
                raise ValueError(f"{attr['displayName']}: bộ TEST cần cả ảnh Có và Không đã duyệt.")
            predictions, samples = [], []
            for index, row in enumerate(targets, 1):
                if cancel and cancel.is_set():
                    raise ValueError("Đã hủy đánh giá; chưa tạo bằng chứng.")
                progress(index, len(targets), attr["displayName"])
                score = classifier.score(inside(root, row["path"]))
                if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("Model trả xác suất không hợp lệ.")
                truth = int(row["labels"][key] == "positive")
                samples.append((truth, score))
                predictions.append({"sha256": row["sha256"], "truth": truth, "positiveScore": score})
            verify_inventory(inventory)
            results[key] = {"checkpointSha256": starting_hashes[key], "attributeIdentity": training_identity(attr),
                            "thresholds": thresholds[key], "trainingInventory": inventory,
                            "metricsAtHalf": binary_metrics(samples), "operatingMetrics": operating_metrics(samples, thresholds[key]),
                            "predictions": predictions}
    if validate_benchmark(root, project)[1] != fingerprint or any(file_hash(project.attribute_models[k]) != v for k, v in starting_hashes.items()):
        raise ValueError("Model hoặc bộ TEST đổi trong lúc đánh giá; kết quả không được ghi nhận.")
    if cancel and cancel.is_set():
        raise ValueError("Đã hủy đánh giá; chưa tạo bằng chứng.")
    report = {"schemaVersion": "HydroExternalEvaluationV1", "projectId": project.id,
              "benchmarkId": benchmark_id, "benchmarkSha256": fingerprint,
              "independenceAttested": True, "createdAt": datetime.now(timezone.utc).isoformat(), "models": results}
    report_id = "evaluation_" + digest(report)
    reports = benchmark_root(store, project) / "evaluations"
    reports.mkdir(exist_ok=True)
    with inside(reports, report_id + ".json").open("x", encoding="utf-8") as output:
        output.write(canonical(report))
    return report_id, report


def load_evaluation(project, store, report_id):
    if not isinstance(report_id, str) or not re.fullmatch(r"evaluation_[a-f0-9]{64}", report_id):
        raise ValueError("Mã báo cáo đánh giá không hợp lệ.")
    report = read_json(inside(benchmark_root(store, project) / "evaluations", report_id + ".json"), 64 * 1024 * 1024)
    if report_id != "evaluation_" + digest(report) or report.get("schemaVersion") != "HydroExternalEvaluationV1" or report.get("projectId") != project.id:
        raise ValueError("Báo cáo đánh giá sai project hoặc đã thay đổi.")
    return report


def approve_evaluation(project, store, report_id, *, confirmed=False, cancel=None):
    if confirmed is not True:
        raise ValueError("Cần kỹ thuật viên xem chỉ số và xác nhận bằng chứng.")
    report = load_evaluation(project, store, report_id)
    validate_evidence(project, store, report, {k: v["thresholds"] for k, v in report["models"].items()})
    # Caller owns the project lock; rollback in-memory metadata if atomic save fails.
    from copy import deepcopy
    before = deepcopy(project.metadata)
    if cancel and cancel.is_set():
        raise ValueError("Đã hủy; chưa duyệt bằng chứng.")
    project.metadata["hydroExternalEvaluationApproval"] = {"reportId": report_id,
        "reviewedAt": datetime.now(timezone.utc).isoformat(), "reportSha256": digest(report)}
    project.metadata["hydroThresholds"] = {k: deepcopy(v["thresholds"]) for k, v in report["models"].items()}
    project.metadata["hydroThresholdModelHashes"] = {k: v["checkpointSha256"] for k, v in report["models"].items()}
    try:
        store.save(project)
    except Exception:
        project.metadata = before
        raise


def validate_evidence(project, store, report, thresholds):
    require_legacy_project(project, store)
    attrs = model_attributes(project)
    if set(report["models"]) != {a["id"] for a in attrs} or set(thresholds) != set(report["models"]):
        raise ValueError("Bằng chứng chưa bao phủ mọi thuộc tính của gói.")
    manifest, fingerprint = validate_benchmark(benchmark_root(store, project, report["benchmarkId"]), project)
    if fingerprint != report["benchmarkSha256"] or report["benchmarkId"] != "benchmark_" + fingerprint:
        raise ValueError("Bộ TEST thay đổi sau đánh giá.")
    if report.get("independenceAttested") is not True:
        raise ValueError("Chưa xác nhận lịch sử độc lập của bộ TEST.")
    for attr in attrs:
        key = attr["id"]; evidence = report["models"][key]
        if file_hash(project.attribute_models[key]) != evidence["checkpointSha256"]:
            raise ValueError(f"{attr['displayName']}: checkpoint đã đổi; hãy đánh giá lại đúng model.")
        if canonical(training_identity(attr)) != canonical(evidence["attributeIdentity"]) or thresholds[key] != evidence["thresholds"]:
            raise ValueError(f"{attr['displayName']}: schema/ngưỡng đã đổi; bằng chứng cũ không áp dụng.")
        verify_inventory(evidence["trainingInventory"])
        reject_overlap(manifest, evidence["trainingInventory"])
    return report


def release_evidence(project, store, thresholds):
    approval = project.metadata.get("hydroExternalEvaluationApproval", {})
    if not approval.get("reportId") or not approval.get("reviewedAt"):
        raise ValueError("Chưa có đánh giá gắn checkpoint được duyệt. Mở Dataset → Bộ TEST ngoài → Đánh giá → Duyệt kết quả; TEST chỉ chia nhóm chưa đủ.")
    report = load_evaluation(project, store, approval["reportId"])
    if approval.get("reportSha256") != digest(report):
        raise ValueError("Phê duyệt không khớp báo cáo đánh giá.")
    validate_evidence(project, store, report, thresholds)
    return {"schemaVersion": "HydroReleaseEvidenceV1", "reportSha256": digest(report),
            "benchmarkSha256": report["benchmarkSha256"], "reviewedAt": approval["reviewedAt"],
            "independenceBasis": "export_provenance_and_operator_attestation",
            "models": {k: {"checkpointSha256": v["checkpointSha256"], "attributeIdentity": v["attributeIdentity"],
                       "thresholds": v["thresholds"], "metricsAtHalf": v["metricsAtHalf"],
                       "operatingMetrics": v["operatingMetrics"], "trainingInventorySha256": digest(v["trainingInventory"])}
                       for k, v in report["models"].items()}}

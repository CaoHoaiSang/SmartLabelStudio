"""Hydro image classifiers. Object localization/RKNN remain separate adapters."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json
import math

from .hardware import best_ultralytics_device
from .hydro_labels import model_attributes
from .hydroponic import is_hydroponic_project
from .label_schema import label_for, meaning_for, training_identity, validate_model_labels

INITIAL_THRESHOLDS = {"lowThreshold": 0.30, "highThreshold": 0.70}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def threshold_defaults(project):
    thresholds, sources = {}, {}
    for attr in model_attributes(project):
        key = attr["id"]
        thresholds[key] = dict(INITIAL_THRESHOLDS)
        sources[key] = "Khởi đầu 0.30 / 0.70 · chưa hiệu chỉnh"
        saved = project.metadata.get("hydroThresholds", {}).get(key)
        path = Path(project.attribute_models.get(key, ""))
        current_hash = file_hash(path) if path.is_file() else None
        saved_hash = project.metadata.get("hydroThresholdModelHashes", {}).get(key)
        if saved and saved_hash and saved_hash != current_hash:
            sources[key] = "Checkpoint đã đổi · không dùng ngưỡng cũ; khởi đầu 0.30 / 0.70, cần đánh giá VAL lại"
        if saved and saved_hash and saved_hash == current_hash:
            thresholds[key] = deepcopy(saved)
            sources[key] = "Giá trị đã xác nhận cho checkpoint hiện tại"
            continue
        if saved and not saved_hash:
            thresholds[key] = deepcopy(saved)
            sources[key] = "Giá trị đã lưu · cần kiểm tra lại nếu model đã đổi"
        report = project.metadata.get("hydroEvaluations", {}).get(key, {}).get("val", {})
        recommendation = report.get("recommendedThresholds")
        if (recommendation and current_hash and report.get("modelSha256") == current_hash
                and json.dumps(report.get("attributeIdentity"), sort_keys=True) == json.dumps(training_identity(attr), sort_keys=True)):
            thresholds[key] = deepcopy(recommendation)
            sources[key] = f"Gợi ý từ validation · {report['metrics']['samples']} ảnh · cần xác nhận hiện trường"
    return thresholds, sources


class HydroClassifier:
    def __init__(self, attribute, path, device="auto"):
        from ultralytics import YOLO
        self.path = Path(path)
        if not self.path.is_file() or self.path.suffix.lower() != ".pt":
            raise ValueError(f"Chưa có checkpoint PT cho {attribute['displayName']}.")
        self.model = YOLO(str(self.path))
        if self.model.task != "classify":
            raise ValueError(f"{attribute['displayName']}: cần classifier toàn ảnh, không phải model định vị.")
        names = self.model.names
        labels = list(names) if isinstance(names, list) else [names[i] for i in sorted(names)]
        positive, negative = label_for(attribute, "positive"), label_for(attribute, "negative")
        if len(labels) != 2 or set(labels) != {positive, negative}:
            raise ValueError(f"{attribute['displayName']}: nhãn model không khớp mã/ý nghĩa thuộc tính.")
        self.positive_index = labels.index(positive)
        validate_model_labels(attribute, {"attributeId": attribute["id"], "outputLabels": labels,
                              "positiveIndex": self.positive_index, "negativeIndex": labels.index(negative)})
        self.device = best_ultralytics_device(device)

    def score(self, path):
        results = self.model.predict(source=str(path), imgsz=224, device=self.device, verbose=False, save=False)
        if len(results) != 1 or results[0].probs is None:
            raise ValueError("Classifier không trả xác suất toàn ảnh.")
        values = results[0].probs.data.tolist()
        if len(values) != 2 or any(not math.isfinite(float(v)) or not 0 <= float(v) <= 1 for v in values):
            raise ValueError("Xác suất classifier không hợp lệ.")
        return float(values[self.positive_index])


def propose_hydro_labels(project, store, *, device, confidence, unlabeled_only, replace_predictions,
                         progress, cancel_event, classifier_factory=HydroClassifier):
    """Read a snapshot; return drafts for conflict-checked application on the UI thread."""
    if not is_hydroponic_project(project):
        raise ValueError("Luồng thuộc tính Hydro chỉ nhận dự án Hydro.")
    if not 0.5 < confidence < 1:
        raise ValueError("Độ tin cậy gợi ý Hydro phải lớn hơn 0.5 và nhỏ hơn 1.")
    attrs = model_attributes(project)
    presence = next(a for a in attrs if a["role"] == "presence")
    attrs = [presence] + [a for a in attrs if a["role"] != "presence"]
    classifiers = {a["id"]: classifier_factory(a, project.attribute_models.get(a["id"], ""), device) for a in attrs}
    proposals, failed, skipped = [], [], 0
    for index, record in enumerate(project.images, 1):
        if cancel_event.is_set():
            break
        progress(index, len(project.images), record.file_name)
        if record.review_status in {"reviewed", "rejected"} or record.asset_role != "slot":
            skipped += 1
            continue
        prior = record.metadata.get("hydroAutoLabels", {})
        manual = record.metadata.get("hydroManualAttributes", [])
        def eligible(attr):
            key = attr["id"]
            if key in manual:
                return False
            value = record.attributes.get(key)
            if not value:
                return True
            if prior.get(key, {}).get("value") == value:
                return not unlabeled_only and replace_predictions
            if record.metadata.get("hydroAttributeDefaults", {}).get(key) == value and not prior.get(key):
                return True
            return (record.review_status == "unlabeled" and not prior.get(key)
                    and meaning_for(attr, value) in {"uncertain", "not_applicable"})
        if not any(eligible(a) for a in attrs):
            skipped += 1
            continue
        values, provenance = deepcopy(record.attributes), deepcopy(prior)
        try:
            for attr in attrs:
                key = attr["id"]
                if not eligible(attr):
                    continue
                score = None
                if attr["role"] == "condition" and meaning_for(presence, values.get(presence["id"])) != "positive":
                    meaning = "not_applicable"
                else:
                    score = classifiers[key].score(store.image_path(project, record))
                    meaning = "positive" if score >= confidence else "negative" if score <= 1 - confidence else "uncertain"
                values[key] = label_for(attr, meaning)
                provenance[key] = {"value": values[key], "positiveScore": score,
                                   "model": project.attribute_models[key], "source": "hydro_classifier"}
            # Never force an AI presence decision over manual condition labels.
            if meaning_for(presence, values.get(presence["id"])) != "positive" and any(
                    a["role"] == "condition" and values.get(a["id"]) and
                    meaning_for(a, values[a["id"]]) != "not_applicable" for a in attrs):
                skipped += 1
                continue
            proposals.append({"id": record.id, "before": deepcopy(record.attributes),
                              "status": record.review_status, "metadataBefore": deepcopy(record.metadata),
                              "values": values, "provenance": provenance})
        except Exception as exc:
            failed.append(f"{record.file_name}: {exc}")
    return {"proposals": proposals, "failed": failed, "skipped": skipped, "cancelled": cancel_event.is_set()}


def apply_hydro_proposals(project, result):
    applied, conflicts = 0, 0
    for proposal in result["proposals"]:
        record = project.image_by_id(proposal["id"])
        if (record is None or record.attributes != proposal["before"] or record.review_status != proposal["status"]
                or record.metadata != proposal["metadataBefore"]):
            conflicts += 1
            continue
        record.attributes = proposal["values"]
        record.metadata["hydroAutoLabels"] = proposal["provenance"]
        record.review_status = "draft"
        applied += 1
    return applied, conflicts


def binary_metrics(samples, center=0.5):
    tp = sum(y == 1 and p >= center for y, p in samples)
    tn = sum(y == 0 and p < center for y, p in samples)
    fp = sum(y == 0 and p >= center for y, p in samples)
    fn = sum(y == 1 and p < center for y, p in samples)
    precision, recall = tp / (tp + fp) if tp + fp else 0, tp / (tp + fn) if tp + fn else 0
    specificity = tn / (tn + fp) if tn + fp else 0
    return {"samples": len(samples), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "accuracy": (tp + tn) / len(samples) if samples else 0, "precision": precision,
            "recall": recall, "specificity": specificity, "balancedAccuracy": (recall + specificity) / 2,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0}


def recommend_thresholds(samples, split):
    # A transparent starting rule, not a calibrated probability or acceptance guarantee.
    if split != "val" or min(sum(y == c for y, _ in samples) for c in (0, 1)) < 20:
        return None
    centers = [i / 100 for i in range(10, 91)]
    center = max(centers, key=lambda t: (binary_metrics(samples, t)["balancedAccuracy"], -abs(t - 0.5)))
    if binary_metrics(samples, center)["balancedAccuracy"] < 0.65:
        return None
    return {"lowThreshold": round(max(0, center - 0.1), 2), "highThreshold": round(min(1, center + 0.1), 2)}


def classifier_assessment(result):
    """Describe measured evidence, never turn a metric band into release approval."""
    m = result["metrics"]
    positive, negative = m["tp"] + m["fn"], m["tn"] + m["fp"]
    lines = ["Nhận định: " + ("Chưa phát hiện lỗi trên bộ ảnh này ở ngưỡng 0.50."
             if m["samples"] and m["fp"] + m["fn"] == 0 else
             f"Còn {m['fp']} lần báo nhầm Có và {m['fn']} lần bỏ sót Có ở ngưỡng 0.50.")]
    lines.append(f"Độ phủ mẫu: Có={positive} · Không={negative}. "
                 "Ảnh cùng cây/vụ không tương đương từng ấy tình huống độc lập.")
    if min(positive, negative) < 20:
        lines.append("Một phía có dưới 20 ảnh: bằng chứng còn ít, cần bổ sung trường hợp đa dạng; "
                     "đây là lưu ý về dữ liệu, không phải điều kiện tự động đạt/rớt vận hành.")
    lines.append("Phạm vi: chỉ thuộc tính này trên bộ ảnh của checkpoint; không chứng minh độ chính xác "
                 "100% ngoài giàn, độc lập mùa vụ hoặc chất lượng các classifier còn lại.")
    lines.append("Ngưỡng 0.50 chia Có/Không để so sánh; chưa đo vùng Chưa chắc chắn của bộ low/high vận hành.")
    if result["split"] == "test":
        lines.append("Không gợi ý ngưỡng từ TEST — đúng nguyên tắc, không phải lỗi hay do thiếu 20 ảnh. "
                     "Muốn chọn ngưỡng, đánh giá VAL chưa dùng train của đúng checkpoint trước; giữ TEST để đánh giá sau khi chốt.")
    elif min(positive, negative) < 20:
        lines.append("Chưa gợi ý ngưỡng từ VAL: quy tắc hiện tại cần ít nhất 20 ảnh Có và 20 ảnh Không.")
    elif not result.get("recommendedThresholds"):
        lines.append("Chưa gợi ý ngưỡng từ VAL: balanced accuracy tốt nhất trong khoảng tìm kiếm chưa đạt 0.65.")
    else:
        t = result["recommendedThresholds"]
        lines.append(f"Gợi ý VAL low/high: {t['lowThreshold']:.2f}/{t['highThreshold']:.2f}. "
                     "Chỉ là điểm khởi đầu; đối chiếu báo nhầm, bỏ sót và số ảnh Chưa chắc chắn trước khi chốt.")
    lines.append("Vận hành: đánh giá/duyệt TEST ngoài với đúng checkpoint và bộ ngưỡng đã chốt; báo cáo này không tự cấp quyền phát hành.")
    return "\n".join(lines)


def evaluate_hydro_attribute(project, attribute_key, store, *, split, device, progress,
                             classifier_factory=HydroClassifier):
    if not is_hydroponic_project(project) or split not in {"val", "test"}:
        raise ValueError("Đánh giá Hydro yêu cầu dự án Hydro và tập val/test.")
    attr = next(a for a in model_attributes(project) if a["id"] == attribute_key)
    path = Path(project.attribute_models.get(attribute_key, ""))
    classifier = classifier_factory(attr, path, device)
    args = getattr(classifier.model, "ckpt", {}).get("train_args", {})
    dataset = Path(str(args.get("data") or ""))
    metadata_path = dataset / "export.json"
    if not metadata_path.is_file():
        raise ValueError("Không tìm thấy dataset gốc của checkpoint. Hãy khôi phục thư mục export đã dùng để train.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (metadata.get("project_id") != project.id or metadata.get("attribute_key") != attribute_key
            or metadata.get("classification_scope") != "image"
            or training_identity(metadata.get("label_attribute", attr)) != training_identity(attr)):
        raise ValueError("Dataset/checkpoint không khớp dự án và thuộc tính Hydro.")
    flag = "validation_enabled" if split == "val" else "independent_test"
    if not metadata.get(flag) or (split == "val" and metadata.get("split_strategy") != "locked"):
        raise ValueError(f"Dataset này không có tập {split} độc lập. Không đánh giá trên bản sao dữ liệu train.")
    classes = metadata["classes"]
    extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    def images(folder):
        return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in extensions)
    targets = []
    for meaning, label in (("negative", 0), ("positive", 1)):
        folder = dataset / split / classes[label_for(attr, meaning)]
        files = images(folder)
        if not files:
            raise ValueError(f"Tập {split} thiếu ảnh {meaning}; chưa đủ đánh giá hai phía.")
        targets.extend((p, label) for p in files)
    train_hashes = {file_hash(p) for p in images(dataset / "train")}
    if not train_hashes:
        raise ValueError("Thiếu dữ liệu train gốc để kiểm tra trùng ảnh với tập đánh giá.")
    rows, samples = [], []
    for index, (image, truth) in enumerate(targets, 1):
        digest = file_hash(image)
        if digest in train_hashes:
            raise ValueError("Phát hiện ảnh đánh giá trùng nội dung tập train; hãy sửa phân tập trước.")
        progress(index, len(targets), image.name)
        score = classifier.score(image)
        samples.append((truth, score))
        rows.append({"image": str(image.relative_to(dataset)), "sha256": digest, "truth": truth, "positiveScore": score})
    result = {"task": "hydro_classify", "attributeId": attribute_key, "title": attr["displayName"],
              "attributeIdentity": training_identity(attr), "model": str(path), "modelSha256": file_hash(path),
              "dataset": str(dataset), "split": split, "metrics": binary_metrics(samples),
              "recommendedThresholds": recommend_thresholds(samples, split), "predictions": rows,
              "thresholdMethod": "validation_balanced_accuracy_margin_0.10_min20_per_class",
              "rating": "Chỉ số ở ngưỡng 0.50; gợi ý low/high chỉ lấy từ val, cần xác nhận hiện trường."}
    result["assessment"] = classifier_assessment(result)
    destination = store.project_dir(project) / "runs" / "evaluations" / f"hydro_{attribute_key}_{split}_{datetime.now():%Y%m%d_%H%M%S_%f}"
    destination.mkdir(parents=True, exist_ok=False)
    result["save_dir"] = str(destination)
    (destination / "evaluation_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result

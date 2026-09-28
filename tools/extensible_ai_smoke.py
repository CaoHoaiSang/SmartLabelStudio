"""Offline cross-repository smoke. Synthetic data, temporary files, no hardware.

Trains small linear classifiers with NumPy (not an agronomic model), packages
real static ONNX, runs the camera ONNX adapter, and validates/persists into the
backend's in-memory test database. Does not contact production HTTP/Mongo/MQTT.
"""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smartlabel.hydroponic import apply_hydroponic_slot_template, import_capture_manifest, hydro_dataset_qa, write_hydro_model_bundle
from smartlabel.hydro_labels import install_label_schema, model_attributes
from smartlabel.label_schema import label_for
from smartlabel.project_store import ProjectStore
from smartlabel.dataset_manager import DatasetManager


def train_toy_onnx(dataset, attribute, target):
    import numpy as np
    import onnx
    from onnx import helper, TensorProto, numpy_helper
    from PIL import Image
    labels = [label_for(attribute, "positive"), label_for(attribute, "negative")]
    features, targets = [], []
    for index, label in enumerate(labels):
        for path in sorted((dataset / "train" / label).glob("*.jpg")):
            with Image.open(path) as image:
                features.append(np.asarray(image.convert("RGB"), dtype=np.float32).mean(axis=(0, 1)) / 255)
            targets.append(float(index == 0))
    x = np.asarray(features, dtype=np.float32)
    y = np.asarray(targets, dtype=np.float32)
    if len(set(targets)) != 2:
        raise ValueError("Toy training requires both labels in the training split")
    weights, bias = np.zeros(3, dtype=np.float32), 0.0
    for _ in range(300):
        prob = 1 / (1 + np.exp(-(x @ weights + bias)))
        error = prob - y
        weights -= .5 * x.T @ error / len(x)
        bias -= .5 * float(error.mean())
    w = np.stack([weights, np.zeros(3, dtype=np.float32)], axis=1).astype(np.float32)
    b = np.asarray([bias, 0], dtype=np.float32)
    graph = helper.make_graph([
        helper.make_node("ReduceMean", ["images"], ["rgb"], axes=[2, 3], keepdims=0),
        helper.make_node("Gemm", ["rgb", "weights", "bias"], ["logits"]),
        helper.make_node("Softmax", ["logits"], ["probabilities"], axis=1),
    ], "SYNTHETIC_PIPELINE_TEST_ONLY",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 224, 224])],
        [helper.make_tensor_value_info("probabilities", TensorProto.FLOAT, [1, 2])],
        [numpy_helper.from_array(w, "weights"), numpy_helper.from_array(b, "bias")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 12)])
    model.ir_version = 7
    helper.set_model_props(model, {"names": repr(dict(enumerate(labels))), "task": "classify",
                                  "purpose": "synthetic_pipeline_smoke_only"})
    onnx.checker.check_model(model)
    onnx.save(model, target)
    return weights, bias


def run(hydro_root):
    import numpy as np
    from PIL import Image
    camera_root = hydro_root / "03_Edge_Server/ai_camera"
    sys.path[:0] = [str(camera_root), str(camera_root / "tests")]
    from test_camera_mvp import site_profile, camera_profile, geometry_profile
    from hydro_ai_camera.capture_pipeline import write_capture
    from hydro_ai_camera.model_bundle import validate_bundle, activate_onnx_bundle
    from hydro_ai_camera.inference import ActiveBundleInference, preprocess_slot
    from hydro_ai_camera.contracts import sha256_file
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix="hydro-extensible-smoke-") as directory:
        root = Path(directory)
        store = ProjectStore(root / "workspace")
        project = store.create_project("Synthetic V3 pipeline", task="classify")
        apply_hydroponic_slot_template(project)
        schema = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/label_schema_v1.json").read_text(encoding="utf-8"))
        install_label_schema(project, schema)
        captures = []
        rng = np.random.default_rng(4096)
        for capture_number in range(6):
            frame = rng.integers(0, 100, (1080, 1920, 3), dtype=np.uint8)
            for slot_number, slot in enumerate(geometry_profile()["slots"]):
                rect = slot["rect"]
                # Artificial color patches, not plants. Texture satisfies image quality gates.
                channel = (capture_number + slot_number) % 2
                frame[rect["y"]:rect["y"]+rect["height"], rect["x"]:rect["x"]+rect["width"], channel] += 100
            timestamp = datetime(2026, 8, 20, tzinfo=timezone.utc) + timedelta(hours=capture_number)
            manifest_path, manifest = write_capture(frame, site_profile(), camera_profile(), geometry_profile(),
                root / "data", trigger="scheduled", captured_at=timestamp)
            captures.append(manifest)
            import_capture_manifest(store, project, manifest_path)
        attrs = model_attributes(project)
        for index, record in enumerate(project.images):
            record.review_status = "reviewed"
            positive_presence = index % 5 != 0
            for attr in attrs:
                meaning = ("positive" if positive_presence else "negative") if attr["role"] == "presence" else (
                    "not_applicable" if not positive_presence else "positive" if index % 2 else "negative")
                record.attributes[attr["id"]] = label_for(attr, meaning)
        store.save(project)
        datasets = DatasetManager(store)
        assignment = datasets.ensure_split_assignment(project, force_rebalance=True)
        qa = hydro_dataset_qa(project, store, assignment)
        errors = [issue for issue in qa["issues"] if issue["severity"] == "error"]
        if errors:
            raise ValueError(errors)
        models, fitted = {}, {}
        for attr in attrs:
            dataset = datasets.export_classification(project, attr["id"])
            model = root / (attr["id"] + ".onnx")
            fitted[attr["id"]] = train_toy_onnx(dataset, attr, model)
            models[attr["id"]] = model
        project.metadata["validationStatus"] = "pipeline_smoke_only"
        bundle_root = write_hydro_model_bundle(project, root / "bundle", models,
            {key: {"lowThreshold": .25, "highThreshold": .75} for key in models},
            dataset_version="synthetic-smoke-only", source_commit="synthetic_fixture",
            camera_profile_ids=["camera_test_v1"], geometry_profile_ids=["geometry_test_v1"],
            runtime_target="windows_onnxruntime_cpu")
        bundle = validate_bundle(bundle_root)
        activate_onnx_bundle(bundle_root, root / "runtime")
        adapter = ActiveBundleInference(root / "runtime")
        result = adapter.infer(captures[-1], root / "data")
        assert result["predictionSchemaVersion"] == 3 and len(result["slots"]) == 10
        # Compare real ONNX execution with the training expression using the SAME preprocessed tensor.
        import cv2
        asset = next(a for a in captures[-1]["assets"] if a["role"] == "slot")
        source = cv2.imread(str(root / "data" / asset["relativePath"]))
        for key, runner in adapter.runners.items():
            tensor = preprocess_slot(source, bundle["models"][key])
            w, b = fitted[key]
            positive = float(1 / (1 + np.exp(-(tensor.mean(axis=(2, 3))[0] @ w + b))))
            actual = 1 - runner.predict_present_probability(tensor)
            assert abs(positive - actual) < 1e-5, (key, positive, actual)
        fixture = root / "result.json"
        fixture.write_text(json.dumps({"result": result, "bundle": bundle}), encoding="utf-8")
        backend = hydro_root / "03_Edge_Server/mqtt_backend"
        script = r"""
const assert = require('node:assert/strict');
process.env.NODE_ENV = 'test';
const fs = require('node:fs');
const payload = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const { validateInferenceResult } = require('./src/validators/aiResultValidator');
const validated = validateInferenceResult(payload.result, { registeredBundle: payload.bundle });
assert.equal(validated.ok, true, JSON.stringify(validated.errors));
assert.equal(validateInferenceResult(payload.result).ok, false);
const { FakeDatabase } = require('./testSupport/fakeMongo');
const { setMongoForTests, resetMongoForTests } = require('./src/mongoClient');
const database = new FakeDatabase();
setMongoForTests(database);
const { upsertAiCapture } = require('./src/services/aiCaptureService');
(async () => {
  const a = await upsertAiCapture(validated.data), b = await upsertAiCapture(validated.data);
  assert.equal(a.inserted, true); assert.equal(b.inserted, false);
  const rows = await database.collection('ai_captures').find({}).toArray();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].labelSchema.schemaId, payload.bundle.labelSchema.schemaId);
  assert.equal((await database.collection('alerts').find({}).toArray()).length, 0);
  assert.equal((await database.collection('commands').find({}).toArray()).length, 0);
  resetMongoForTests();
  console.log('Backend: schema validation + idempotent storage + no alerts/commands PASS');
})().catch(e => { console.error(e); process.exitCode = 1; });
"""
        completed = subprocess.run(["node", "-e", script, str(fixture)], cwd=backend, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        print(completed.stdout.strip())
        # Corrupting a new candidate must not change the active pointer.
        pointer = (root / "runtime/active_bundle.json").read_bytes()
        first = next(iter(bundle["models"].values()))
        (bundle_root / first["path"]).write_bytes(b"corrupt-smoke-fixture")
        try:
            activate_onnx_bundle(bundle_root, root / "runtime")
            raise AssertionError("corrupt model was accepted")
        except ValueError:
            pass
        assert (root / "runtime/active_bundle.json").read_bytes() == pointer
        return {"captures": 6, "slotsImported": len(project.images), "classifiersTrained": len(models),
                "onnxExecuted": len(models), "schemaVersion": bundle["schemaVersion"],
                "labelSchemaId": schema["schemaId"], "mode": "synthetic_shadow_only", "corruptBundleRollback": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hydro-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.hydro_root.resolve()), indent=2))

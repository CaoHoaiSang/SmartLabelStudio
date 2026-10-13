"""Run a synthetic SmartLabel export -> ORI train -> RKNN simulator acceptance.

All files are generated in --output; no operator workspace or deployment device is touched.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--rknn", action="store_true")
    from smartlabel.ori_runtime import ORI_MODEL, ORI_MODEL_PRESETS
    parser.add_argument("--model", choices=list(ORI_MODEL_PRESETS), default=ORI_MODEL)
    parser.add_argument("--pretrained", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    from PIL import Image, ImageDraw
    from smartlabel.models import Annotation
    from smartlabel.project_store import ProjectStore
    from smartlabel.dataset_manager import DatasetManager
    from smartlabel.ori_runtime import inspect_checkpoint, evaluate_ori_model
    from smartlabel.model_export import RknnExportConfig, RknnExportJob

    store = ProjectStore(output / "workspace")
    project = store.create_project("Synthetic ORI acceptance", classes=["part: test"])
    sources = output / "sources"
    sources.mkdir()
    for i in range(9):
        image = Image.new("RGB", (160, 96), (25, 25, 25))
        if i % 3 != 0:
            draw = ImageDraw.Draw(image)
            draw.rectangle((40, 30, 120, 66), fill=(80, 120, 220))
            draw.line((80, 48, 110, 48), fill="white", width=3)
        image.putpixel((0, 0), (i, 25, 25))
        image.save(sources / f"{i}.png")
    store.import_images(project, [sources])
    for record in project.images:
        record.review_status = "reviewed"
        with Image.open(store.image_path(project, record)) as image:
            index = image.getpixel((0, 0))[0]
        record.annotations = []
        if index % 3 != 0:
            annotation = Annotation.create_box(0, [40, 30, 80, 36])
            annotation.orientation = [[80, 48], [110, 48]]
            record.annotations = [annotation]
    store.save(project)
    export = DatasetManager(store).export_yolo(project, task="ori")
    config = {"task":"ori", "model":args.model, "data":str(export / "data.yaml"), "epochs":1,
              "image_size":96,"batch":2,"patience":2,"device":"cpu","project_dir":str(output / "runs"),"run_name":"smoke","validate":True,"pretrained_backbone":args.pretrained}
    subprocess.run([sys.executable,"-u","-m","smartlabel.train_worker",json.dumps(config)],cwd=ROOT,check=True)
    model = output / "runs" / "smoke" / "weights" / "best.pt"
    info = inspect_checkpoint(model)
    assert info == {"task":"ori","names":{"0":"part: test"}}, info
    metadata = json.loads(model.with_suffix(".ori.json").read_text())
    family, scale, _ = ORI_MODEL_PRESETS[args.model]
    assert metadata["architecture"] == {"family":family,"scale":scale}, metadata
    assert metadata["heading_encoding"] == "cos_sin_vector_v2", metadata
    from smartlabel.auto_label import YoloAutoLabeler
    registered = store.register_model(model)
    assert registered.with_suffix(".ori.json").read_bytes() == model.with_suffix(".ori.json").read_bytes()
    labeler = YoloAutoLabeler(registered, device="cpu")
    process = labeler._ori.process
    try:
        assert labeler.task == "ori" and labeler.names == {0: "part: test"}
        for _ in range(2):
            predictions = labeler.predict(store.image_path(project, project.images[0]), .00001, 96)
            assert predictions and all(a.kind == "ori" and len(a.obb) == 4 and len(a.orientation) == 2 for a in predictions)
            from smartlabel.annotation_geometry import direction
            import math
            for ann in predictions:
                expected = direction(ann.bbox, ann.obb, ann.orientation[1], (160, 96), snap=False)
                assert expected and all(math.dist(a, b) < 1e-5 for a, b in zip(ann.orientation, expected))
            assert process.poll() is None and labeler._ori.process is process
    finally:
        labeler.close()
    assert process.poll() is not None
    from smartlabel.frame_filter import FrameFilterSettings, _run_yolo
    metrics = _run_yolo([store.image_path(project, project.images[0])], registered,
                        FrameFilterSettings(), None, None)
    assert len(metrics) == 1 and "accepted" in next(iter(metrics.values()))
    report = evaluate_ori_model(model,data_path=export / "data.yaml",split="test",image_size=96,device="cpu",output_root=output / "evaluation")
    assert report["metric_kind"] == "ORI + OBB" and "box_metrics" in report
    if args.rknn:
        results = []
        job = RknnExportJob(RknnExportConfig(model=model,output=output / "ori.rknn",converter_dir=ROOT / "tools" / "rknn_converter",task="ori",class_count=1), print, lambda *result: results.append(result))
        job._run()
        assert results and results[0][0] == 0, results
        manifest = json.loads((output / "ori.json").read_text())
        assert manifest["architecture"] == metadata["architecture"], manifest
    print("ORI_PIPELINE_OK", flush=True)


if __name__ == "__main__":
    main()

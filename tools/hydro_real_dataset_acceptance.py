"""Opt-in acceptance of a real Hydro ZIP in a NEW, isolated SmartLabel workspace.

Does not label plants, train models, contact providers, or mutate the input ZIP.
GUI callback and worker run for real; file chooser/messages are automated locally.
"""
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import argparse
import hashlib
import gc
import json
import os
import shutil
import sys
import time
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path, help="New directory outside the normal workspace")
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    output = args.output.resolve()
    normal = Path(__file__).resolve().parents[1] / "workspace"
    if output == normal or output.is_relative_to(normal) or archive.is_relative_to(output):
        raise ValueError("Use a separate acceptance output, not the source workspace/archive directory")
    output.mkdir()  # Existing outputs are never reused.
    archive_sha = sha(archive)
    with zipfile.ZipFile(archive) as package:
        index = json.loads(package.read("dataset-export.json"))
        manifests = {row["captureId"]: json.loads(package.read(row["manifestPath"])) for row in index["captures"]}
    os.environ["SMARTLABEL_WORKSPACE"] = str(output / "workspace")
    from smartlabel import app as app_module
    from smartlabel.project_store import ProjectStore
    from smartlabel.dataset_manager import DatasetManager
    from smartlabel.hydroponic import (apply_hydroponic_slot_template, import_capture_dataset_archive,
        hydro_dataset_qa, CaptureManifestError, CaptureRepairConfirmationRequired)
    from PIL import Image, ImageChops, ImageStat

    store = ProjectStore(output / "workspace")
    project = store.create_project("DATA-01 — ảnh thật, chưa gán nhãn", task="classify")
    apply_hydroponic_slot_template(project, crop_code=index["cropCode"],
        crop_display_name=index.get("cropCycle", {}).get("cropDisplayName", index["cropCode"]))
    store.save(project)
    errors = []
    with patch.object(app_module.SmartLabelApp, "_refresh_hardware"), \
            patch.object(app_module.messagebox, "showinfo"), \
            patch.object(app_module.messagebox, "showerror", side_effect=lambda *a, **k: errors.append(str(a))):
        app = app_module.SmartLabelApp()
        app.withdraw()
        try:
            app._change_project_context(store.load(project.id))
            def gui_import(file):
                gc.collect()  # Dispose retired Tk variables on their owning thread.
                with patch.object(app_module.filedialog, "askopenfilename", return_value=str(file)):
                    app._import_capture_dataset_archive()
                deadline = time.monotonic() + 60
                def check_finished():
                    if not app.import_in_progress or time.monotonic() >= deadline:
                        app.quit()
                    else:
                        app.after(10, check_finished)
                app.after(10, check_finished)
                app.mainloop()
                assert not app.import_in_progress and not errors, errors
            gui_import(archive)
            project = app.project
            assert len(project.images) == index["slotImageCount"]
            stable = lambda p: {r.id: (r.sha256, dict(r.attributes), r.review_status, dict(r.metadata), dict(r.lineage)) for r in p.images}
            original = stable(project)
            gui_import(archive)
            assert stable(project) == original, "Re-import changed image identity, labels or provenance"
            gui_import("")
            assert stable(project) == original, "Cancel changed project data"
        finally:
            for timer in app.tk.call("after", "info"):
                app.tk.call("after", "cancel", timer)
            app.destroy()  # Avoid application shutdown saves unrelated to this probe.

    project = store.load(project.id)
    assets = {a["assetId"]: a for m in manifests.values() for a in m["assets"]}
    geometry_errors = []
    contexts = {}
    for record in project.images:
        manifest = manifests[record.metadata["captureId"]]
        asset = assets[record.metadata["assetId"]]
        image_path = store.project_dir(project) / "images" / record.file_name
        assert sha(image_path) == record.sha256 == asset["sha256"]
        assert record.metadata["slotId"] == asset["slotId"]
        assert record.metadata["cropCycleId"] == manifest["cropCycleId"]
        assert record.metadata["capturedAt"] == manifest["capturedAt"]
        row = next(item for item in index["captures"] if item["captureId"] == manifest["captureId"])
        context = row.get("effectiveCropContext") or manifest.get("cropContext")
        if context:
            for key in ("sowingDate", "nftStartDate", "daysAfterSowing", "daysAfterNft", "timezone"):
                assert record.metadata[key] == context[key]
            assert record.metadata["captureLocalDate"] == context["localDate"]
        else:
            cycle = index["cropCycle"]
            local_day = datetime.fromisoformat(manifest["capturedAt"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=7))).date()
            assert record.metadata["cropContextSource"] == "dataset_crop_cycle"
            assert record.metadata["originalSowingDate"] is None
            assert record.metadata["captureLocalDate"] == local_day.isoformat()
            for field, age in (("sowingDate", "daysAfterSowing"), ("nftStartDate", "daysAfterNft")):
                assert record.metadata[field] == cycle[field]
                assert record.metadata[age] == (local_day - date.fromisoformat(cycle[field])).days
        assert record.lineage["rectInFullFrame"] == asset["rectInFullFrame"]
        assert record.review_status == "unlabeled", "Image quality approval must not approve training labels"
        for label in record.attributes.values(): assert label in {"uncertain", "not_applicable"}
        for parent in record.lineage["parentAssets"].values():
            assert sha(store.project_dir(project) / parent["projectRelativePath"]) == assets[parent["assetId"]]["sha256"]
        with Image.open(image_path) as slot, Image.open(store.project_dir(project) / record.lineage["fullFrameRelativePath"]) as full:
            assert slot.size == (asset["width"], asset["height"])
            rect = asset["rectInFullFrame"]
            crop = full.convert("RGB").crop((rect["x"], rect["y"], rect["x"] + rect["width"], rect["y"] + rect["height"]))
            geometry_errors.append(sum(ImageStat.Stat(ImageChops.difference(crop, slot.convert("RGB"))).mean) / 3)
        contexts[manifest["captureId"]] = {key: record.metadata.get(key) for key in
            ("capturedAt", "captureLocalDate", "sowingDate", "nftStartDate", "daysAfterSowing", "daysAfterNft", "cropContextSource", "originalSowingDate")}

    # Fault injection uses another copy; the reviewable acceptance project stays intact.
    fault_store = ProjectStore(output / "fault-workspace")
    shutil.copytree(store.project_dir(project), fault_store.projects_dir / project.id)
    fault = fault_store.load(project.id)
    removed = fault.images[0]
    kept_ids = {record.id for record in fault.images[1:]}
    fault_store.delete_image(fault, removed)
    before = sha(fault_store.project_dir(fault) / "project.json")
    try:
        import_capture_dataset_archive(fault_store, fault, archive)
    except CaptureRepairConfirmationRequired as error:
        plan = error.plan
    else:
        raise AssertionError("Partial capture did not require confirmation")
    assert sha(fault_store.project_dir(fault) / "project.json") == before
    try:
        import_capture_dataset_archive(fault_store, fault, archive, confirmed_repair_digest="wrong")
    except CaptureRepairConfirmationRequired:
        pass
    else:
        raise AssertionError("Wrong repair confirmation was accepted")
    repair = import_capture_dataset_archive(fault_store, fault, archive, confirmed_repair_digest=plan["digest"])
    assert repair["slotImagesRepaired"] == 1 and kept_ids.issubset({r.id for r in fault.images})
    assert len(fault.images) == index["slotImageCount"]
    before = sha(fault_store.project_dir(fault) / "project.json")
    damaged = output / "damaged-fixture.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(damaged, "w") as dest:
        changed = next(a["relativePath"] for a in assets.values() if a["role"] == "slot")
        for name in source.namelist(): dest.writestr(name, b"corrupt-fixture" if name == changed else source.read(name))
    try:
        import_capture_dataset_archive(fault_store, fault, damaged)
    except CaptureManifestError:
        pass
    else:
        raise AssertionError("Corrupt ZIP was accepted")
    assert sha(fault_store.project_dir(fault) / "project.json") == before
    missing = fault_store.project_dir(fault) / "images" / fault.images[0].file_name
    parked = missing.with_suffix(".missing-fixture")
    missing.rename(parked)
    try:
        try:
            import_capture_dataset_archive(fault_store, fault, archive)
        except CaptureManifestError:
            pass
        else:
            raise AssertionError("Missing file with a live record was overwritten")
        assert not missing.exists() and sha(fault_store.project_dir(fault) / "project.json") == before
    finally:
        parked.rename(missing)

    retry_store = ProjectStore(output / "retry-workspace")
    retry = retry_store.create_project("Interrupted import fixture", task="classify")
    apply_hydroponic_slot_template(retry); retry_store.save(retry)
    real_save, calls = retry_store.save, 0
    def failing_save(p):
        nonlocal calls
        calls += 1
        if calls == 2: raise OSError("Acceptance fixture: disk failure on second capture")
        return real_save(p)
    with patch.object(retry_store, "save", side_effect=failing_save):
        try: import_capture_dataset_archive(retry_store, retry, archive)
        except OSError: pass
        else: raise AssertionError("Injected disk failure did not propagate")
    retained = {r.id for r in retry.images}
    assert len(retained) == index["captures"][0]["slotCount"]
    retry_result = import_capture_dataset_archive(retry_store, retry, archive)
    assert len(retry.images) == index["slotImageCount"] and retained.issubset({r.id for r in retry.images})

    datasets = DatasetManager(store)
    assignment = datasets.ensure_split_assignment(project)
    qa = hydro_dataset_qa(project, store, assignment)
    assert not qa["pilotReadiness"]["shadowBundleReady"] and not qa["pilotReadiness"]["operationalBundleReady"]
    try: datasets.export_classification(project, "plant_presence")
    except ValueError: pass
    else: raise AssertionError("Unlabeled real images must not become a training dataset")
    assert sha(archive) == archive_sha
    report = {"passed": True, "archiveSha256": archive_sha, "datasetExportId": index["datasetExportId"],
        "project": str(store.project_dir(project)), "captures": len(manifests), "slotImages": len(project.images),
        "parentImages": sum(1 for a in assets.values() if a["role"] != "slot"), "contexts": contexts,
        "maxCropJpegMeanAbsoluteError": max(geometry_errors), "repair": repair, "retry": retry_result,
        "checks": ["Tk import callback + worker", "all slot/parent hashes", "dimensions and lineage", "crop dates and provenance",
            "re-import identity/labels unchanged", "cancel", "repair confirmation", "corrupt ZIP", "missing file not overwritten", "disk failure + retry", "unlabeled training gate"],
        "qa": qa, "realLabelsAssigned": 0, "modelTrained": False, "userWorkspaceModified": False}
    (output / "smartlabel-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "images": len(project.images), "project": str(store.project_dir(project)), "maxCropJpegMeanAbsoluteError": max(geometry_errors)}))


if __name__ == "__main__":
    main()

"""Replay project navigation on COPIES, never the production workspace.

python scripts/verify_project_switch.py --copied-workspace <fixture> --show
The two projects and images must have been copied into fixture/projects first.
"""
import argparse
import hashlib
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smartlabel import app as app_module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--copied-workspace", type=Path, required=True)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    fixture = args.copied_workspace.resolve()
    if fixture == (app_module.APP_ROOT / "workspace").resolve():
        parser.error("Use a separate COPY of the workspace, not the app workspace")
    snapshots = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (fixture / "projects").glob("*/project.json")}
    errors = []
    with patch.object(app_module, "WORKSPACE", fixture), \
         patch.object(app_module.SmartLabelApp, "_refresh_hardware"), \
         patch.object(app_module.messagebox, "showerror", side_effect=lambda *a, **k: errors.append(a)):
        app = app_module.SmartLabelApp()
        app.withdraw()
        try:
            for iteration in range(3):
                for project_id, count in (("project_215835e70a62", 237), ("project_fed647613d52", 80)):
                    app._refresh_project_menu()
                    label = next(k for k, v in app.project_lookup.items() if v.parent.name == project_id)
                    app._switch_project(label)
                    assert app.project.id == project_id
                    assert len(app.project.images) == count
                    assert len(app.filtered_images) == count
                    assert app.canvas.project.id == project_id
                    assert app.canvas.record.id in {record.id for record in app.project.images}
                    assert app.project.name in app.project_summary.get("1.0", "end")
                    if project_id.endswith("fed647613d52"):
                        assert app.canvas.active_class_id is None
                        assert set(app.attribute_widgets) == {"plant_presence", "yellow_leaf", "wilt"}
                        packed = app.import_folder_button.master.pack_slaves()
                        assert packed.index(app.hydro_archive_import_button) < packed.index(app.hydro_import_button) < packed.index(app.import_folder_button)
                    print(f"round={iteration + 1} project={project_id} images={count} canvas=OK", flush=True)
            assert not errors, errors
            assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in snapshots.items())
            print("PROJECT_JSON_UNCHANGED=YES", flush=True)
            if args.show:
                app.title("SmartLabel · KIEM THU BAN SAO · Project switching")
                app.deiconify()
                # CTk schedules titlebar/appearance work during initialization;
                # restore visibility after those callbacks have run.
                app.after(500, app.deiconify)
                app.mainloop()
        finally:
            try:
                app.destroy()
            except app_module.tk.TclError:
                pass


if __name__ == "__main__":
    main()

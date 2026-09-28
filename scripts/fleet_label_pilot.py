"""Explicit operator-run acceptance helper; no credentials in arguments or output.

Creates only a named pilot project. Receive/review codes arrive via stdin; this
does not train, approve a model, or alter other projects. Real data requires the
owner's prior permission. Withdrawal remains the normal Fleet user workflow.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smartlabel.project_store import ProjectStore
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.fleet_intake import receive
from smartlabel.fleet_review import FleetReviewSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "receive", "draft"])
    parser.add_argument("--project")
    parser.add_argument("--presence", choices=["present", "absent", "uncertain"], help="Explicit observation after viewing the selected image; never an AI ground-truth label")
    args = parser.parse_args()
    store = ProjectStore(Path(__file__).resolve().parents[1] / "workspace")
    if args.action == "create":
        project = store.create_project("Fleet pilot 20-09-2026 · kiểm tra ảnh đóng góp", task="classify")
        apply_hydroponic_slot_template(project)
        project.metadata["fleetAcceptancePilot"] = True
        store.save(project)
        print(json.dumps({"projectId": project.id, "root": str(store.project_dir(project))}))
        return
    project = store.load(args.project)
    if project.metadata.get("fleetAcceptancePilot") is not True:
        raise ValueError("Only a dedicated acceptance project is allowed")
    code = sys.stdin.read().strip()
    root = store.project_dir(project)
    if args.action == "receive":
        result = receive(root, project.id, code)
        print(json.dumps(result))
        return
    session = FleetReviewSession(root, project.id, code)
    try:
        if args.presence is None:
            raise ValueError("View the selected image and explicitly provide --presence before saving a draft")
        data, revision = session.refresh()
        if len(data["images"]) != 1:
            raise ValueError("This acceptance selects exactly one plant photo")
        row = data["images"][0]
        session.preview_path(row)  # Re-hash the managed copy before a draft annotation.
        data, revision = session.save(project, row["id"], "draft", revision,
            attributes={"plant_presence": args.presence},
            other_abnormal="Nghiệm thu luồng ảnh Fleet. Nhãn bản nháp theo ảnh xem trước; không phải nhãn đã được kỹ thuật viên kiểm định, không dùng train.")
        print(json.dumps({"ok": True, "projectId": project.id, "contributionId": data["contributionId"],
                          "source": row["source"], "reviewStatus": data["images"][0]["reviewStatus"], "trainAllowed": data["trainAllowed"]}))
    finally:
        session.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Fleet acceptance not confirmed; inspect scope, code expiry and receiver without exposing credentials", file=sys.stderr)
        sys.exit(1)

from pathlib import Path
import sys

from smartlabel.project_store import ProjectStore


ROOT = Path(__file__).resolve().parent
DEMO_IMAGES = Path(r"D:\DeltaX\Tai Lieu Demo\Phan Loai Chai Nhua\Data\images")
DEMO_MODEL = Path(r"D:\DeltaX\Tai Lieu Demo\Phan Loai Chai Nhua\Model\best.pt")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    store = ProjectStore(ROOT / "workspace")
    existing = []
    for path in store.list_projects():
        project = store.load(path)
        if project.name == "Demo phân loại chai nhựa":
            existing.append(project)
    project = existing[0] if existing else store.create_project(
        "Demo phân loại chai nhựa",
        task="instance_segmentation",
        classes=["Chai_trong", "Chai_lo", "Chai_xanh_la"],
    )
    project.attribute_schema = {
        "condition": ["nguyen_ven", "bep_nhe", "can_dep", "vo_nat"],
        "occlusion": ["none", "partial", "heavy"],
        "cap": ["co_nap", "mat_nap", "khong_xac_dinh"],
    }
    if DEMO_IMAGES.exists():
        added, skipped = store.import_images(project, [DEMO_IMAGES])
        print(f"Ảnh: thêm {added}, bỏ qua {skipped}")
    else:
        print(f"Không tìm thấy ảnh: {DEMO_IMAGES}")
    if DEMO_MODEL.exists():
        project.active_model = str(store.register_model(DEMO_MODEL))
        store.save(project)
        print(f"Model: {project.active_model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

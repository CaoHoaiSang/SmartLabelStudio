"""Stable Hydro machine values with Vietnamese presentation shared by editors."""

HYDRO_VALUE_LABELS = {
    "plant_presence": {"present": "Có cây", "absent": "Không có cây", "uncertain": "Chưa chắc chắn"},
    "yellow_leaf": {"present": "Có lá vàng", "absent": "Không có lá vàng",
                    "uncertain": "Chưa chắc chắn", "not_applicable": "Không áp dụng"},
    "wilt": {"present": "Có héo", "absent": "Không héo",
             "uncertain": "Chưa chắc chắn", "not_applicable": "Không áp dụng"},
}


def is_hydro_attribute(project, key):
    from .hydro_labels import model_keys
    return project.metadata.get("template") == "Hydroponic Slot Condition" and key in model_keys(project)

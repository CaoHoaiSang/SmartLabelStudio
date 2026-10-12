import hashlib
import json
from pathlib import Path
from typing import Type, List
from YOLORKNN.engine.model import BaseYoloModel, Task
from YOLORKNN.predictor.RKNNPredictor import BaseRKNNYoloPredictor
from YOLORKNN.predictor.RKNNPredictor import DetRKNNPredictor, SegRKNNPredictor, OBBRKNNPredictor, OriRKNNPredictor


class YOLORKNN(BaseYoloModel):
    def __init__(self,
                 task: Task,
                 rknn_model_path: str,
                 names: List[str],
                 iou: int = 0.5,
                 conf: int = 0.5, 
                 ) -> None:
        super().__init__()
        metadata_path = Path(rknn_model_path).with_suffix(".json")
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("Model metadata must be a JSON object")
            if task == Task.ORI and metadata.get("task") not in {None, "ori", "orienty"}:
                raise ValueError("Selected ORI task does not match model metadata task")
            if metadata.get("task") == "ori" or metadata.get("output_layout") == "deltax_orienty_5_heads_v1":
                if task != Task.ORI:
                    raise ValueError("This model requires the ORI task")
                expected = [[1, 64 + len(names), side, side] for side in (80, 40, 20)] + [[1, 1, 8400], [1, 1, 8400]]
                metadata_names = metadata.get("names", {})
                if not isinstance(metadata_names, dict):
                    raise ValueError("ORI metadata must contain indexed class names")
                if (metadata.get("output_layout") != "deltax_orienty_5_heads_v1" or metadata.get("output_shapes") != expected
                        or metadata.get("imgsz") != [640, 640] or metadata.get("target") != "rk3588"
                        or metadata.get("compiler") != "rknn-toolkit2==2.2.0"
                        or metadata.get("heading") != "image_x_clockwise_degrees"
                        or set(metadata_names) != {str(i) for i in range(len(names))}
                        or [metadata_names.get(str(i)) for i in range(len(names))] != list(names)
                        or metadata.get("model_sha256") != hashlib.sha256(Path(rknn_model_path).read_bytes()).hexdigest()):
                    raise ValueError("ORI metadata, labels, output contract or SHA256 does not match model/settings")
        self._predictor = self.predict_map[task](
            rknn_model_path=rknn_model_path,
            names=names,
            iou=iou,
            conf=conf
            )

    @property
    def predict_map(self) -> dict[Task, Type[BaseRKNNYoloPredictor]]:
        return {
            Task.DET: DetRKNNPredictor,
            Task.SEG: SegRKNNPredictor,
            Task.OBB: OBBRKNNPredictor,
            Task.ORI: OriRKNNPredictor,
        }
    
    @property
    def predictor(self) -> BaseRKNNYoloPredictor:
        return self._predictor

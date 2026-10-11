import numpy as np
from copy import deepcopy

from YOLORKNN.engine.result import Result, IResultConverter
from YOLORKNN.utils.plotting import Annotator, colors


class ImageResultConverter(IResultConverter):
    def __init__(self, image: np.ndarray) -> None:
        super().__init__()
        self.image = image
    
    def convert(self, result: Result)-> np.ndarray:
        """
        Plots the predict results on an input RGB image. Accepts a numpy array (cv2).

        Args:
            Result of prediction
        Returns:
            (numpy.ndarray): A numpy array of the annotated image.
        """
        img = self.image
        names = result.names
        is_obb = result.obb is not None
        pred_boxes = result.obb if is_obb else result.boxes
        pred_masks = result.masks
        pred_degs = result.degs
        annotator = Annotator(
            deepcopy(img),
        )

        # Plot Segment results
        if pred_masks is not None:
            idx = pred_boxes.cls if pred_boxes else range(len(pred_masks))
            annotator.masks(pred_masks.data, colors=[colors(int(x), True) for x in idx])

        # Plot Detect results
        if pred_boxes is not None:
            for d in reversed(pred_boxes):
                c, conf, id = int(d.cls.item()), float(d.conf.item()), None if d.id is None else int(d.id.item())
                name = ("" if id is None else f"id:{id} ") + names[c]
                label = (f"{name} {conf:.2f}" if conf else name)
                box = np.reshape(d.xyxyxyxy, (-1, 4, 2)).squeeze() if is_obb else np.squeeze(d.xyxy)
                annotator.box_label(box, label, color=colors(c, True), rotated=is_obb)

        # Plot Deg results
        if pred_degs:
            data = pred_degs.data.ravel()
            for i in range(len(data)):
                deg = data[i].item()
                xywh = pred_boxes.xywhr[i] if is_obb else pred_boxes.xywh[i]
                # if self.keypoints is not None:
                #     firstPoint = self.keypoints.data[i][0]
                #     center = (firstPoint[0].item(), firstPoint[1].item())  # x_firstPoint, y_firstPoint
                # else:
                center = (xywh[0].item(), xywh[1].item())  # x_center, y_center
                orienty_line_length = min(xywh[2].item(), xywh[3].item())  # min (w, h)
                c = int(pred_boxes.cls[i].item())
                annotator.orienty_line(deg, center, orienty_line_length, color=colors(c, True))

        # Plot Classify results
        # if pred_probs is not None:
        #     text = ",\n".join(f"{names[j] if names else j} {pred_probs.data[j]:.2f}" for j in pred_probs.top5)
        #     x = round(self.orig_shape[0] * 0.03)
        #     annotator.text([x, x], text, txt_color=(255, 255, 255))  # TODO: allow setting colors

        # Plot Pose results
        # if self.keypoints is not None:
        #     for k in reversed(self.keypoints.data):
        #         annotator.kpts(k, img)

        return annotator.result()

class JSONResultConverter(IResultConverter):
    def __init__(self) -> None:
        super().__init__()
    
    def convert(self, result: Result)-> dict:
        output = {}
        data = []
        names = result.names
        is_obb = result.obb is not None
        pred_boxes = result.obb if is_obb else result.boxes
        pred_degs = result.degs

        output["type"] = "seg" if result.masks is not None else ("box" if not is_obb else ("obb" if pred_degs is None else "orient"))

        # Process bounding boxes (obb or box type)
        if pred_boxes is not None:
            for i, d in enumerate(pred_boxes):
                entry = {
                    "name": names[int(d.cls.ravel().item())],
                    "x": int(round(d.xywh.ravel()[0].item() if not is_obb else d.xywhr.ravel()[0].item())),
                    "y": int(round(d.xywh.ravel()[1].item() if not is_obb else d.xywhr.ravel()[1].item())),
                    "w": int(round(d.xywh.ravel()[2].item() if not is_obb else d.xywhr.ravel()[2].item())),
                    "h": int(round(d.xywh.ravel()[3].item() if not is_obb else d.xywhr.ravel()[3].item())),
                    "angle": d.xywhr.ravel()[4].item() if is_obb else None,
                    "id": None if d.id is None else int(d.id.item()),
                    "conf": round(float(d.conf.ravel().item()), 4),
                }
                # Remove angle key if it's None
                if entry["angle"] is None or pred_degs:
                    del entry["angle"]
                if is_obb and pred_degs is None:
                    entry["deg"] = float(np.degrees(entry["angle"]))
                    entry["angle_unit"] = "radians"
                if entry["id"] is None:
                    del entry["id"]
                # Add segment points if masks available (as integer pixel coordinates)
                if result.masks is not None:
                    segments = result.masks.xy  # pixel coordinates
                    if i < len(segments):
                        entry["segments"] = [[int(round(pt[0])), int(round(pt[1]))] for pt in segments[i]]
                data.append(entry)

        # Process degrees (deg type)
        if pred_degs:
            pred_degs = pred_degs.data.ravel()
            for i, deg in enumerate(pred_degs):
                deg = deg.item()
                data[i]["deg"] = deg
        output["data"] = data
        return output
        

class StringResultConverter(IResultConverter):

    PARAMETER_SEPARATOR = ", "
    OBJECT_SEPARATOR = "; "
    LAST_STRING_DATA = "\n"
    FIRST_STRING_DATA = "#Object = "

    def __init__(self) -> None:
        super().__init__()

    def convert(self, result: Result) -> str:
        output = []
        names = result.names
        is_obb = result.obb is not None
        pred_boxes = result.obb if is_obb else result.boxes
        pred_degs = result.degs

        # Process bounding boxes (obb or box type)
        if pred_boxes is not None:
            for d in pred_boxes:
                entry = [
                    names[int(d.cls.ravel().item())],
                    f"{d.xywh.ravel()[0].item() if not is_obb else d.xywhr.ravel()[0].item():.6f}",
                    f"{d.xywh.ravel()[1].item() if not is_obb else d.xywhr.ravel()[1].item():.6f}",
                    f"{d.xywh.ravel()[2].item() if not is_obb else d.xywhr.ravel()[2].item():.6f}",
                    f"{d.xywh.ravel()[3].item() if not is_obb else d.xywhr.ravel()[3].item():.6f}",
                ]
                if is_obb and not pred_degs:
                    entry.append(f"{d.xywhr.ravel()[4].item():.6f}")
                if d.id is not None:
                    entry.append(str(int(d.id.item())))
                entry.append(f"{float(d.conf.ravel().item()):.6f}")    
                output.append(entry)

        # Process degrees (deg type)
        if pred_degs:
            pred_degs = pred_degs.data.ravel()
            for i, deg in enumerate(pred_degs):
                output[i].insert(-1, f"{deg.item():.6f}")

        for i, entry in enumerate(output):
            output[i] = self.PARAMETER_SEPARATOR.join(entry)
        
        return (self.FIRST_STRING_DATA 
                + self.OBJECT_SEPARATOR.join(output) 
                + self.LAST_STRING_DATA)
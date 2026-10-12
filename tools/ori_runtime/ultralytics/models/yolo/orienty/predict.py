# Ultralytics YOLO 🚀, AGPL-3.0 license

import torch

from ultralytics.engine.results import Results
from ultralytics.models.yolo.detect.predict import DetectionPredictor
from ultralytics.utils import DEFAULT_CFG, ops
from deltax_ori_contract import heading_encoding


class OrientationPredictor(DetectionPredictor):
    """
    A class extending the DetectionPredictor class for prediction based on a orientation model.

    Example:
        ```python
        from ultralytics.utils import ASSETS
        from ultralytics.models.yolo.orienty import OrientationPredictor

        args = dict(model='yolov8n-ori.pt', source=ASSETS)
        predictor = OrientationPredictor(overrides=args)
        predictor.predict_cli()
        ```
    """

    def __init__(self, cfg=DEFAULT_CFG, overrides=None, _callbacks=None):
        """Initializes OrientationPredictor with optional model and data configuration overrides."""
        super().__init__(cfg, overrides, _callbacks)
        self.args.task = "orienty"

    def postprocess(self, preds, img, orig_imgs):
        preds = ops.non_max_suppression(
            preds,
            self.args.conf,
            self.args.iou,
            agnostic=self.args.agnostic_nms,
            max_det=self.args.max_det,
            nc=len(self.model.names),
            classes=self.args.classes,
            rotated=True,
        )

        if not isinstance(orig_imgs, list):  # input images are a torch.Tensor, not a list
            orig_imgs = ops.convert_torch2numpy_batch(orig_imgs)

        results = []
        for pred, orig_img, img_path in zip(preds, orig_imgs, self.batch[0]):
            rboxes = torch.cat([pred[:, :4], pred[:, -1:]], dim=-1)
            rboxes[:, :4] = ops.scale_boxes(img.shape[2:], rboxes[:, :4], orig_img.shape, xywh=True)
            degs = pred[:, -2]
            radiants = degs * torch.pi / 180
            rboxes = ops.regularize_orientyBoxes(rboxes, radiants, align_to_heading=heading_encoding(self.model) == "cos_sin_vector_v2")
            degs = rboxes[:, 4] * 180 / torch.pi
            # xywh, r, conf, cls
            obb = torch.cat([rboxes, pred[:, 4:6]], dim=-1)
            results.append(Results(orig_img, path=img_path, names=self.model.names, degs=degs, obb=obb))
        return results

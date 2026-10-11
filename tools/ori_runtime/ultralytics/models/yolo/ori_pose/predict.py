# Ultralytics YOLO 🚀, AGPL-3.0 license

import torch

from ultralytics.engine.results import Results
from ultralytics.models.yolo.detect.predict import DetectionPredictor
from ultralytics.utils import DEFAULT_CFG, LOGGER, ops


class OriPosePredictor(DetectionPredictor):
    """
    A class extending the DetectionPredictor class for prediction based on a oripose model.

    Example:
        ```python
        from ultralytics.utils import ASSETS
        from ultralytics.models.yolo.orienty import OriPosePredictor

        args = dict(model='yolov8n-ori-pose.pt', source=ASSETS)
        predictor = OriPosePredictor(overrides=args)
        predictor.predict_cli()
        ```
    """

    def __init__(self, cfg=DEFAULT_CFG, overrides=None, _callbacks=None):
        super().__init__(cfg, overrides, _callbacks)
        self.args.task = "ori_pose"
        if isinstance(self.args.device, str) and self.args.device.lower() == "mps":
            LOGGER.warning(
                "WARNING ⚠️ Apple MPS known Pose bug. Recommend 'device=cpu' for Pose models. "
                "See https://github.com/ultralytics/ultralytics/issues/4031."
            )

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
        for i, pred in enumerate(preds):
            img_path = self.batch[0][i]
            orig_img = orig_imgs[i]
            rboxes = torch.cat([pred[:, :4], pred[:, -1:]], dim=-1)
            rboxes[:, :4] = ops.scale_boxes(img.shape[2:], rboxes[:, :4], orig_img.shape, xywh=True)
            degs = pred[:, -2]
            radiants = degs * torch.pi / 180
            rboxes = ops.regularize_orientyBoxes(rboxes, radiants)
            # xywh, r, conf, cls
            obb = torch.cat([rboxes, pred[:, 4:6]], dim=-1)
            pred_kpts = pred[:, 6:-2].view(len(pred), *self.model.kpt_shape) if len(pred) else pred[:, 6:-2]
            pred_kpts = ops.scale_coords(img.shape[2:], pred_kpts, orig_img.shape)
            results.append(
                Results(
                    orig_img,
                    path=img_path,
                    names=self.model.names,
                    degs=degs,
                    keypoints=pred_kpts,
                    obb=obb,
                )
            )
        return results

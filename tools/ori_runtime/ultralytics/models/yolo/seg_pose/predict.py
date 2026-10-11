# Ultralytics YOLO 🚀, AGPL-3.0 license

from ultralytics.engine.results import Results
from ultralytics.models.yolo.detect.predict import DetectionPredictor
from ultralytics.utils import DEFAULT_CFG, LOGGER, ops


class SegPosePredictor(DetectionPredictor):
    """
    A class extending the DetectionPredictor class for prediction based on a segpose model.

    Example:
        ```python
        from ultralytics.utils import ASSETS
        from ultralytics.models.yolo.seg_pose import SegPosePredictor

        args = dict(model='yolov8n-seg-pose.pt', source=ASSETS)
        predictor = SegPosePredictor(overrides=args)
        predictor.predict_cli()
        ```
    """

    def __init__(self, cfg=DEFAULT_CFG, overrides=None, _callbacks=None):
        """Initializes SegPosePredictor, sets task to 'pose' and logs a warning for using 'mps' as device."""
        super().__init__(cfg, overrides, _callbacks)
        self.args.task = "seg_pose"
        if isinstance(self.args.device, str) and self.args.device.lower() == "mps":
            LOGGER.warning(
                "WARNING ⚠️ Apple MPS known Pose bug. Recommend 'device=cpu' for Pose models. "
                "See https://github.com/ultralytics/ultralytics/issues/4031."
            )

    def postprocess(self, preds, img, orig_imgs):
        """Return detection results for a given input image or list of images."""
        p = ops.non_max_suppression(
            preds,
            self.args.conf,
            self.args.iou,
            agnostic=self.args.agnostic_nms,
            max_det=self.args.max_det,
            classes=self.args.classes,
            nc=len(self.model.names),
        )

        if not isinstance(orig_imgs, list):  # input images are a torch.Tensor, not a list
            orig_imgs = ops.convert_torch2numpy_batch(orig_imgs)

        results = []
        kpt_size = self.model.kpt_shape[0] * self.model.kpt_shape[1]
        proto = preds[1][-1] if len(preds[1]) == 4 else preds[1]  # second output is len 4 if pt, but only 1 if exported
        for i, pred in enumerate(p):
            orig_img = orig_imgs[i]
            img_path = self.batch[0][i]
            if not len(pred):  # save empty boxes
                masks = None
            elif self.args.retina_masks:
                pred[:, :4] = ops.scale_boxes(img.shape[2:], pred[:, :4], orig_img.shape)
                masks = ops.process_mask_native(proto[i], pred[:, 6:-kpt_size], pred[:, :4], orig_img.shape[:2])  # HWC
            else:
                masks = ops.process_mask(
                    proto[i], pred[:, 6:-kpt_size], pred[:, :4], img.shape[2:], upsample=True
                )  # HWC
                pred[:, :4] = ops.scale_boxes(img.shape[2:], pred[:, :4], orig_img.shape)

            pred_kpts = pred[:, -kpt_size:].view(len(pred), *self.model.kpt_shape) if len(pred) else pred[:, -kpt_size:]
            pred_kpts = ops.scale_coords(img.shape[2:], pred_kpts, orig_img.shape)
            results.append(
                Results(
                    orig_img, path=img_path, names=self.model.names, boxes=pred[:, :6], masks=masks, keypoints=pred_kpts
                )
            )
        return results

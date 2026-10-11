# Ultralytics YOLO 🚀, AGPL-3.0 license

from pathlib import Path

import numpy as np
import torch

from ultralytics.models.yolo.detect import DetectionValidator
from ultralytics.utils import ops
from ultralytics.utils.metrics import OKS_SIGMA, OriPoseMetrics, batch_probiou, deg_tolerances, kpt_iou
from ultralytics.utils.plotting import output_to_rotated_target, plot_images


class OriPoseValidator(DetectionValidator):
    """
    A class extending the DetectionValidator class for validation based on a oripose model.

    Example:
        ```python
        from ultralytics.models.yolo.ori_pose import OriPoseValidator

        args = dict(model='yolov8n-ori-pose.pt')
        validator = OriPoseValidator(args=args)
        validator()
        ```
    """

    def __init__(self, dataloader=None, save_dir=None, pbar=None, args=None, _callbacks=None):
        """Initialize OriPoseValidator and set task to 'ori_pose', metrics to OriPoseMetrics."""
        super().__init__(dataloader, save_dir, pbar, args, _callbacks)
        self.sigma = None
        self.kpt_shape = None
        self.process = None
        self.args.task = "ori_pose"
        self.metrics = OriPoseMetrics(save_dir=self.save_dir, on_plot=self.on_plot)

    def preprocess(self, batch):
        """Preprocesses batch by converting degs to float and sending to device."""
        batch = super().preprocess(batch)
        batch["degs"] = batch["degs"].to(self.device).float()
        batch["keypoints"] = batch["keypoints"].to(self.device).float()
        return batch

    def init_metrics(self, model):
        """Initialize metrics."""
        super().init_metrics(model)
        self.kpt_shape = self.data["kpt_shape"]
        is_pose = self.kpt_shape == [17, 3]
        nkpt = self.kpt_shape[0]
        self.sigma = OKS_SIGMA if is_pose else np.ones(nkpt) / nkpt
        self.stats = dict(tp_p=[], tp=[], tp_deg=[], conf=[], pred_cls=[], target_cls=[], target_img=[])

    def _prepare_batch(self, si, batch):
        """Prepares a batch for processing by converting keypoints to float and moving to device."""
        idx = batch["batch_idx"] == si
        cls = batch["cls"][idx].squeeze(-1)
        bbox = batch["bboxes"][idx]
        ori_shape = batch["ori_shape"][si]
        imgsz = batch["img"].shape[2:]
        ratio_pad = batch["ratio_pad"][si]
        degs = batch["degs"][idx]
        if len(cls):
            bbox[..., :4].mul_(torch.tensor(imgsz, device=self.device)[[1, 0, 1, 0]])  # target boxes
            ops.scale_boxes(imgsz, bbox, ori_shape, ratio_pad=ratio_pad, xywh=True)  # native-space labels
        kpts = batch["keypoints"][batch["batch_idx"] == si]
        kpts = kpts.clone()
        kpts[..., 0] *= imgsz[0]
        kpts[..., 1] *= imgsz[1]
        kpts = ops.scale_coords(imgsz, kpts, ori_shape, ratio_pad=ratio_pad)
        return dict(cls=cls, bbox=bbox, degs=degs, kpts=kpts, ori_shape=ori_shape, imgsz=imgsz, ratio_pad=ratio_pad)

    def _prepare_pred(self, pred, pbatch):
        """Prepares and scales keypoints in a batch for pose processing."""
        predn = pred.clone()
        ops.scale_boxes(
            pbatch["imgsz"], predn[:, :4], pbatch["ori_shape"], ratio_pad=pbatch["ratio_pad"], xywh=True
        )  # native-space pred
        nk = pbatch["kpts"].shape[1]
        pred_kpts = predn[:, 6:-2].view(len(predn), nk, -1)
        ops.scale_coords(pbatch["imgsz"], pred_kpts, pbatch["ori_shape"], ratio_pad=pbatch["ratio_pad"])
        return predn, pred_kpts

    def get_desc(self):
        """Return a formatted description of evaluation metrics."""
        return ("%22s" + "%11s" * 14) % (
            "Class",
            "Images",
            "Instances",
            "Box(P",
            "R",
            "mAP50",
            "mAP50-95)",
            "Deg(P",
            "R",
            "mAP50",
            "mAP50-95)",
            "Pose(P",
            "R",
            "mAP50",
            "mAP50-95)",
        )

    def postprocess(self, preds):
        """Apply Non-maximum suppression to prediction outputs."""
        return ops.non_max_suppression(
            preds,
            self.args.conf,
            self.args.iou,
            labels=self.lb,
            multi_label=True,
            agnostic=self.args.single_cls or self.args.agnostic_nms,
            max_det=self.args.max_det,
            nc=self.nc,
            rotated=True,
        )

    def update_metrics(self, preds, batch):
        """Metrics."""
        for si, pred in enumerate(preds):
            self.seen += 1
            npr = len(pred)
            stat = dict(
                conf=torch.zeros(0, device=self.device),
                pred_cls=torch.zeros(0, device=self.device),
                tp=torch.zeros(npr, self.niou, dtype=torch.bool, device=self.device),
                tp_p=torch.zeros(npr, self.niou, dtype=torch.bool, device=self.device),
                tp_deg=torch.zeros(npr, self.niou, dtype=torch.bool, device=self.device),
            )
            pbatch = self._prepare_batch(si, batch)
            cls, bbox = pbatch.pop("cls"), pbatch.pop("bbox")
            nl = len(cls)
            stat["target_cls"] = cls
            stat["target_img"] = cls.unique()
            if npr == 0:
                if nl:
                    for k in self.stats.keys():
                        self.stats[k].append(stat[k])
                continue
            # Degs
            degs = pbatch.pop("degs")

            # Predictions
            if self.args.single_cls:
                pred[:, 5] = 0
            predn, pred_kpts = self._prepare_pred(pred, pbatch)
            stat["conf"] = predn[:, 4]
            stat["pred_cls"] = predn[:, 5]

            # Evaluate
            if nl:
                stat["tp"] = self._process_batch(predn, bbox, cls)
                stat["tp_p"] = self._process_batch(predn, bbox, cls, pred_kpts, pbatch["kpts"])
                stat["tp_deg"] = self._process_batch(predn, bbox, cls, target_degs=degs)
            if self.args.plots:
                self.confusion_matrix.process_batch(
                    torch.cat([predn[:, :6], predn[:, -1:]], dim=-1), # convert ori-pose to obb
                    bbox,
                    cls,
                )

            for k in self.stats.keys():
                self.stats[k].append(stat[k])

            # Save
            if self.args.save_json:
                self.pred_to_json(predn, batch["im_file"][si])

    def _process_batch(self, detections, gt_bboxes, gt_cls, pred_kpts=None, gt_kpts=None, target_degs=None):
        """
        Return correct prediction matrix.

        Args:
            detections (torch.Tensor): Tensor of shape [N, 6] representing detections.
                Each detection is of the format: x1, y1, x2, y2, conf, class.
            labels (torch.Tensor): Tensor of shape [M, 5] representing labels.
                Each label is of the format: class, x1, y1, x2, y2.
            pred_kpts (torch.Tensor, optional): Tensor of shape [N, 51] representing predicted keypoints.
                51 corresponds to 17 keypoints each with 3 values.
            gt_kpts (torch.Tensor, optional): Tensor of shape [N, 51] representing ground truth keypoints.
            target_degs (torch.Tensor): Tensor of shape [M] representing degs.
        Returns:
            torch.Tensor: Correct prediction matrix of shape [N, 10] for 10 IoU levels.
        """
        if pred_kpts is not None and gt_kpts is not None:
            # `0.53` is from https://github.com/jin-s13/xtcocoapi/blob/master/xtcocotools/cocoeval.py#L384
            # convert degree to radiant
            target_bboxes = gt_bboxes.clone()
            target_bboxes = ops.xywhr2xyxyxyxy(target_bboxes)
            x = target_bboxes[..., 0]
            y = target_bboxes[..., 1]
            xmin = x.min(dim=-1).values.unsqueeze(dim=-1)
            ymin = y.min(dim=-1).values.unsqueeze(dim=-1)
            xmax = x.max(dim=-1).values.unsqueeze(dim=-1)
            ymax = y.max(dim=-1).values.unsqueeze(dim=-1)
            # xyxy boxes
            target_bboxes = torch.cat((xmin, ymin, xmax, ymax), dim=-1)
            area = ops.xyxy2xywh(target_bboxes)[:, 2:].prod(1) * 0.53
            iou = kpt_iou(gt_kpts, pred_kpts, sigma=self.sigma, area=area)
        elif target_degs is not None:
            iou = deg_tolerances(target_degs, detections[:, -2])
        else:  # boxes
            iou = batch_probiou(gt_bboxes, torch.cat([detections[:, :4], detections[:, -1:]], dim=-1))

        return self.match_predictions(detections[:, 5], gt_cls, iou)

    def plot_val_samples(self, batch, ni):
        """Plots validation samples with bounding box labels."""
        plot_images(
            batch["img"],
            batch["batch_idx"],
            batch["cls"].squeeze(-1),
            batch["bboxes"],
            kpts=batch["keypoints"],
            degs=batch["degs"],
            paths=batch["im_file"],
            fname=self.save_dir / f"val_batch{ni}_labels.jpg",
            names=self.names,
            on_plot=self.on_plot,
        )

    def plot_predictions(self, batch, preds, ni):
        """Plots predicted bounding boxes on input images and saves the result."""
        degPreds = torch.cat([p[: self.args.max_det, -2] for p in preds], -1)
        pred_kpts = torch.cat([p[: self.args.max_det, 6:-2].view(-1, *self.kpt_shape) for p in preds], 0)
        obbPreds = [torch.cat([p[..., :6], p[..., -1:]], dim=-1) for p in preds]
        plot_images(
            batch["img"],
            *output_to_rotated_target(obbPreds, max_det=self.args.max_det),
            kpts=pred_kpts,
            degs=degPreds,
            paths=batch["im_file"],
            fname=self.save_dir / f"val_batch{ni}_pred.jpg",
            names=self.names,
            on_plot=self.on_plot,
        )  # pred

    def pred_to_json(self, predn, filename):
        """Serialize YOLO predictions to COCO json format."""
        stem = Path(filename).stem
        image_id = int(stem) if stem.isnumeric() else stem
        rbox = torch.cat([predn[:, :4], predn[:, -2:-1]], dim=-1)
        poly = ops.xywhr2xyxyxyxy(rbox).view(-1, 8)
        degs = predn[..., -1]
        keypoints = predn[..., 6:-2]
        for i, (r, b, p) in enumerate(zip(rbox.tolist(), poly.tolist(), keypoints.tolist())):
            self.jdict.append(
                {
                    "image_id": image_id,
                    "category_id": self.class_map[int(predn[i, 5].item())],
                    "score": round(predn[i, 4].item(), 5),
                    "rbox": [round(x, 3) for x in r],
                    "poly": [round(x, 3) for x in b],
                    "deg": round(degs[i].item(), 3),
                    "keypoints": [round(x, 3) for x in p],
                }
            )

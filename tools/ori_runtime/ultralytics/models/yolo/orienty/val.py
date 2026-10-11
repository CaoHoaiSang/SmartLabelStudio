# Ultralytics YOLO 🚀, AGPL-3.0 license

from pathlib import Path

import torch

from ultralytics.models.yolo.detect import DetectionValidator
from ultralytics.utils import LOGGER, ops
from ultralytics.utils.metrics import OrientyMetrics, batch_probiou, deg_tolerances
from ultralytics.utils.plotting import output_to_rotated_target, plot_images


class OrientationValidator(DetectionValidator):
    """
    A class extending the DetectionValidator class for validation based on a Orientation model.

    Example:
        ```python
        from ultralytics.models.yolo.orienty import OrientationValidator

        args = dict(model='yolov8n-ori.pt')
        validator = OrientationValidator(args=args)
        validator()
        ```
    """

    def __init__(self, dataloader=None, save_dir=None, pbar=None, args=None, _callbacks=None):
        """Initialize OrientationValidator and set task to 'orienty', metrics to OrientyMetrics."""
        super().__init__(dataloader, save_dir, pbar, args, _callbacks)
        self.args.task = "orienty"
        self.metrics = OrientyMetrics(save_dir=self.save_dir, plot=True, on_plot=self.on_plot)

    def preprocess(self, batch):
        """Preprocesses batch by converting degs to float and sending to device."""
        batch = super().preprocess(batch)
        batch["degs"] = batch["degs"].to(self.device).float()
        return batch

    def init_metrics(self, model):
        """Initialize evaluation metrics for YOLO."""
        super().init_metrics(model)
        self.stats = dict(tp_deg=[], tp=[], conf=[], pred_cls=[], target_cls=[], target_img=[])

    def get_desc(self):
        """Return a formatted description of evaluation metrics."""
        return ("%22s" + "%11s" * 10) % (
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

    def _prepare_batch(self, si, batch):
        """Prepares and returns a batch for Oriented validation."""
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
        return dict(cls=cls, bbox=bbox, degs=degs, ori_shape=ori_shape, imgsz=imgsz, ratio_pad=ratio_pad)

    def _prepare_pred(self, pred, pbatch):
        """Prepares and returns a batch for Orienty validation with scaled and padded bounding boxes."""
        predn = pred.clone()
        ops.scale_boxes(
            pbatch["imgsz"], predn[:, :4], pbatch["ori_shape"], ratio_pad=pbatch["ratio_pad"], xywh=True
        )  # native-space pred
        rboxes = ops.regularize_orientyBoxes(torch.cat([predn[:, :4], predn[:, -1:]], dim=-1), predn[:, -2] * torch.pi / 180)
        predn[:, :4] = rboxes[:, :4]
        predn[:, -1] = rboxes[:, 4]
        predn[:, -2] = rboxes[:, 4] * 180 / torch.pi
        return predn

    def update_metrics(self, preds, batch):
        """Metrics."""
        for si, pred in enumerate(preds):
            self.seen += 1
            npr = len(pred)
            stat = dict(
                conf=torch.zeros(0, device=self.device),
                pred_cls=torch.zeros(0, device=self.device),
                tp=torch.zeros(npr, self.niou, dtype=torch.bool, device=self.device),
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
            predn = self._prepare_pred(pred, pbatch)
            stat["conf"] = predn[:, 4]
            stat["pred_cls"] = predn[:, 5]

            # Evaluate
            if nl:
                stat["tp"] = self._process_batch(predn, bbox, cls)
                stat["tp_deg"] = self._process_batch(predn, bbox, cls, degs)
            if self.args.plots:
                self.confusion_matrix.process_batch(
                    torch.cat((predn[:, :-2], predn[:, -1:]), dim=1), # convert orienty to obb
                    bbox,
                    cls,
                )
            for k in self.stats.keys():
                self.stats[k].append(stat[k])

            # Save
            if self.args.save_json:
                self.pred_to_json(predn, batch["im_file"][si])
            if self.args.save_txt:
                file = self.save_dir / "labels" / f'{Path(batch["im_file"][si]).stem}.txt'
                self.save_one_txt(predn, self.args.save_conf, pbatch["ori_shape"], file)

    def _process_batch(self, detections, gt_bboxes, gt_cls, target_degs=None):
        """
        Return correct prediction matrix.

        Args:
            detections (torch.Tensor): Tensor of shape [N, 6] representing detections.
                Each detection is of the format: x1, y1, x2, y2, conf, class, degree.
            gt_bboxes (torch.Tensor): Tensor of shape [N, 5] representing gt_bboxes.
                Each label is of the format: x, y, w, h, degree
            gt_cls (torch.Tensor): Tensor of shape [N, 1] representing gt_cls.
                Each label is of the format: class, x1, y1, x2, y2.
            target_deg (torch.Tensor): Tensor of shape [N, 1] representing degree.
        Returns:
            torch.Tensor: Correct prediction matrix of shape [N, 10] for 10 IoU levels.
        """
        if target_degs is not None:
            iou = torch.minimum(deg_tolerances(target_degs, detections[:, -2]),
                                batch_probiou(gt_bboxes, torch.cat([detections[:, :4], detections[:, -1:]], dim=-1)))
        else:  # boxes
            iou = batch_probiou(gt_bboxes, torch.cat([detections[:, :4], detections[:, -1:]], dim=-1))

        return self.match_predictions(detections[:, 5], gt_cls, iou)

    def plot_val_samples(self, batch, ni):
        """Plots validation samples with orienty line and bounding box labels."""
        plot_images(
            batch["img"],
            batch["batch_idx"],
            batch["cls"].squeeze(-1),
            batch["bboxes"],
            degs=batch["degs"],
            paths=batch["im_file"],
            fname=self.save_dir / f"val_batch{ni}_labels.jpg",
            names=self.names,
            on_plot=self.on_plot,
        )

    def plot_predictions(self, batch, preds, ni):
        """Plots predicted orienty bounding boxes on input images and saves the result."""
        degPreds = torch.cat([p[: self.args.max_det, -2] for p in preds], -1)
        obbPreds = [torch.cat([pred[..., :-2], pred[..., -1:]], -1) for pred in preds]
        plot_images(
            batch["img"],
            *output_to_rotated_target(obbPreds, max_det=self.args.max_det),
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
        rbox = torch.cat([predn[:, :4], predn[:, -1:]], dim=-1)
        poly = ops.xywhr2xyxyxyxy(rbox).view(-1, 8)
        degs = predn[..., -2]
        for i, (r, b) in enumerate(zip(rbox.tolist(), poly.tolist())):
            self.jdict.append(
                {
                    "image_id": image_id,
                    "category_id": self.class_map[int(predn[i, 5].item())],
                    "score": round(predn[i, 4].item(), 5),
                    "rbox": [round(x, 3) for x in r],
                    "poly": [round(x, 3) for x in b],
                    "deg": round(degs[i].item(), 3),
                }
            )

    def save_one_txt(self, predn, save_conf, shape, file):
        """Save YOLO detections to a txt file in normalized coordinates in a specific format."""
        gn = torch.tensor(shape)[[1, 0]]  # normalization gain whwh
        for *xywh, conf, cls, degs, angle in predn.tolist():
            xywha = torch.tensor([*xywh, angle]).view(1, 5)
            xyxyxyxy = (ops.xywhr2xyxyxyxy(xywha) / gn).view(-1).tolist()  # normalized xywh
            line = (cls, *xyxyxyxy, conf) if save_conf else (cls, *xyxyxyxy)  # label format
            with open(file, "a") as f:
                f.write(("%g " * len(line)).rstrip() % line + "\n")

    def eval_json(self, stats):
        """Evaluates YOLO output in JSON format and returns performance statistics."""
        if self.args.save_json and len(self.jdict):
            import json
            import re
            from collections import defaultdict

            pred_json = self.save_dir / "predictions.json"  # predictions
            pred_txt = self.save_dir / "predictions_txt"  # predictions
            pred_txt.mkdir(parents=True, exist_ok=True)
            data = json.load(open(pred_json))
            # Save split results
            LOGGER.info(f"Saving predictions with DOTA format to {pred_txt}...")
            for d in data:
                image_id = d["image_id"]
                score = d["score"]
                classname = self.names[d["category_id"]].replace(" ", "-")
                p = d["poly"]

                with open(f'{pred_txt / f"Task1_{classname}"}.txt', "a") as f:
                    f.writelines(f"{image_id} {score} {p[0]} {p[1]} {p[2]} {p[3]} {p[4]} {p[5]} {p[6]} {p[7]}\n")
            # Save merged results, this could result slightly lower map than using official merging script,
            # because of the probiou calculation.
            pred_merged_txt = self.save_dir / "predictions_merged_txt"  # predictions
            pred_merged_txt.mkdir(parents=True, exist_ok=True)
            merged_results = defaultdict(list)
            LOGGER.info(f"Saving merged predictions with DOTA format to {pred_merged_txt}...")
            for d in data:
                image_id = d["image_id"]
                bbox, score, cls = d["rbox"], d["score"], d["category_id"]
                bbox.extend([score, cls])
                merged_results[image_id].append(bbox)
            for image_id, bbox in merged_results.items():
                bbox = torch.tensor(bbox)
                max_wh = torch.max(bbox[:, :2]).item() * 2
                c = bbox[:, 6:7] * max_wh  # classes
                scores = bbox[:, 5]  # scores
                b = bbox[:, :5].clone()
                b[:, :2] += c
                # 0.3 could get results close to the ones from official merging script, even slightly better.
                i = ops.nms_rotated(b, scores, 0.3)
                bbox = bbox[i]

                b = ops.xywhr2xyxyxyxy(bbox[:, :5]).view(-1, 8)
                for x in torch.cat([b, bbox[:, 5:7]], dim=-1).tolist():
                    classname = self.names[int(x[-1])].replace(" ", "-")
                    p = [round(i, 3) for i in x[:-2]]  # poly
                    score = round(x[-2], 3)

                    with open(f'{pred_merged_txt / f"Task1_{classname}"}.txt', "a") as f:
                        f.writelines(f"{image_id} {score} {p[0]} {p[1]} {p[2]} {p[3]} {p[4]} {p[5]} {p[6]} {p[7]}\n")

        return stats

from typing import List
import numpy as np
import math
import cv2
from abc import abstractmethod

from YOLORKNN.engine.predictor import BasePredictor
from YOLORKNN.engine.result import Result
from YOLORKNN.runtime.RKNNRuntime import RKNNRuntime
from YOLORKNN.utils.ops import (
    non_max_suppression, scale_boxes, regularize_rboxes, regularize_orientBoxes,
    process_mask, scale_masks
    )
from YOLORKNN.utils.neuralOperations import sigmoid

from .utils import yolov8_obb_decoding, yolov8_decoding


class BaseRKNNYoloPredictor(BasePredictor):

    STRIDES = np.array([8, 16, 32])
    REGRESSION_LENGTH = 15

    def __init__(self, 
                 rknn_model_path: str, 
                 names: List[str],
                 iou=0.5, 
                 conf=0.5) -> None:
        super().__init__(iou, conf)
        self._runtime = RKNNRuntime(rknn_model_path)
        self.names = names

    @property
    def runtime(self) -> RKNNRuntime:
        return self._runtime

    def inference(self, image: np.ndarray) -> Result:
        self.origin_height, self.origin_width, _ = image.shape
        infer_datas: List[np.ndarray] = self.runtime.execute(image)
        return self.post_processing(infer_datas)
    
    @abstractmethod
    def post_processing(self, infer_datas: List[np.ndarray])-> Result:
        pass

class DetRKNNPredictor(BaseRKNNYoloPredictor):

    def _prepare_endnodes(self, infer_datas: List[np.ndarray]):

        defualt_branch=3
        pair_per_branch = len(infer_datas)//defualt_branch
        endnodes: List[np.ndarray] = []
        for i in range(defualt_branch):
            endnodes.append(infer_datas[pair_per_branch*i])
            endnodes.append(infer_datas[pair_per_branch*i+1])

        return [_v.transpose(0,2,3,1) for _v in endnodes]

    def _generate_yolo_predictions(self, endnodes):
        """
        endnodes is a list of 6 tensors:
            endnodes[0]:  bbox output with shapes (BS, 80, 80, 64)
            endnodes[1]:  scores output with shapes (BS, 80, 80, 80)
            endnodes[2]:  bbox output with shapes (BS, 40, 40, 64)
            endnodes[3]:  scores output with shapes (BS, 40, 40, 80)
            endnodes[4]:  bbox output with shapes (BS, 20, 20, 64)
            endnodes[5]:  scores output with shapes (BS, 20, 20, 80)
        Returns:
            numpy.ndarray: A concatenated array of shape (BS, total_predictions, 4 + num_classes) where:
                - `total_predictions` is the sum of predictions across all scales (20x20, 40x40, 80x80).
                - Each prediction contains:
                    - `4` values for the bounding box coordinates in the format [x_min, y_min, x_max, y_max].
                    - `num_classes` values for the confidence scores for each class.
        """
        image_dims = self.runtime.height, self.runtime.width
        raw_boxes = endnodes[:5:2]
        scores = [np.reshape(s, (-1, s.shape[1] * s.shape[2], len(self.names))) for s in endnodes[1:6:2]]
        scores = np.concatenate(scores, axis=1)
        decoded_boxes = yolov8_decoding(raw_boxes, self.STRIDES, image_dims, self.REGRESSION_LENGTH)
        return np.concatenate([decoded_boxes, scores], axis=2)
    
    def post_processing(self, infer_datas: List[np.ndarray])-> Result:
        endnodes = self._prepare_endnodes(infer_datas)
        preds = self._generate_yolo_predictions(endnodes)
        preds = non_max_suppression(
            preds,
            len(self.names),
            self.conf,
            self.iou
        )

        pred = preds[0] # in source code, batch_size only = 1
        if len(pred) == 0:
            return Result()
        pred[:, :4] = scale_boxes(
                        (self.runtime.height, self.runtime.width), 
                        pred[:, :4], 
                        (self.origin_height, self.origin_width),
                    )
        return Result(self.origin_height, self.origin_width, 
                                  names=self.names, 
                                  boxes=pred)

class OBBRKNNPredictor(BaseRKNNYoloPredictor):
    
    def _prepare_endnodes(self, infer_datas: List[np.ndarray]):

        defualt_branch=3
        channels_boxes = 64
        endnodes: List[np.ndarray] = []
        for i in range(defualt_branch):
            # Split the first tensor based on channels_boxes
            endnodes.append(infer_datas[i][:, :channels_boxes, :, :])
            endnodes.append(sigmoid(infer_datas[i][:, channels_boxes:, :, :]))

            # Process infer_datas[-1] angles
            if i == 0:
                endnodes.append(infer_datas[-1][:, :, :80 * 80])
            elif i == 1:
                endnodes.append(infer_datas[-1][:, :, 80 * 80: 80 * 80 + 40 * 40])
            elif i == 2:
                endnodes.append(infer_datas[-1][:, :, 80 * 80 + 40 * 40:])

        # Ensure no errors occur regardless of tensor dimension (3D or 4D)
        result = []
        for _v in endnodes:
            if _v.ndim == 4:
                # If the tensor has 4 dimensions, apply transpose (0, 2, 3, 1)
                result.append(_v.transpose(0, 2, 3, 1))
            elif _v.ndim == 3:
                # If the tensor has 3 dimensions, apply transpose (0, 2, 1)
                result.append(_v.transpose(0, 2, 1))
            else:
                raise ValueError(f"Unsupported tensor dimension: {_v.ndim}")

        return result

    def _generate_yolo_predictions(self, endnodes):
        """
        endnodes is a list of 9 tensors:
            endnodes[0]:  bbox output with shapes (BS, 80, 80, 64)
            endnodes[1]:  scores output with shapes (BS, 80, 80, 80)
            endnodes[2]:  angles output with shapes (BS, 80*80, 1)
            endnodes[3]:  bbox output with shapes (BS, 40, 40, 64)
            endnodes[4]:  scores output with shapes (BS, 40, 40, 80)
            endnodes[5]:  angles output with shapes (BS, 40*40, 1)
            endnodes[6]:  bbox output with shapes (BS, 20, 20, 64)
            endnodes[7]:  scores output with shapes (BS, 20, 20, 80)
            endnodes[8]:  angles output with shapes (BS, 20*20, 1)
        Returns:
            numpy.ndarray: A concatenated array of shape (BS, total_predictions, 5 + num_classes) where:
                - `total_predictions` is the sum of predictions across all scales (20x20, 40x40, 80x80).
                - Each prediction contains:
                    - `4` values for the bounding box coordinates in the format [x, y, w, h].
                    - `1` value representing the angle of rotation.
                    - `num_classes` values for the confidence scores for each class.
        """
        image_dims = self.runtime.height, self.runtime.width
        raw_boxes = endnodes[:7:3]
        angles = [(x - 0.25) * math.pi for x in endnodes[2::3]]
        decoded_boxes = yolov8_obb_decoding(raw_boxes, angles, self.STRIDES, image_dims, self.REGRESSION_LENGTH)
        scores = [np.reshape(s, (-1, s.shape[1] * s.shape[2], len(self.names))) for s in endnodes[1:8:3]]
        scores = np.concatenate(scores, axis=1)
        angles = np.concatenate(angles, axis=1)
        return np.concatenate([decoded_boxes, scores, angles], axis=2)
    
    def post_processing(self, infer_datas: List[np.ndarray])-> Result:
        endnodes = self._prepare_endnodes(infer_datas)
        preds = self._generate_yolo_predictions(endnodes)
        preds = non_max_suppression(
            preds,
            len(self.names),
            self.conf,
            self.iou,
            rotated=True
        )

        pred = preds[0] # in source code, batch_size only = 1
        if len(pred) == 0:
            return Result()
        rboxes = regularize_rboxes(np.concatenate([pred[:, :4], pred[:, -1:]], -1))
        rboxes[:, :4] = scale_boxes((self.runtime.height, self.runtime.width), 
                        rboxes[:, :4], 
                        (self.origin_height, self.origin_width),
                        xywh=True
                        )
        # xywh, r, conf, cls
        obb = np.concatenate([rboxes, pred[:, 4:6]], -1)
        return Result(self.origin_height, self.origin_width, 
                                  names=self.names, 
                                  obb=obb)

class OriRKNNPredictor(BaseRKNNYoloPredictor):
    def _prepare_endnodes(self, infer_datas: List[np.ndarray]):

        expected = [(1, 64 + len(self.names), side, side) for side in (80, 40, 20)] + [(1, 1, 8400), (1, 1, 8400)]
        if len(infer_datas) != 5 or [tuple(t.shape) for t in infer_datas] != expected:
            raise ValueError(f"ORI requires 5 heads at 640x640; expected {expected}, got {[tuple(t.shape) for t in infer_datas]}")
        if any(not np.isfinite(t).all() for t in infer_datas):
            raise ValueError("ORI outputs contain NaN or infinity")

        defualt_branch=3
        channels_boxes = 64
        endnodes: List[np.ndarray] = []
        for i in range(defualt_branch):
            # Split the first tensor based on channels_boxes
            endnodes.append(infer_datas[i][:, :channels_boxes, :, :])
            endnodes.append(sigmoid(infer_datas[i][:, channels_boxes:, :, :]))

            # Process infer_datas[-2] angles, infer_datas[-1] degs
            if i == 0:
                endnodes.append(infer_datas[-2][:, :, :80 * 80])
                endnodes.append(infer_datas[-1][:, :, :80 * 80])
            elif i == 1:
                endnodes.append(infer_datas[-2][:, :, 80 * 80: 80 * 80 + 40 * 40])
                endnodes.append(infer_datas[-1][:, :, 80 * 80: 80 * 80 + 40 * 40])
            elif i == 2:
                endnodes.append(infer_datas[-2][:, :, 80 * 80 + 40 * 40:])
                endnodes.append(infer_datas[-1][:, :, 80 * 80 + 40 * 40:])

        # Ensure no errors occur regardless of tensor dimension (3D or 4D)
        result = []
        for _v in endnodes:
            if _v.ndim == 4:
                # If the tensor has 4 dimensions, apply transpose (0, 2, 3, 1)
                result.append(_v.transpose(0, 2, 3, 1))
            elif _v.ndim == 3:
                # If the tensor has 3 dimensions, apply transpose (0, 2, 1)
                result.append(_v.transpose(0, 2, 1))
            else:
                raise ValueError(f"Unsupported tensor dimension: {_v.ndim}")

        return result

    def _generate_yolo_predictions(self, endnodes):
        """
        endnodes is a list of 9 tensors:
            endnodes[0]:  bbox output with shapes (BS, 80, 80, 64)
            endnodes[1]:  scores output with shapes (BS, 80, 80, 80)
            endnodes[2]:  angles output with shapes (BS, 80*80, 1)
            endnodes[3]:  degs output with shapes (BS, 80*80, 1)
            endnodes[4]:  bbox output with shapes (BS, 40, 40, 64)
            endnodes[5]:  scores output with shapes (BS, 40, 40, 80)
            endnodes[6]:  angles output with shapes (BS, 40*40, 1)
            endnodes[7]:  degs output with shapes (BS, 40*40, 1)
            endnodes[8]:  bbox output with shapes (BS, 20, 20, 64)
            endnodes[9]:  scores output with shapes (BS, 20, 20, 80)
            endnodes[10]:  angles output with shapes (BS, 20*20, 1)
            endnodes[11]:  degs output with shapes (BS, 20*20, 1)
        Returns:
            numpy.ndarray: A concatenated array of shape (BS, total_predictions, 6 + num_classes) where:
                - `total_predictions` is the sum of predictions across all scales (20x20, 40x40, 80x80).
                - Each prediction contains:
                    - `4` values for the bounding box coordinates in the format [x, y, w, h].
                    - `1` value representing the deg of rotation.
                    - `1` value representing the angle of rotation.
        """
        image_dims = self.runtime.height, self.runtime.width
        raw_boxes = endnodes[:9:4]
        angles = [(x - 0.25) * math.pi for x in endnodes[2:11:4]]
        decoded_boxes = yolov8_obb_decoding(raw_boxes, angles, self.STRIDES, image_dims, self.REGRESSION_LENGTH)
        scores = [np.reshape(s, (-1, s.shape[1] * s.shape[2], len(self.names))) for s in endnodes[1:10:4]]
        scores = np.concatenate(scores, axis=1)
        degs = np.concatenate(endnodes[3::4], axis=1) * 180  # [-180, 179.99]
        angles = np.concatenate(angles, axis=1)
        return np.concatenate([decoded_boxes, scores, degs, angles], axis=2)
    
    def post_processing(self, infer_datas: List[np.ndarray])-> Result:
        endnodes = self._prepare_endnodes(infer_datas)
        preds = self._generate_yolo_predictions(endnodes)
        preds = non_max_suppression(
            preds,
            len(self.names),
            self.conf,
            self.iou,
            rotated=True
        )
        pred = preds[0] # in source code, batch_size only = 1
        if len(pred) == 0:
            return Result()
        rboxes = np.concatenate([pred[:, :4], pred[:, -1:]], -1)
        rboxes[:, :4] = scale_boxes((self.runtime.height, self.runtime.width), 
                        rboxes[:, :4], 
                        (self.origin_height, self.origin_width),
                        xywh=True
                        )
        degs = pred[:, -2]
        rboxes, degs = regularize_orientBoxes(rboxes, degs)
        # xywh, r, conf, cls
        obb = np.concatenate([rboxes, pred[:, 4:6]], -1)
        return Result(self.origin_height, self.origin_width, 
                                  names=self.names,
                                  degs=degs, 
                                  obb=obb)


class SegRKNNPredictor(BaseRKNNYoloPredictor):
    """
    Predictor for YOLOv8 Instance Segmentation on RKNN.
    
    Expected RKNN output structure (13 tensors):
        Scale 80x80: box(64), obj(1), cls(nc), seg(32)  [indices 0-3]
        Scale 40x40: box(64), obj(1), cls(nc), seg(32)  [indices 4-7]
        Scale 20x20: box(64), obj(1), cls(nc), seg(32)  [indices 8-11]
        Proto: (1, 32, 160, 160)  [index 12]
    """

    def _dfl_decode(self, box_head, h, w):
        """DFL decode: (1,64,h,w) -> (h*w, 4) xyxy boxes."""
        img_h, img_w = self.runtime.height, self.runtime.width
        stride_h, stride_w = img_h // h, img_w // w
        
        # DFL softmax: (1,64,h,w) -> (4,16,h,w) -> softmax -> weighted sum
        x = box_head[0].reshape(4, 16, h, w)
        x = np.exp(x - x.max(axis=1, keepdims=True))
        x = x / x.sum(axis=1, keepdims=True)
        out = (x * np.arange(16).reshape(1, 16, 1, 1)).sum(axis=1)  # (4,h,w)
        
        # Grid + decode
        col, row = np.meshgrid(np.arange(w), np.arange(h))
        x1 = (col + 0.5 - out[0]) * stride_w
        y1 = (row + 0.5 - out[1]) * stride_h
        x2 = (col + 0.5 + out[2]) * stride_w
        y2 = (row + 0.5 + out[3]) * stride_h
        
        return np.stack([x1, y1, x2, y2], axis=-1).reshape(-1, 4)

    def _nms(self, boxes, scores, thresh=0.45):
        """Simple NMS."""
        order = scores.argsort()[::-1]
        keep = []
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        
        while order.size > 0:
            i = order[0]
            keep.append(i)
            if order.size == 1:
                break
            xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
            yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
            xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
            yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
            inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
            iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-8)
            order = order[1:][iou <= thresh]
        return keep

    def post_processing(self, infer_datas: List[np.ndarray]) -> Result:
        img_h, img_w = self.runtime.height, self.runtime.width
        nc = len(self.names)  # number of classes
        
        # Decode boxes + flatten scores/seg for each scale
        # Output order: box(64), obj(nc), cls(1), seg(32)
        scales = [(80, 80, 0), (40, 40, 4), (20, 20, 8)]
        all_boxes, all_obj, all_cls, all_seg = [], [], [], []
        
        for h, w, idx in scales:
            all_boxes.append(self._dfl_decode(infer_datas[idx], h, w))
            all_obj.append(infer_datas[idx+1].transpose(0,2,3,1).reshape(-1, nc))  # (h*w, nc)
            all_cls.append(infer_datas[idx+2].transpose(0,2,3,1).reshape(-1, 1))   # (h*w, 1)
            all_seg.append(infer_datas[idx+3].transpose(0,2,3,1).reshape(-1, 32))
        
        boxes = np.concatenate(all_boxes)      # (8400, 4)
        obj_raw = np.concatenate(all_obj)      # (8400, nc)
        cls_raw = np.concatenate(all_cls)      # (8400, 1)
        seg = np.concatenate(all_seg)          # (8400, 32)
        
        # Apply sigmoid if values are outside [0,1] range (indicating raw logits)
        def sigmoid(x):
            return 1.0 / (1.0 + np.exp(-np.clip(x, -50, 50)))
        
        obj = sigmoid(obj_raw) if obj_raw.min() < 0 or obj_raw.max() > 1.1 else obj_raw
        cls = sigmoid(cls_raw) if cls_raw.min() < 0 or cls_raw.max() > 1.1 else cls_raw
        
        # For multi-class SEG model:
        #   - obj(nc) contains per-class confidence scores  
        #   - cls(1) is objectness
        # For single-class SEG model (like testrknn.py):
        #   - obj(1) is objectness, cls(1) is class conf
        #   - score = obj * cls
        
        if nc > 1:
            # Multi-class: Try different score strategies
            cls_ids = obj.argmax(axis=1)
            class_scores = obj.max(axis=1)
            objectness = cls[:, 0]
            
            # Use geometric mean (sqrt) to make scores comparable to DET
            # DET has single score, SEG has obj*cls which is always lower
            # sqrt(obj*cls) gives similar range as DET scores
            scores = np.sqrt(class_scores * objectness)
        else:
            # Single-class: same as testrknn.py
            scores = obj[:, 0] * cls[:, 0]
            cls_ids = np.zeros(len(obj))
        
        # Filter by conf
        keep = scores >= self.conf
        if not keep.any():
            return Result()
        
        boxes, scores, cls_ids, seg = boxes[keep], scores[keep], cls_ids[keep], seg[keep]
        
        # NMS
        keep_idx = self._nms(boxes, scores, self.iou)
        if not keep_idx:
            return Result()
        
        boxes = boxes[keep_idx]
        scores = scores[keep_idx]
        cls_ids = cls_ids[keep_idx]
        seg_coefs = seg[keep_idx]
        
        # Decode masks: seg_coefs @ proto -> sigmoid -> threshold
        proto = infer_datas[12][0]  # (32, 160, 160)
        masks_small = 1 / (1 + np.exp(-seg_coefs @ proto.reshape(32, -1)))  # (N, 25600)
        masks_small = (masks_small.reshape(-1, 160, 160) > 0.5).astype(np.uint8)
        
        # Resize masks to input size and crop by bbox
        masks = np.zeros((len(boxes), img_h, img_w), dtype=np.uint8)
        for i, (m, box) in enumerate(zip(masks_small, boxes)):
            masks[i] = cv2.resize(m, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
            x1, y1, x2, y2 = box.astype(int).clip([0, 0, 0, 0], [img_w, img_h, img_w, img_h])
            masks[i, :y1, :] = masks[i, y2:, :] = masks[i, :, :x1] = masks[i, :, x2:] = 0
        
        # Scale to original size
        gain = min(img_h / self.origin_height, img_w / self.origin_width)
        pad_h, pad_w = int((img_h - self.origin_height * gain) / 2), int((img_w - self.origin_width * gain) / 2)
        
        final_masks = np.zeros((len(masks), self.origin_height, self.origin_width), dtype=np.uint8)
        for i, m in enumerate(masks):
            cropped = m[pad_h:img_h-pad_h, pad_w:img_w-pad_w]
            final_masks[i] = cv2.resize(cropped, (self.origin_width, self.origin_height), interpolation=cv2.INTER_NEAREST)
        
        # Scale boxes
        boxes = scale_boxes((img_h, img_w), boxes, (self.origin_height, self.origin_width))
        
        # Result: [x1, y1, x2, y2, conf, cls]
        result_boxes = np.column_stack([boxes, scores, cls_ids])
        
        return Result(self.origin_height, self.origin_width, names=self.names, boxes=result_boxes, masks=final_masks)

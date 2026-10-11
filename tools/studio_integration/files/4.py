import numpy as np
import math
import cv2


PI = math.pi
TWO_PI = 2 * math.pi

def crop_mask(masks, boxes):
    """
    Crop masks by bounding boxes.
    
    Args:
        masks (np.ndarray): Masks with shape (H, W, N).
        boxes (np.ndarray): Bounding boxes with shape (N, 4) in xyxy format.
    
    Returns:
        np.ndarray: Cropped masks with shape (H, W, N).
    """
    n, h, w = masks.shape
    x1, y1, x2, y2 = np.split(boxes[:, :4], 4, axis=1)  # (N, 1) each
    
    # Create coordinate grids
    r = np.arange(w, dtype=np.float32)[None, None, :]  # (1, 1, W)
    c = np.arange(h, dtype=np.float32)[None, :, None]  # (1, H, 1)
    
    # Create masks for each dimension
    mask_x = (r >= x1.reshape(-1, 1, 1)) & (r < x2.reshape(-1, 1, 1))  # (N, 1, W)
    mask_y = (c >= y1.reshape(-1, 1, 1)) & (c < y2.reshape(-1, 1, 1))  # (N, H, 1)
    
    return masks * (mask_x & mask_y).astype(np.float32)


def process_mask(protos, masks_in, bboxes, shape, upsample=False):
    """
    Apply masks to bounding boxes using mask prototypes.
    
    Args:
        protos (np.ndarray): Mask prototypes with shape (H, W, C) where C is 32.
        masks_in (np.ndarray): Mask coefficients with shape (N, C).
        bboxes (np.ndarray): Bounding boxes in xyxy format with shape (N, 4).
        shape (tuple): Input image shape (height, width).
        upsample (bool): Whether to upsample masks to input shape.
    
    Returns:
        np.ndarray: Binary masks with shape (N, H, W).
    """
    c, mh, mw = protos.shape[2], protos.shape[0], protos.shape[1]
    ih, iw = shape
    
    # Compute masks: (N, C) @ (C, H*W) -> (N, H*W) -> (N, H, W)
    # protos: (H, W, C) -> (C, H*W)
    protos_flat = protos.reshape(-1, c).T  # (C, H*W)
    masks = sigmoid_np(masks_in @ protos_flat)  # (N, H*W)
    masks = masks.reshape(-1, mh, mw)  # (N, H, W)
    
    # Scale bboxes (xyxy) to mask size
    scale_x = mw / iw
    scale_y = mh / ih
    bboxes_scaled = bboxes.copy()
    bboxes_scaled[:, [0, 2]] *= scale_x
    bboxes_scaled[:, [1, 3]] *= scale_y
    
    # Crop masks
    masks = crop_mask(masks, bboxes_scaled)
    
    if upsample:
        # Upsample to input size
        masks_upsampled = np.zeros((masks.shape[0], ih, iw), dtype=np.float32)
        for i, mask in enumerate(masks):
            masks_upsampled[i] = cv2.resize(mask, (iw, ih), interpolation=cv2.INTER_LINEAR)
        masks = masks_upsampled
    
    return masks > 0.5  # Binarize


def sigmoid_np(x):
    """Numpy sigmoid function."""
    return 1 / (1 + np.exp(-np.clip(x, -500, 500)))


def scale_masks(masks: np.ndarray, im0_shape):
    """
    Rescale segment masks to original image shape.

    Args:
        masks (np.ndarray): Masks with shape (N, H, W).
        im0_shape (tuple): The original image shape (height, width).

    Returns:
        np.ndarray: Rescaled masks with shape (N, im0_shape[0], im0_shape[1]).
    """
    if masks.shape[1:] == im0_shape[:2]:
        return masks
    
    n, mh, mw = masks.shape
    ih, iw = im0_shape[:2]
    
    # Calculate gain and padding
    gain = min(mh / ih, mw / iw)
    pad_h = (mh - ih * gain) / 2
    pad_w = (mw - iw * gain) / 2
    
    # Crop out padding
    top, left = int(pad_h), int(pad_w)
    bottom, right = int(mh - pad_h), int(mw - pad_w)
    
    scaled_masks = np.zeros((n, ih, iw), dtype=masks.dtype)
    for i in range(n):
        cropped = masks[i, top:bottom, left:right]
        scaled_masks[i] = cv2.resize(cropped.astype(np.float32), (iw, ih), interpolation=cv2.INTER_LINEAR)
    
    return scaled_masks > 0.5


def scale_image(masks: np.ndarray, im0_shape, ratio_pad=None):
    """
    Takes a mask, and resizes it to the original image size.

    Args:
        masks (np.ndarray): resized and padded masks/images, [h, w, num]/[h, w, 3].
        im0_shape (tuple): the original image shape
        ratio_pad (tuple): the ratio of the padding to the original image.

    Returns:
        masks (np.ndarray): The masks that are being returned.
    """
    # Rescale coordinates (xyxy) from im1_shape to im0_shape
    im1_shape = masks.shape
    if im1_shape[:2] == im0_shape[:2]:
        return masks
    if ratio_pad is None:  # calculate from im0_shape
        gain = min(im1_shape[0] / im0_shape[0], im1_shape[1] / im0_shape[1])  # gain  = old / new
        pad = (im1_shape[1] - im0_shape[1] * gain) / 2, (im1_shape[0] - im0_shape[0] * gain) / 2  # wh padding
    else:
        # gain = ratio_pad[0][0]
        pad = ratio_pad[1]
    top, left = int(pad[1]), int(pad[0])  # y, x
    bottom, right = int(im1_shape[0] - pad[1]), int(im1_shape[1] - pad[0])

    if len(masks.shape) < 2:
        raise ValueError(f'"len of masks shape" should be 2 or 3, but got {len(masks.shape)}')
    masks = masks[top:bottom, left:right]
    masks = cv2.resize(masks, (im0_shape[1], im0_shape[0]))
    if len(masks.shape) == 2:
        masks = masks[:, :, None]

    return masks

def rad_delta_t_np(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    a, b: radians arrays (broadcastable)
    return: | ((a - b + pi) mod 2pi) - pi |
    """
    return np.abs(np.remainder(a - b + PI, TWO_PI) - PI)

def naive_is_nonneg_np(rad_r: np.ndarray, rad_deg: np.ndarray) -> np.ndarray:
    return (rad_r - rad_deg) >= 0

def regularize_orientBoxes(
    rboxes: np.ndarray,  # (N, 5) xywhr, r in radians
    degs: np.ndarray,    # (N,) degrees in [-180, 180)
) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns:
        out_rboxes: (N,5) with new angle in radians
        new_deg:   (N,)  with new angle in degrees
    """
    rboxes = np.asarray(rboxes)
    degs = np.asarray(degs)

    # Unbind columns
    x = rboxes[:, 0]
    y = rboxes[:, 1]
    w = rboxes[:, 2]
    h = rboxes[:, 3]
    r = rboxes[:, 4]

    # deg -> rad (match dtype of rboxes)
    dtype = rboxes.dtype
    rad_deg = (degs * (PI / 180.0)).astype(dtype).reshape(-1)
    rad_r = r.astype(dtype).reshape(-1)

    signed_delta = np.remainder(rad_deg - rad_r + PI, TWO_PI) - PI
    delta = np.abs(signed_delta)

    th1 = PI / 4.0
    th2 = 3.0 * PI / 4.0

    m1 = (delta >= th1) & (delta < th2)
    m2 = delta >= th2

    s = signed_delta < 0  # Choose direction using the wrapped difference, including +/-180 boundary.

    # Case 0
    new_rad_deg = rad_r.copy()

    # Case 1: +/- pi/2 depending on sign
    new_rad_deg_m1 = np.where(s, rad_r - PI / 2.0, rad_r + PI / 2.0)
    new_rad_deg = np.where(m1, new_rad_deg_m1, new_rad_deg)

    # Case 2: +/- pi depending on sign
    new_rad_deg_m2 = np.where(s, rad_r - PI, rad_r + PI)
    new_rad_deg = np.where(m2, new_rad_deg_m2, new_rad_deg)

    new_rad_deg = np.remainder(new_rad_deg + PI, TWO_PI) - PI

    # swap w/h for case m1 only
    new_w = np.where(m1, h, w)
    new_h = np.where(m1, w, h)

    # rad -> deg
    new_deg = new_rad_deg * (180.0 / PI)

    out_rboxes = np.stack([x, y, new_w, new_h, new_rad_deg], axis=-1).astype(dtype)

    return out_rboxes, new_deg

def regularize_rboxes(rboxes):
    """
    Regularize rotated boxes in range [0, pi/2].

    Args:
        rboxes (numpy.ndarray): (N, 5), xywhr.

    Returns:
        (numpy.ndarray): The regularized boxes.
    """
    x, y, w, h, t = np.split(rboxes, 5, axis=-1)
    # Swap edge and angle if h >= w
    w_ = np.where(w > h, w, h)
    h_ = np.where(w > h, h, w)
    t = np.where(w > h, t, t + math.pi / 2) % math.pi
    return np.concatenate([x, y, w_, h_, t], axis=-1)

def clip_boxes(boxes, shape):
    """
    Takes a list of bounding boxes and a shape (height, width) and clips the bounding boxes to the shape.

    Args:
        boxes (np.arrayr): the bounding boxes to clip
        shape (tuple): the shape of the image

    Returns:
        (numpy.ndarray): Clipped boxes
    """
    boxes[..., [0, 2]] = boxes[..., [0, 2]].clip(0, shape[1])  # x1, x2
    boxes[..., [1, 3]] = boxes[..., [1, 3]].clip(0, shape[0])  # y1, y2
    return boxes

def scale_boxes(img1_shape, boxes, img0_shape, ratio_pad=None, padding=True, xywh=False):
    """
    Rescales bounding boxes (in the format of xyxy by default) from the shape of the image they were originally
    specified in (img1_shape) to the shape of a different image (img0_shape).

    Args:
        img1_shape (tuple): The shape of the image that the bounding boxes are for, in the format of (height, width).
        boxes (numpy.ndarray): the bounding boxes of the objects in the image, in the format of (x1, y1, x2, y2)
        img0_shape (tuple): the shape of the target image, in the format of (height, width).
        ratio_pad (tuple): a tuple of (ratio, pad) for scaling the boxes. If not provided, the ratio and pad will be
            calculated based on the size difference between the two images.
        padding (bool): If True, assuming the boxes is based on image augmented by yolo style. If False then do regular
            rescaling.
        xywh (bool): The box format is xywh or not, default=False.

    Returns:
        boxes (numpy.ndarray): The scaled bounding boxes, in the format of (x1, y1, x2, y2)
    """
    if ratio_pad is None:  # calculate from img0_shape
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])  # gain  = old / new
        pad = (
            round((img1_shape[1] - img0_shape[1] * gain) / 2 - 0.1),
            round((img1_shape[0] - img0_shape[0] * gain) / 2 - 0.1),
        )  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    if padding:
        boxes[..., 0] -= pad[0]  # x padding
        boxes[..., 1] -= pad[1]  # y padding
        if not xywh:
            boxes[..., 2] -= pad[0]  # x padding
            boxes[..., 3] -= pad[1]  # y padding
    boxes[..., :4] /= gain
    return clip_boxes(boxes, img0_shape)


def xyxy2xywh(x: np.ndarray):
    """
    Convert bounding box coordinates from (x1, y1, x2, y2) format to (x, y, width, height) format where (x1, y1) is the
    top-left corner and (x2, y2) is the bottom-right corner.

    Args:
        x (np.ndarray): The input bounding box coordinates in (x1, y1, x2, y2) format.

    Returns:
        y (np.ndarray): The bounding box coordinates in (x, y, width, height) format.
    """
    assert x.shape[-1] == 4, f"input shape last dimension expected 4 but input shape is {x.shape}"
    y = np.empty_like(x)  # faster than clone/copy
    y[..., 0] = (x[..., 0] + x[..., 2]) / 2  # x center
    y[..., 1] = (x[..., 1] + x[..., 3]) / 2  # y center
    y[..., 2] = x[..., 2] - x[..., 0]  # width
    y[..., 3] = x[..., 3] - x[..., 1]  # height
    return y

def xywhr2xyxyxyxy(rboxes: np.ndarray):
    """
    Convert batched Oriented Bounding Boxes (OBB) from [xywh, rotation] to [xy1, xy2, xy3, xy4]. Rotation values should
    be in degrees from 0 to 90.

    Args:
        rboxes (numpy.ndarray): Input data in [cx, cy, w, h, rotation] format of shape (n, 5) or (b, n, 5).

    Returns:
        (numpy.ndarray): Converted corner points of shape (n, 4, 2) or (b, n, 4, 2).
    """
    cos, sin = (np.cos, np.sin)

    ctr = rboxes[..., :2]
    w, h, angle = (rboxes[..., i : i + 1] for i in range(2, 5))
    cos_value, sin_value = cos(angle), sin(angle)
    vec1 = [w / 2 * cos_value, w / 2 * sin_value]
    vec2 = [-h / 2 * sin_value, h / 2 * cos_value]
    vec1 = np.concatenate(vec1, axis=-1)
    vec2 = np.concatenate(vec2, axis=-1)
    pt1 = ctr + vec1 + vec2
    pt2 = ctr + vec1 - vec2
    pt3 = ctr - vec1 - vec2
    pt4 = ctr - vec1 + vec2
    return np.stack([pt1, pt2, pt3, pt4], axis=-2)

def xywh2xyxy(x):
    """
    Convert bounding box coordinates from (x, y, width, height) format to (x1, y1, x2, y2) format where (x1, y1) is the
    top-left corner and (x2, y2) is the bottom-right corner.

    Args:
        x (np.ndarray): The input bounding box coordinates in (x, y, width, height) format.

    Returns:
        y (np.ndarray): The bounding box coordinates in (x1, y1, x2, y2) format.
    """
    assert x.shape[-1] == 4, f"input shape last dimension expected 4 but input shape is {x.shape}"
    y = np.empty_like(x)  # faster than clone/copy
    dw = x[..., 2] / 2  # half-width
    dh = x[..., 3] / 2  # half-height
    y[..., 0] = x[..., 0] - dw  # top left x
    y[..., 1] = x[..., 1] - dh  # top left y
    y[..., 2] = x[..., 0] + dw  # bottom right x
    y[..., 3] = x[..., 1] + dh  # bottom right y
    return y

def _get_covariance_matrix(boxes):
    """
    Generate covariance matrix from obbs using numpy.

    Args:
        boxes (np.ndarray): Array of shape (N, 5) representing rotated bounding boxes in xywhr format.

    Returns:
        tuple of np.ndarrays: Covariance matrix components (a, b, c) corresponding to the original rotated bounding boxes.
    """
    # Gaussian bounding boxes, ignore the center points (first two columns).
    gbbs = np.concatenate((np.power(boxes[:, 2:4], 2) / 12, boxes[:, 4:]), axis=-1)
    a, b, c = np.split(gbbs, 3, axis=-1)

    return (
        a * np.cos(c) ** 2 + b * np.sin(c) ** 2,
        a * np.sin(c) ** 2 + b * np.cos(c) ** 2,
        a * np.cos(c) * np.sin(c) - b * np.sin(c) * np.cos(c),
    )

def batch_probiou(obb1, obb2, eps=1e-7):
    """
    Calculate the prob IoU between oriented bounding boxes using numpy.

    Args:
        obb1 (np.ndarray): Array of shape (N, 5) representing ground truth obbs, with xywhr format.
        obb2 (np.ndarray): Array of shape (M, 5) representing predicted obbs, with xywhr format.
        eps (float, optional): A small value to avoid division by zero. Defaults to 1e-7.

    Returns:
        np.ndarray: Array of shape (N, M) representing obb similarities.
    """
    x1, y1 = obb1[..., 0:1], obb1[..., 1:2]
    x2, y2 = (x.reshape(1, -1) for x in obb2[..., :2].T)
    a1, b1, c1 = _get_covariance_matrix(obb1)
    a2, b2, c2 = (np.round(x.flatten(), 4).reshape(1, -1) for x in _get_covariance_matrix(obb2))

    t1 = (
        ((a1 + a2) * (np.power(y1 - y2, 2)) +
         (b1 + b2) * (np.power(x1 - x2, 2))) /
        ((a1 + a2) * (b1 + b2) - np.power(c1 + c2, 2) + eps)
    ) * 0.25

    t2 = (
        ((c1 + c2) * (x2 - x1) * (y1 - y2)) /
        ((a1 + a2) * (b1 + b2) - np.power(c1 + c2, 2) + eps)
    ) * 0.5

    t3 = (
        np.log(
            ((a1 + a2) * (b1 + b2) - np.power(c1 + c2, 2)) /
            (4 * np.sqrt(np.clip(a1 * b1 - np.power(c1, 2), 0, None) *
             np.clip(a2 * b2 - np.power(c2, 2), 0, None)) + eps) + eps
        ) * 0.5
    )

    bd = t1 + t2 + t3
    bd = np.clip(bd, eps, 100.0)
    hd = np.sqrt(1.0 - np.exp(-bd) + eps)
    return 1 - hd

def rotated_nms(boxes, scores, threshold=0.45):
    """
    NMS for obbs using numpy, powered by probiou and fast-nms.

    Args:
        boxes (np.ndarray): (N, 5), xywhr.
        scores (np.ndarray): (N, ).
        threshold (float): IoU threshold.

    Returns:
        np.ndarray: Indices of selected boxes.
    """
    if len(boxes) == 0:
        return np.empty((0,), dtype=np.int8)
    
    # Sort indices by scores in descending order
    sorted_idx = np.argsort(scores.ravel())[::-1]
    boxes = boxes[sorted_idx, :]

    # Compute IoU matrix and set the upper triangle to zero to prevent double comparisons
    ious = batch_probiou(boxes, boxes)
    ious = np.triu(ious, k=1)
    
    # Find indices where max IoU across each column is less than threshold
    pick = np.where(ious.max(axis=0) < threshold)[0]
    
    return sorted_idx[pick]

def nms_boxes(boxes, scores, threshold=0.45):
    """
    Non-Maximum Suppression (NMS) implementation using numpy.

    Parameters:
        boxes (np.ndarray): Array of shape (N, 4) with bounding boxes in [x1, y1, x2, y2] format.
        scores (np.ndarray): Array of shape (N,) with scores for each bounding box.
        threshold (float): IoU threshold to suppress overlapping boxes.

    Returns:
        np.ndarray: Indices of boxes to keep.
    """
    if len(boxes) == 0:
        return np.array([], dtype=int)

    if scores.ndim == 2 and scores.shape[1] == 1:
        scores = scores.flatten()

    # Sort the boxes by scores in descending order
    indices = np.argsort(scores)[::-1]
    keep = []

    while len(indices) > 0:
        # Always pick the box with the highest score
        current = indices[0]
        keep.append(current)

        # Compute IoU of the picked box with the rest
        other_boxes = boxes[indices[1:]]
        picked_box = boxes[current]

        x1 = np.maximum(picked_box[0], other_boxes[:, 0])
        y1 = np.maximum(picked_box[1], other_boxes[:, 1])
        x2 = np.minimum(picked_box[2], other_boxes[:, 2])
        y2 = np.minimum(picked_box[3], other_boxes[:, 3])

        inter_area = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
        picked_area = (picked_box[2] - picked_box[0]) * (picked_box[3] - picked_box[1])
        other_areas = (other_boxes[:, 2] - other_boxes[:, 0]) * (other_boxes[:, 3] - other_boxes[:, 1])

        union_area = picked_area + other_areas - inter_area
        iou = inter_area / union_area

        # Keep only boxes with IoU less than the threshold
        indices = indices[1:][iou < threshold]

    return np.array(keep, dtype=int)

def non_max_suppression(
    prediction, 
    nc,
    conf_thres=0.25,
    iou_thres=0.45,
    max_det=300,
    rotated=False,
    nm=0
    ):
    """Non-Maximum Suppression (NMS) on inference results to reject overlapping predictions
    Args:
        prediction: numpy.ndarray with shape (batch_size, num_proposals, 4 + nc + nm)
        nc (int): The number of classes output by the model. Any indices after this will be considered masks.
        conf_thres: confidence threshold for NMS
        iou_thres: IoU threshold for NMS
        max_det: Maximal number of predictions to keep after NMS
        rotated: Set to True if the model uses rotated bounding boxes.
        nm: Number of mask coefficients (32 for segmentation, 0 otherwise).
    Returns:
        A list[numpy.ndarray] of per image predictions with shape (total_predictions, 6 + nm)
    """

    assert 0 <= conf_thres <= 1, f"Invalid Confidence threshold {conf_thres}, valid values are between 0.0 and 1.0"
    assert 0 <= iou_thres <= 1, f"Invalid IoU threshold {iou_thres}, valid values are between 0.0 and 1.0"

    xc = prediction[..., 4] > conf_thres  # candidates
    mi = 4 + nc  # mask start index
    max_wh = 7680  # (pixels) maximum box width and height

    xc = (np.amax(prediction[:, :, 4:mi], axis=2) > conf_thres)

    output = []
    for xi, x in enumerate(prediction):  # image index, image inference
        x = x[xc[xi]]  # confidence
        # If none remain process next image
        if not x.shape[0]:
            output.append(np.array([]))
            continue

        # (center_x, center_y, width, height) to (x1, y1, x2, y2)
        boxes = x[:, :4]
        mask = x[:, mi:]
        conf = np.expand_dims(x[:, 4:mi].max(1), 1)
        j = np.expand_dims(x[:, 4:mi].argmax(1), 1).astype(np.float32)

        if not rotated:
            boxes = xywh2xyxy(boxes)
        keep = np.squeeze(conf, 1) > conf_thres
        x = np.concatenate((boxes, conf, j, mask), 1)[keep]

        # sort by confidence
        x = x[x[:, 4].argsort()[::-1]]

        # per-class NMS
        cls_shift = x[:, 5:6] * max_wh
        boxes = x[:, :4] + cls_shift
        conf = x[:, 4:5]

        if rotated:
            r_boxes = np.concatenate((
                x[:, :2] + cls_shift, 
                x[:, 2:4],
                x[:, -1:]),
                -1
                )
            keep = rotated_nms(r_boxes, conf, iou_thres) 
        else:
            keep = nms_boxes(boxes, conf, iou_thres)
        
        if keep.shape[0] > max_det:
            keep = keep[:max_det]

        out = x[keep]
        output.append(out)

    return output
# Note tích hợp Classification nhiều model trên Radxa

> Trạng thái: **chưa áp dụng lên Radxa**. Tài liệu này là contract để triển khai khi cần.

## 1. Luồng chuẩn

```text
Camera → calibration/warp/crop trên Radxa
       → Detection hoặc SEG RKNN trên toàn frame
       → một Detection cho mỗi chai: class + bbox/mask + pose
       → crop ROI theo bbox, cộng padding 5%
       → resize/center-crop theo manifest của từng classifier
       → chạy các classifier RKNN đang bật
       → gộp thuộc tính vào đúng Detection và frame_id
       → Tracking Manager → Blockly → Robot/PLC
```

Detection/SEG trả lời **đây là loại chai nào và nằm ở đâu**. Classification trả lời **chai vừa tìm thấy có thuộc tính gì**. Không chạy classifier trên toàn frame và không tạo một tracking object mới cho kết quả Classification.

## 2. Gói triển khai

Ứng dụng PC tạo một thư mục chứa:

```text
deltax_vision_bundle_<timestamp>/
├── localization_<detector>.rknn
├── localization_<detector>.json
├── classifier_condition_<model>.rknn
├── classifier_condition_<model>.json
├── classifier_cap_<model>.rknn
├── classifier_cap_<model>.json
├── vision_bundle.json
└── RADXA_CLASSIFICATION_INTEGRATION.md
```

`vision_bundle.json` là nguồn cấu hình duy nhất. Không hard-code thứ tự label trong Python vì thư mục Classification có thể làm thay đổi thứ tự class. Luôn đọc `labels` từ manifest.

## 3. Contract classifier RKNN

- Target: `rk3588`.
- Compiler: `rknn-toolkit2==2.2.0`.
- Input runtime: `NHWC`, `uint8`, RGB.
- Kích thước mặc định: `224×224`; dùng đúng `input_size` trong manifest.
- Resize: giữ tỉ lệ rồi center-crop.
- Normalization trong RKNN: mean `[0,0,0]`, std `[255,255,255]`.
- Output: một tensor `[1, số_lớp]` đã qua softmax.
- Kết quả: `argmax(output)` và confidence bằng giá trị lớn nhất.
- Nếu confidence thấp hơn `confidence_threshold`, trả `unknown`.

Không đưa output `[1,N]` vào decoder `YOLORKNN` hoặc `SegRKNNPredictor`; cần một `RKNNClassifier` riêng.

## 4. Khung runtime cần bổ sung

Pseudocode, chưa chép trực tiếp vào Radxa:

```python
class RKNNClassifier:
    def __init__(self, model_path, labels, input_size, threshold=0.60):
        self.runtime = RKNNLite()
        self.runtime.load_rknn(model_path)
        self.runtime.init_runtime()
        self.labels = labels
        self.input_size = tuple(input_size)
        self.threshold = threshold

    def predict(self, rgb_crop):
        tensor = resize_short_edge_then_center_crop(rgb_crop, self.input_size)
        output = self.runtime.inference(inputs=[tensor])[0].reshape(-1)
        index = int(output.argmax())
        confidence = float(output[index])
        value = self.labels[str(index)] if confidence >= self.threshold else "unknown"
        return {"value": value, "confidence": confidence}
```

Quản lý pipeline:

```python
detector = load_localization(manifest["localization"])
classifiers = {
    item["attribute_key"]: RKNNClassifier(...)
    for item in manifest["classifiers"]
}

for detection in detector.predict(frame):
    crop = crop_with_padding(frame, detection.bbox, ratio=0.05)
    detection.attributes = {
        key: classifier.predict(crop)
        for key, classifier in classifiers.items()
    }
```

Tất cả model phải được load **một lần khi service khởi động**. Không load/unload RKNN theo frame.

## 5. Kết quả gửi Tracking/Blockly

```json
{
  "frame_id": 12345,
  "type_id": 0,
  "class_name": "Chai_trong",
  "confidence": 0.94,
  "bbox": [315, 180, 220, 90],
  "tcp_u": 425,
  "tcp_v": 225,
  "width": 220,
  "height": 90,
  "angle": -8.4,
  "attributes": {
    "condition": {
      "value": "can_dep",
      "confidence": 0.91,
      "model": "classifier_condition.rknn"
    },
    "cap": {
      "value": "mat_nap",
      "confidence": 0.88,
      "model": "classifier_cap.rknn"
    }
  }
}
```

Giữ nguyên các trường Detection cũ để tương thích. `attributes` là trường mở rộng; Blockly cũ có thể bỏ qua.

## 6. Blockly cần bổ sung sau này

- Lấy giá trị thuộc tính theo key: `Vision attribute "condition"`.
- Lấy confidence thuộc tính.
- So sánh thuộc tính với một giá trị.
- Nhánh `unknown` hoặc confidence thấp.
- Cho phép recipe bật/tắt từng classifier để giảm thời gian xử lý.

Ví dụ:

```text
nếu condition = can_dep hoặc cap = mat_nap
    đặt vào khay NG
ngược lại
    đặt theo class chai
```

## 7. Các điểm cần sửa trên Radxa khi triển khai

1. Thêm bộ đọc `vision_bundle.json`.
2. Thêm lớp `RKNNClassifier`, tách khỏi `YOLORKNN` Detection/SEG.
3. Thêm crop có clamp biên ảnh và padding.
4. Thêm resize + center-crop RGB đúng contract.
5. Load nhiều RKNN khi service khởi động và release khi dừng.
6. Mở rộng object Detection/Tracking thêm `attributes`.
7. Mở rộng giao thức TCP v2 nhưng giữ trường cũ.
8. Bổ sung block Blockly đọc thuộc tính.
9. Ghi log thời gian riêng: detection, crop, từng classifier và tổng cycle.
10. Chỉ đưa vật vào Tracking khi frame còn mới và kết quả bắt buộc không phải `unknown`.

## 8. Tối ưu và an toàn

- Ban đầu chạy classifier tuần tự để dễ kiểm chứng.
- Chỉ chạy classifier được bật trong recipe.
- Không chạy lại classifier cho tracking object đã có thuộc tính tin cậy.
- Nếu nhiều chai, có thể batch crop theo từng classifier sau khi đo benchmark.
- Không giả định chạy song song nhiều RKNN context sẽ nhanh hơn; đo theo NPU core và nhiệt độ thực tế.
- Nếu classifier lỗi, giữ Detection nhưng đánh dấu thuộc tính `unknown`; không tự suy ra OK.
- Có thể suy ra `OK/NG` bằng rule từ `condition` và `cap` để giảm một model.

## 9. Kiểm thử bắt buộc trên Radxa

- So sánh cùng 100 crop giữa `.pt` trên PC và `.rknn` trên Radxa.
- Top-1 phải trùng phần lớn mẫu; điều tra mọi sai khác do RGB/BGR, resize hoặc label order.
- Kiểm tra crop sát bốn mép ảnh và bbox rất nhỏ.
- Đo latency với 1, 2 và 3 classifier.
- Chạy liên tục ít nhất 30 phút để kiểm tra RAM, nhiệt độ và backlog frame.
- Rút mạng/mất model/corrupt manifest phải dừng an toàn, không gửi lệnh Robot sai.


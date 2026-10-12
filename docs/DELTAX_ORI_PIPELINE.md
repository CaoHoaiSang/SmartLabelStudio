# ORI DeltaX: SmartLabel → Studio

Task `ori` là luồng chính để học khung xoay và hướng có chiều. Task `pose`
vẫn dùng hai keypoint và được giữ riêng. Nhãn OBB/ORI đã gán trong các dự án
cũ được dùng trực tiếp; không cần đổi schema dự án hay gán lại chỉ vì nâng cấp.

## Sử dụng

1. Gán khung OBB (hoặc RECT), bật **Bám trục**, đặt mũi tên từ tâm về đầu vật,
   rồi Duyệt ảnh. Hướng phải bám một trong bốn trục có chiều của khung.
2. Trong Train chọn **ori**, bấm Model gợi ý để dùng `deltax-yolo11n-ori`.
   Có thể nhập các alias YOLO11 `deltax-yolo11s-ori`, `deltax-yolo11m-ori`,
   `deltax-yolo11l-ori`, `deltax-yolo11x-ori` (cỡ lớn cần nhiều tài nguyên hơn).
   Khởi tạo mới dùng backbone/neck YOLO11 pretrained đúng cỡ; hai nhánh góc học từ nhãn
   dự án. Lần đầu cần tải weights; các lần sau dùng cache riêng SmartLabel.
   Có thể dùng checkpoint ORI cùng file `.ori.json` để train tiếp.
   `deltax-yolov8n-ori` và checkpoint YOLOv8-ORI có metadata cũ vẫn được hỗ trợ;
   mở checkpoint cũ giữ kiến trúc cũ, không âm thầm chuyển trọng số sang YOLO11.
3. Train tự export dataset ORI và dùng cùng cơ chế phân tập, job ownership,
   dừng train và giữ Test của SmartLabel. Dữ liệu không hợp lệ được báo tên
   ảnh/nhãn trước khi tạo snapshot. Chỉ những ảnh được chọn theo trạng thái
   Duyệt mới tham gia. Không tự chuyển nhãn thiếu hướng thành hướng 0°.
4. Đánh giá trên Test. Báo cáo ORI yêu cầu đồng thời khớp khung và hướng có
   chiều; có thêm chỉ số khung riêng. Không dùng chỉ số khung để kết luận
   đầu/đuôi đã đúng. Auto-Label cũng nhận checkpoint ORI, chạy model một lần
   trong process riêng cho cả batch và trả lại khung + mũi tên ở trạng thái draft.
5. Dùng **Xuất RKNN hiện có**, chọn `best.pt`, Image size **640**. Xuất ra
   `.rknn` và `.json`; giữ cả hai. Trong Studio chọn **ORI**, khai báo tên lớp
   theo đúng thứ tự `names` trong JSON. Các task DET/SEG/Classification tiếp
   tục dùng converter cũ độc lập.

Không dùng checkpoint Pose/OBB để nạp vào ORI. Checkpoint Orienty cũ chưa có
metadata quy ước góc không được âm thầm chuyển đổi; train lại bằng task `ori`
hoặc thực hiện một migration đã đối chứng. Model ORI cũ trên Studio vẫn có
thể chạy theo đường legacy nếu không có metadata mới, nhưng chưa có nghĩa
là đã nghiệm thu hướng của model đó.

## Hợp đồng dữ liệu và model

Dataset ORI có marker `deltax_ori_contract: corners_normalized_heading_v1`.
Mỗi dòng là `class x1 y1 x2 y2 x3 y3 x4 y4 heading`: bốn góc chia cho kích
thước ảnh; hướng tính trong hệ tọa độ đã chuẩn hóa. Trainer khôi phục vector
hướng về pixel trước khi scale/flip/affine. Vì vậy ảnh không vuông vẫn giữ
đúng khung và hướng độc lập. Lật ảnh cũng lật vector; ảnh background vẫn được
giữ khi mosaic. Hướng tự do lệch trục khung nên dùng Pose.

Quy ước pixel: 0° sang phải, 90° xuống dưới, −90° lên trên; hướng 180° khác
hướng 0°. Loss và kiểm tra hướng dùng sai số vòng tròn. ORI v1 tinh chỉnh về một trong bốn trục khung. ORI v2 lấy hướng từ atan2(sin,cos)
và căn trục khung theo vector (hoán đổi w/h theo trục gần nhất), giữ góc liên tục;
không ép hướng thật về góc OBB nhiễu, nhất là với vật gần vuông.

Fork Orienty 8.3.38 được lưu trong `tools/ori_runtime`, giữ giấy phép và nguồn
gốc/checksum trong `UPSTREAM.json`; thay đổi của bản tích hợp được mô tả ở đây.
YOLO11 dùng C3k2/C2PSA và đầu Orienty hai nhánh góc; đây là kiến trúc tùy chỉnh,
không phải model YOLO11-OBB tiêu chuẩn. Metadata mới ghi `architecture.family`
và `architecture.scale`, kiểm tra khớp checkpoint khi load/export. Trường
`runtime` 8.3.38 nhận diện phiên bản fork, không phải họ kiến trúc model.
Model mới học vector cos/sin bằng SmoothL1 trực tiếp, không chặn góc bằng
Hardtanh. Checkpoint cũ không bị đổi khi load/inference/export; khi train tiếp,
trainer giữ các weights tương thích và tạo đầu cos/sin mới. Metadata ghi
`heading_encoding`; không đổi activation/ý nghĩa tensor âm thầm trên file cũ.
Train ORI bật rotation180°, tắt mirror và perspective; box/vector cùng biến đổi.
Process chính tiếp tục dùng Ultralytics tiêu chuẩn. Train, đánh giá và
Auto-Label ORI dùng process riêng, cùng thư mục settings/cache riêng.

Đăng ký model sau train hoặc qua nút Chọn model phải giữ cả `.pt` và
`.ori.json` dưới tên đã đăng ký trong `workspace/models`. Metadata gắn bằng
SHA256 đầy đủ; bản v1 không có `heading_encoding` vẫn hợp lệ. Đăng ký lại
checkpoint gốc sẽ bổ sung sidecar còn thiếu cho bản đã sao chép, giữ weights.
Không đoán quy ước hướng hoặc tự tạo metadata cho model không có nguồn xác nhận.

RKNN Toolkit **2.2.0**, RK3588, RGB uint8 NHWC, letterbox 640, chia 255, không
quantize. Đầu ra đúng thứ tự Studio:

| Đầu ra | Shape | Ý nghĩa |
|---|---|---|
| Scale 8/16/32 | `[1,64+nc,80,80]`, `[1,64+nc,40,40]`, `[1,64+nc,20,20]` | DFL bbox + class logits; Studio áp sigmoid lớp |
| OBB angle | `[1,1,8400]` | sigmoid; Studio tính `(x−0.25)×π` |
| Heading v1 | `[1,1,8400]` | normalized degrees trong `[−1,1]`; giữ model cũ |
| Heading v2 | `[1,2,8400]` | raw cos/sin; Studio tính atan2 trên CPU |

Exporter kiểm tra PT↔ONNX và PT↔RKNN simulator trên ảnh nhiễu tái lập trước
khi công nhận kết quả. JSON gắn SHA256 của model, tên lớp, preprocessing,
shapes, hướng và trạng thái kiểm chứng. Layout v2 là `deltax_orienty_5_heads_v2`,
`heading_encoding: cos_sin_vector_v2`, `heading_refinement: align_obb_axes_to_heading_vector`.
Cần Studio đã nhận patch v2 trước khi dùng model mới. Kiểm tra simulator không thay cho
đo trên NPU hoặc nghiệm thu độ chính xác ở dây chuyền.

## Các sửa tại Studio

Patch có version/checksum tại `tools/studio_integration` gồm sáu file (thêm VisionTool preview):

- ORI nhận cả v1/v2, kiểm arity theo JSON và từ chối sai shape/lớp/NaN/Infinity.
- Preview ORI bỏ lệch90° của mũi tên; mặc định script/SEG/Template giữ cách vẽ cũ.
  Không đổi dấu/góc bù Tracking/Pick.
- Metadata ORI mới phải khớp model, tên lớp, RK3588/640/compiler và SHA256
  trước khi mở runtime NPU.
- Bám trục dùng chênh lệch góc có vòng tròn, sửa chọn nhầm đầu ở mốc ±180°.
- OBB JSON có thêm `deg`; giữ trường `angle` radian cho tương thích.
- AIX nhận cả `deg` và OBB legacy `angle` radian, bỏ góc không hữu hạn.

Giữ phép đổi dấu ở AIX và góc bù ở Pick; giữ Template Matching hiện có.
Template Matching vẫn có thể tinh chỉnh 180° theo thiết lập của Studio.

Áp vào source tương thích bằng:

```powershell
python tools/studio_integration/apply_patch.py --root D:/DeltaX/source/config/release/DeltaX_Radxa_Clean_Installer --backup D:/DeltaX/AI/Studio/ORI_IMPLEMENTATION_20261011/studio-backup
```

Script kiểm tra toàn bộ checksum trước khi sửa, giữ backup, áp lại không sửa
lần hai. Nếu source Radxa đã đổi thì phải rebase patch lên source thực tế,
không ghi đè mù. Việc áp source trên Windows không restart dịch vụ hoặc đổi
AI setting/model trên Radxa.

## Kiểm chứng tái lập

`python -m unittest discover -s tests -v` gồm kiểm tra nhãn ORI, hình học ảnh
không vuông, đầu/đuôi, augmentation, loss/metric qua ±180°, không ghép hướng
với vật ở vị trí khác, tensor contract và đường AIX. Các test không sửa dự án
vận hành. Source Studio được test trực tiếp từ payload patch.

`python tools/verify_ori_pipeline.py --output <thư_mục_mới> --rknn` tạo dữ liệu
giả lập riêng, export bằng DatasetManager, train một epoch, load checkpoint,
Auto-Label hai lần qua cùng process, đánh giá Test và chuyển RKNN/simulator.
Fixture có ảnh background và tên lớp chứa dấu `:` để kiểm tra hợp đồng đầy đủ.
Mặc định dùng YOLO11n-ORI; `--model deltax-yolov8n-ori` kiểm tra luồng legacy.
`--pretrained` bật kiểm tra nạp trọng số pretrained đúng cỡ. Smoke test tắt pretrained backbone để không tải weights không liên quan đến
việc kiểm tra pipeline; model giả lập không phải model triển khai.

CI có job riêng chạy pipeline YOLO11-ORI/RKNN trên Linux và train/Auto-Label/
đánh giá YOLOv8-ORI legacy. Các cỡ n/s/m/l/x được kiểm tra khởi tạo và raw heads;
chỉ YOLO11n được nghiệm thu train/export/simulator/NPU, chưa đo NPU cỡ lớn. Windows cần Docker
Linux Engine hoạt động; lỗi WSL `0x800705aa` là trở ngại môi trường trước bước
converter, không được báo thành export thành công.

YOLO11n đã smoke test trên NPU Radxa/core2 và qua uploader/decoder hiện có
ngày12/10/2026. Đây là model train một epoch trên ảnh tổng hợp: góc OBB/hướng
PT↔NPU lệch tối đa0.09°/0.38° trên ảnh nhiễu, nhưng một số logits bbox vượt
ngưỡng dùng cho simulator. Không gắn `hardware_validated=true` cho mọi export
hoặc suy ra độ chính xác; NPU dùng tính toán giảm độ chính xác số.

Nghiệm thu phần cứng còn cần model train trên ảnh vật thật, chạy Radxa để
so PT/NPU, kiểm tra 0/90/180/−90 và góc chéo, ảnh không vuông, đầu/đuôi,
Template Matching bật/tắt, góc sau Tracking/Pick và thử gắp trong điều kiện
vận hành. Chưa được suy ra độ chính xác từ dataset QA hay smoke test.

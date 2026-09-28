# Chế độ vận hành tách khỏi kiểm định — 24/09/2026

Theo yêu cầu chủ hệ thống: chưa có bộ TEST độc lập **không còn bắt buộc
chặn xuất model vận hành**, nhưng tuyệt đối không đổi nó thành bằng chứng
đã kiểm định. Đây là thay đổi chính sách pilot, không chứng minh model tốt hơn.

## Cách xuất ngay

1. Chọn đúng checkpoint các classifier trong project Hydro, xem low/high.
2. **Tạo gói Model Hydro → Chế độ sử dụng: Vận hành thật**.
3. **Hồ sơ kiểm định: Chưa kiểm định độc lập**; tích xác nhận cho gói này.
4. Chọn runtime Windows hoặc Nano đúng máy đích và xuất ZIP.
5. Hydro mới: nhập ZIP, xem hồ sơ, xác nhận kích hoạt. Nhập không tự kích hoạt.
   Email vẫn cần cấu hình/bật riêng; không tự gửi thư khi xuất hoặc nhập gói.

Mỗi lần mở form, xác nhận mặc định tắt; đổi chính sách/chế độ cũng xóa xác
nhận. Không có công tắc chung bỏ mọi kiểm tra. Shadow không cần xác nhận này
và không được nâng thành Operational ngầm. Mặc định project mới vẫn Shadow.

| Chế độ | Hồ sơ | Điều kiện riêng | Kết quả |
|---|---|---|---|
| Chạy thử | Chưa kiểm định | Các guard kỹ thuật/QA | Đối chiếu, không cảnh báo tự động |
| Vận hành thật | Chưa kiểm định | Gói V3 + xác nhận cho gói | Có thể cảnh báo; công bố chưa kiểm định |
| Vận hành thật | Đã kiểm định đúng checkpoint | Bằng chứng TEST được duyệt còn khớp | Có thể cảnh báo, giữ bằng chứng |

QA dataset có vụ độc lập không tự biến thành kết quả đánh giá model. Khi
chạy QA, trạng thái phân tập được lưu riêng `hydroDatasetQaStatus`; xuất gói
không tin cờ `validationStatus` cũ trong project để tuyên bố đã kiểm định.
Các cờ readiness trong báo cáo dataset là thông tin về dữ liệu, không phải
quyền phát hành; chọn chính sách tại cửa sổ xuất gói mới quyết định luồng.

## Chọn TEST ở Đánh giá model

Trong thẻ **ĐÁNH GIÁ MODEL · VALIDATION / TEST**, trường **Tập** có:

- `val`: dùng classifier đang chọn trên VAL của snapshot checkpoint; có thể gợi ý ngưỡng.
- `test`: TEST trong snapshot dataset đã train, không dùng chọn ngưỡng.
- **TEST độc lập (chọn bộ…)**: nút Đánh giá mở luồng bộ TEST hiện có,
  chọn bộ theo vụ/lô, xem checkpoint + ngưỡng của **tất cả classifier**,
  xác nhận lịch sử độc lập, đánh giá và duyệt kết quả. Không khởi chạy âm thầm.

Dataset vẫn là nơi quản lý/thu thập ảnh TEST; không tạo hệ đánh giá thứ hai.
Các dự án định vị giữ nguyên dropdown và luồng đánh giá cũ.

### Vụ mới chụp bằng Hydro sau này

1. Dành trọn vụ mới cho đánh giá; chưa đưa ảnh vụ đó vào TRAIN/VAL, kể cả
   checkpoint cha. Chụp bằng Hydro giữ đúng nguồn vụ/giàn/rọ và điều kiện camera.
2. Nhập, gán nhãn và duyệt. Chọn cả vụ trong **Tạo bộ TEST từ vụ đã chọn**.
   Tạo benchmark là sao chép, **không tự sửa phân tập ảnh nguồn**. Cách an toàn
   khi thu bộ ngoài là xử lý ảnh vụ TEST trong project nguồn riêng rồi nhập
   benchmark vào project đang chứa model; không cần làm lại project/nhãn cũ.
3. Nhập bộ có `benchmark.json` bằng **Nhập bộ TEST ngoài**. Bản nhập được lưu
   cách ly ngoài project.images và TRAIN/VAL; không nhập ảnh rời từ kho benchmark.
4. Chốt checkpoint và low/high trước; đánh giá bộ độc lập. Sau khi xem số
   mẫu Có/Không, bỏ sót, báo nhầm, độ phủ và chưa chắc chắn, mới duyệt bằng chứng.
5. Xuất **Đã kiểm định đúng checkpoint**. Nếu đổi checkpoint/ngưỡng/schema,
   bằng chứng cũ không còn áp dụng; không tự hạ xuống chưa kiểm định.

Final Train+Val giữ TEST; Final100 đã học TEST nội bộ cũ. **Cả hai có thể xuất
gói chưa kiểm định sau xác nhận**. Muốn công bố kiểm định cho Final100 phải
dùng bộ ngoài chưa học/chọn model. Không chuyển ảnh đã học sang TEST để tạo
độc lập giả. Nhiều ảnh một cây không phải nhiều cây độc lập. Bộ thiếu mẫu Có
hoặc Không của một classifier chưa đủ bằng chứng cho toàn bộ gói; không tự
đổi mẫu thiếu thành nhãn Không. Không cần làm cây héo/vàng để vượt điều kiện.

## Contract và tương thích

- `deploymentMode` giữ `shadow | operational`; không thêm một đường inference khác.
- `validationStatus=operational_unvalidated` chỉ dùng với Operational V3,
  không phải `validated_holdout` hoặc `pipeline_smoke_only`.
- `operationalAcceptance: HydroOperationalAcceptanceV1`: xác nhận, UTC, hash
  checkpoint từng model, SHA256 canonical của toàn manifest trừ chính trường
  acceptance. Hash ràng buộc ONNX, thứ tự output, schema, ngưỡng, runtime,
  profile, crop và các metadata khác. Đây **không phải chữ ký nhà phát hành**.
- Gói chưa kiểm định không kèm `evaluationEvidence`; gói đã kiểm định tiếp tục
  dùng `HydroReleaseEvidenceV1`, đối chiếu hai lần khi xuất như trước.
- Runtime Hydro cũ từ chối trạng thái mới. Cập nhật **Camera + Backend + Web**
  đồng bộ trước khi dùng, không sửa JSON để giả `validated_holdout`.
- Model PT, schema output, checksum, crop/profile, low/high, QA lỗi, cặp nhãn
  Có/Không đã duyệt, smoke runtime và rollback vẫn được kiểm. Không đổi pump,
  EC, calibration, safety, Fleet hoặc dữ liệu train hiện có.

Nguồn phương pháp, đối chiếu 24/09/2026:
[tránh dùng TEST để chọn model/ngưỡng](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage),
[đánh giá dữ liệu lặp theo nhóm](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data).
Quyền cho model vận hành là lựa chọn sản phẩm của chủ hệ thống, không phải
điều kiện kỹ thuật do các tài liệu này áp đặt.

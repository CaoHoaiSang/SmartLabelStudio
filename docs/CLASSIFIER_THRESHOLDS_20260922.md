# Checkpoint, ngưỡng và nhận định classifier — 22/09/2026

## Cách đọc

Checkpoint là bộ trọng số PT của một lần train. Mỗi thuộc tính (hiện diện,
Lá vàng, Héo) có checkpoint riêng; SHA-256 phân biệt tệp, không dựa tên best.pt.
Ngưỡng không train lại model: p là điểm lớp Có, p ≤ low thành Không,
p ≥ high thành Có, vùng giữa là Chưa chắc chắn. Condition cần hiện diện cây.
Điểm này không phải tỷ lệ đúng đã kiểm định.

0.30/0.70 là khởi đầu chưa hiệu chỉnh; 0.40/0.60 không mặc nhiên tốt hơn.
Ngưỡng đã lưu chỉ được tái sử dụng khi checkpoint hash còn khớp. Nếu đổi model,
UI nay nói rõ không dùng ngưỡng cũ thay vì chỉ ghi Khởi đầu. Báo cáo VAL dùng
gợi ý phải khớp checkpoint và identity thuộc tính. Dữ liệu cũ không có hash vẫn
ghi rõ cần kiểm tra lại, không biến thành bằng chứng phát hành.

Quy tắc gợi ý hiện tại: VAL có >=20 ảnh mỗi phía; tìm tâm 0.10..0.90 theo
balanced accuracy, yêu cầu tốt nhất >=0.65, biên low/high ±0.10. Không tối ưu
ngưỡng bằng TEST. Đây là heuristic ban đầu, không chuẩn đảm bảo chất lượng.
Đối chiếu FP/FN và số ảnh chưa chắc theo mục đích trên VAL chưa dùng train;
chốt checkpoint/ngưỡng trước đánh giá TEST ngoài. Không sửa split/export cũ
để tạo vẻ độc lập cho checkpoint đã học các ảnh đó.

## Bằng chứng đọc từ workspace (không sửa dataset/model)

Project `project_eb99e9722cff` — Phân Loại Cải Ngọt:

| Thuộc tính | SHA checkpoint đầu | TEST Có / Không | FP / FN | F1 | VAL Có / Không |
|---|---|---|---|---|---|
| Cây hiện diện | 471e6a2b97a6 | 160 / 13 | 0 / 0 | 1.000 | 310 / 18 |
| Lá vàng | e30fff01d9bb | 6 / 154 | 0 / 2 | 0.800 | 22 / 288 |
| Héo | a8004058f164 | 23 / 133 | 4 / 6 | 0.773 | 65 / 239 |

Các hash thực khớp báo cáo lưu. Không suy ra các TEST độc lập cả vụ/tổ tiên
chỉ từ flag independent_test. Export gốc strategy=locked, validation_enabled=true.
Chưa có báo cáo VAL cho các checkpoint này trong metadata project. Riêng hiện
diện không đủ 20 ảnh Không trên VAL hiện hữu, dù TEST đúng hết 173 ảnh.

Các low/high 0.40/0.60 lưu trong project gắn với các hash PT cũ
02f7eb21… / 45d42d72… / 9a269f9e… nên không áp cho ba checkpoint hiện chọn.
Hydro đang dùng gói shadow `hydro_cai_ngot_20260916T075353Z` với 0.40/0.60;
đó là gói đã nhập khác, không tự cập nhật theo checkpoint SmartLabel.

## Trình bày mới

Log đánh giá thêm nhận định định lượng, số mẫu từng phía, giới hạn độc lập,
phân biệt ngưỡng so sánh 0.50 với low/high vận hành, và lý do không gợi ý riêng
cho TEST / VAL ít mẫu / VAL chưa phân biệt tốt. Thêm trợ giúp Low/High/checkpoint
ở cửa sổ tạo gói. Không xếp hạng “vận hành đạt” dựa riêng F1/Accuracy, không đổi
quality gate, ngưỡng thật, model đã chọn, split/nhãn hoặc quyền phát hành.

Kiểm thử: 325/325 full unittest; model tools 16, UI review 19 targeted đạt.
Các UI tests dùng project/ảnh tạm, không đánh giá/train model thật. Lưu công việc
và mở lại SmartLabel để nạp code; báo cáo cũ trên ổ đĩa không bị ghi lại.

Nguồn phương pháp đọc22/09/2026: [scikit-learn — chọn ngưỡng](https://scikit-learn.org/stable/modules/classification_threshold.html),
[rò dữ liệu](https://scikit-learn.org/stable/common_pitfalls.html).
Không nâng framework hay thêm dependency; không có dịch vụ có phí.

# Trạng thái tích hợp HydroFlow ngày 10 tháng 9 năm 2026

Baseline chức năng SmartLabel `0533740`, Hydro `2f3d2171`. Đợt đồng bộ tài liệu
không sửa workspace, nhãn, model hay chương trình. Các số test là bằng chứng theo đợt,
không phải kiểm tra thời gian thực máy người dùng.

## Đã có

- Hydro xuất qua preview chọn một vụ/ngày/từng capture, tổng số slot và thumbnail.
  Ảnh đã đóng gói cần chủ động chọn lại; không phải tất cả ảnh đều chưa từng nhập.
- SmartLabel import V1/V2, nhận topology nhiều ống/rọ; checksum/lineage phải hợp lệ.
- Slot thiếu do xóa khỏi project được bổ sung sau xác nhận, giữ nhãn/ID/review cũ.
  Lỗi giữa nhiều capture giữ phần đã hoàn tất, retry bỏ qua phần trùng; không tự ghi
  đè file còn record nhưng mất/hỏng bên ngoài.
- Classifier toàn ảnh Hydro không cần class định vị; luồng classification crop và
  detection cũ vẫn còn. Xóa project có thể khôi phục, không tự xóa dataset nguồn.
- Bundle V3: một presence + 1–15 condition nhị phân; tên Việt/ý nghĩa/output order/
  threshold theo schema. Giữ V1/V2, không tự migrate nhãn cũ.

## Chưa hoàn tất

1. Nghiệm thu xuất ZIP ảnh thật qua UI Hydro → project kiểm thử riêng, số lượng/
   ngày/vụ/rọ và hành vi nhập lại. Code/unit/pipeline tổng hợp đã được kiểm thử.
2. Báo cáo QA/review/dataset version từ SmartLabel về readiness Hydro chưa triển khai.
   Duyệt chất lượng ảnh ở Hydro không đồng nghĩa đã gán/duyệt nhãn SmartLabel.
3. Nhãn bệnh thật, train/đánh giá và holdout vụ độc lập. Một vụ chỉ pilot shadow
   khi đủ QA; hai vụ không tự bảo đảm model đạt. Không bịa negative hoặc dùng
   uncertain/not_applicable như nhãn Không.
4. Jetson/ArUco/Drive còn hoãn; Windows vẫn giữ giới hạn shadow hiện có.

## Vai trò báo cáo nhãn và dataset đề xuất

Hữu ích để Hydro biết tiến độ sau xuất ZIP, nhưng không bắt buộc cho luồng train/
chạy model thử hiện có. MVP nên xuất/nhập một báo cáo JSON nhỏ theo đúng gói ảnh,
dataset/schema version và asset checksum: số đã nhập/duyệt, phân bố nhãn, lỗi QA,
chia nhóm/vụ và ngày báo cáo. Không cần sync ảnh/nhãn qua mạng hoặc Cloud.

SmartLabel vẫn là nguồn quản lý nhãn; Hydro chỉ đối chiếu và hiển thị. Báo cáo
không chứng minh nhãn đúng, không thay kiểm thử holdout, không tự kích hoạt model,
không tự đổi duyệt ảnh Hydro hoặc tác động bơm. Chưa triển khai trong đợt tài liệu.

## Bảo toàn và kiểm thử

Local SmartLabel 102/103 pass, 1 SAM skip; target 101/103 pass, 2 layout skip qua SSH
trong đợt nhập lại. 69/69 JSON metadata/config đối chiếu giữ nguyên. Pipeline V3
tổng hợp 6 capture → 60 slot → train 4 classifier → ONNX → Hydro đạt, không chứng
minh độ chính xác trên bệnh cây. Backup Protected của Hydro đã gồm workspace/model
được quản lý, có restore thử cô lập và replica một lần sang máy hiện tại.

Không bắt người dùng tạo lại project cũ, không rewrite Git history hoặc đưa ảnh/model/
credential lên GitHub. Chỉ push từ máy đích; xác minh target và công việc chưa lưu
trước cập nhật ứng dụng, không tự đóng SmartLabel.

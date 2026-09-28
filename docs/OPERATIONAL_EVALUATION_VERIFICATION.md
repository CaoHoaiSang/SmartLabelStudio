# Kiểm chứng thay chính sách phát hành — 24/09/2026

## Phạm vi

Nhánh `feat/hydro-operational-evaluation-policy`. Xem
[thiết kế/cách dùng](OPERATIONAL_EVALUATION_POLICY.md). Giữ 5 file dirty
workspace có trước; chỉ stage source/test/docs của tác vụ. Không tự xuất model
khách, train, đổi nhãn/phân tập, khởi động lại SmartLabel hoặc dịch vụ Hydro.

## Đã chạy

- Toàn bộ `python -m unittest discover -s tests -v`: **385/385 đạt**,382.770s.
- Nhóm export **19/19 đạt**: xác nhận strict boolean, QA, smoke, checkpoint
  đổi khi xuất, shadow không giả kiểm định, verified không tự hạ chính sách,
  snapshot model/project/split giữ nguyên và rollback staging.
- Nhóm Hydro UI **22/22 đạt**,63.253s: chọn TEST độc lập dùng luồng cũ,
  không ghi project/train, không mở tác vụ khi chưa nhấn đánh giá, project
  generic trả về dropdown native, runtime tách mode, xác nhận không tự tick.
- compile/diff check đạt. Tất cả source đã test trùng index, không phụ thuộc
  5 file workspace dirty. Tests tự tạo project tạm.
- Liên thông hai repo: `AI_KL/tools/verify_operational_pilot_roundtrip.py`:
  ZIP thật do writer tạo, nhập Camera thật, ORT smoke/inference thật trên
  **ONNX constant và ảnh tổng hợp**, V3 registered ingest vào FakeDatabase,
  20 cảnh báo (10rọ×2dấu hiệu giả lập), metadata ảnh Email ghi chưa kiểm định,
  replay không nhân cảnh báo, 0 pump/dosing/command writes; sửa ngưỡng bị chặn.

Lần toàn bộ đầu có2 lỗi hồi quy: test form chưa xác nhận mới và đổi renderer
dropdown generic ngoài ý muốn. Đã sửa, chạy lại22 và toàn bộ385 đạt. Không
nới assertion bảo vệ native menu. Có log Tcl after/ThemeChanged lúc hủy các
root test; không coi log này là nghiệm thu thẩm mỹ cửa sổ SmartLabel thật.

## Chưa làm/giới hạn

Chưa gửi SMTP thật, nạp checkpoint người dùng, nghiệm thu thực địa hoặc Nano.
Không điều khiển UI SmartLabel đang mở; native desktop automation không sẵn
có. Cần cập nhật cả Camera/Backend/Web trước nhập gói mới, nếu chưa cập nhật
thì guard cũ từ chối là đúng. Không hứa độ chính xác từ kết quả test phần mềm.

Độc lập kiểm định giữ nguyên các test external_benchmark/heldout_collection:
trùng byte/pixel/vụ, thiếu lớp, giả báo cáo, đổi ngưỡng/checkpoint/data, hủy job,
switch project, nhãn/ảnh cũ và Final100 vẫn được bảo vệ. TEST không bị xóa.

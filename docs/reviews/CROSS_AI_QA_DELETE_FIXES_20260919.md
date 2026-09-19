# Sửa QA topology và khóa xóa bổ trợ — 19/09/2026

Theo yêu cầu triển khai tất cả phát hiện của đợt CROSS-AI-MULTILAYER-REVIEW.
Nhánh `fix/review-qa-and-supplement-safety`, kế thừa `91f38f4`.

## Hành vi

- Rọ thiếu trong capture còn hợp lệ: giữ warning `capture_slots_excluded`.
- Rọ ngoài tập topology hoặc trống/null: error `unexpected_capture_slots`,
  gắn imageId đúng ảnh sai và danh sách `unexpected`. Không hạ nhầm thành
  ảnh bị loại; readiness model bị chặn. Thêm ảnh có mã lạ vào capture vốn đủ
  rọ cũng bị chặn. Duplicate và topology invalid giữ gate hiện có.
- QA chỉ đọc, không đổi nhãn, split, metadata hay phục hồi ảnh đã xóa.
- `_project_job_busy()` dùng lại đúng các cờ sở hữu job trước đây của
  `_can_change_project()`, không dựa vào subprocess còn sống hay không.
- Xóa bổ trợ kiểm active source/project, job và revision trước/sau modal.
  ID không có không fallback sang ảnh đang chọn. Nút × theo cùng gate qua
  vòng sự kiện UI hiện có; không thêm worker hoặc polling riêng.
- Sidecar lock, CAS, kiểm đường dẫn, shared-file và rollback lỗi ghi giữ
  nguyên. Không mở rộng thao tác xóa sang ảnh Giàn/snapshot/model.

## Kiểm chứng

Test V1/V2: thay mã bằng ID lạ/empty/null, thêm ID lạ khi đủ rọ, duplicate,
thiếu rọ được phép, readiness bị chặn và QA không đổi project.
Test Tk: cả 9 cờ job, completion chưa xử lý, đổi job/project/revision/source
trong modal, ID không tồn tại và xóa idle có xác nhận. Toàn bộ dùng workspace
tạm; không xóa/train/ghi nhãn dự án thật. Lượt cuối toàn bộ SmartLabel đạt
266/266 (216,962 giây); hai regression độc lập từ đợt review và năm ca
an toàn xóa cũng đạt. Log đầu có một lỗi alias trong fixture V2 mới, đã
sửa bản sao metadata của test rồi chạy lại toàn bộ; không sửa sản phẩm
để né assertion. Log Tk vẫn có cảnh báo callback khi hủy cửa sổ test như
trước; không tuyên bố đã nghiệm thu mọi vấn đề vòng đời UI thực tế.

Đã đưa vào source Windows. Phiên SmartLabel đang mở phải đóng/mở lại khi hết
job và đã lưu công việc để nạp Python mới; không cưỡng bức đóng phiên người dùng.
Không sửa workspace/model/dataset hoặc quy tắc TRAIN/VAL/TEST. Đây là sửa phần
mềm, không chứng minh độ chính xác model hoặc nghiệm thu Nano.

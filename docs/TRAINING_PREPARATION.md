# Chuẩn bị train không chặn giao diện

Cập nhật 26/09/2026 · nhánh `fix/training-preparation-responsive`.

## Sử dụng

1. Bấm **Bắt đầu Train** như trước. Ứng dụng ghi nhận yêu cầu ngay và chuyển
   nút sang **Đang chuẩn bị dataset…**. Chưa có epoch trong giai đoạn này.
2. Nhật ký hiển thị kiểm nguồn/phân tập, kiểm model, đối chiếu nội dung ảnh
   gốc, rồi xuất ảnh cho từng classifier hoặc bài định vị. Có số ảnh đã xử lý.
3. **Dừng train** dùng được cả trước epoch đầu. Dừng có phối hợp: chờ thao tác
   đọc/nạp model hoặc ảnh hiện tại trả về, không giết luồng đang ghi tệp.
4. Chỉ sau khi mọi dataset được kiểm tra thành công mới mở TrainingJob.
   Lỗi phân tập vẫn có nút mở đúng nhóm cần sửa; không bỏ các guard dữ liệu.
5. Muốn đổi/nhập/xóa dự án hoặc sửa phân tập, chờ thông báo kết thúc (kể cả
   sau khi nhấn Dừng). Đóng cửa sổ lúc đang chuẩn bị sẽ yêu cầu dừng trước,
   không âm thầm giết tác vụ ghi dữ liệu.

Ảnh/nhãn và thông số được chụp thành snapshot trong bộ nhớ khi bấm Train.
Chỉnh nhãn sau thời điểm đó dùng cho lần tiếp theo, không thay snapshot đang
xuất. Đổi schema/loại bài trong khi chuẩn bị bị chặn tại bước chuyển giao.

## Ranh giới kỹ thuật

- Tk chỉ đọc lựa chọn, xác nhận và cập nhật giao diện. `TrainingPreparationJob`
  nhận bản sao project/request; worker chỉ gửi sự kiện vào queue.
- Giữ `training_preparation_running` tới khi UI xử lý completion, không chỉ
  tới lúc thread chết. Sự kiện gắn đúng job và source project; completion cũ
  không được giải phóng khóa của lượt mới. Hủy sát thời điểm chuyển giao vẫn
  không được mở TrainingJob.
- `PreparationProgress` giới hạn cập nhật theo ảnh ở 4 lần/giây, giữ thông báo
  chuyển giai đoạn/kết thúc và kiểm hủy ở từng ảnh. Không bỏ kiểm hash, pixel,
  nguồn, ảnh gốc/biến thể, độ phủ lớp TRAIN hoặc ranh giới Fleet/TEST ngoài.
- Kiểm lại revision phân tập/manifest ảnh bổ trợ sau từng dataset trong batch.
  Không tự phân lại 70/15/15. `ensure_split_assignment` chỉ giữ hành vi hiện có
  là gán nhóm mới theo chính sách của dự án.
- Export lỗi/hủy dọn chỉ các thư mục con mới mà job đã tạo độc quyền dưới
  `exports` của đúng project; kiểm đường dẫn trước khi xóa. Không xóa snapshot
  cũ, ảnh/nhãn gốc, checkpoint hoặc kết quả train đã có. Nếu dọn lỗi, ghi cảnh
  báo và giữ tệp. Hủy sau khi worker hoàn thành có thể để lại snapshot đầy đủ,
  nhưng không khởi động train hoặc đăng ký model từ snapshot đó.
- TrainingJob nhớ yêu cầu dừng cả khi đang dò CPU/CUDA và xử lý khoảng đua
  trong lúc tạo subprocess. Không thay đổi cách chọn weights, epoch hoặc resume.

## Kiểm chứng và giới hạn

Regression gồm export ảnh thật trong project tạm, snapshot nhãn/thông số,
giữ phân tập, dọn lỗi/hủy, sai model, thiếu lớp, revision thay đổi, UI heartbeat,
khóa đổi dự án, bấm trùng, lỗi tạo thread, hủy trước chuyển giao và đóng app.
Các kiểm tra này không train model thật và không sửa project người dùng.

Smoke Tk riêng ngày 26/09 với model nền `yolo11n-cls.pt` thật: 7,312 giây,
582 nhịp giao diện, khoảng cách lớn nhất 125 ms. Dataset rỗng tạm bị từ chối
đúng sau kiểm model, không có epoch và export tạm được dọn. Không dùng số đo
cửa sổ fixture này thay cho nghiệm thu lượt train thật của người sử dụng.

Đây là sửa chặn event loop trong **bước chuẩn bị**. Không cam kết loại bỏ mọi
tình trạng thiếu RAM/CPU/GPU khi epoch đã chạy; cần profile riêng nếu còn gặp.
Chưa cache pixel giữa các classifier: chấp nhận đọc lại để giữ kiểm toàn vẹn.
Không tăng số worker, nâng thư viện hoặc thay chính sách xuất Operational.
SmartLabel đang mở phải lưu việc và mở lại để nạp mã mới.

Tham chiếu chính thức đối chiếu ngày 26/09/2026:
[Tkinter threading model](https://docs.python.org/3/library/tkinter.html#threading-model),
[Ultralytics Train](https://docs.ultralytics.com/modes/train/).

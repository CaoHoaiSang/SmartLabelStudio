# 22/09/2026 — giải thích điều kiện gói Hydro vận hành thật

Hai vụ có ảnh chưa đồng nghĩa TEST độc lập. Nhóm mới nhập mặc định vào
TRAIN để giữ benchmark đã khóa. QA hiện yêu cầu các vụ ở TEST không có
ảnh ở TRAIN/VAL; không tự chia lại hoặc chuyển cả vụ khi bấm tạo gói.

QA bổ sung `holdout` (số ảnh TRAIN/VAL/TEST/chưa chia theo vụ, danh sách vụ
development/test/giao nhau). Cùng formatter giải thích được dùng tại
Kiểm tra Dataset Hydro và lỗi worker Tạo gói Hydro. Bản ghi thiếu mã vụ,
null hoặc chuỗi trống không thể làm TEST độc lập. Không tự đổi chế độ sang
Shadow, không ghi project/split trong export, không chạy ONNX trước khi QA đạt.

Đối chiếu project Cải Ngọt trên máy 22/09: 1.861 ảnh; vụ đầu
TRAIN 1.241 / VAL 352 / TEST 188; vụ hai TRAIN 80 / VAL 0 / TEST 0.
QA không có lỗi dữ liệu nhưng chưa có holdout vụ độc lập. Có155 ảnh chưa
duyệt và19 capture đã loại bớt rọ (cảnh báo, không phải nguyên nhân trực tiếp).
Các snapshot train ngày21/09 của ba classifier đều có80 ảnh vụ hai ở TRAIN.

Không chỉ chuyển dữ liệu đã học sang TEST rồi dùng checkpoint cũ. Cần đối
chiếu nguồn checkpoint, dành trọn vụ độc lập và train lại không dùng vụ đó,
hoặc dùng vụ độc lập khác chưa dùng để train/hiệu chỉnh. Sau đó đo model
trên TEST có nhãn phù hợp. Không tự gán nhãn, thêm ảnh Có/Không giả hay dùng
ảnh bổ trợ làm TEST. Đổi phân tập/train là bước riêng do kỹ thuật viên chốt.

`validated_holdout` vẫn là QA dữ liệu/phân tập, chưa phải bằng chứng chất
lượng model gắn hash checkpoint/dataset/ngưỡng. Bản sửa không hoàn thiện
evaluation gate/phát hành; không được quảng bá giá trị này là độ chính xác.

Kiểm Windows:305/305 unittest, gồm5 test thống kê holdout, pipeline fail
trước ONNX, bảo toàn split/checkpoint và21 test export/Tk job. Chỉ fixture;
không train/đóng gói/kích hoạt model người dùng. Cần lưu công việc và mở lại
SmartLabel để phiên đang mở nạp source mới; không cưỡng bức đóng ứng dụng.

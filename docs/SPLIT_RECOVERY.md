# Phân tập và ảnh bổ trợ — 26/09/2026

## Vì sao ảnh mới vào TRAIN?

Đây là phân tập khóa theo nhóm: ảnh thêm vào một nhóm đã có giữ tập của nhóm;
nhóm mới mặc định TRAIN. Không tự đưa ảnh mới vào VAL/TEST vì điều đó đổi bộ
đánh giá giữa các lần train. 70/15/15 là mục tiêu số ảnh, không phải tỷ lệ
cứng cho từng nhãn, từng vụ hoặc từng cây.

Ảnh biến thể tổng hợp chỉ dùng TRAIN. Nếu ảnh gốc thuộc VAL/TEST, biến thể
đang bật TRAIN sẽ gây rò dữ liệu. Export phải chặn kể cả Final Train 100%;
không bỏ kiểm tra này để sửa lỗi phân tập.

## Luồng xử lý mới

1. Dataset hiển thị cảnh báo số nhóm xung đột. Khi bấm Train, kiểm tra ràng
   buộc trước khi nạp model, giải mã hàng nghìn ảnh hoặc tạo snapshot xuất;
   thông báo một lần, có lựa chọn mở đúng nhóm cần xử lý.
2. **Xem / chuyển nhóm → Chỉ nhóm xung đột** chỉ ra vụ/nhóm, số biến thể,
   số ảnh đã duyệt và Có/Không. Có nút đưa đúng nhóm nguồn về TRAIN, giữ nguyên
   ảnh, nhãn, biến thể và các nhóm khác; phải xác nhận trước khi ghi.
3. Hộp xác nhận chuyển nhóm hiển thị Có/Không dự kiến ở từng tập. Sửa xung
   đột không đồng nghĩa đủ dữ liệu đánh giá: chuyển một nhóm có thể làm VAL
   hết ảnh Có. Nếu muốn giữ nhóm ở VAL/TEST, tắt dùng train các biến thể liên
   quan trong GÁN NHÃN → Bổ trợ. Không tự tắt thay người dùng.
4. **Phân lại 70/15/15** xem trước số ảnh, số nhóm đổi tập, số nhóm phải giữ
   ở TRAIN và độ phủ nhãn. Nhóm nguồn của biến thể đang bật được giữ TRAIN
   ngay trong bộ phân; phần còn lại phân theo dung lượng ảnh. Không tách cây
   hoặc ép đúng tỷ lệ bằng cách để ảnh gốc/biến thể ở hai tập.
5. Chuyển thủ công nhóm nguồn sang VAL/TEST bị chặn trước khi ghi. Nếu dữ
   liệu/nhãn/sidecar đã thay đổi sau khi mở hộp xác nhận, yêu cầu tải lại.
   Khóa/phân lại bị chặn khi ứng dụng có công việc giữ quyền dự án.

## Độ bền và giới hạn

- Ghi phân tập bằng tệp tạm, fsync và thay thế nguyên tử. Khi thành viên các
  tập thay đổi, giữ bản gần nhất ở `split_assignment.previous.json`. Đây là
  bản dự phòng phục hồi có kiểm tra, không tự hoàn tác hoặc áp dụng lại ảnh
  cũ. Sau mỗi thay đổi tiếp theo, bản dự phòng được thay bằng trạng thái trước
  thay đổi đó. Không coi đây là lịch sử vô hạn.
- Đọc thống kê/xem trước không ghi phân tập; gọi persist nhưng nội dung không
  đổi cũng không cập nhật timestamp. Tệp phân tập hỏng không bị tự cân bằng
  lại rồi ghi đè. Kiểm tra revision bảo vệ khoảng chờ xác nhận trong UI;
  không phải khóa phân tán cho hai tiến trình cùng ghi một project.
- Snapshot classifier mới có `class_counts_by_split`, chỉ tính ảnh thực sự
  xuất và không tính VAL mirror của Final. Bắt đầu train kiểm tra riêng TRAIN
  đủ hai lớp; locked cần VAL có ảnh xuất được, không tự dùng TEST thay thế.
  VAL/TEST thiếu một lớp có cảnh báo độ phủ, không tự tạo nhãn. Snapshot cũ
  chưa có trường mới vẫn đi đường kiểm tra tương thích cũ.
- Bộ phân chưa tối ưu đa nhãn/hiếm lớp; dùng số Có/Không xem trước và số nhãn
  của từng nhóm để chọn có chủ đích. Không dựa vào xác suất AI làm nhãn thật.
- Phân lại không xóa kiến thức của checkpoint cũ. TEST mới gồm ảnh model
  từng học không độc lập với model đó. Train mới từ model khởi tạo phù hợp;
  TEST độc lập theo vụ/benchmark vẫn dùng luồng riêng hiện có.
- Chưa tự hợp nhất mã nhóm giữa gói Hydro cũ chưa có binding (`cycle:slot`)
  và gói có binding (`cycle:rack:position`). Nếu dự án chứa cả hai kiểu cho
  cùng vị trí/vụ, cần đối chiếu nguồn và giữ các nhóm cùng cây trong cùng tập
  trước khi công bố kết quả đánh giá độc lập. Không sửa lineage tự động.
- Không thay chính sách Operational: TEST độc lập không bắt buộc để xuất
  gói chưa kiểm định với xác nhận rõ ràng. Không thay Hydro/Email/bơm/Fleet.

## Nghiệm thu

Các test mới dùng project tạm: xung đột, hủy/sửa, chuyển thủ công, phân có
ràng buộc, stale confirmation, dữ liệu hỏng, lỗi ghi, giữ nhãn/sidecar,
độ phủ nhãn, lớp TRAIN thực, kiểm tra sớm và popup Tk.
Số liệu/bằng chứng thực chạy được ghi trong báo cáo AI_KL ngày26/09.
Không tuyên bố đã nghiệm thu hình ảnh cửa sổ thật khi công cụ capture bị lỗi.

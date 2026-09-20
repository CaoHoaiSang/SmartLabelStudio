# Nhãn ảnh khách đóng góp từ Fleet — 20/09/2026

## Cách dùng

1. Lưu việc và mở lại SmartLabel để nạp source mới; không cần tạo lại dự án cũ.
2. Trong project Hydro chọn **Nhận dữ liệu từ Fleet**, lấy mã project.
3. Trên Fleet chọn đợt đã duyệt tiếp nhận cho phát triển model, cấp mã đúng
   project. Dán mã để nhận vào vùng chờ nếu chưa nhập.
4. Lấy/dán mã còn hạn và chọn **Mở đợt đã nhập để gán nhãn**. Nguồn
   **Khách đóng góp** dùng chính canvas, thuộc tính, bộ lọc và nút duyệt hiện có.

Mỗi phiên mở một đợt, tối đa50ảnh; mã tối đa5phút, giữ trong RAM. Ảnh được
kiểm quyền lại nền khi đang mở (display lease tối đa30giây, đồng hồ monotonic).
Hết quyền/không kết nối sẽ xóa ảnh khỏi canvas và danh sách thumbnail, khóa
thao tác. Mất mạng không xóa nhãn đã lưu. Bộ nhận bận được thử lại có chờ;
không biến thông báo “đang bận” thành đăng xuất hoặc lặp vô hạn khi mã hết hạn.

## Nhãn và nguồn

- Không áp dụng nhãn mặc định hoặc tự chép kết quả AI vào nhãn Fleet.
- Phone hiển thị riêng, không giả thành ảnh Internet. Hydro giữ nguyên nguồn,
  rọ/vụ/cây, nhưng chưa đưa sang Giàn khi chưa có adapter slot-only/QA đầy đủ.
- Không gán nhãn plant classifier cho ảnh toàn cảnh/overview.
- Nhãn được ghi qua receiver vào review.json, có kiểm hash/schema/revision;
  project.json, project.images và nhãn cũ không bị ghi đè.
- Duyệt nhãn chưa đưa ảnh vào dataset/train. `trainAllowed:false` vẫn bắt buộc.
  Exporter không đọc vùng chờ; generic import không dùng để đi vòng quyền Fleet.
- Xóa đợt trên Fleet dọn ảnh, nhãn và lịch sử sidecar tại project, kể cả khi
  app đóng. Từ chối trong SmartLabel chỉ là loại ảnh, không xóa đóng góp khách.

## Chưa hoàn tất

Chưa có quản lý bản sao snapshot/dataset/model của Fleet và các gate đồng bộ
quyền trước export/train/phát hành; chưa mở tính năng train ảnh Fleet.
Chưa được coi nguồn Hydro là bộ kiểm chứng độc lập. Không nới validator ZIP
Hydro, không tạo ảnh cha giả hoặc bắt người dùng làm lại nhãn/project.

Kiểm chứng: full281 tests pass trước sửa duration; targeted Fleet16/16 cuối
pass (10,314s); fixture Tk cùng widgets/không khóa chuột, API Python thật
qua receiver/Fleet và xóa nhãn khi app đóng. Audit ảnh thật lưu tại AI_KL.

Pilot Internet20/09 lúc23:43–23:44:1ảnh Hydro slot-only vào đúng project thử
qua adapter Python SmartLabel, mở sau kiểm quyền/hash rồi lưu nháp chỉ presence
quan sát. Nhập lại cùng mã không trùng, không ghi đè review.json/project.json;
không có export/run/version. Chưa train, chờ xác nhận rút/xóa. Đây là nghiệm
thu adapter/API thật, không tuyên bố đã click toàn bộ giao diện desktop thật.

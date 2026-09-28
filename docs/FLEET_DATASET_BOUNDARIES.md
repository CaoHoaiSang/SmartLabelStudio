# Khóa đường dataset/train cũ đối với Fleet — 21/09/2026

Đợt nối tiếp kiểm tra nguồn/preflight. Chưa mở admission hoặc train ảnh Fleet.
Các dự án cũ không liên quan tiếp tục xuất/train cục bộ như trước; chỉ có vùng
chờ Fleet trong thư mục project không làm khóa toàn bộ project.

## Lớp chặn

- Trước tạo version, YOLO/COCO/classification export và gói model Hydro: từ chối
  record có provenance Fleet hoặc đường dẫn tới kho/vùng chờ Fleet. Chặn trước
  khi tạo thư mục/tệp đầu ra, không xóa/sửa nhãn để chữa lỗi.
- Trước khởi chạy train và trong chính train_worker: kiểm cả đường gọi mới và
  ứng dụng cũ đang mở. Chưa nạp Ultralytics/model khi phát hiện dữ liệu Fleet.
- Kiểm đường dẫn thật, thư mục split/class, liên kết/junction, file YAML,
  danh sách ảnh TXT và bản kê export/manifest. Bản kê không xác minh được thì
  báo lỗi, không giả coi như không có dependency.
- Cờ `trainAllowed:true` trong JSON không thay quyền. Không tạo nút vượt khóa.
- Generic importer kiểm cả chính thư mục đích chứ không chỉ các thư mục cha:
  junction trỏ thẳng vào fleet_inbox không thể đi vòng khi thư mục đang rỗng.

Đây là **khóa chặn trong giai đoạn chưa có pipeline snapshot**, không phải
đã triển khai đồng bộ quyền rút dữ liệu xuyên mọi dataset/model. Chưa quản lý
bản sao thủ công đã xóa sạch nguồn gốc bên ngoài ứng dụng; không hứa tìm ra
nguồn của mọi ảnh đã bị sao chép hoặc thay đổi. Không train/đổi model thật.

## Kiểm tra giao nhau với dữ liệu cũ

Preflight không chỉ dò trùng byte/pixel. Nếu cùng mã vụ với ảnh cũ nhưng thiếu
namespace Gateway/nhóm thì báo chưa thể đối chiếu, không tự chứng nhận độc lập.
Nhóm cùng vụ đã ở holdout bị chặn, kể cả ảnh khác pixel. Gateway khác có mã
cục bộ giống nhau không bị gộp. Không tự đổi assignment cũ để làm test xanh.
Bản kê nguồn được kiểm cùng project/nhãn, thêm hash vào báo cáo chỉ đọc.

Pixel fingerprint V1: SHA-256 của `FleetRGBV1` + byte NUL + width/height mỗi
số nguyên unsigned 32-bit big-endian + chuỗi byte RGB đã giải mã. Không dò
ảnh gần giống hoặc phân tích chất lượng model. Report không phải snapshot.

## Trước khi mở dataset Fleet thật

Phải đăng ký custody cho mỗi bản sao trước copy, snapshot có lineage đến từng
đợt/ảnh/nhãn/split, dọn được snapshot managed khi rút (kể cả khi app đóng),
kiểm quyền mới trước export/train/phát hành và chặn khôi phục từ backup.
Không bỏ module chặn này trước khi đường quản lý đó được kiểm thử đầy đủ.
Giữ trainAllowed false và không coi đợt4 đã xong.

## Kiểm thử và bàn giao

Nhánh `fix/fleet-dataset-boundaries` nối tiếp app `473e440` của nhánh nguồn.
Vòng full cuối 21/09/2026: **299/299 unittest đạt trong249,691 giây**;
targeted Fleet33/33 đạt; receiver15/15 đạt với Python adapter/ProjectStore
thật trong fixture, gồm preflight/rút dữ liệu, không tạo dataset.
Regression junction trước sửa đã thất bại đúng guard bỏ sót chính thư mục.
Các project/test cũ qua hồi quy; năm tệp workspace dirty sẵn không sửa/stage.
Full Tk suite có cảnh báo callback sau destroy cửa sổ fixture, không failure;
không coi đây là nghiệm thu thao tác desktop người dùng.

Cloud/bộ nhận Windows đã nạp phần nguồn; SmartLabel cần lưu việc/mở lại để
nạp UI mới. Không gửi ảnh mới, không train/model hoặc đổi vận hành Hydro.
Chi tiết Git/rollout/giới hạn ở AI_KL
`audits/2026-09-21/FLEET-SOURCE-QUALIFICATION-PREFLIGHT.md`.

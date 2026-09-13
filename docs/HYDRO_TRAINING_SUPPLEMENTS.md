# Tổng quan thuộc tính và ảnh bổ trợ Hydro

Ngày 13/09/2026. Source tiếp nối công cụ Hydro/Chai hiện có, không đổi contract model/bundle.

Tổng quan Hydro đếm **giá trị thuộc tính trên ảnh rọ đã duyệt**, thay cho số
khung hình học thường bằng 0. Mỗi thuộc tính có Có/Không/Chưa chắc/Không áp dụng,
thiếu giá trị và số ảnh chưa duyệt/bị loại. Bảng TRAIN/VAL/TEST hiển thị số ảnh
đủ nhãn Có/Không theo phân tập khóa; condition chỉ tính khi presence dương.
Mặc định trên ảnh chưa duyệt không được coi là nhãn đã duyệt. Tập TEST thiếu
một lớp được nhắc rõ. Chai nhựa giữ thống kê hình học/Class/nguồn nhãn.

## Dùng ảnh bổ trợ

Ảnh tổng hợp hoặc ảnh ngoài giàn nằm trong `training_supplements/` của project,
không import thành ảnh capture có lineage giả. Nút **Xem ảnh bổ trợ train** tại
Dự án mở thư mục ảnh và manifest. Tổng quan báo riêng số ảnh đang bật; nhấn Train
vẫn dùng exporter Classification hiện có, tự thêm ảnh phù hợp vào TRAIN đúng
thuộc tính. Nhật ký train ghi số ảnh bổ trợ. Chưa chạy train khi chỉ xem Tổng quan.

Đặt `enabled: false` cho ảnh cần bỏ trước lần Train tiếp theo. Không chỉnh nhãn
hay bật/tắt bằng cách sửa snapshot đã export. Các snapshot giữ độc lập; thay
manifest chỉ ảnh hưởng lần export/Train mới. Dữ liệu supplement không được tính
vào QA capture thực địa, không dùng vá số lượng TEST hoặc chứng minh chất lượng.

Manifest local v1:

- `schemaVersion: 1`, `projectId` và `labelIdentities` từ `training_identity`
  của từng thuộc tính. Tên hiển thị có thể đổi; ID/ý nghĩa đổi phải duyệt lại.
- `images`: mỗi ảnh có `id`, `enabled`, đường dẫn `file` nằm trong thư mục,
  `sha256`, `kind` (`synthetic`/`external`), `split: train`, `cropCode`,
  `attributes` (chỉ thuộc tính được kiểm), `presenceMeaning`,
  `reviewStatus: reviewed`, `reviewNote`, `provenance`.
- Ảnh synthetic phải có `parentImageId`, `parentSha256`, `method`, `prompt`.
  Ảnh gốc phải còn trong project, đã duyệt, hash khớp và vẫn ở TRAIN khóa.
  Nếu ảnh gốc chuyển sang VAL/TEST, exporter chặn cả khi chọn Train All/Final;
  phải tắt biến thể hoặc xem lại phân tập, không tự chuyển benchmark.
- Ảnh external cần URL, tác giả, giấy phép, URL giấy phép, ngày truy cập.
  Người nhập phải kiểm quyền sử dụng, đúng giống cây và nhãn thị giác;
  việc có chuỗi giấy phép trong manifest không tự xác minh quyền tác giả.

Export kiểm hash ảnh và trùng nội dung RGB nguyên kích thước với ảnh trong
project/các supplement; không có bộ tìm near-duplicate của ảnh bị crop/đổi kích
thước. Nguồn ngoài cần kiểm gần trùng riêng. Manifest và nguồn từng ảnh được
ghi vào `export.json`; ảnh chỉ vào TRAIN, kể cả các thư mục VAL tương thích
ở chế độ Final/Train All. Ảnh chỉ có nhãn Lá vàng không vào classifier Hiện diện/Héo.
Project không có sidecar hoặc tắt mọi ảnh vẫn train theo luồng trước.

## Lô thử thực tế trên máy chủ hệ thống

Project Cải ngọt có 1.300 ảnh giàn: Lá vàng TRAIN 80 Có/755 Không,
VAL 21 Có/219 Không, TEST 0 Có/126 Không; phần còn lại không áp dụng.
Đã thêm **4 ảnh vàng tổng hợp + 2 ảnh xanh tổng hợp đối chứng**, từ ảnh TRAIN đã
duyệt, chỉ cho Lá vàng. TRAIN sau bổ sung 84 Có/757 Không; VAL/TEST giữ nguyên.
Đây là lô nhỏ để thử augmentation, không giải quyết toàn bộ thiếu dữ liệu và
chưa chứng minh model tốt hơn. Không có lần train hay phát hành model trong đợt này.
Ảnh tạo bằng ImageGen có thể thay đổi chi tiết nhỏ ngoài phần sửa; cần so sánh
model mới/cũ trên VAL thật rồi nghiệm thu TEST/hiện trường có đủ hai phía.

Khảo sát nguồn công khai ngày 13/09/2026:

- [mustard disease — syam jr](https://universe.roboflow.com/syam-jr/mustard-disease), CC BY 4.0:
  ảnh mẫu xem thấy lỗ ăn lá; chưa xác minh giống Cải ngọt/biểu hiện vàng.
- [chinese cabbage labels — chinese cabbage](https://universe.roboflow.com/chinese-cabbage-qgkyk/chinese-cabbage-labels), CC BY 4.0:
  ảnh mẫu có cải khác giống, lá rời và ánh sáng gắt; không đủ điều kiện nhập bài Cải ngọt.
- [Skripsi — Skripsi](https://universe.roboflow.com/skripsi-les8w/skripsi-kktsv), CC BY 4.0:
  có lớp Daun Kuning nhưng mẫu lá dài/lá rời, chưa xác minh giống; không tự đổi thành `cai_ngot`.

Đã tải 8 thumbnail công khai để kiểm nguồn/độ phù hợp, giữ ngoài dataset train.
Quyết định loại chỉ áp dụng mẫu đã xem, không khẳng định toàn bộ dataset không phù hợp.
Không tạo billing, mua dữ liệu hoặc gọi cloud training. Dataset/ảnh runtime không commit Git.

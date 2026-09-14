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

## Hiện hành: thêm 64 ảnh vàng, ưu tiên trưởng thành — 14/09/2026

Đã tạo, xem từng ảnh và cài **64 ảnh vàng mới từ 64 ảnh gốc chưa dùng**, mỗi
ảnh gốc một biến thể. Theo lựa chọn của chủ hệ thống: 48 ảnh tuổi 32–39 ngày,
10 ảnh tuổi 24–28 ngày, 6 ảnh tuổi 19–23 ngày. Vàng một phần lá, trọn một lá,
nhiều lá, toàn cây: mỗi mức 16 ảnh. Không dùng lại ID/hash ảnh gốc hoặc cặp
cây/ngày của các lô trước. Vẫn là **7 nhóm cây TRAIN trong cùng vụ**, không
phải 64 cây độc lập; tuổi trưởng thành không bảo đảm tán lớn ở mọi ảnh.

Giữ nguyên 51 ảnh và bản ghi cũ. Tổng hiện hành **115 ảnh bổ trợ: 108 vàng,
7 xanh đối chứng**. Lô mới ở
`training_supplements/batches/yellow_mature_64_20260913/`; tên batch giữ ngày
bắt đầu, hoàn tất ngày 14/09. `generation-jobs.json` lưu prompt chính xác,
ảnh gốc, kết quả và ghi chú duyệt. Dùng OpenAI built-in ImageGen tham chiếu
trực tiếp ảnh thật; gân/viền có thể được dựng lại. Chỉ duyệt nhãn thị giác
`yellow_leaf=present`, không suy thêm nhãn Héo, nguyên nhân bệnh hoặc số lá.

Trong dự án **Phân Loại Cải Ngọt**, chọn **Dự án → Xem ảnh bổ trợ train**,
mở `XEM_ANH.html`. Gallery có 115 cặp gốc/tổng hợp, lọc theo lô, cây và mức
vàng; mặc định xem 64 ảnh mới, ưu tiên trưởng thành. Ảnh đã nằm trong dự án,
lần Train Lá vàng mới tự đọc manifest; không cần nhập từng ảnh vào danh sách
capture. Snapshot/model đã train trước đó không tự thay đổi khi thêm ảnh.

Kiểm ngày 14/09: 14/14 test adapter đạt; preflight cả ba classifier; cài lại
không nhân đôi; xuất dữ liệu thật qua output tạm cho kết quả:

| Bộ dữ liệu Lá vàng | TRAIN Có/Không | VAL Có/Không | TEST Có/Không |
| --- | ---: | ---: | ---: |
| Ảnh thật | 2/833 | 0/238 | 0/125 |
| Kèm 51 bổ trợ cũ | 46/840 | 0/238 | 0/125 |
| Kèm toàn bộ 115 bổ trợ | **110/840** | **0/238** | **0/125** |

Ảnh TRAIN cũ và VAL/TEST giữ nguyên từng byte khi export. Project/split/ba PT
giữ hash từ ngay trước cài; project.json đã đổi ngoài tác vụ kể từ lúc chọn
nguồn nên installer kiểm trạng thái hiện hành và bảo toàn thay đổi đó.
Hiện diện/Héo nhận 0 supplement. Gallery đã kiểm cấu trúc/230 đường dẫn ảnh;
chưa kiểm render bằng browser do URL file bị công cụ chặn ở đợt trước.

Chưa chạy train hoặc triển khai model, chưa chứng minh chất lượng tăng.
VAL/TEST vẫn thiếu ảnh vàng thật độc lập: cần bổ sung trước khi đánh giá
hai phía hoặc hiệu chỉnh ngưỡng. Không dùng ảnh tổng hợp để vá benchmark.
Source runtime không đổi. Nhánh `feat/hydro-yellow-mature-diversity-64`
kế thừa `82aac1d`; Git chỉ lưu tài liệu, bộ ảnh lưu local trong project.

## Lịch sử: lô đa dạng 40 ảnh vàng — 13/09/2026

Theo yêu cầu mở rộng của chủ hệ thống, đã tạo và kiểm từng ảnh bằng mắt:
**40 ảnh vàng mới + 5 ảnh xanh đối chứng**, từ 10 ảnh giàn có sẵn ở mốc
19–39 ngày. Cả 10 ảnh gốc đã duyệt và thuộc TRAIN khóa; mỗi biến thể tham
chiếu trực tiếp ảnh gốc, không nối nhiều lần sửa trên ảnh tổng hợp.

| Mức vàng mô phỏng | Cây nhỏ | Cây vừa | Cây lớn | Tổng |
| --- | ---: | ---: | ---: | ---: |
| Một phần lá | 3 | 4 | 3 | 10 |
| Trọn một lá | 3 | 4 | 3 | 10 |
| Nhiều lá | 3 | 4 | 3 | 10 |
| Toàn cây | 3 | 4 | 3 | 10 |
| Xanh đối chứng | 2 | 2 | 1 | 5 |

Giữ nguyên 6 ảnh lô trước, tổng **51 ảnh bổ trợ: 44 vàng + 7 xanh**.
Lô mới nằm trong `training_supplements/batches/yellow_diversity_40_20260913/`.
Mở `XEM_ANH.html` từ thư mục bổ trợ để lọc theo kích thước/mức vàng và xem
ảnh gốc cạnh ảnh tổng hợp. Manifest lưu prompt đầy đủ, SHA, parent/group,
ngày duyệt; `growthStage`, `ageDays`, `severity` chỉ mô tả lô ảnh, không thêm
class mới. Luồng train vẫn học Có/Không của `yellow_leaf`; Hiện diện/Héo
không nhận nhãn suy đoán. Không đổi source runtime hoặc contract trong đợt này.

**Số liệu hiện hành trước cài:** project đã được chỉnh ngoài tác vụ trong lúc
tạo ảnh, từ 1.300 còn 1.297 ảnh và nhãn vàng đã đổi. Không khôi phục dữ liệu
về bản cũ. Snapshot kiểm ngày 13/09: TRAIN thật 2 Có/833 Không, VAL 0/238,
TEST 0/125. Export sau bổ sung: **TRAIN 46 Có/840 Không**; VAL/TEST và ảnh
TRAIN cũ giữ nguyên từng byte. Project, split và ba PT giữ hash từ ngay trước
cài đến sau kiểm. Kiểm 14 test adapter đạt; cài lại không nhân đôi lô hoặc
đổi manifest. Sáu ảnh cũ giữ file và bản ghi nguồn. Các số 80/755, 21/219,
0/126 và 84/757 thuộc mốc lô 6 ảnh trước đó, không còn là số hiện hành.

Ảnh tổng hợp bằng built-in ImageGen có thể dựng lại gân, viền và chi tiết.
Mức độ vàng không phải nhãn đếm lá chính xác hoặc kết luận nguyên nhân bệnh.
10 ảnh gốc thuộc 7 nhóm cây cùng một vụ, không tạo thêm vụ/cây độc lập.
Chưa train hoặc phát hành model mới. VAL và TEST hiện đều thiếu lớp Có:
cần bổ sung ảnh vàng thật vào benchmark độc lập trước khi đo hai phía;
không đưa ảnh tổng hợp hoặc chuyển ảnh gốc TRAIN vào đó để đủ số lượng.
Sau đó mới so sánh model có/không augmentation. Không suy số ảnh tăng thành
chất lượng tăng.

## Khảo sát nguồn ngoài trước lô đa dạng

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

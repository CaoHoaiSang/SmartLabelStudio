# Tổng quan thuộc tính và ảnh bổ trợ Hydro

Ngày 15/09/2026. Source tiếp nối công cụ Hydro/Chai hiện có, không đổi contract model/bundle.

## Sửa nhãn và chuyển ảnh — 15/09/2026

Sửa thuộc tính tự lưu. Nếu nhãn mới làm ảnh ra khỏi bộ lọc (ví dụ đang xem
Đã duyệt nhưng sửa ảnh thành nháp), giữ ảnh và giá trị vừa sửa trên canvas;
báo rõ ảnh không còn thuộc bộ lọc. Không tự nhảy sang ảnh khác có giá trị cũ.
Ảnh sau / Ảnh trước hoặc chọn thumbnail mới sẽ tiếp tục danh sách còn khớp.
Duyệt & tiếp vẫn là thao tác chủ động lưu duyệt rồi chuyển ảnh.

Số thứ tự / tổng ảnh nằm ở vùng riêng góc trên trái, không bị tên tệp dài
che mất. Giàn tính trên toàn bộ ảnh giàn; Bổ trợ tính trên nguồn đang làm
việc, tách ảnh lưu trữ. Bộ lọc/phân trang vẫn hiển thị số ảnh khớp riêng.

**Tải lại từ tệp** chỉ hiện ở Bổ trợ: đọc lại sidecar khi một công cụ/phiên
khác đã cập nhật, hoặc để xử lý xung đột revision. Không cần nhấn sau mỗi
lần sửa/duyệt. Giàn dùng dữ liệu đang mở và tự cập nhật danh sách; ẩn nút
tải lại dư thừa ở nguồn này. Giữ xác nhận ghi chú chưa lưu trước tải lại.

Tối ưu không thay đổi nhãn hoặc điều kiện nhận mẫu train:

- Lưu project mã hóa trực tiếp một lần, giữ JSON và thay tệp atomic; snapshot
  to_dict vẫn là bản sao độc lập. Lỗi lưu thuộc tính Giàn khôi phục giá trị
  đã lưu trên form và báo lỗi tại chỗ.
- Lưu nháp Bổ trợ chỉ cần schema/settings; không sao chép cả danh sách ảnh
  hoặc quét phân tập. Giữ ảnh/zoom khi lưu chính ảnh đang xem.
- Thống kê trang Tổng quan/Dataset được đánh dấu cần cập nhật và dựng khi
  mở trang, không dựng lại hai trang ẩn sau mỗi lần gán nhãn.
- Duyệt vẫn kiểm tất cả dữ liệu liên quan, nguồn TRAIN, nhãn, ảnh trùng,
  checksum, revision và khóa ghi. Cache chỉ dùng lại dấu vân tay pixel
  sau khi đọc và băm lại toàn bộ byte của tệp; không dùng mtime làm bằng chứng.
  Có bước chuẩn bị cache nền khi mở Bổ trợ; cache giới hạn 4.096 mục và tách
  theo project. Lần kiểm tra đầu hoặc khi tệp đổi vẫn có thể lâu hơn.
  Export train không dùng cache này và vẫn kiểm toàn bộ nguồn độc lập.

Mở lại SmartLabel để nạp Python source mới. Các mốc dữ liệu phía dưới là
lịch sử; đợt 15/09 không tự sửa nhãn/dataset, train hoặc thay model của người dùng.

Tổng quan Hydro đếm **giá trị thuộc tính trên ảnh rọ đã duyệt**, thay cho số
khung hình học thường bằng 0. Mỗi thuộc tính có Có/Không/Chưa chắc/Không áp dụng,
thiếu giá trị và số ảnh chưa duyệt/bị loại. Bảng TRAIN/VAL/TEST hiển thị số ảnh
đủ nhãn Có/Không theo phân tập khóa; condition chỉ tính khi presence dương.
Mặc định trên ảnh chưa duyệt không được coi là nhãn đã duyệt. Tập TEST thiếu
một lớp được nhắc rõ. Chai nhựa giữ thống kê hình học/Class/nguồn nhãn.

## Giao diện dùng chung Giàn / Bổ trợ — 14/09/2026

Mở **GÁN NHÃN → Bổ trợ** ở bên phải **DANH SÁCH ẢNH**. Hai nguồn dùng
chính các widget hiện hữu: danh sách thumbnail/phân trang, bộ lọc, canvas,
zoom %, căn giữa, thuộc tính, ghi chú và các nút duyệt. Không còn màn hình
Bổ trợ riêng hoặc bộ lọc Đợt/tuổi cây. Ba ô lọc giống Giàn: **trạng thái →
nhãn/thuộc tính → giá trị**. Chỉ có **Chưa gán giá trị** khi nguồn ảnh đang
xem còn thiếu giá trị của thuộc tính đã chọn. Giàn và Bổ trợ dùng cùng năm
trạng thái: Tất cả, Chưa gán nhãn, Bản nháp, Đã duyệt và Từ chối. Bản ghi Bổ
trợ cũ từng có `archived: true` cũng hiện trong **Từ chối** và khôi phục được;
không còn bộ lọc lưu trữ riêng.

Dữ liệu Bổ trợ vẫn đọc sidecar, không đưa ảnh gốc hoặc biến thể vào
project.images. Thumbnail dùng cùng thành phần với Giàn; số nhãn Hydro
đếm thuộc tính đã gán. Canvas chỉ xem/phóng/kéo đối với Bổ trợ; các thao tác
hình học và phím Delete/Undo không tác động vào ảnh Giàn đang chọn trước đó.
Đổi về Giàn khôi phục bộ lọc, trang và ảnh đang xem; bài Chai giữ luồng cũ.

- Đổi thuộc tính **tự lưu bản nháp**, tắt ảnh khỏi export mới tới khi duyệt.
  Dùng cùng dropdown/ngữ nghĩa của Giàn. Chọn Không có cây/Chưa chắc/bỏ Hiện
  diện đưa tình trạng về Không áp dụng; không suy Héo=Không từ ảnh gốc.
- **Duyệt & tiếp** lưu các nhãn đủ điều kiện, bật train và chuyển ảnh kế tiếp.
  Ảnh đã duyệt khóa nút này; dùng **Ảnh sau** để đi tiếp. Sửa nhãn hoặc bỏ
  duyệt mới mở lại thao tác duyệt, tránh lưu lại lịch sử không có thay đổi.
  Bổ trợ giữ contract duyệt từng thuộc tính: mỗi classifier chỉ nhận giá trị
  Có/Không của chính nó. Mục thiếu/Chưa chắc/Không áp dụng không train.
- **Bỏ duyệt / Từ chối** giữ nhãn đã lưu và tắt train. **Khôi phục** đưa về
  bản nháp để kiểm lại, chưa bật train. Ghi chú bất thường lưu riêng, không train.
- Nút `×` trên thumbnail Bổ trợ là **xóa vĩnh viễn**: sau xác nhận, Studio xóa
  tệp ảnh thuộc project, nhãn, nguồn và lịch sử của riêng ảnh đó. Ảnh Giàn gốc
  và Dataset đã export không bị thay đổi. Nếu chỉ chưa muốn dùng train, chọn
  **Từ chối** để còn có thể **Khôi phục**. Backend chỉ giữ khả năng đọc
  `archived` cho dữ liệu cũ, không tạo trạng thái lưu trữ mới từ giao diện.
  Không suy ảnh trùng chỉ vì Lá vàng=Không.
  Từ 19/09, xóa bị khóa khi project đang nhập/duyệt, Auto-Label, train, đánh
  giá hoặc xuất model. Nhấn Dừng chưa mở khóa ngay: cần đợi completion. Sau
  hộp xác nhận, Studio kiểm lại job, project và revision trước khi xóa; nếu
  ngữ cảnh đổi thì không xóa và yêu cầu chọn lại ảnh. Không tự chuyển sang
  xóa ảnh đang chọn khác nếu ID mục tiêu không còn trong danh sách.
- Lưu chạy ở worker, khóa đổi ảnh/nguồn/dự án trong khi ghi. Xung đột revision
  hoặc lỗi ghi giữ thay đổi trên form và báo lỗi; không ghi đè phiên khác.
  Ghi chú chưa lưu được hỏi trước khi chuyển nguồn/dự án hoặc đóng.

### Mặc định và chuyển nguồn ảnh — cập nhật 14/09/2026

Bổ trợ điền thuộc tính ảnh còn thiếu theo mặc định hợp lệ tại **Quản lý nhãn,
thuộc tính**. Giữ giá trị đã gán, kể cả Chưa chắc/Không áp dụng. Hiện diện
thực tế của bản ghi quyết định giá trị Không áp dụng cho tình trạng mới
được điền; không chép thuộc tính từ ảnh gốc và không dùng tên mã cố định.
Không có mặc định hợp lệ thì để trống. Người dùng chủ động bỏ một giá trị
vẫn được giữ trống khi tải lại; lúc đó bộ lọc Chưa gán giá trị xuất hiện.

Mặc định mới là nhãn chờ xác nhận. Ảnh thiếu nhãn có mặc định hiển thị Bản
nháp; duyệt trong UI mới lưu và bật dữ liệu cho train. API sửa dữ liệu cũ
`materialize_missing_defaults` lưu nhãn còn thiếu, tắt train/chuyển nháp,
giữ nhãn cũ/lịch sử/ảnh lưu trữ và kiểm revision/lock trước khi thay manifest.
Không tự đổi nhãn đã lưu khi đổi giá trị mặc định. Export không lấy mặc định
chưa lưu từ UI làm bằng chứng; snapshot/model cũ không thay đổi.

Áp dụng dữ liệu ngày 14/09: giữ yellow_01 đã được người dùng gán đủ nhãn và
7 hàng lưu trữ. Điền Héo=`absent` theo cấu hình cho 107 hàng còn thiếu,
chuyển 107 hàng về nháp/tắt train; một hàng đã duyệt giữ bật. Giữ mọi nhãn
đã lưu trước đó và hash 1.422 tệp ảnh/project/split/model/workspace. Có
backup manifest và lịch sử từng hàng; không chạy train. Cần xem ảnh và duyệt
lại nhãn mới trước lần train tiếp theo, không khôi phục manifest cũ ghi đè.

Danh sách chung giữ tối đa 120 hàng thumbnail gần dùng (hoặc số hàng của
trang hiện hành nếu lớn hơn), ẩn/tái sử dụng khi chuyển nguồn; xóa cache khi
đổi project, làm mới thumbnail khi tệp thay đổi. Cache kiểm preview tối đa
150 đường dẫn có SHA và thời điểm/kích thước tệp; tải lại chủ động làm mới.
Duyệt/export vẫn kiểm hash và nguồn đầy đủ. Không so nhãn Giàn với ảnh Bổ
trợ cũ để hỏi nhầm chưa lưu. Không dựng danh sách hai lần khi chọn ảnh.

Đo đọc dữ liệu thật, 50 ảnh/trang tại 1180×720 với cProfile: median chuyển
Bổ trợ từ 4,7427 xuống 0,6309 giây, Giàn từ 2,5022 xuống 0,3783 giây qua
ba vòng. Lượt Bổ trợ đầu chưa có cache vẫn 4,412 giây; các lượt dùng lại
trang đã tải 0,1347–0,6309 giây. Đây là đo tại Windows hiện tại, không phải
cam kết thời gian cho mọi máy/dataset. Lỗi hỏi nhãn chưa lưu giảm từ 2 về 0.

### Hiện diện và nhãn tình trạng

Sidecar cũ có `presenceMeaning=positive` để xác nhận cây trước khi gán Lá
vàng/Héo nhưng thiếu thuộc tính hiện diện tương ứng. Adapter nay biểu diễn
xác nhận này bằng đúng mã Có cây của schema, dùng nhất quán ở form, bộ lọc,
validator và snapshot train. Chỉ chuyển khi có xác nhận dương cũ cùng nhãn
tình trạng Có/Không; không đoán từ tên nhãn, ảnh gốc hoặc ảnh chưa xác nhận.
Giá trị hiện diện đã gán rõ luôn được giữ; nếu mâu thuẫn thì validator chặn.
Khi người dùng sửa/bỏ Hiện diện, xác nhận cũ được cập nhật hoặc xóa theo,
không tự xuất hiện trở lại từ trường cũ.

Dữ liệu ở mốc sửa Hiện diện trước bổ sung mặc định: 108 ảnh làm việc, 7 đối chứng xanh lưu trữ. Một ảnh đã có
nhãn Hiện diện do người dùng gán; sửa một lần chuyển 107 xác nhận cũ còn lại
thành nhãn Có cây, giữ nguyên Lá vàng, trạng thái duyệt và enablement. Có
backup, revision, history và kiểm hash ảnh/project/split/model. Preflight lúc đó:
Hiện diện 108, Lá vàng 108, Héo 0. Không chạy train hoặc thay model hiện hành.
Ảnh tổng hợp chỉ vào TRAIN; VAL/TEST vẫn giữ nguồn ảnh thật độc lập.

Tổng quan và Dataset dùng chung thành phần hiển thị có vùng cuộn tự cập nhật
khi mở/đóng chi tiết. Dataset mặc định mở chi tiết Train/Val/Test; Tổng quan có
thể mở khi cần. Sửa ngày 14/09: giữ handler Configure của CTkScrollableFrame,
không ghi đè scrollregion khi bổ sung xử lý đổi chiều rộng.

Hydro hiển thị ba số chính **Ảnh giàn / Đã duyệt / Chưa duyệt** và
thẻ riêng cho mỗi thuộc tính, nhấn mạnh **Có / Không**. Chỉ hiện nhóm chưa
chắc/không áp dụng/thiếu nhãn/chưa duyệt khi có dữ liệu. Chi tiết phân tập nằm
trong **Xem chi tiết Train / Val / Test**. Ảnh bổ trợ có ba số tương ứng,
trạng thái dùng train và số Có/Không theo từng thuộc tính; không cộng vào số
ảnh giàn hoặc VAL/TEST. Khối nền xanh của Bổ trợ nằm sau toàn bộ số liệu ảnh
Giàn để thứ bậc nguồn chính → nguồn bổ sung rõ ràng. Chai và bài vật thể có cùng
cách trình bày thẻ nhưng thống kê nhãn hình học, Class, nguồn và các thuộc tính
theo phạm vi trên ảnh/trên vật thể; không có mục Ảnh bổ trợ Hydro. Chỉnh phân tập
cập nhật cả hai bảng. Không thay đổi luật export hoặc tự chuyển ảnh giữa các tập.

## Dùng ảnh bổ trợ

Ảnh tổng hợp hoặc ảnh ngoài giàn nằm trong `training_supplements/` của project,
không import thành ảnh capture có lineage giả. Mở **GÁN NHÃN → Bổ trợ** để xem
và duyệt bằng cùng giao diện ảnh giàn; trang Dự án/Dataset chỉ thống kê, không
lặp nút điều hướng. Nhấn Train
vẫn dùng exporter Classification hiện có, tự thêm ảnh phù hợp vào TRAIN đúng
thuộc tính. Nhật ký train ghi số ảnh bổ trợ. Chưa chạy train khi chỉ xem Tổng quan.

Chuyển ảnh về chờ duyệt hoặc từ chối để đặt `enabled: false` trước lần Train tiếp theo. Không chỉnh nhãn
hay bật/tắt bằng cách sửa snapshot đã export. Các snapshot giữ độc lập; thay
manifest chỉ ảnh hưởng lần export/Train mới. Dữ liệu supplement không được tính
vào QA capture thực địa, không dùng vá số lượng TEST hoặc chứng minh chất lượng.

Manifest local v1:

- `schemaVersion: 1`, `projectId` và `labelIdentities` từ `training_identity`
  của từng thuộc tính. Tên hiển thị có thể đổi; ID/ý nghĩa đổi phải duyệt lại.
- `images`: mỗi ảnh có `id`, `enabled`, đường dẫn `file` nằm trong thư mục,
  `sha256`, `kind` (`synthetic`/`external`), `split: train`, `cropCode`,
  `attributes` (chỉ thuộc tính được kiểm), `presenceMeaning`,
  `reviewStatus`, `reviewNote`, `provenance`. `archived: true` buộc `enabled: false`.
  Thuộc tính được lưu cả Chưa chắc/Không áp dụng theo ID schema; chỉ các giá
  trị Có/Không hợp lệ được lấy làm mẫu của từng classifier. Bản nháp có thể
  chưa gán nhãn, nhưng ảnh bật train phải có ít nhất một nhãn Có/Không.
- Ảnh synthetic phải có `parentImageId`, `parentSha256`, `method`, `prompt`.
  Ảnh gốc phải còn trong project, đã duyệt, hash khớp và vẫn ở TRAIN khóa.
  Nếu ảnh gốc chuyển sang VAL/TEST, exporter chặn cả khi chọn Train All/Final;
  phải tắt biến thể hoặc xem lại phân tập, không tự chuyển benchmark.
- Ảnh external cần URL, tác giả, giấy phép, URL giấy phép, ngày truy cập.
  Người nhập phải kiểm quyền sử dụng, đúng giống cây và nhãn thị giác;
  việc có chuỗi giấy phép trong manifest không tự xác minh quyền tác giả.

Duyệt qua UI dùng lại validator của exporter (nhãn, nguồn, hash, parent TRAIN,
trùng RGB). Không ghi lại SHA để hợp thức hóa ảnh đã bị sửa. Lưu bằng tệp tạm
và atomic replace; khóa `.review.lock` ngăn hai phiên Studio cùng ghi, kiểm
revision trước/sau xác minh để phát hiện manifest đã đổi bên ngoài. Mỗi lần
lưu thêm `reviewHistory` gồm trạng thái/nhãn trước đó; không sửa project.json,
ảnh, split hoặc model. Nếu ứng dụng bị tắt cưỡng bức đúng lúc lưu, có thể còn
`.review.lock`; chỉ gỡ khóa sau khi xác minh không còn phiên đang ghi.

Export kiểm hash ảnh và trùng nội dung RGB nguyên kích thước với ảnh trong
project/các supplement; không có bộ tìm near-duplicate của ảnh bị crop/đổi kích
thước. Nguồn ngoài cần kiểm gần trùng riêng. Manifest và nguồn từng ảnh được
ghi vào `export.json`; ảnh chỉ vào TRAIN, kể cả các thư mục VAL tương thích
ở chế độ Final/Train All. Ảnh có xác nhận Có cây và nhãn Lá vàng được dùng cho đúng hai classifier
Hiện diện/Lá vàng; Héo chỉ nhận khi người dùng đã gán nhãn Héo đủ điều kiện.
Project không có sidecar hoặc tắt mọi ảnh vẫn train theo luồng trước.

## Mốc lịch sử: thêm 64 ảnh vàng, ưu tiên trưởng thành — 14/09/2026

Các số liệu 115 ảnh/7 đối chứng dưới đây là trước lần lưu trữ đối chứng xanh.
Danh sách hiện tại 108 ảnh làm việc/7 lưu trữ được mô tả phía trên.

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

Trong dự án **Phân Loại Cải Ngọt**, chọn **GÁN NHÃN → Ảnh bổ trợ** để xem và
duyệt 115 ảnh bổ trợ. `XEM_ANH.html` là gallery tĩnh cũ để đối chiếu nguồn,
không tự cập nhật quyết định duyệt mới; UI SmartLabel đọc manifest hiện hành. Ảnh đã nằm trong dự án,
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

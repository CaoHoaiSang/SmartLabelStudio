# Trạng thái tích hợp HydroFlow và SmartLabel — cập nhật 23/09/2026

## Hiện hành: sửa nền và quản lý nhãn, trả dropdown định vị — 23/09

Nhánh `fix/smartlabel-hydro-surfaces-label-editor`. Vùng cuộn popup cùng nền
`#0a131c` với Thuộc tính toàn ảnh Hydro, kể cả canvas Tk; ô nhập dùng nền đen
qua StudioEntry (bao gồm dòng thêm mới). Khôi phục CTkOptionMenu gốc cho
menu chung và bài định vị; menu Hydro riêng có hàng bo nhẹ, khoảng đệm,
tên dài xuống dòng, cuộn và bàn phím. Không bind_all hoặc truy cập clipboard.
Popup Quản lý nhãn sửa toolbar grid, thu gọn phần contract và tách rõ tên
giá trị/ý nghĩa; thùng rác bớt khoảng trống theo số dự án. Giữ các guard nhãn,
schema, model và QA. Xem [quy tắc hiện hành](DIALOG_DESIGN_SYSTEM.md).

377/377test toàn bộ đạt487,693s,14/14test nhãn Hydro đạt. Sau cleanup timer
cuối, nhóm popup chạy lại **27/27 đạt66,337s** (có test mới đóng ngay trước idle).
Compileall/diff check đạt. Không tăng timeout hoặc nới guard để vượt test.
Chưa nghiệm thu trực quan trên app thật: Computer Use vẫn lỗi
SetIsBorderRequired/0x80004002 sau một lần phục hồi. Không tự đóng app đang
làm; cần lưu việc và mở lại để nạp source. Kết quả test cuối ghi ở báo cáo AI_KL.

## Mốc trước: sửa mật độ popup/dropdown sau phản hồi — 23/09

Nhánh `fix/smartlabel-popup-density-dropdowns`: sửa vòng tự co wraplength khiến
mô tả còn100px dù khung rộng; title cyan#22b9ee, inset12–16px, gom các hàng ngắn.
Dropdown dùng một component owned hỗ trợ keyboard/cuộn/đóng ngoài/Esc và trả
grab; không xóa callback resize của CTk. Thùng rác dự án có layout riêng, tất cả
popup dựng khi ẩn rồi hiện với owner để tránh chu kỳ withdraw của CTk titlebar.
Dataset Phân tập / Kiểm định hai cột responsive; thống kê Giàn có nền riêng.
Không đổi dữ liệu, split, nhãn hoặc điều kiện phát hành. Xem
[quy tắc chi tiết](DIALOG_DESIGN_SYSTEM.md). Bản cuối372/372test đạt392,383s;
compileall và diff check đạt. Lượt đầu tìm ra hồi quy wrap ô số liệu tổng quan,
đã sửa và chạy lại đầy đủ, không tăng timeout/đổi test xuất model để che lỗi.
Capture Windows vẫn lỗi0x80004002: cần lưu việc/mở lại và đối chiếu trực quan;
không coi kiểm thử widget là audit hình ảnh toàn ứng dụng.

## Popup và phân nhóm nguồn ảnh — 23/09

Chuẩn hóa vị trí/DPI/cửa sổ con, chữ và hành động popup. Fleet non-modal có
transient owner, không luôn nổi trên ứng dụng khác; modal con trả grab cho cha.
Trợ giúp dài cuộn, xác nhận/nhập liệu dùng cùng bộ giao diện. Bốn nguồn danh
sách ảnh thành2×2; thẻ Có/Không của Bổ trợ giống Giàn, thêm TEST riêng không
cộng train/bản benchmark đóng băng. Dataset có nhóm Bộ kiểm định độc lập:
Thu thập ảnh TEST → Bộ TEST ngoài, không đưa thêm công cụ R&D vào Hydro.
[Quy tắc, ngữ nghĩa và giới hạn nghiệm thu](DIALOG_DESIGN_SYSTEM.md).
362/362test đầy đủ đạt463,296s, gồm13test mới; compileall/diff check đạt.
Cần lưu việc/mở lại Studio. Chưa đối chiếu hình ảnh runtime do lỗi công cụ
capture Windows; không thay việc test widget bằng tuyên bố nghiệm thu trực quan.

## Thu ảnh lô TEST riêng — Windows pilot 23/09

DATASET → Thu thập TEST: camera/ROI Hydro chỉ đọc, worker riêng không inference;
lượt1 10 cây, lượt2 6 cây + 4 rọ trống, giữ đủ20ảnh rọ. Gán nhãn trong form
GÁN NHÃN → TEST hiện hữu, không nhãn tự động hoặc thêm vào TRAIN/VAL.
Freeze/import contract riêng rồi đánh giá/duyệt theo checkpoint hiện hữu.
Lô cùng đợt gieo được khai báo đúng, không giả thành vụ khác; vị trí thay đổi
được, mã cây tùy chọn, kết quả theo ảnh. Không có tính năng mới trong Hydro.
Đọc [hướng dẫn, giới hạn, bàn giao camera](HELDOUT_CAPTURE_COLLECTOR.md).
349/349 test đầy đủ đạt (273,530s), gồm24test mới; fixture gói ONNX/ZIP giữ
phạm vi lô riêng. Chưa thu cây thật/đánh giá model thật hoặc nghiệm thu Nano.

## Nhận định classifier và trợ giúp ngưỡng — tối22/09

Log phân biệt TEST/VAL ít mẫu, lỗi FP/FN, ngưỡng0.50 với low/high vận hành;
gói có trợ giúp checkpoint và cảnh báo ngưỡng đã lưu thuộc model cũ. Không đổi
model/ngưỡng/split thật hoặc gate.325/325test đạt. Xem
[bằng chứng và cách đọc](CLASSIFIER_THRESHOLDS_20260922.md); mở lại Studio để nạp.

## Bộ TEST ngoài gắn checkpoint — hiện hành22/09

Đã nối Dataset → tạo/nhập TEST ngoài → đánh giá → duyệt → cổng tạo gói operational.
Ràng buộc bộ ảnh/schema/PT/ngưỡng/inventory và ONNX đóng gói; không tự dùng QA
phân tập thay bằng chứng đo. Split UI thêm nguồn vụ/ngày/lọc/chọn nhiều nhóm.
324/324test đầy đủ bản cuối đạt (294,645s). Không train hoặc
đánh giá model thật, không thay dữ liệu người dùng. Cần mở lại Studio; xem
[cách dùng, contract và giới hạn](EXTERNAL_BENCHMARK_CHECKPOINT.md).
Các mục dưới là lịch sử, đặc biệt câu benchmark ngoài “chưa nối” đã được thay thế.

## Final Train / TEST / thử Email — bổ sung22/09

Cửa sổ cấu hình gói có trợ giúp `TEST, Final Train và thử Email`: phân biệt
Final Train+Val giữ TEST với Train100% đã học TEST, chính sách phát hành với
giới hạn ONNX, và đường thử Email ảnh rọ độc lập của Hydro.306/306test đạt.
Không đổi gate, split, checkpoint hay train thật; benchmark ngoài gắn hash
checkpoint vẫn chưa nối vào cổng phát hành. Cần mở lại Studio để nạp trợ giúp.

## Giải thích QA operational — 22/09/2026

Tạo gói và Kiểm tra Dataset Hydro nay hiện số ảnh theo vụ/phân tập, lý do
TEST chưa độc lập và hướng xử lý. Không tự chuyển split hoặc bỏ QA. Cả80
ảnh vụ hai của project Cải Ngọt đang ở TRAIN, cũng có trong snapshot train
21/09; chưa thể chỉ chuyển thành TEST để dùng checkpoint cũ.305/305 test
đạt; dữ liệu/model giữ nguyên, cần mở lại Studio để nạp source. Xem
[contract và giới hạn](HYDRO_HOLDOUT_DIAGNOSTICS.md).

## Fleet: chặn đường vòng dataset/train — 21/09/2026

Đã thêm guard trước các exporter/version/bundle và launcher/worker train:
nguồn Fleet không được chuyển qua luồng cũ để mất custody. Kiểm đường dẫn
thật, junction, split YAML/TXT và metadata; giữ các project không liên quan.
Preflight phát hiện mã vụ trùng với dữ liệu cũ thiếu namespace, không tự chứng
nhận độc lập hoặc di chuyển holdout. [Giới hạn và bước tiếp](FLEET_DATASET_BOUNDARIES.md).
Chưa có managed snapshot/admission/withdrawal gate hoàn chỉnh; chưa train.
Cloud Fleet/bộ nhận Windows đã nạp nguồn mới ngày21/09; không restart Hydro.
SmartLabel đã cập nhật source nhưng chưa cưỡng bức đóng/mở phiên người dùng.
Lưu việc/mở lại để nghiệm thu giao diện thật; không cần làm lại project/nhãn.
Full cuối299/299 unittest đạt249,691s; Fleet targeted33/33 và receiver15/15
liên repo đạt. Không dùng kết quả fixture thay nghiệm thu ảnh thật/thiết bị.

## Fleet: kiểm tra nguồn trước duyệt — 21/09/2026

Thêm phân loại Giàn/Hydro qua Fleet, Bổ trợ điện thoại và nguồn cần kiểm tra
trong vùng gán nhãn có quản lý. Bằng chứng Gateway/thế hệ sở hữu/hash đến từ
server, ảnh không kèm cha có contract riêng, giống/rọ/vụ/ngày được kiểm tra.
Nhóm tương lai giữ cả vụ, không rò cùng vụ/cây giữa các tập; điện thoại chỉ
TRAIN. Lưu nháp vẫn được nếu thiếu thông tin; Duyệt bị khóa đến khi nguồn hợp
lệ. Giữ nhãn/project cũ; `trainAllowed:false`, chưa admission dataset.
[Chi tiết và giới hạn](FLEET_SOURCE_QUALIFICATION.md). Source/fixture đã qua
kiểm thử; không suy ra đã nạp vào desktop đang mở hoặc nghiệm thu ảnh thật.

## Fleet: vùng chờ project có quản lý — 20/09/2026

Cập nhật tiếp: đã nối vào **GÁN NHÃN → Khách đóng góp**, dùng canvas/form
hiện có và nhãn riêng được receiver quản lý. Không tự lấy kết quả AI làm nhãn;
mở/lưu kiểm quyền ngắn hạn, CAS/hash/schema, rút đợt xóa cả ảnh lẫn nhãn khi
app đóng. `trainAllowed:false`; chưa mở dataset/train hoặc slot-only→Giàn.
[Cách dùng và giới hạn gán nhãn](FLEET_LABEL_REVIEW.md). Phép thử ảnh thật
đã nhập đúng project thử qua adapter Python/receiver/Fleet Internet, xem ảnh
đúng hash và lưu nháp presence; nhập lại không trùng/ghi đè nhãn hoặc project.
Không train; chủ xác nhận rút/xóa, ảnh và nhãn tại project đã xóa23:48:49;
Fleet tự hoàn tất23:58:52 sau bản sửa cloud giữ bằng chứng đã dọn kho đệm.
Ảnh gốc Hydro giữ nguyên. Chưa nghiệm thu thao tác toàn bộ desktop UI thật;
không dùng fixture để thay bằng chứng này. Đợt4 chưa xong.

Mốc trước (vùng chờ chưa nối gán nhãn):

Đã thêm **Nhận dữ liệu từ Fleet** vào project Hydro, job nền khóa đúng đích,
nhận bằng quyền nhập riêng 5phút qua bộ nhận Windows hiện hữu. Receiver
quản lý custody trước copy/retry/withdrawal kể cả SmartLabel đóng. Không
sửa nhãn/project.images/dataset, chưa gán nhãn hoặc train từ vùng chờ.
[Cách dùng, contract và giới hạn](FLEET_MANAGED_INTAKE.md). Đợt4 chưa xong;
không dùng fixture làm nghiệm thu ảnh khách thật qua Internet.

## QA rọ và khóa xóa bổ trợ — 19/09/2026

QA tiếp tục cho phép thiếu ảnh rọ đã loại khỏi dataset với cảnh báo, nhưng
chặn mã rọ ngoài topology, trống/null và rọ trùng ở cả V1/V2. Báo lỗi liên kết
đúng ảnh để kiểm tra; không tự đổi mã, phục hồi ảnh hoặc gán lại nhãn.
Xóa Bổ trợ dùng cùng quyền sở hữu project/job như lưu nhãn, giữ khóa tới khi
completion được xử lý. Kiểm lại project/revision/job sau hộp xác nhận; nút ×
tạm khóa khi có job và mở lại khi idle. Giữ xác nhận xóa, sidecar CAS/lock,
rollback khi ghi lỗi, dữ liệu Giàn và snapshot đã xuất.
Chi tiết: [bản sửa sau review](reviews/CROSS_AI_QA_DELETE_FIXES_20260919.md).

## Hiện hành: hợp nhất thống kê và quyền xoá ảnh bổ trợ — 17/09/2026

Trang Dự án/Dataset thống kê ảnh Giàn và Bổ trợ theo cùng cấu trúc tổng số,
đã duyệt, chưa duyệt; ảnh Bổ trợ có thêm trạng thái đang dùng train, tạm tắt,
từ chối và số Có/Không của từng thuộc tính. Bỏ hai nút điều hướng lặp
`Xem ảnh bổ trợ train`/`Xem & duyệt ảnh bổ trợ`; thao tác tập trung tại
**GÁN NHÃN → Bổ trợ**.

Giao diện chỉ còn một trạng thái loại khỏi train là **Từ chối**; bỏ bộ lọc
**Đã lưu trữ** để không tạo hai khái niệm giống nhau. Các bản ghi cũ có
`archived: true` được ánh xạ vào **Từ chối**, vẫn giữ
ảnh/nhãn/lịch sử và có thể **Khôi phục** về bản nháp. Backend tiếp tục đọc trạng
thái cũ để tương thích dữ liệu, nhưng giao diện không tạo bản ghi lưu trữ mới.
Nút `×` của Bổ trợ là thao tác khác: xóa vĩnh viễn tệp ảnh thuộc project cùng
nhãn, nguồn và lịch sử sau xác nhận; không xóa ảnh Giàn gốc hoặc snapshot đã
export. Khối thống kê Bổ trợ dùng nền xanh và nằm sau toàn bộ thông tin ảnh Giàn.
`CaptureManifestV1` vẫn giữ contract cho
nhập/phục hồi một capture nhưng được ghi rõ là công cụ nâng cao; gói `.zip` là
luồng nhập HydroFlow thông thường. Tăng cỡ tiêu đề **DANH SÁCH ẢNH**; không đổi
ảnh, nhãn, split, model hoặc luật export/train.

Khi chọn nguồn **Bổ trợ**, số thứ tự/tổng số và kích thước ảnh ở vùng xem trước
lẫn tiêu đề cửa sổ đều được lấy từ chính danh sách Bổ trợ đang chọn. Không còn
trường hợp nội dung đã chuyển sang ảnh Bổ trợ nhưng tiêu đề vẫn giữ số lượng và
kích thước của ảnh Giàn. Chuyển qua lại giữa hai nguồn cũng khôi phục đúng vị trí
đang xem của từng nguồn.

## Hiện hành: sửa thuộc tính và độ phản hồi — 15/09/2026

Nhánh `fix/label-edit-responsiveness`, kế thừa `2c19af8`.
Giàn/Bổ trợ giữ ảnh vừa sửa khi ảnh ra khỏi bộ lọc; báo đã lưu và cho người
dùng chủ động đi tiếp. Khắc phục hành vi tự chuyển ảnh khiến thuộc tính
trông như quay lại giá trị cũ. Vùng số thứ tự riêng cho cả hai nguồn.
Lưu Giàn tránh serialize/deepcopy lặp, giữ hợp đồng JSON và ghi atomic;
lưu thất bại không giả báo thành công. Bổ trợ giữ canvas/zoom khi lưu,
không quét phân tập khi lưu nháp, không dựng thống kê hai trang đang ẩn.
Duyệt chuẩn bị dấu vân tay pixel nền, nhưng vẫn đọc/băm toàn bộ byte để
xác minh trước dùng cache; export giữ kiểm chứng nguồn đầy đủ độc lập.
Nút Tải lại từ tệp chỉ ở Bổ trợ để nhận thay đổi bên ngoài/xử lý conflict,
không phải bước bắt buộc sau sửa nhãn. Không đổi dữ liệu, model hoặc runtime.
[Quy tắc thao tác và kiểm tra](HYDRO_TRAINING_SUPPLEMENTS.md).

Kiểm chứng: toàn bộ 249/249 đạt (187,524 giây); sau rà soát điều hướng cuối,
16/16 UI Bổ trợ và 17/17 UI Hydro đạt, thêm kiểm Map thật khi mở Tổng quan.
Đo bản sao cô lập 1.297 ảnh (không profiler): sửa Giàn 0,24–0,26 giây,
sửa Bổ trợ 0,37–0,46 giây, duyệt sau chuẩn bị cache 0,97 giây. Duyệt đầu
còn 6,81 giây, mở Bổ trợ đầu 3,94 giây; không hứa mọi lượt tức thì.
1.428 tệp gốc giữ hash, không callback error trong benchmark. Cần mở lại
SmartLabel để nạp source; không dùng kiểm thử UI thay nghiệm thu chất lượng model.

## Mốc trước: Mặc định, duyệt và tốc độ chuyển nguồn ảnh — 14/09/2026

Nhánh `fix/supplement-defaults-and-switch-performance`, từ `d357be2`.
Bổ trợ khóa Duyệt & tiếp khi ảnh đã duyệt; phím tắt không ghi lịch sử trùng.
Điền thuộc tính còn thiếu theo mặc định cấu hình, giữ nhãn đã gán/chủ động
xóa. Nhãn mặc định mới cần duyệt trước train; không suy Héo từ ảnh gốc.
Chưa gán giá trị chỉ hiện khi nguồn đang xem thực sự thiếu giá trị tương ứng.
Giàn/Chai giữ nhãn cũ và bộ lọc đúng phạm vi ảnh/vật thể.

Sửa hỏi nhầm chưa lưu khi trở lại Bổ trợ, bỏ render lặp, giữ cache có giới
hạn cho thumbnail và kiểm preview. Duyệt/export vẫn kiểm nguồn/hash đầy đủ.
Median 3 vòng chuyển Bổ trợ 4,7427 → 0,6309 giây, Giàn 2,5022 → 0,3783 giây.
Lượt Bổ trợ đầu chưa có cache vẫn 4,412 giây. Mở lại Studio để nạp code mới.
Đã bổ sung Héo=Không theo cấu hình vào 107 ảnh còn thiếu, chuyển nháp/tắt
train để duyệt lại; giữ nguyên yellow_01 đã có đủ nhãn và 7 ảnh lưu trữ.
1.422 tệp ảnh/project/split/model/workspace ngoài tác vụ giữ hash; có backup
manifest và lịch sử từng hàng. Model/snapshot cũ không đổi, chưa chạy train.
Full suite 239/239 đạt (199,523 giây), gồm defaults không ghi đè nhãn, duyệt/
export, Hydro/Chai, nguồn ảnh/bộ lọc, cache giới hạn và tệp đổi/xóa.
Sau guard render cuối, 11/11 test UI đạt (38,944 giây).
[Quy tắc mặc định, thao tác và giới hạn](HYDRO_TRAINING_SUPPLEMENTS.md).

## Mốc trước: Một giao diện gán nhãn, hai nguồn ảnh — 14/09/2026

Nhánh `fix/supplement-shared-label-workspace`, kế thừa `8f6e4ac`.
Giàn/Bổ trợ dùng cùng widget danh sách, bộ lọc trạng thái/thuộc tính/giá trị,
canvas, zoom, thuộc tính, ghi chú và nút duyệt. Bỏ UI Bổ trợ riêng và bộ lọc
đợt/tuổi cây. Bộ lọc trạng thái Bổ trợ có Đã lưu trữ để xem lại 7 đối chứng.
Adapter riêng chỉ đọc/ghi sidecar; không đưa biến thể vào danh sách ảnh giàn.
Sửa nhãn tự lưu nháp; Duyệt & tiếp bật nhãn đủ điều kiện vào TRAIN. Giữ
atomic/lock/revision/source validation, nhãn partial và các guard tác vụ.

Hiện diện cũ từng lưu riêng tại presenceMeaning. Nay xác nhận dương có nhãn
tình trạng được đọc nhất quán thành nhãn hiện diện theo schema; không chép
Héo từ parent. Sửa một lần 107 hàng thiếu nhãn, giữ hàng người dùng đã gán và
7 hàng lưu trữ; 108 Có cây / 108 Lá vàng / 0 Héo vào preflight bổ trợ. Không
train, đổi model, sửa ảnh hoặc phân tập. Các mục dưới là lịch sử trước sửa.
Kiểm thử: full suite 227/227 đạt (204,851 giây); sau guard QA cuối, 8/8 test
UI đạt (53,716 giây), gồm cùng widget/geometry, phân trang, lưu và chuyển nguồn.
Mở lại SmartLabel để nạp code mới; không cưỡng bức đóng phiên đang làm việc.
[Thao tác, ý nghĩa dữ liệu và giới hạn](HYDRO_TRAINING_SUPPLEMENTS.md).

## Mốc trước: Ảnh bổ trợ gán nhiều thuộc tính và lưu trữ đối chứng — 14/09/2026

Nhánh `feat/supplement-multi-attribute-workspace`, kế thừa `410ccad`.
Chuyển đổi **Giàn / Bổ trợ** nằm cạnh phải tiêu đề **DANH SÁCH ẢNH** trong
ô trái, cùng header cho hai vùng. Bổ trợ dùng bố cục ba cột/chi tiết nhãn như
ảnh giàn; hiện tất cả thuộc tính trong schema, cho thêm Héo/Hiện diện, sửa
hoặc bỏ nhãn. Không chép nhãn từ ảnh gốc hoặc tự gán giá trị còn thiếu.

Lưu nháp giữ chỉnh sửa, tắt train; Duyệt bật nhãn đủ điều kiện vào TRAIN của
từng classifier. Mục chưa gán/chưa chắc/không áp dụng không train; không cây
đặt tình trạng không áp dụng, backend vẫn chặn mâu thuẫn. Có thể lưu trữ để
ẩn khỏi danh sách làm việc và train, xem/khôi phục bằng bộ lọc Đã lưu trữ.
Sidecar vẫn atomic/revision/lock/history, kiểm nguồn/hash/parent TRAIN khi duyệt.
Không đổi contract bundle/runtime hoặc luồng gán nhãn của bài vật thể.

Đã lưu trữ 7 đối chứng xanh cũ trong project Phân Loại Cải Ngọt, giữ tệp/lịch
sử. Hiện 108 ảnh làm việc/108 bật train, 7 lưu trữ. Đối chiếu 115 bổ trợ/1297 ảnh giàn
không có RGB trùng ở cùng kích thước; các đối chứng xanh được tạo gần nội dung
gốc, không gọi chúng là biến thể vàng mới. Từng byte ảnh giàn/bổ trợ, project,
split và 3 PT giữ nguyên; 108 bản ghi khác giữ nguyên. Chưa tự gán Héo hay train:
preflight hiện Lá vàng 108, Hiện diện 0, Héo 0, người dùng bổ sung nhãn sau khi xem.

225/225 test đầy đủ đạt 205,712s, gồm nhiều thuộc tính tới export, loại nhãn
chưa chắc, chỉ TRAIN, lưu nháp, lưu trữ/khôi phục, revision/atomic và Hydro/Chai.
Bố cục Tk 1180×720 và 1600×900 đạt; Computer Use capture vẫn lỗi
`SetIsBorderRequired`/`0x80004002`, chưa có ảnh chụp nghiệm thu thị giác.
Mở lại Studio để dùng source mới, Tải lại danh sách nếu phiên đã nạp code mới.
[Thao tác và contract](HYDRO_TRAINING_SUPPLEMENTS.md).

## Mốc trước: Tổng quan/Dataset, model Auto-Label và Windows operational — 14/09/2026

Nhánh `fix/studio-workflow-runtime-consistency`, kế thừa `4de4813`.
Tổng quan và Dataset dùng chung `ProjectOverview`; giữ handler cập nhật
scrollregion của CustomTkinter khi gắn handler đổi chiều rộng. Mở chi tiết
Train/Val/Test rồi cuộn chuột hoặc kéo thanh cuộn đều xem được nội dung cuối.
Dataset mở sẵn chi tiết, Tổng quan mặc định thu gọn. Đổi phân tập làm mới cả
hai nơi. Hydro giữ thống kê ảnh rọ/bổ trợ riêng; các bài vật thể dùng cùng thẻ
nhưng đếm class, nguồn và thuộc tính theo scope ảnh/vật thể, gồm cả bản nháp.

Auto-Label Hydro hiện checkpoint của từng thuộc tính trong `attribute_models`,
phân biệt có tệp PT/thiếu tệp/chưa train, tooltip đường dẫn; cập nhật ngay sau
đăng ký model từ train. Có tệp chưa chứng minh đúng nhãn, worker vẫn kiểm khi
chạy. Bài vật thể giữ chọn model đơn và các công cụ riêng.

Tạo gói tách Runtime đích khỏi Chế độ sử dụng: mặc định mới **Vận hành thật**
cho cả Windows/Nano, có thể chủ động chọn Shadow; nhớ chế độ đã xuất thành công.
Không tự sửa chế độ gói cũ. Vận hành thật vẫn yêu cầu QA `validated_holdout`;
giá trị này phản ánh QA dữ liệu, không bảo đảm độ chính xác model. Hộp cấu hình
giữ nút thao tác ở đáy khi thu nhỏ. Hydro đi kèm nhánh
`fix/windows-ai-operational-parity`: bỏ giới hạn Windows chỉ shadow ở validator
Camera/backend, giữ smoke/QA/tương thích/ghi active atomic và liên động hiện hữu.

Kiểm chứng: 216 test toàn bộ SmartLabel đạt; sau bổ sung làm mới phân tập và
footer hộp cấu hình, chạy lại 14/14 test UI liên quan đạt (25,854 giây). Hydro
Camera 123 đạt/1 bỏ qua; backend 569 đạt/7 bỏ qua. Kiểm xuyên repo bằng ZIP fixture
qua import/activate/suy luận ONNX Runtime thật đạt ở cả hai chế độ, 10 rọ mỗi
chế độ; QA và chuyển PT→ONNX dùng fixture, không chứng minh chất lượng model thật.
Project Cải Ngọt hiện có đủ ba tệp PT nhưng metadata vẫn `pilot_unvalidated`.
Không train, sửa dữ liệu, kích hoạt model hay khởi động lại dịch vụ đang chạy.
Mở lại Studio và nạp lại Camera/backend mới trước khi dùng operational Windows;
nghiệm thu model/camera thật và Nano vẫn là bước riêng.

## Mốc trước: Xem/duyệt ảnh bổ trợ trong SmartLabel và Tổng quan mới — 14/09/2026

Nhánh `feat/supplement-review-and-overview`, kế thừa `9235460`.
GÁN NHÃN có chuyển đổi **Danh sách ảnh / Ảnh bổ trợ** riêng cho Hydro.
Ảnh bổ trợ đọc sidecar hiện có, không nhập trùng ảnh gốc: thumbnail phân trang,
lọc trạng thái/đợt/tuổi/nhãn, preview phóng to/kéo, nguồn và trạng thái duyệt.
Cho sửa giá trị nhãn đã có rồi Duyệt & dùng train; Từ chối/Chờ duyệt tắt ảnh
khỏi export mới. Snapshot/model cũ giữ nguyên. Ghi sidecar atomic, kiểm revision,
giữ lịch sử duyệt và dùng lại validator export; không sửa project/split/ảnh.

Tổng quan Hydro thay văn bản dày bằng số chính và thẻ thuộc tính Có/Không,
chi tiết Train/Val/Test có thể mở, ảnh bổ trợ thống kê riêng. Chai vẫn dùng
thống kê hình học và không hiện chuyển đổi bổ trợ. Không đổi contract model.
Chi tiết thao tác và kiểm chứng tại [hướng dẫn](HYDRO_TRAINING_SUPPLEMENTS.md).

Kiểm Windows: 212/212 test toàn bộ đạt (164,867 giây); 13 test mới bao gồm
duyệt/từ chối/sửa nhãn tới export, xung đột revision, tệp lỗi, ghi atomic,
chuyển Hydro/Chai và bố cục Tk ở 1180×720, 1600×900. Kiểm đọc dữ liệu thật:
1.297 ảnh giàn, đúng 115 ảnh tổng hợp/115 đường dẫn riêng; Lá vàng nhận 115,
Hiện diện/Héo nhận 0; project/split/manifest/các PT giữ hash. Chưa train mới.
Công cụ chụp cửa sổ Windows báo `SetIsBorderRequired` / `0x80004002`, nên
chưa đối chiếu ảnh chụp UI; không coi kiểm bố cục Tk là nghiệm thu thị giác.
Sau bổ sung chặn phím tắt của canvas ảnh giàn khi chuyển sang ảnh bổ trợ,
chạy lại 13/13 test chức năng mới đạt (15,150 giây).

## Mốc trước: thêm 64 ảnh vàng từ ảnh gốc khác nhau — 14/09/2026

Nhánh `feat/hydro-yellow-mature-diversity-64`, kế thừa `82aac1d`.
Đã tạo/duyệt/cài 64 ảnh vàng, một biến thể mỗi ảnh gốc chưa dùng; 48 ảnh
tuổi 32–39 ngày, 10 ảnh 24–28 ngày, 6 ảnh 19–23 ngày. Bốn mức vàng mỗi mức
16 ảnh. Không dùng lại ảnh gốc hoặc cặp cây/ngày trước đó; 7 nhóm cây cùng
vụ TRAIN hiện có theo lựa chọn của chủ hệ thống, không nhận là 64 cây mới.
Giữ 51 bổ trợ cũ: tổng **115 (108 vàng/7 xanh)**, chỉ classifier Lá vàng.
Đã nằm trong project Phân Loại Cải Ngọt; lần Train mới tự đọc. Xem ảnh bổ trợ
train → XEM_ANH.html có lọc lô/cây/mức vàng, gốc cạnh biến thể, lô mới ở đầu.

14/14 test adapter đạt (0,167 giây), preflight cả ba classifier và cài lại
không nhân đôi. Export thật trong output tạm: TRAIN **110 Có/840 Không**,
VAL 0/238, TEST 0/125; toàn bộ TRAIN cũ và VAL/TEST giữ từng byte. Project/
split/ba PT giữ hash từ ngay trước cài. Không đổi runtime source, không train
hay phát hành model. VAL/TEST vẫn thiếu vàng thật độc lập, chưa đo chất lượng
hai phía. [Chi tiết và cách dùng](HYDRO_TRAINING_SUPPLEMENTS.md).

## Mốc trước: 40 ảnh vàng đa dạng từ ảnh giàn — 13/09/2026

Nhánh `feat/hydro-yellow-diversity-40`, kế thừa `fe6bc35`.
Đã tạo/duyệt/cài **40 ảnh vàng mới + 5 xanh đối chứng**, giữ 6 ảnh lô trước:
tổng 51 (44 vàng/7 xanh), chỉ vào TRAIN Lá vàng qua adapter hiện có.
Ảnh gốc 19–39 ngày, 10 ảnh từ 7 nhóm cây TRAIN trong cùng vụ; bốn mức vàng
mỗi mức 10 ảnh. Gallery `training_supplements/XEM_ANH.html` có lọc kích thước,
mức độ và ảnh gốc bên cạnh. Prompt/SHA/parent/review lưu đầy đủ ở sidecar.
Không sửa runtime source, không tạo capture hoặc class mới.

Project được chỉnh ngoài tác vụ trong thời gian tạo ảnh. Đã kiểm lại trạng
thái thực trước cài, bảo toàn chỉnh sửa: 1.297 ảnh; TRAIN vàng thật 2 Có/833
Không, VAL 0/238, TEST 0/125. Export mới TRAIN 46 Có/840 Không, 51 supplement;
VAL/TEST và TRAIN cũ giữ từng byte. Project/split/baPT giữ hash từ trước cài.
14/14 test adapter đạt (0,203 giây); preflight kiểm cả 3 classifier; cài lại
không nhân đôi. Chưa train hay triển khai model. VAL/TEST thiếu Có nên chưa
đủ đo chất lượng Lá vàng hai phía. [Chi tiết lô và cách dùng](HYDRO_TRAINING_SUPPLEMENTS.md).

## Mốc trước: Tổng quan thuộc tính và ảnh bổ trợ train — 13/09/2026

Nhánh `feat/hydro-attribute-overview-yellow-training`, kế thừa `427a734`.
Kiểm thử Windows: **199/199 đạt** (89,031 giây), gồm 15 ca mới cho thống kê,
UI và các ràng buộc dữ liệu bổ trợ; giữ các regression Hydro/Chai có sẵn.
Tổng quan Hydro thay số khung bằng số giá trị thuộc tính đã duyệt, phân bố
Có/Không/Chưa chắc/Không áp dụng và TRAIN/VAL/TEST đủ nhãn; mặc định chưa duyệt
không được tính thành nhãn đã duyệt. Chai nhựa vẫn đếm hình học/Class.
Ảnh bổ trợ có manifest nguồn riêng trong project, chỉ vào TRAIN của thuộc tính
được gán; kiểm hash, ảnh gốc TRAIN và trùng RGB, không tạo capture giả hoặc
đổi benchmark. Nút Xem ảnh bổ trợ train mở thư mục để kiểm ảnh/nguồn, nhật ký
train ghi số ảnh bổ trợ. [Thiết kế và cách dùng](HYDRO_TRAINING_SUPPLEMENTS.md).

Project Cải ngọt trên máy có thêm 4 ảnh vàng tổng hợp + 2 ảnh xanh đối chứng,
chỉ cho Lá vàng: TRAIN 84 Có/757 Không, VAL 21/219, TEST 0/126. Đã thử export
trên dữ liệu thật với output tạm: ảnh VAL/TEST và ảnh TRAIN cũ giữ nguyên từng
byte, project/split/PT không đổi. Chưa train model mới, chưa chứng minh cải
thiện; TEST thật vẫn thiếu Có. Đã tìm nguồn mạng/Roboflow và kiểm 8 thumbnail,
chưa nhập ảnh ngoài vì mẫu chưa xác minh cùng giống/bối cảnh. Dữ liệu nằm local,
không push ảnh/dataset. Không mở dịch vụ trả phí.


## Lọc nhãn, ngưỡng và công cụ model Hydro — 13/09/2026

Nhánh `feat/hydro-review-and-model-tools`, kế thừa `596eb23`:

Kiểm thử Windows: **184/184 đạt**, gồm 23 test mới (15 quy tắc/model và
8 Tk/worker). Thử inference thật trên checkpoint hiện có; hash project và
ba PT giữ nguyên ở lần kiểm cuối. Test/UI dùng workspace tạm; không gán nhãn
thử vào project người dùng. Mở lại SmartLabel để nạp các công cụ mới.

- Danh sách ảnh có lọc Class/thuộc tính và giá trị, kết hợp trạng thái duyệt;
  hỗ trợ nhãn toàn ảnh Hydro và nhãn/thuộc tính trên vật của Chai nhựa.
  Trước/sau chỉ đi trong tập lọc, lưu lựa chọn theo project, tự cập nhật khi
  sửa nhãn. Mở ảnh từ kết quả QA chủ động bỏ bộ lọc nếu cần đến đúng ảnh.
- Hộp xuất Hydro điền sẵn low/high 0.30/0.70, ghi rõ là khởi đầu chưa hiệu
  chỉnh. Gợi ý từ Val được dùng khi đủ điều kiện và SHA checkpoint/ý nghĩa
  nhãn còn khớp. Ngưỡng người dùng đã xác nhận khi xuất được gắn SHA của PT
  thực sự dùng; giữ cho cùng checkpoint và bỏ khi model đổi. Ngưỡng legacy
  thiếu SHA được giữ với nhắc kiểm tra. Dataset/source/profile có sẵn bị
  khóa, chỉ trường thiếu mới nhập; runtime đích vẫn được chọn.
- Hydro Auto-Label dùng classifier từng thuộc tính trên ảnh slot, không
  dùng detector hoặc tạo thêm Class. Đọc xác suất theo mã/ý nghĩa nhãn trong
  model, xử lý presence trước condition; kết quả là bản nháp, không tự duyệt.
  Giữ ảnh reviewed/rejected, nhãn tay và chỉnh sửa đến trong lúc worker chạy.
  Ảnh nhập mới lưu nguồn giá trị mặc định; thao tác tay lưu dấu riêng. Nhãn
  cũ Có/Không không có nguồn gốc được giữ nguyên, không đoán là mặc định.
  Placeholder Chưa chắc/Không áp dụng ở ảnh unlabeled cũ có thể được gợi ý.
- Đánh giá Hydro có chọn thuộc tính; tự đọc dataset gốc của checkpoint,
  kiểm đúng project/thuộc tính/scope và tập Val/Test độc lập. Tập thiếu một
  phía hoặc trùng nội dung Train bị từ chối. Báo Accuracy, Precision, Recall,
  F1, TP/TN/FP/FN và lưu từng score ảnh trong báo cáo. Val có thể đề xuất
  ngưỡng; Test chỉ đo kết quả, không chọn ngưỡng. Train All/Final thiếu tập
  độc lập tương ứng phải chuẩn bị benchmark riêng; không đánh giá trên bản
  sao train hoặc tự thay dataset.
- `hydro_model_tools.py` và `image_filters.py` chứa quy tắc riêng; GUI chỉ
  điều phối. Luồng generic detection/SEG/OBB/pose, SAM và RKNN của Chai nhựa
  vẫn riêng. Khóa job dùng cơ chế ownership hiện có; snapshot controls trên
  Tk trước khi chạy, không đọc Tk từ worker Auto-Label. Không đổi contract
  bundle, không triển khai model lên Hydro/Nano.

Quy tắc gợi ý Val: ít nhất 20 ảnh mỗi phía, tìm ngưỡng giữa 0.10–0.90 tăng
0.01 để tối đa balanced accuracy, hòa thì gần 0.50; cần đạt ít nhất 0.65,
low/high là ngưỡng giữa ±0.10. Đây là heuristic minh bạch, không hiệu chuẩn
xác suất hoặc bảo đảm chất lượng; vẫn cần Test/hiện trường. Không dùng ngưỡng
đơn 0.50 như quyết định Có/Không bắt buộc trong vận hành Hydro.

Đã kiểm bằng classifier thật trên dữ liệu gốc, báo cáo ở vùng tạm: có cây
139 ảnh Test (126 Có/13 Không) đều đúng ở ngưỡng 0.50; Héo 126 ảnh, TP1/TN118/
FP0/FN7 (Recall 12.5%, F1 0.222 dù Accuracy 94.4%); Lá vàng thiếu ảnh Có ở
Test. Không suy kết quả tập nhỏ thành độ chính xác thực địa. Auto-Label được
thử trên bản sao hai ảnh slot trong bộ nhớ, không ghi nhãn thử vào project.

Nguồn thiết kế tra cứu 13/09/2026: [Ultralytics classification probabilities](https://docs.ultralytics.com/modes/predict/)
và [scikit-learn threshold tuning](https://scikit-learn.org/stable/modules/classification_threshold.html).
Chỉ dùng thư viện hiện có, không nâng framework/cài dịch vụ trả phí.

## Một nút tạo gói Hydro — 13/09/2026

Thay hai nút ONNX/Bundle bằng **TẠO GÓI MODEL HYDRO**. Sau xác nhận cấu hình
và chọn nơi lưu, job nền tự kiểm đủ PT/QA, xuất ONNX từ từng PT rồi đóng ZIP
theo contract hiện có. Nhật ký và dòng trạng thái hiển thị ba bước cùng số
model đang chuyển. ONNX vẫn có trong thư mục models của gói để kiểm tra riêng.
Không tái sử dụng đường dẫn ONNX cũ nên không vô tình đóng gói model cũ sau train.

Job chụp metadata dự án và cấu hình khi bắt đầu, đọc phân tập với persist=False;
không sửa split/project trong worker. PT được sao vào vùng tạm trước export để
Ultralytics không ghi ONNX cạnh checkpoint gốc. Kiểm tra và đóng gói trong vùng
tạm; chỉ khi thành công mới lưu folder/ZIP và cập nhật đường dẫn dự án trên Tk.
Đích lưu độc quyền, lỗi lưu cuối dọn riêng phần do job tạo, giữ gói có sẵn.

Nút Dừng tạo gói chờ bước hiện tại kết thúc rồi hủy; không cưỡng bức dừng thread
giữa lúc ghi. Giữ ownership đến completion, chặn đổi/tạo dự án và Train trùng.
Đóng app khi còn xuất yêu cầu dừng và chờ. Lỗi/hủy nhả nút; lỗi lưu metadata dự
án vẫn báo rõ ZIP đã tạo ở đâu. Chức năng RKNN của dự án DeltaX giữ nguyên.

Không tự đoán ngưỡng, không nới QA/Windows shadow/contract. Source export ONNX
riêng vẫn có cho công cụ kỹ thuật; UI không yêu cầu người dùng thực hiện bước
trung gian. Hướng dẫn hai nút bên dưới thuộc mốc trước và đã được thay bằng
quy trình một nút trong HUONG_DAN_SU_DUNG.md.

Kiểm Windows:161/161 test đạt, gồm19 test mới cho pipeline và Tk/worker.
Đã tạo bundle V3 bằng ONNX tổng hợp qua writer thật; kiểm lỗi/hủy/QA/trùng
tên/publish rollback, snapshot, ownership và lỗi lưu metadata. Đã xuất ONNX
thực từ bản sao một checkpoint người dùng trên worker, onnx.checker đạt,
opset12/thứ tự nhãn đúng và hash PT gốc giữ nguyên; tệp thử ở vùng tạm đã dọn.
Tk tại1180×720 và1500×900: một nút chính và nút Dừng nằm trong hàng, đúng
tiêu đề Hydro. Không train mới, không kích hoạt model hoặc nghiệm thu Nano.

Quan sát 09:41 ngày 13/09: project_eb99e9722cff đã có đủ checkpoint của
plant_presence, yellow_leaf và wilt; không còn worker train. Không cần train
lại Héo theo ghi chú cũ bên dưới. Mở lại SmartLabel để nạp bản hoàn chỉnh;
việc đủ checkpoint không thay thế kiểm tra QA và đánh giá độ chính xác.

## Worker Windows và thứ tự xuất Hydro — 13/09/2026

Sửa regression của4afe44f khi SmartLabel chưa mở lại: parent cũ chưa đặt
PYTHONIOENCODING, worker mới in tiếng Việt trước import Ultralytics trên
stdout cp1252 nên UnicodeEncodeError/mã1 trước khi học. Worker nay tự đặt
stdout và stderr UTF-8 trước mọi thông báo, kể cả lỗi thiếu đối số; không
phụ thuộc vào biến môi trường của launcher. Kiểm thêm subprocess thực dùng
cp1252 và YOLO giả, không train dữ liệu thật. Nhánh sửa
`fix/train-worker-windows-encoding`.
Full suite Windows đạt142/142;15 test train/GUI tập trung đạt. Không khởi
động train thật, không ghi đè hai model đã hoàn thành hay năm tệp dirty cũ.

Tại mốc kiểm lỗi lúc 02:15, project_eb99e9722cff đã lưu model plant_presence
và yellow_leaf; wilt chưa có run. Đây là quan sát lịch sử, đã được cập nhật
ở phần trên. Luồng xuất hai nút ở mốc này đã được thay bằng một nút. ZIP PT
tự tạo sau batch chỉ là gói quản lý checkpoint, không thay ZIP Hydro.

## Nhật ký train/xuất model — 13/09/2026

Sửa lỗi sau mở/chuyển project: `_replace_text` đặt Textbox về disabled nhưng
`_append_log` trước đây insert trực tiếp, khiến Tk bỏ qua mọi dòng. Hàm ghi
nay mở khóa trong lúc ghi rồi trả về chỉ đọc; các lượt Train/Auto-Label xóa
nhật ký qua cùng hàm thay nội dung. Áp dụng cả train, xuất RKNN và Auto-Label.

Nút Train báo nhận yêu cầu trước khi kiểm tra model/xuất dataset, giữ nguyên
log chuẩn bị và ghi lỗi/hủy. Worker báo kiểm tra thiết bị, PID và nạp thư viện;
stdout không đệm, UTF-8 để đọc log tiếng Việt trong lúc chạy. Nút Train khóa
đến completion; dùng trạng thái sở hữu job hiện có để chặn chạy trùng cả khi
thread vừa kết thúc và giữa hai classifier. Lỗi tạo thread đi qua completion
bình thường để mở khóa. Không đổi dataset, nhãn, schema, tham số học/QA gate.

Full suite Windows `python -m unittest discover -s tests -v` đạt140/140,
gồm13 test mới bằng Tk thật trong workspace tạm và subprocess tổng hợp,
không khởi động train dữ liệu người dùng. Năm tệp workspace đã dirty giữ
nguyên SHA256. Nhánh sửa `fix/training-log-feedback`.
Lượt CPU do người dùng mở trước bản sửa được
giữ nguyên; muốn áp dụng phần UI phải mở lại SmartLabel sau khi lượt đó kết
thúc. Log phiên cũ không được hồi phục tự động. Chuẩn bị model/dataset vẫn
đồng bộ trên giao diện; chuyển công việc này ra nền là hạng mục riêng.

## Chỉnh tên giá trị Hydro — 12/09/2026

Mẫu Hydro cho sửa `displayName` từng giá trị trực tiếp, bên cạnh ý nghĩa cố định
được sinh từ role/meaning/tên tình trạng. ID, meaning, requires và số lớp vẫn khóa;
không thay LabelSchemaV1/bundle V3. Chỉ thay tên không phải train lại. Lưu cập
nhật fingerprint schema nhưng giữ ID/nhãn ảnh/review/default/model/output order.
Hủy và tên không hợp lệ không sửa project; tên trống, quá100 ký tự, ký tự điều
khiển và trùng trong nhóm bị chặn. Tên gợi ý tự theo rename nhóm cùng khái niệm,
còn tên tùy chỉnh giữ nguyên.

Mặc định/Gán nhãn/QA cùng dùng tên đã lưu kèm tiền tố nghĩa, ví dụ
`Có · Phát hiện vàng lá`; tên trùng đúng gợi ý không lặp lại. Tên cũ khác nghĩa
không được dùng thay meaning: vẫn hiện tiền tố cố định, mở project không migrate
schema/nhãn. Menu giữ chiều rộng, tooltip cho xem tên dài. Generic giữ luồng cũ.
Các bundle đã xuất và model đang chạy trên Hydro không bị đổi; bundle mới mang
tên mới qua trường displayName sẵn có. Đây là thay đổi SmartLabel, không deploy Nano.

Kiểm Windows: toàn suite127/127 đạt, gồm14 test dialog và luồng app thật
save → gán nhãn/QA → chuyển project/mở lại. Bốn ảnh dialog ở900/760 px và
tên dài đã kiểm. Fixture xuất ONNX hằng số/V3 sau sửa tên được `validate_bundle`
của source Hydro hiện tại chấp nhận, output positive-first và SHA model giữ
nguyên. Đây là kiểm contract bằng model tổng hợp, không train/đo độ chính xác
hoặc kích hoạt model trên thiết bị. Năm tệp workspace dirty giữ nguyên SHA256.

## Mặc định thuộc tính và cấu hình Hydro — 12/09/2026

Khôi phục chọn Mặc định trong quản lý thuộc tính Hydro; giá trị lưu bằng ID,
hiển thị theo meaning và tên tình trạng. Lưu schema không xóa mặc định nữa;
đổi tên cùng tình trạng giữ lựa chọn và mã, hủy không đổi project/nhãn.
Bắt buộc, Mục đích và Phạm vi được hiện lại ở trạng thái cố định: required,
classification, image. Project generic giữ các điều khiển chỉnh được.

Mặc định toàn ảnh áp dụng lúc tạo ảnh nhập mới qua manifest/ZIP hoặc ProjectStore
(ảnh/thư mục/frame video). Không sửa ảnh cũ/nhập trùng, không tự duyệt; xuất train
toàn ảnh vẫn yêu cầu reviewed. Hydro áp dụng dependency có cây theo meaning;
chưa xác nhận có cây thì các tình trạng Không áp dụng. Không đặt mặc định giữ
khởi tạo chưa kết luận như trước. Không sửa schema/bundle contract hoặc model.

Tên tình trạng tùy chỉnh đã được hỗ trợ bởi labelSchema V1 / bundle V3, gồm
model ID, displayName, value meanings và actual output order. Tình trạng độc lập
nhị phân cho phép nhiều dấu hiệu đồng thời; không suy ra khỏe từ một negative.
[Hướng dẫn các trường và cách dùng mặc định](HUONG_DAN_SU_DUNG.md#3-tạo-dự-án).

Kiểm Windows: `python -m unittest discover -s tests -v` đạt122/122, gồm6 test
mới cho mặc định/lưu/hủy/custom meaning/import/review gate. Render dialog Tk
thực trên project tạm ở900 và760 px: các trường hiện và vừa chiều rộng. Năm
tệp workspace đã dirty trước tác vụ giữ nguyên SHA256; không train model thật.

## Ảnh thật và crop context cũ — 12/09/2026

Đã nhập ZIP do dialog/API Hydro xuất từ snapshot ảnh thật qua callback Tk và
worker SmartLabel: ba capture ngày21/08,09/09,10/09,30 slot +9 parent images.
Hash/kích thước/lineage/ID/vụ/thời gian khớp; re-import/cancel, repair thiếu một
ảnh có xác nhận, ZIP hỏng, file mất và lỗi lưu giữa capture/retry được kiểm.
Workspace nghiệm thu riêng; không sửa project nguồn hoặc lịch sử xuất DB live.

Phát hiện manifest21/08 không có cropContext dù index có cropCycle. Importer nay
bổ sung các ngày/tuổi cây thiếu từ đúng cropCycle/cropCode đã kiểm, ghi nguồn
`dataset_crop_cycle` và datasetExportId; original dates vẫn null. Manifest đã có
ngày không bị registry ghi đè; audited correction giữ contract hiện có. Re-import
có thể bổ sung metadata còn thiếu, giữ ID/nhãn/review; xung đột ngày đã lưu bị chặn.
Không có lifecycle đáng tin trong gói thì giữ trạng thái thiếu, không đoán ngày.

Full116/116 đạt, thêm5 regression; sau siết provenance cuối đã chạy lại28 test
importer. `tools/hydro_real_dataset_acceptance.py` kiểm ZIP thật trong workspace
mới, không gán nhãn cây hay train. Toàn bộ30 ảnh thật chưa có nhãn được duyệt,
QA/bundle readiness và export train bị chặn đúng. Đã nghiệm thu vận chuyển/import;
dataset train/bundle với nhãn thật, topology V2 thực địa và model accuracy còn mở.
Hydro có hướng dẫn phối hợp tại `docs/REAL_DATASET_ACCEPTANCE.md` trong repo Hydro.

## Ý nghĩa nhãn Hydro — 12/09/2026

Nhánh `fix/hydro-label-semantics-ui` sửa luồng Quản lý nhãn và các lựa chọn gán
nhãn/QA Hydro. Có/Không/Chưa chắc/Không áp dụng được hiển thị từ `meaning` và tên
tình trạng, không lấy nguyên tên nhãn tùy ý làm ý nghĩa. UI không còn ô sửa tự do
từng nhãn Hydro. Mã và tên schema cũ được xem trong phần chi tiết chỉ đọc; mở
project không sửa metadata hoặc nhãn ảnh. Generic annotation/classification giữ
luồng sửa giá trị cũ. LabelSchemaV1 và bundle V3/output order không thay contract.

Thêm tình trạng tạo ID/nhãn mới, không kế thừa model của tình trạng khác. Đổi tên
cùng tình trạng là thao tác riêng có xác nhận giữ cùng ý nghĩa; hủy không đổi
project. Callback lưu cũng chặn đổi title hoặc nhãn ngoài luồng này. Không dùng
từ khóa/AI để đoán rằng hai tên chỉ khác chính tả; người kỹ thuật xác nhận cùng
khái niệm. Schema tùy chỉnh cũ giữ ID/meaning/order và tên đã lưu, kể cả khi UI
trình bày tên rõ nghĩa hơn. Tên hiển thị thay thế không phải gán nhãn lại dữ liệu.

Đã tái hiện ba regression lỗi trước sửa; sau sửa toàn suite Windows đạt 111/111,
gồm bảy test UI mới, import/QA/V3, model mapping và bảo vệ chuyển project. Test
dùng project tạm; không train model bệnh, không nghiệm thu ảnh thật qua toàn
luồng. Phần QA đã sửa split train tiếp tục được giữ. Còn mở: DATA-01, model
evaluation gate và export ONNX/QA dài trên worker, theo bộ nhớ AI_KL.

## Đối chiếu source ngày 11 tháng 9 năm 2026

Kiểm tra local từ HEAD `e12e1a6`: baseline 103/103 test đạt; sau sửa QA và thêm
regression là 104/104 đạt. Năm file project/split đã có thay đổi trước lượt được
đối chiếu SHA256 và giữ nguyên. Bản sửa QA được giao trên nhánh riêng
`fix/hydro-training-split-counts`; không train dữ liệu thật hoặc cài SmartLabel lên Nano.

Hydro đã thử được Python riêng/TensorRT/PyCUDA và model tổng hợp trên Nano; lỗi
CUDA context khi gọi từ nhiều luồng đã được sửa trong source Hydro. Kết quả này
không thay thế đánh giá model bệnh, nghiệm thu Camera hoặc cơ chế phát hành model.

Đã sửa `hydro_dataset_qa`: reviewedTrainable/workflowTrainable chỉ đếm nhãn reviewed
ở split=train. Validation/test/chưa chia không được bù lớp thiếu trong train.
Regression tái hiện trường hợp train một lớp nhưng validation có đủ hai lớp,
trước sửa báo sẵn sàng sai, sau sửa báo class_pair_incomplete.

Cần đọc đúng `validated_holdout`: hiện QA xác định từ vụ test độc lập và không có
lỗi dữ liệu, chưa chạy/đối chiếu số đo chất lượng của model. Export dialog hiện cố
định shadow; Python bundle API có operational nhưng chưa bắt buộc evaluation record
gắn đúng hash model/dataset/split/ngưỡng. Hoàn thiện hồ sơ/gate này trước phát hành
model operational. Khách hàng không phải nhập báo cáo QA về Hydro.

Các việc kỹ thuật còn cần: nghiệm thu ZIP ảnh thật, nhãn/holdout model bệnh,
chuyển ONNX export/QA dài khỏi callback UI bằng job có tiến độ và ownership project,
kiểm chứng Nano và quy trình tương thích profile giữa các hộ. Dịch vụ nhận ảnh từ
xa, chữ ký nhà phát hành/OTA chưa có. Workspace legacy vẫn được Git theo dõi;
không tự xóa/untrack hoặc ghi đè để “làm sạch”.

Báo cáo local: `D:/DeltaX/AI_KL/audits/2026-09-11/REPORT.md`.
Các mục 10/09 dưới đây là mốc lịch sử, không phải kiểm tra live hôm nay.

## Mốc triển khai đã ghi nhận ngày 10 tháng 9

Baseline chức năng SmartLabel `0533740`, Hydro `2f3d2171`. Đợt đồng bộ tài liệu
không sửa workspace, nhãn, model hay chương trình. Các số test là bằng chứng theo đợt,
không phải kiểm tra thời gian thực máy người dùng.

## Đã có

- Hydro xuất qua preview chọn một vụ/ngày/từng capture, tổng số slot và thumbnail.
  Ảnh đã đóng gói cần chủ động chọn lại; không phải tất cả ảnh đều chưa từng nhập.
- SmartLabel import V1/V2, nhận topology nhiều ống/rọ; checksum/lineage phải hợp lệ.
- Slot thiếu do xóa khỏi project được bổ sung sau xác nhận, giữ nhãn/ID/review cũ.
  Lỗi giữa nhiều capture giữ phần đã hoàn tất, retry bỏ qua phần trùng; không tự ghi
  đè file còn record nhưng mất/hỏng bên ngoài.
- Classifier toàn ảnh Hydro không cần class định vị; luồng classification crop và
  detection cũ vẫn còn. Xóa project có thể khôi phục, không tự xóa dataset nguồn.
- Bundle V3: một presence + 1–15 condition nhị phân; tên Việt/ý nghĩa/output order/
  threshold theo schema. Giữ V1/V2, không tự migrate nhãn cũ.

## Chưa hoàn tất

1. Nghiệm thu xuất ZIP ảnh thật qua UI Hydro → project kiểm thử riêng, số lượng/
   ngày/vụ/rọ và hành vi nhập lại. Code/unit/pipeline tổng hợp đã được kiểm thử.
2. QA/review do công ty quản lý trong SmartLabel; không yêu cầu khách hàng nhập báo cáo
   về Hydro. Duyệt chất lượng ảnh ở Hydro không đồng nghĩa đã gán/duyệt nhãn SmartLabel.
3. Nhãn bệnh thật, train/đánh giá và holdout vụ độc lập. Một vụ chỉ pilot shadow
   khi đủ QA; hai vụ không tự bảo đảm model đạt. Không bịa negative hoặc dùng
   uncertain/not_applicable như nhãn Không.
4. Jetson/ArUco/Drive còn hoãn; Windows vẫn giữ giới hạn shadow hiện có.

## Vai trò công ty và người sử dụng · quyết định thay thế 10/09

SmartLabel tại công ty quản lý nhãn, QA, phân bố lớp, split chống leakage, holdout vụ
độc lập và train/export. Báo cáo QA chi tiết giữ ở công ty. Không bắt khách hàng tự
đánh nhãn, thu hai mùa hoặc nhập báo cáo vào Hydro để dùng model đã phát hành.

Bundle hiện có đã mang datasetVersion/sourceCommit, schema, preprocessing, threshold,
validationStatus, runtime và các profile tương thích. Hydro đọc tự động và vẫn kiểm
tra checksum/tương thích/smoke-test/rollback. Không thêm màn hình báo cáo trùng chức năng
trong SmartLabel và không đổi project/nhãn cũ. Windows vẫn shadow; gói operational
vẫn cần đánh giá vụ độc lập tại bên tạo model, không phải hai vụ tại từng nhà khách hàng.

Khách hàng có thể đóng góp ảnh qua gói xuất, nhưng đây là lựa chọn riêng. Hiện chưa
có dịch vụ nhận ảnh từ xa, chữ ký nhà phát hành hay OTA; chỉ nhận model từ nguồn tin cậy.
Checksum không chứng minh danh tính nhà cung cấp hoặc độ chính xác của model.

## Bảo toàn và kiểm thử

Local SmartLabel 102/103 pass, 1 SAM skip; target 101/103 pass, 2 layout skip qua SSH
trong đợt nhập lại. 69/69 JSON metadata/config đối chiếu giữ nguyên. Pipeline V3
tổng hợp 6 capture → 60 slot → train 4 classifier → ONNX → Hydro đạt, không chứng
minh độ chính xác trên bệnh cây. Backup Protected của Hydro đã gồm workspace/model
được quản lý, có restore thử cô lập và replica một lần sang máy hiện tại.

Không bắt người dùng tạo lại project cũ, không rewrite Git history hoặc đưa ảnh/model/
credential lên GitHub. Chỉ push từ máy đích; xác minh target và công việc chưa lưu
trước cập nhật ứng dụng, không tự đóng SmartLabel.

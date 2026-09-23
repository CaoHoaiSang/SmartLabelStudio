# Thu thập lô TEST riêng — Windows pilot, 23/09/2026

## Phạm vi và cách dùng

Tính năng nằm trong **SmartLabel → DATASET → THU THẬP TEST · CAMERA RIÊNG**.
Hydro không có thêm màn hình kỹ thuật; không tạo vụ giả, sửa calibration, gọi
capture vận hành, điều khiển bơm hoặc chạy model khi thu ảnh TEST.

1. Lưu công việc và mở lại SmartLabel để nạp source mới. Chọn project Hydro
   chứa các classifier cần kiểm định. Tạo lô **16 cây thùng xốp**, nhập ngày
   gieo thật, giữ **Cùng đợt gieo với cây phát triển model** nếu đúng thực tế.
   Chỉ xác nhận dành riêng TEST nếu toàn bộ cây chưa được dùng phát triển model.
2. **Nạp camera + ROI từ Hydro**: chọn thư mục `ai_camera` chứa thư viện
   `hydro_ai_camera`, rồi camera profile và geometry profile đang dùng trên giàn.
   Với Hydro V2 chọn `site_profile.v1.json` chứa geometry đang hoạt động, không
   dùng geometry cũ bên ngoài. Cặp profile có khai báo liên kết phải khớp ID.
   Công cụ giữ bản sao cấu hình, kiểm profile locked/DirectShow/1920×1080/10 ROI.
   Không ghi vào cấu hình gốc hoặc tự chọn camera khác khi kiểm tra thất bại.
3. Trước khi đưa cây TEST lên giàn, kỹ thuật viên dừng **riêng dịch vụ Camera**
   và cơ chế tự khởi động lại dịch vụ đó bằng quy trình vận hành hiện hữu.
   Không dừng backend, MQTT hay bơm. Công cụ không tự dừng/khởi động dịch vụ.
   Xác nhận đã nhường camera và bố trí đúng cây trong hộp thoại.
4. Lượt 1: đặt 10 cây TEST, chọn **Lượt 1: 10 cây**, **Chụp để xem trước**,
   kiểm ảnh và ROI rồi **Lưu đủ 10 ROI đã xem**.
5. Lượt 2: thay bằng 6 cây TEST còn lại, để **4 rọ trống**, chọn mẫu
   **Lượt 2: 6 cây + 4 trống**. Mẫu mặc định đánh dấu 4 ROI cuối danh sách;
   phải chỉnh đúng các vị trí trống thực tế trước khi lưu. Cả 10 ảnh rọ được giữ,
   không chỉ lưu 6 ảnh có cây. Hai lượt tạo 20 ảnh rọ và 2 ảnh toàn cảnh nguồn.
6. Trả đúng 10 cây vận hành về giàn trước khi bật lại dịch vụ Camera Hydro.
   Không để lịch chụp vận hành ghi nhận các cây TEST như cây của vụ đang trồng.
7. **Gán nhãn TEST** mở lại canvas/form sẵn có trong **GÁN NHÃN → TEST**.
   Chọn nhãn dựa trên ảnh, duyệt hoặc từ chối từng ảnh. Ô `Trống` lúc chụp chỉ
   ghi bố trí, không tự biến thành nhãn. Khi xác nhận không có cây, các dấu hiệu
   lá vàng/héo phải là **Không áp dụng**, không phải mẫu âm của bệnh.
8. Quay lại bộ thu → chọn lô → **Tạo & nhập bộ TEST đã duyệt**. Chọn thư mục mới
   và xác nhận chưa dùng lô này để train/chọn model/ngưỡng, kể cả checkpoint cha.
   Toàn bộ ảnh phải được duyệt hoặc từ chối; không âm thầm bỏ qua ảnh chưa duyệt.
9. **DATASET → Bộ TEST ngoài**: đánh giá checkpoint/ngưỡng đã cố định, đọc chỉ số
   rồi chủ động duyệt bằng chứng. Tạo gói operational vẫn qua cổng kiểm định
   hiện hữu; thu đủ ảnh không đồng nghĩa model đạt chất lượng hoặc được phát hành.

Ngày sau có thể đổi vị trí các cây TEST. Mã cây tùy chọn giúp truy vết, không bắt
nhập cho mọi cây. Không đặt cây đã dùng train vào lô này. Vị trí ROI chỉ chỉ ra
nơi cắt ảnh trong lần chụp, **không được coi là danh tính cây suốt nhiều ngày**.

## Độc lập, mẫu trống và ý nghĩa kết quả

Đây là **lô cây giữ riêng cùng đợt gieo**, không phải một mùa vụ độc lập theo
thời gian. Nguồn luôn ghi `heldout_capture` + lot/capture/slot, không tạo
`cropCycleId`, `siteId`, `deviceId` giả để vượt kiểm tra nguồn Hydro cũ.

Kết quả tính **theo ảnh**, số cây là khai báo, không xác minh đủ 16 cây khác
nhau chỉ bằng 16 ảnh. Chụp cùng cây nhiều ngày không tạo thêm cá thể độc lập;
không suy độ tổng quát qua vụ/điều kiện khác từ bộ này. Báo cáo và bằng chứng
phát hành giữ phạm vi đó (`reserved_cohort`, `plantIdentityVerified:false`).

4 rọ trống bổ sung mẫu âm cho **Cây hiện diện**. Chúng không thay mẫu cây không
héo/không vàng, và 16 cây khỏe chưa cung cấp mẫu dương héo/vàng. Đánh giá vẫn
chặn classifier thiếu một phía Có/Không. Mẫu ít không đủ để kết luận chất lượng
rộng; giữ thông tin số mẫu, bỏ sót, báo nhầm, chưa chắc chắn và độ phủ.

Sau khi dùng kết quả TEST để điều chỉnh model/ngưỡng hoặc chọn checkpoint,
không gọi lại bộ đó là kiểm định độc lập cho lựa chọn mới. Cần bộ chưa khai thác.
Kiểm hash/pixel không phát hiện mọi ảnh gần trùng hoặc chứng minh lịch sử cây;
vẫn cần xác nhận nguồn thực tế và lịch sử các checkpoint cha.

## Lưu trữ và độ bền

- Sidecar `workspace/projects/<id>/heldout/heldout_collection.json`, ảnh dưới
  `captures/<captureId>/`. Không thêm vào `project.images` hoặc split_assignment.
- `HydroHeldoutFrameV1`: khung nguồn, đủ 10 crop, profile snapshot, controls/quality,
  checksum/pixel, rect và thời gian. Không kết quả AI/nhãn tự động. Crop phải
  khớp từng pixel với vùng trên ảnh cha. Ảnh xem trước chưa lưu là tạm thời.
- `HydroHeldoutBenchmarkV1`: hợp đồng riêng của bộ đã duyệt. Validator cũ
  `HydroBenchmarkV1` vẫn đòi nguồn Hydro đầy đủ, không bị nới lỏng. Bản freeze chỉ
  chứa ảnh rọ/nhãn/metadata; ảnh toàn cảnh nguồn ở kho thu, không vào train/test.
- Khóa ghi OS liên tiến trình + revision chống ghi đè, ghi JSON tạm/fsync/replace,
  copy kiểm hash trước khi công bố. Lặp lưu cùng capture không nhân bản; thay
  lựa chọn/bytes phải báo lỗi. Bản freeze không đổi khi nhãn kho nguồn thay đổi.
- Pilot tối đa 5000 ảnh rọ, 2 GiB ảnh nguồn/crop mỗi project, chừa 100 MiB ổ đĩa;
  bản kê tối đa 16 MiB. Không tự xóa ảnh cũ để nhường chỗ. Export/import cần thêm
  dung lượng cho bản copy; lỗi giữ nguyên kho nguồn. Không có dịch vụ trả phí.
- Nếu mất điện/lỗi ghi bản kê sau khi thư mục ảnh đã được công bố, giữ thư mục
  lưu dở để phục hồi và chặn lưu thêm. Cần kỹ thuật viên kiểm ảnh/bản kê trước
  phục hồi; chưa có nút tự phục hồi. Không tự xóa hoặc tuyên bố lưu thành công.
- Marker TEST ngăn import/train thông thường, kể cả thư mục con. Không thể
  chống người cố ý chép ra ngoài rồi xóa nguồn gốc; kiểm trùng checkpoint vẫn giữ.
- Hủy job không công bố benchmark dở. Nếu đã xuất xong nhưng hủy/lỗi ở bước nhập,
  thư mục xuất còn nguyên và có thể nhập lại qua **Bộ TEST ngoài**.

## Camera và an toàn

Tái sử dụng thư viện thu ảnh, ROI, quality và kiểm controls của Hydro đã cài;
không xây pipeline suy luận thứ hai. Worker riêng giới hạn 45 giây, hủy chỉ kết
thúc worker của chính tác vụ. Không khởi tạo runtime điều phối vận hành Hydro.
Các bộ thu SmartLabel dùng khóa liên tiến trình để không đồng thời mở camera.

Kiểm cổng loopback 8091 và tiến trình Camera Python trước/sau khi chụp; lỗi kiểm
tra thì không nhận ảnh. Các kiểm tra này **không thay thế việc tắt supervisor**
hoặc khóa camera của hệ điều hành, không bảo đảm chặn một ứng dụng camera khác
hay dịch vụ được khởi động lại đúng lúc. Cần bàn giao camera thủ công cho pilot.
Chưa áp dụng luồng này trên Nano; không tự chụp liên tục hay bật lịch TEST.

Dependency mới: `cv2-enumerate-cameras==1.3.3` chỉ trên Windows, để dùng cơ chế
nhận diện DirectShow hiện hữu của Hydro. Không nâng framework. Máy thử đã có
dependency; không chạy cài gói hoặc đổi Python môi trường người dùng.

## Kiểm thử và giới hạn nghiệm thu

Bản cuối: `python -m unittest discover -s tests -v`, **349/349 đạt**, 273,530s;
24 test mới. `compileall` và `git diff --check` đạt. Suite Tk cũ còn cảnh báo
callback `after` khi hủy root trong test; không dùng test pass để cam kết mọi
tương tác desktop đã nghiệm thu trực tiếp.

Fixture kiểm hai lượt 20 ROI/4 trống; gán nhãn bằng form thật trên project tạm;
không biến TEST thành train; đổi project/CAS; lặp lưu; lỗi ghi/ổ đầy/hủy;
ảnh sai crop/hash/đường dẫn/nguồn giả; pipeline Hydro với frame sinh trong test,
kiểm profile bằng worker thật nhưng không mở camera; checkpoint/ngưỡng/report;
gói ONNX/ZIP giả giữ scope lô và hash model. Không nới gate đóng gói để test đạt.
Test dùng dữ liệu giả, không chứng minh accuracy hoặc chất lượng camera thật.

Chưa chụp 16 cây thật, chưa nghiệm thu giao diện trực tiếp với người dùng, chưa
đánh giá/phê duyệt checkpoint thật, chưa xuất/kích hoạt model thật hoặc gửi Gmail.
Không đóng/restart phiên SmartLabel có công việc chưa lưu của người dùng.

Nguồn chính thức kiểm ngày 23/09/2026:

- [OpenCV VideoCapture](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html): dùng backend/cấu hình hiện hữu, không suy rằng API bảo đảm độc quyền camera.
- [Python subprocess](https://docs.python.org/3/library/subprocess.html): worker có timeout/cancel hữu hạn.
- [scikit-learn grouped cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data): ảnh cùng cá thể không được coi là mẫu độc lập khi phân tập/đánh giá.

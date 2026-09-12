# Trạng thái tích hợp HydroFlow ngày 10 tháng 9 năm 2026

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

Lượt người dùng project_eb99e9722cff đã lưu model plant_presence và yellow_leaf;
wilt chưa có run. Không train lại hai nhóm đã hoàn tất. Mở lại app để nạp UI
log đã sửa, chỉ tick Héo và train nhóm còn thiếu. Sau đó Xuất ONNX Hydro lấy
đủ model đã lưu của mọi nhóm, rồi Tạo Hydro Model Bundle để tạo ZIP cho Hydro.
Hai nút là hai bước nối tiếp; ZIP PT tự tạo sau batch chỉ là gói quản lý
checkpoint, không thay ZIP Hydro. Xem hướng dẫn trong HUONG_DAN_SU_DUNG.md.

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

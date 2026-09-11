# Trạng thái tích hợp HydroFlow ngày 10 tháng 9 năm 2026

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

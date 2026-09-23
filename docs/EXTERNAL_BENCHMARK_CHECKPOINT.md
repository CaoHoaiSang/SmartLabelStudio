# Bộ TEST ngoài gắn checkpoint — 22/09/2026

**Cập nhật 24/09:** kiểm định độc lập không còn bắt buộc với mọi gói vận hành.
Có luồng xuất chưa kiểm định với xác nhận riêng, không đổi hoặc nới kiểm tra
bằng chứng trong tài liệu này. Đánh giá model có lựa chọn TEST độc lập mở
chính luồng này. Xem [chính sách hiện hành](OPERATIONAL_EVALUATION_POLICY.md).

Bổ sung 23/09: **Thu thập TEST · Camera riêng** dùng `HydroHeldoutBenchmarkV1`
cho lô cây giữ riêng, gồm cả rọ trống; không giả nguồn vụ Hydro. Form gán nhãn
và đánh giá/checkpoint vẫn là luồng hiện hữu. Phạm vi cùng đợt gieo được ghi
trong báo cáo và gói, không thay bằng kết luận kiểm định qua vụ khác. Xem
[quy trình thu ảnh TEST](HELDOUT_CAPTURE_COLLECTOR.md). Contract `HydroBenchmarkV1`
bên dưới vẫn giữ yêu cầu nguồn giàn/vụ/rọ như cũ.

## Cách dùng

Trong Dataset chọn **Bộ TEST ngoài · Đánh giá checkpoint**. Đây là một luồng
đánh giá trong SmartLabel, không tạo hệ train hoặc project nhãn song song.

1. Nếu ảnh đang ở project đã gán nhãn: chọn vụ theo mã, giàn và khoảng ngày chụp,
   **Tạo bộ TEST từ vụ đã chọn**. Chỉ sao chép ảnh rọ đã duyệt và nhãn dứt khoát;
   không sao chép ảnh toàn giàn, không di chuyển split hay sửa ảnh gốc.
2. Tại project chứa checkpoint cần kiểm định, **Nhập bộ TEST ngoài**: chọn thư mục
   có `benchmark.json` và `images/`, xem số ảnh/nguồn vụ rồi xác nhận. Không nhận
   thư mục ảnh trần thiếu nhãn/nguồn. Ảnh bổ trợ/Fleet chưa được đi qua luồng này.
3. Xem checkpoint/SHA256 từng thuộc tính, cố định low/high trước đánh giá. Xác nhận
   TEST chưa dùng để train, chọn model/ngưỡng, kể cả checkpoint cha. Chạy đánh giá.
4. Xem TP/TN/FP/FN, số mẫu Có/Không, số chưa chắc, độ phủ và tỷ lệ phát hiện tính
   trên toàn bộ mẫu Có. **Duyệt kết quả** là quyết định kỹ thuật rõ ràng; không có
   ngưỡng chất lượng tự bịa hoặc tuyên bố đạt độ chính xác chỉ vì có hai vụ.
5. Mở Tạo gói Model Hydro, kiểm lại các ngưỡng đã được lưu cho checkpoint rồi chọn
   chế độ mong muốn. Operational yêu cầu bằng chứng được duyệt còn khớp. Shadow
   vẫn độc lập; không tự hạ chế độ nếu kiểm tra thất bại.

Xem/chuyển nhóm cũ vẫn dùng được: nay hiện nguồn vụ/giàn/ngày, lọc vụ và chọn nhiều
nhóm (Ctrl/Shift hoặc Chọn các nhóm đang lọc), chuyển cả nhóm trong một lần ghi.
Trước đây danh sách chỉ chọn một nhóm và chỉ hiện mã; ngoài thao tác đó còn có
phân tập 70/15/15, nhưng phân ngẫu nhiên không bảo đảm TEST vụ độc lập.

## Độc lập và giới hạn

Final Train+Val giữ TEST dùng được nếu checkpoint chưa học bộ kiểm định. Final100
vẫn có thể được kiểm định bằng một bộ khác chưa dùng. Chuyển ảnh đã học sang TEST
không làm checkpoint cũ trở nên độc lập. 80 ảnh vụ hai đã nằm trong snapshot train
21/09 của hệ hiện tại: tác vụ này không đổi chúng thành TEST, không train lại.

Ảnh nguồn khi **tạo** benchmark vẫn giữ phân tập cũ. Không train thêm với vụ đó
nếu muốn giữ nó độc lập. Bản **nhập** được cách ly ngoài project.images/splits;
đường import ảnh thường và train chặn thư mục đánh dấu benchmark (kể cả con/YAML).
Không thể ngăn một người cố ý chép ảnh ra ngoài rồi xóa nguồn gốc; hash và xác nhận
độc lập là kiểm soát ứng dụng, không phải chứng thực pháp lý/chữ ký nhà phát hành.

Đối chiếu dataset trong `checkpoint.ckpt.train_args.data`, không dùng split hiện
tại để suy lịch sử. Kiểm byte/pixel, hash ảnh gốc khi có, nguồn vụ và namespace.
Thiếu Gateway thì chặn bảo thủ nếu trùng mã vụ. Nguồn mới được chụp vào export.json;
export cũ chỉ phục hồi nguồn từ tên ảnh khớp duy nhất, không suy vụ theo ngày.
Phải giữ dataset đã train để tái kiểm tra. VAL tương thích của Final được loại khỏi
dữ liệu đã học chỉ khi cả metadata export và checkpoint chứng minh validation tắt.
Lịch sử checkpoint cha/nguồn pretraining không tự suy ra được: cần kỹ thuật viên
xác nhận và lưu provenance thích hợp; hệ không hứa phát hiện mọi ảnh gần trùng.

Không dùng TEST để tối ưu ngưỡng hoặc chọn checkpoint tốt nhất rồi gọi kết quả đó
là kiểm định độc lập. Cần bộ kiểm định mới nếu đã khai thác TEST cho chọn model.
Nguồn phương pháp, kiểm ngày22/09/2026:
[scikit-learn: tránh rò dữ liệu và tách tập kiểm thử](https://scikit-learn.org/1.8/common_pitfalls.html).

## Contract và ràng buộc

- `HydroBenchmarkV1`: crop, schema/ý nghĩa nhãn, nguồn vụ/giàn/rọ, nhãn đã duyệt,
  đường dẫn tương đối, SHA256 file/pixel và dung lượng. JPEG/PNG một khung,
  tối đa20MP/10MiB mỗi ảnh,5000ảnh/2GiB mỗi bộ. Không đi theo symlink/junction.
- Sao chép vào staging và kiểm lại trước rename; nhập cùng bản kê là idempotent.
  Không ghi đè bản đã nhập hoặc nhãn. Dừng tác vụ không công bố gói dở.
- `HydroExternalEvaluationV1`: hash bộ TEST, hash checkpoint từng thuộc tính,
  schema, ngưỡng cố định, inventory train/val, dự đoán và metrics. ID là hash nội
  dung; bản kê/báo cáo bị thay thì vô hiệu. Đọc/xuất/duyệt đều kiểm project.
- Phê duyệt lưu report hash/ngày duyệt và ngưỡng/model hash trong project qua
  atomic save; lỗi ghi trả lại metadata trong RAM. Không tự phát hành/kích hoạt.
- Khi xuất operational: kiểm QA dataset, kiểm lại bằng chứng, sao chép PT vào
  staging riêng, so hash trước ONNX, kiểm lại nguồn/bằng chứng sau chuyển đổi.
  Manifest chứa `evaluationEvidence` tối giản và hash ONNX thực sự đóng gói;
  không đưa ảnh TEST, đường dẫn nội bộ hay toàn bộ dự đoán vào gói.
- ONNX output ordering/hợp đồng vẫn theo validator hiện hữu. Binding nguồn xuất
  không thay thế nghiệm thu độ tương đương số học ONNX/Jetson hoặc chất lượng
  model ngoài bộ kiểm định này. Không tự tạo chữ ký phát hành Fleet.
- Worker dùng khóa `evaluation_running` hiện hữu, giữ đến khi xử lý kết quả;
  chặn đổi project/train/xuất trong lúc chạy; không áp dụng callback vào project khác.

## Kiểm chứng

324/324 unittest toàn bộ chạy cuối đạt (294,645s), bao gồm15 test
contract/evaluation/export +3 test Tk worker. Fixture tạo
ảnh/checkpoint mô phỏng và ONNX hợp lệ trong thư mục tạm; không dùng dataset thật
để sửa nhãn/train/phê duyệt. Tk fixture có thông báo cleanup `after` từ CTk khi
hủy các root thử; không có test fail. Chưa nghiệm thu thao tác native Studio
đang mở hoặc đánh giá checkpoint thật với bộ TEST độc lập thực địa.

Cần lưu công việc và mở lại SmartLabel để nạp source mới. Không cưỡng bức đóng
phiên người dùng. Hydro Backend đã nạp riêng; không cần đụng bơm hay bật model
operational để thử Gmail bằng ảnh rọ được người dùng chọn/xem trước/xác nhận.

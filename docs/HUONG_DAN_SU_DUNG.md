# Hướng dẫn sử dụng DeltaX Smart Label Studio

## 1. Mục đích

Smart Label Studio rút ngắn thời gian tạo dataset. YOLO tìm vật và đoán class; SAM2 tùy chọn tạo đường mask; người dùng kiểm tra, sửa và duyệt. Dữ liệu đã duyệt mới được dùng để train.

Ứng dụng không để AI tự duyệt kết quả và không tự thay model đang sử dụng.

## 2. Chuẩn bị

### Máy chỉ có CPU

1. Chạy `setup.bat`.
2. Chạy `run.bat`.
3. Vào **PHẦN CỨNG**.
4. Xác nhận PyTorch/ONNX Runtime đã được nhận.
5. Trong Auto-label và Train chọn `auto` hoặc `cpu`.

### Máy Công ty có RTX 4060 Ti

1. Cài NVIDIA Driver mới phù hợp.
2. Cài PyTorch CUDA bằng lệnh được tạo tại trang chính thức của PyTorch.
3. Chạy kiểm tra:

   ```bat
   python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
   ```

4. Kết quả đầu tiên phải là `True` và tên thiết bị phải chứa `RTX 4060 Ti`.
5. Mở ứng dụng, vào **PHẦN CỨNG** và quét lại.
6. Chọn `auto` hoặc `cuda` khi auto-label/train.

Nếu chọn `cuda` nhưng CUDA chưa sẵn sàng, ứng dụng dừng job và báo lỗi; không âm thầm chạy CPU.

## 3. Tạo dự án

1. Nhấn **Dự án mới**.
2. Nhập tên dự án.
3. Chọn **Mẫu cấu hình ban đầu**. Đây chỉ là bộ Class/thuộc tính/kiểu bài toán được tạo sẵn cho dự án mới, không phải danh sách dự án đã lưu:
   - **DeltaX chai**: tạo sẵn ba Class chai và các nhóm thuộc tính hiện có.
   - **Hydroponic**: tạo Classification toàn ảnh cho 10 slot với `plant_presence`, `yellow_leaf`, `wilt`.
   - **Dự án trống**: không tạo sẵn Class hay thuộc tính.
4. Muốn mở dự án `Cao` hoặc dự án đã có khác, đóng hộp thoại **Dự án mới** và chọn ở danh sách trên thanh trên cùng.
5. Nhấn **Quản lý Class & thuộc tính**.
6. Trong tab **CLASS**, thêm Class, đổi tên hoặc bấm ô màu để chọn màu overlay.
7. Chỉ Class cuối chưa được nhãn sử dụng mới có thể xóa; quy tắc này bảo vệ ánh xạ Class ID của model/dataset.
8. Trong tab **THUỘC TÍNH**, nhấn **+ Thêm nhóm thuộc tính** để tạo nhóm mới hoặc sửa các nhóm tình trạng, che khuất và nắp chai có sẵn.
9. Mỗi nhóm gồm:
   - **Tên nhóm**: tên nhìn thấy trong trang Gán nhãn.
   - **Mã**: khóa ổn định lưu trong `project.json`; ứng dụng tự tạo và không đổi khi sửa tên.
   - **Mặc định**: tự gán cho nhãn mới; chọn “Không mặc định” nếu muốn người dùng quyết định từng nhãn.
   - **Bắt buộc**: không cho Duyệt ảnh khi nhãn còn thiếu nhóm này.
   - **Mục đích**: metadata, Classification hai giai đoạn, hoặc điều kiện OK/NG. Nhóm Classification có thể được export thành các crop để train classifier riêng.

Nên đặt tên class theo loại sản phẩm, không theo hình dạng tạm thời. Ví dụ chai bị cán dẹp vẫn là `Chai_trong`; chọn thuộc tính `condition=can_dep`.

## 4. Nhập dữ liệu

Trong trang **DỰ ÁN**:

- **Nhập thư mục ảnh**: quét cả thư mục con.
- **Nhập các ảnh**: chọn một hoặc nhiều file.
- **Tách frame từ video**: ứng dụng đọc tổng số frame, đề xuất khoảng `N` để tạo tối đa khoảng 500 ảnh và cảnh báo trước nếu lựa chọn dự kiến tạo quá nhiều ảnh. `N=4` nghĩa là lưu mỗi 4 frame, không phải chỉ lưu 4 ảnh.
- **Xóa lần nhập gần nhất · N**: xóa đúng toàn bộ `N` ảnh của lượt nhập thành công gần nhất cùng nhãn/trạng thái trong dự án. Hộp xác nhận hiển thị trước dự án, thời gian, nguồn rút gọn, số ảnh và số nhãn. Ảnh/video nguồn ban đầu và Dataset đã export không bị xóa.

Ứng dụng sao chép ảnh vào dự án. Ảnh giống hệt nhau được nhận diện bằng SHA-256 và bỏ qua.

## 5. Gán nhãn thủ công

1. Mở trang **GÁN NHÃN**.
2. Chọn ảnh bên trái.
3. Chọn Class bằng nút màu ở cột phải; dùng ô tìm kiếm khi có nhiều Class.
4. Chọn **Box**, kéo từ một góc vật đến góc đối diện.
5. Hoặc chọn **Polygon**, bấm lần lượt quanh vật và double-click để hoàn thành.
6. Chọn nhãn để chỉnh Class. Tick **Bật Classification thuộc tính** khi muốn gán và train thuộc tính; bỏ tick để trở về luồng train định vị bình thường cho Radxa.
7. Nhấn Delete hoặc **Xóa nhãn** để xóa.
8. `Ctrl+Z` để undo, `Ctrl+Y` để redo.
9. Danh sách bên trái hiển thị thumbnail, số nhãn và trạng thái; ảnh đang chọn có viền xanh và danh sách tự cuộn đến ảnh đó.
10. Dùng cụm điều khiển ở góc dưới phải ảnh: `−`, phần trăm zoom, `+`, **Vừa**, **⌾ Căn giữa**.
11. Ở chế độ **Chọn**, kéo vùng trống để di chuyển ảnh. Cũng có thể giữ `Space` rồi kéo hoặc kéo bằng nút chuột giữa.
12. Lăn chuột để zoom tại vị trí con trỏ; rê chuột lên nút để xem giải thích chức năng.

### Chỉnh RECT do YOLO đề xuất chưa sát

1. Chọn **RECT** ở thanh loại nhãn và chọn công cụ **Chọn**.
2. Bấm vào bounding box. Tám tay nắm trắng sẽ xuất hiện ở bốn góc và bốn cạnh.
3. Kéo tay nắm để thay đổi kích thước; kéo vùng bên trong hộp để di chuyển toàn bộ RECT.
4. Nhãn AI được sửa sẽ đổi nguồn thành `manual`, bỏ confidence cũ và trở về bản nháp cần duyệt.
5. Nếu đối tượng đã có SEG, OBB hoặc ORI, các điểm này được co giãn/di chuyển cùng RECT để không lệch vật.

### RECT, SEG, OBB và ORI

- **RECT**: bounding box thẳng theo trục ảnh, dùng cho YOLO Detection. Đây là loại nhanh nhất và cần ít công gán nhãn nhất.
- **SEG**: polygon/mask sát biên vật, dùng cho YOLO Instance Segmentation. Phù hợp chai cán dẹp, chồng lấn hoặc hình dạng bất quy tắc.
- **OBB**: hộp chữ nhật quay, dùng cho YOLO OBB. Phù hợp khi cần tâm, kích thước và góc vật nhưng không cần biên pixel chính xác.
- **ORI**: hướng từ tâm vật đến đầu/nắp. Đây là tên gọi của ứng dụng; khi export/train được ánh xạ sang YOLO Pose với hai keypoint `center` và `direction`.

OBB có góc theo chu kỳ 180° nên không luôn phân biệt đầu và đuôi. ORI biểu diễn hướng 0–360°, nhưng chỉ nên dùng khi chai có dấu hiệu đầu/nắp rõ ràng.

Để tạo OBB, chọn một RECT/SEG rồi nhấn **SEG/RECT → OBB**. Nếu có SEG, ứng dụng tính hộp quay nhỏ nhất ôm polygon; nếu chưa có SEG, OBB ban đầu trùng RECT. Muốn chỉnh OBB, hãy sửa RECT/SEG nguồn rồi nhấn tạo OBB lại. Để đặt ORI, chọn vật, nhấn **Đặt hướng ORI**, rồi bấm lên phía đầu/nắp của chai. Chọn lại công cụ **Chọn** khi hoàn tất.

Các thuộc tính mặc định:

- `condition`: nguyên vẹn, bẹp nhẹ, cán dẹp hoặc vỡ nát.
- `occlusion`: không che, che một phần hoặc che nhiều.
- `cap`: có nắp, mất nắp hoặc chưa xác định.

Dấu tick là công tắc chế độ, không chỉ ẩn/hiện. Tắt dấu tick giữ nguyên dữ liệu đã gán nhưng trang Train dùng Detection/SEG/OBB/ORI. Bật dấu tick hiển thị bảng thuộc tính và chuyển sang Classification. `OK` nghĩa là đạt yêu cầu (Pass/Good); `NG` là không đạt (No Good/Fail).

## 6. Auto-label bằng YOLO

1. Vào **AUTO-LABEL**.
2. Chọn `best.pt` hoặc model khác.
3. Chọn thiết bị.
4. Đặt confidence ban đầu khoảng `0.25`.
5. Bật **Chỉ ảnh chưa có nhãn** để không đụng vào ảnh đã làm.
6. Bật **Thay dự đoán AI cũ** khi muốn chạy lại model; nhãn manual và nhãn đã duyệt được giữ lại.
7. Nhấn **CHẠY AUTO-LABEL**.
8. Theo dõi tiến trình.
9. Quay lại **GÁN NHÃN** và kiểm tra từng ảnh bản nháp.

Confidence thấp giúp tìm được nhiều vật nhưng tăng nhãn sai. Confidence cao giảm nhãn sai nhưng có thể bỏ sót chai khó.

## 7. Tạo mask bằng SAM2

1. Cài package SAM2.
2. Trong **AUTO-LABEL**, nhấn **Tải SAM2 Small tương thích**; hoặc chọn đúng file checkpoint `.pt`/`.pth` đã có.
3. Nhấn **Kiểm tra cấu hình SAM2** và chỉ tiếp tục khi trạng thái là **Sẵn sàng**.
4. Vẽ box hoặc chạy YOLO để có box.
5. Chọn box trong **GÁN NHÃN**.
6. Nhấn **SAM2 → SEG**. SAM2 dùng RECT như một prompt rồi trả về mask; ứng dụng lưu mask thành polygon Segmentation.
7. Kết quả mask được chuyển thành polygon có thể kiểm duyệt và export.
8. Chọn **SAM +** rồi bấm vào phần vật bị thiếu để thêm vùng.
9. Chọn **SAM −** rồi bấm vào nền/vật khác đang bị dính để loại vùng.

Nếu chỉ muốn train YOLO Detection bằng nhãn hình chữ nhật, chọn nhãn SEG rồi nhấn **SEG → RECT**. Ứng dụng xóa đường polygon nhưng giữ lại đúng bounding box RECT trước khi chạy SAM2. Nút `↶` cũng có thể hoàn tác ngay lần chuyển đổi gần nhất; **SEG → RECT** rõ ràng hơn và vẫn dùng được sau khi đã chuyển sang ảnh khác.

Nếu ô checkpoint trống, trỏ tới thư mục hoặc sai đuôi file, ứng dụng sẽ yêu cầu chọn lại trước khi nạp SAM2. Nút tải mặc định dùng checkpoint SAM2 Hiera Small khoảng 176 MB, phù hợp với config `sam2_hiera_s.yaml` của package hiện tại.

Trên CPU thao tác đầu tiên của mỗi ảnh có thể chậm vì phải tạo embedding. RTX 4060 Ti phù hợp hơn cho thao tác tương tác.

## 8. Duyệt nhãn

Với từng ảnh:

1. Kiểm tra đủ số chai.
2. Kiểm tra class.
3. Kiểm tra box/mask không dính băng tải hoặc chai bên cạnh.
4. Chọn thuộc tính biến dạng và che khuất.
5. Nhấn **DUYỆT ẢNH & TIẾP**.

Nút này đánh dấu toàn bộ nhãn trong ảnh là đã kiểm tra và chuyển ảnh sang `reviewed`. Nếu ảnh không dùng được, chọn **Từ chối ảnh**.

- **Nhãn đang chọn đã kiểm tra** chỉ áp dụng cho một nhãn cụ thể và được lưu theo nhãn đó.
- **DUYỆT ẢNH & TIẾP** duyệt toàn bộ nhãn trong ảnh.
- **Duyệt & tiếp** và **Bỏ duyệt** nằm cùng một hàng vì cùng quản lý trạng thái duyệt.
- **Bỏ duyệt** đưa ảnh về bản nháp và bỏ dấu kiểm của các nhãn.
- **Từ chối** và **Khôi phục** nằm cùng một hàng; từ chối loại ảnh khỏi dataset mặc định nhưng không xóa dữ liệu.
- **Khôi phục** đưa ảnh bị từ chối về trạng thái phù hợp trước đó.
- Nếu sửa nhãn của ảnh đã duyệt, ảnh tự trở về bản nháp để tránh dùng nhãn chưa kiểm tra.

Nút ảnh trước/sau và thao tác mở từ trang Kiểm duyệt sẽ đồng bộ dòng được chọn trong danh sách và hiển thị tên file phía trên ảnh.

Danh sách ảnh được phân trang, mặc định chỉ nạp 50 thumbnail mỗi lần. Dùng nút `◀/▶` bên trên danh sách để đổi trang. Nút Ảnh trước/sau tự chuyển trang khi đi qua ranh giới; thumbnail của trang cũ được giải phóng để dự án video hàng nghìn ảnh không làm treo ứng dụng.

### Xóa ảnh và toàn bộ nhãn liên quan

1. Tìm ảnh trong **Danh sách ảnh**.
2. Nhấn nút `×` màu đỏ ngay trên thumbnail của ảnh. Hàng ảnh đó sẽ được chọn tự động.
3. Đọc số nhãn sẽ bị xóa và xác nhận.

Ứng dụng xóa bản sao ảnh trong dự án, mọi nhãn RECT/SEG/OBB/ORI, tọa độ, thuộc tính và trạng thái duyệt gắn với ảnh. Ảnh nguồn ban đầu không bị xóa. Dataset đã export trước đó là một snapshot độc lập nên không tự thay đổi; hãy export lại dataset nếu muốn bộ dữ liệu mới không còn ảnh vừa xóa.

### Quy tắc gán nhãn vật bị che khuất

- Mặc định nên gán nhãn khi vật còn nhìn thấy **ít nhất 50%** và vẫn xác định chắc chắn được Class. Nói cách khác, mức che khuất tối đa khuyến nghị là **50%**.
- Dữ liệu tốt nhất cho Detection/SEG là vật bị che khuất không quá **30%**. Hãy ưu tiên thu thập nhiều ảnh thuộc nhóm này.
- Nếu che khuất từ **30–50%**, chỉ gán khi Class và ranh giới phần đang thấy vẫn rõ; chọn thuộc tính `Che khuất` tương ứng nếu dự án bật Classification thuộc tính.
- Nếu che khuất trên **50%**, không đoán nhãn từ phần bị ẩn. Thông thường nên từ chối/bỏ qua ảnh, trừ khi bài toán thực tế bắt buộc nhận dạng loại trường hợp này và đã có quy ước riêng.
- Với SEG, chỉ vẽ vùng pixel thực sự nhìn thấy; không tự suy diễn hình dạng phía sau vật che. Với RECT/OBB, bao phần vật nhìn thấy theo cùng một quy tắc nhất quán trong toàn bộ dataset.

### Lọc ảnh thông minh

1. Vào **Dự án → Lọc ảnh thông minh**.
2. Chọn nguồn **Tất cả ảnh**, **Frame video** hoặc **Ảnh nhập / thư mục**.
3. Mặc định ứng dụng chỉ phân tích ảnh thuộc **lượt nhập thành công gần nhất**. Bật **Bao gồm ảnh cũ đang có trong dự án** khi cần quét lại toàn bộ dữ liệu cũ và mới.
4. Giữ mặc định `99%` gần trùng, `0.20` confidence và `10%` ảnh nền. Nếu dự án đã có model phù hợp, bật **Dùng model**.
5. Nhấn **Phân tích**. Trên máy CPU, AI có thể cần vài phút khi số ảnh lớn nhưng chạy nền và không khóa cửa sổ chính.
6. Kiểm tra các nhóm **Nên giữ**, **Giữ ảnh nền**, **Gần trùng**, **Ảnh trống/Cần kiểm tra**, **Chất lượng kém** và **Chưa chắc**.
7. Chọn một dòng để xem toàn bộ ảnh theo chế độ **vừa khung, giữ nguyên tỷ lệ**, cùng độ sáng, độ nét, nguồn và trạng thái bảo vệ. Double-click dòng để đổi `GIỮ ↔ XÓA`; hàng focus và badge xem trước đổi **xanh khi GIỮ**, **đỏ khi XÓA**, đồng thời nội dung quyết định cập nhật ngay.
8. Nhấn **Xóa các ảnh đề xuất** và xác nhận lần cuối.

Model được chạy với ngưỡng thấp để các dự đoán yếu đi vào nhóm **Chưa chắc** thay vì bị xóa. OpenCV đo độ giống, độ nét và độ sáng. Với video, hệ thống còn đo thay đổi so với nền theo từng chuỗi; với ảnh nhập, hệ thống tìm gần trùng trên toàn bộ nguồn ảnh nhập và không giả định một ảnh đơn là ảnh nền. Trong một cụm gần trùng, ứng dụng ưu tiên ảnh đã có công sức gán nhãn, vật rõ, confidence cao, diện tích vật lớn và không chạm mép.

Ảnh đã có nhãn hoặc đã duyệt luôn mặc định **GIỮ/KHÓA**, kể cả khi AI đề xuất là gần trùng hoặc ảnh trống. Người dùng vẫn có thể double-click để chủ động chuyển sang **XÓA**, sau đó phải xác nhận lần cuối. Ảnh/video nguồn ban đầu và các Dataset đã export không bị xóa.

Ứng dụng gắn một mã `import_batch` cho mỗi lần nhập có thêm ảnh thành công. Nếu một lượt nhập chỉ gặp ảnh trùng và không thêm ảnh nào thì lượt mới nhất trước đó vẫn được giữ nguyên. Khi mở bộ lọc lần đầu với dự án cũ chưa có mã này, ứng dụng tự nhóm metadata theo các phiên nhập liên tiếp dựa trên `created_at`; thao tác chuyển đổi không sửa ảnh, nhãn hay trạng thái duyệt.

Trang **KIỂM DUYỆT** tìm các lỗi như class không tồn tại, box ngoài ảnh, polygon thiếu điểm hoặc ảnh đã duyệt nhưng không có nhãn.

## 9. Tạo dataset

1. Mở **DATASET**.
2. Bật **Chỉ ảnh đã duyệt**.
3. Có thể nhấn **Tạo phiên bản bất biến** để lưu snapshot metadata phục vụ đối chiếu. Đây là bước tùy chọn: **Bắt đầu Train** luôn tự export ảnh và nhãn mới nhất của dự án tại thời điểm bấm. Snapshot hiện dùng cho lịch sử/audit, không tự thay thế nguồn Train.
   - Nhập tên hoặc để trống rồi bấm **Tạo** để tạo snapshot.
   - Bấm **Hủy**, dấu **X** hoặc phím **Esc** thì không tạo gì.
4. Chọn export:
   - **RECT · Detection** cho bounding box.
   - **SEG · Segmentation** khi vật đã có polygon/mask.
   - **OBB · Rotated Box** cho bốn góc hộp quay.
   - **ORI · Pose 2 điểm** cho tâm và hướng đầu/nắp.
   - **Crop · Classification**: chọn một nhóm thuộc tính, cắt từng vật theo RECT và xếp crop vào thư mục mang giá trị thuộc tính.
   - COCO JSON để lưu trữ và trao đổi tổng quát.

**Export tại trang DATASET là export dữ liệu gán nhãn, không phải export model.** Mỗi bản export chứa ảnh được chia vào `train/val/test`, các file `.txt` mang Class và tọa độ nhãn đã chuẩn hóa, `data.yaml` mô tả dataset và `export.json` ghi task/thống kê. Mặc định chỉ ảnh đã duyệt được đưa vào export.

Sau khi Export Dataset, đường dẫn `data.yaml` hoặc thư mục Classification được tự điền vào trang **TRAIN**. Nếu dùng dataset ngoài, app cho chọn file YAML với task định vị hoặc chọn thư mục với task Classification.

Ảnh có timestamp hoặc cùng video được giữ nguyên theo `capture_group`. Lần đầu, ứng dụng lấy phân tập lịch sử gần nhất nếu có; nếu chưa có thì cân bằng gần **70% train / 15% validation / 15% test**. Kết quả được khóa trong `split_assignment.json`. Từ đó ảnh/nhóm cũ không tự đổi tập; capture group mới mặc định vào Train. Nút **PHÂN LẠI 70/15/15** là thao tác chủ động tạo chu kỳ Benchmark mới và có cảnh báo vì nó làm mất khả năng so sánh khách quan model cũ với Test mới.

Nút **XEM / CHUYỂN NHÓM** mở danh sách `capture_group`, cho lọc Train/Validation/Test và chuyển toàn bộ nhóm sang tập khác. Ứng dụng không cho tách riêng các frame trong cùng video vì làm vậy sẽ gây rò rỉ dữ liệu. Mọi lần chuyển đều có cảnh báo rằng Benchmark của model cũ có thể không còn so sánh trực tiếp được.

- `train`: dữ liệu dùng để cập nhật trọng số model.
- `validation`: dữ liệu không cập nhật trọng số, dùng để theo dõi chất lượng mỗi epoch và chọn `best.pt`.
- `test`: dữ liệu giữ riêng để đánh giá cuối cùng sau khi đã chốt model.

Ba tập là cần thiết nếu muốn biết model có thực sự tổng quát hóa hay chỉ nhớ ảnh đã học. Mỗi lần nhấn **BẮT ĐẦU TRAIN**, ứng dụng tạo một export mới từ trạng thái dự án hiện tại nhưng giữ nguyên assignment đã khóa.

## 10. Train model

1. Tắt **Bật Classification thuộc tính** nếu cần train model định vị.
2. Chọn task RECT/Detection, SEG, OBB hoặc ORI/Pose tại trang **TRAIN**.
3. Chọn đúng model khởi tạo, hoặc nhấn **Dùng model khởi tạo phù hợp**:
   - RECT/Detection: `yolo11n.pt`.
   - SEG/Segmentation: `yolo11n-seg.pt`.
   - OBB: `yolo11n-obb.pt`.
   - ORI/Pose: `yolo11n-pose.pt`.
   - Classification thuộc tính: `yolo11n-cls.pt`.
4. Chọn epoch, image size, batch và patience.
5. Chọn `auto`, `cpu` hoặc `cuda`.
6. Nhấn **BẮT ĐẦU TRAIN**. Ứng dụng tự export ảnh/nhãn theo task đang chọn, tạo `data.yaml`, kiểm tra có nhãn hợp lệ rồi mới khởi chạy train.

Ý nghĩa thông số:

- **Epoch**: số lần model đi qua toàn bộ Train. Bắt đầu 30–50 epoch; nếu loss/validation còn cải thiện có thể tăng. Với Final Train không có validation, dùng gần epoch tốt nhất của lần phát triển trước (model chai hiện tại đạt validation tốt nhất khoảng epoch 47).
- **Image size**: cạnh ảnh đầu vào sau resize/letterbox. Detection/SEG triển khai DeltaX RKNN dùng `640`; Classification thường `224`. Tăng kích thước giúp giữ chi tiết nhỏ nhưng chậm và tốn RAM/VRAM hơn.
- **Batch**: số ảnh dùng trước một lần cập nhật trọng số. CPU nên thử 4–8; RTX 4060 Ti thử 8–16 rồi tăng nếu còn VRAM. Nếu báo hết bộ nhớ, giảm Batch trước.
- **Patience**: số epoch validation không cải thiện trước khi early stopping. Thường 10–20. Hai chế độ Final tắt validation trong lúc học nên Patience bị bỏ qua và model chạy đủ Epoch.

Chiến lược dữ liệu trong trang Train:

- **Phát triển · Khóa Train/Val/Test**: mặc định; có validation, early stopping và test độc lập. Dùng để thử nghiệm và so sánh model.
- **Final · Train + Val, giữ Test**: gộp Train+Validation để học, tắt validation ở từng epoch và early stopping, vẫn giữ Test chưa học để báo cáo một lần ở cuối run. Đây là lựa chọn khuyến nghị trước khi đưa model lên Radxa.
- **Final · Train 100% dữ liệu**: học cả Test, không còn chỉ số khách quan. Phải nhập `TRAIN ALL` để xác nhận và cần tạo Benchmark mới nếu muốn đánh giá.

Không còn bắt buộc phải mở trang Dataset trước khi train model định vị. Các nút **Export thủ công** trong trang Dataset chỉ dùng khi muốn xem cấu trúc dữ liệu, sao chép dataset hoặc kiểm tra nhãn trước khi train. Mặc định auto-export chỉ lấy ảnh đã duyệt theo công tắc **Chỉ ảnh đã duyệt**.

Ứng dụng chặn train nếu task trong `export.json`, task đang chọn và kiến trúc checkpoint không khớp nhau. Model Detection `best.pt` hiện tại không thể dùng trực tiếp để train SEG, OBB hay ORI.

Train chạy trực tiếp trên máy đang mở ứng dụng. Chọn `cpu` dùng CPU; chọn `cuda` hoặc `auto` trên máy có RTX/PyTorch CUDA sẽ dùng GPU. Kết quả quan trọng nhất:

- `weights/best.pt`: checkpoint có kết quả validation tốt nhất.
- `weights/last.pt`: trạng thái ở epoch cuối, phù hợp tiếp tục train.
- biểu đồ, confusion matrix và thông số train nằm cùng thư mục run.

Sau khi train định vị thành công, ứng dụng đăng ký `best.pt` và chọn nó tại trang **AUTO-LABEL**. Model Classification được đăng ký riêng theo mã nhóm thuộc tính và không ghi đè model định vị.

Trang **AUTO-LABEL** hiển thị dòng xanh `ĐANG DÙNG` cùng tên model và thời điểm cập nhật. Nếu ứng dụng bị đóng đúng lúc train vừa hoàn tất, lần khởi động sau sẽ tự khôi phục `best.pt` mới nhất từ thư mục `runs`.

### Đánh giá model

Khung **ĐÁNH GIÁ MODEL · VALIDATION / TEST** tách riêng hai đầu vào:

1. **Chọn model .pt**: chọn `best.pt` cần kiểm tra; ứng dụng mặc định điền model vừa train mới nhất.
2. **Chọn Dataset**: Detection/SEG/OBB/ORI chọn `data.yaml`, Classification chọn thư mục dataset. Hộp này chỉ hiện Dataset, không hiện model `.pt`.
3. Chọn `test` để đánh giá cuối cùng trên ảnh không dùng cập nhật trọng số; chỉ chọn `val` khi cần kiểm tra lại kết quả trong lúc phát triển.
4. Nhấn **ĐÁNH GIÁ MODEL**. Báo cáo, confusion matrix và các đường Precision–Recall được lưu trong `runs/evaluations`.

Các chỉ số Detection/SEG:

- **Precision**: trong những vật model báo có, tỷ lệ báo đúng. Precision thấp nghĩa là nhiều báo nhầm.
- **Recall**: trong những vật thật sự có, tỷ lệ model tìm thấy. Recall thấp nghĩa là bỏ sót nhiều vật.
- **mAP50**: chất lượng phân loại và định vị với điều kiện box chồng khớp vật thật ít nhất 50%; chỉ số này tương đối dễ.
- **mAP50-95**: trung bình từ IoU 50% đến 95%, nghiêm khắc hơn về độ sát của box và nên là chỉ số chính.
- **Theo Class**: phải kiểm tra từng loại chai; trung bình cao không bù được một Class có Recall quá thấp.

Ngưỡng màu/nhận định trong ứng dụng chỉ là hướng dẫn học tập. Với Robot công nghiệp, tiêu chuẩn thật phải được chốt bằng tỷ lệ bỏ sót/báo nhầm cho phép, ảnh hiện trường độc lập và sai số TCP sau calibration.

### Train thuộc tính theo hướng hai giai đoạn

1. Ở trang **GÁN NHÃN**, tick **Bật Classification thuộc tính**.
2. Gán giá trị thuộc tính cho từng vật; mỗi nhóm cần một classifier riêng.
3. Duyệt ảnh, mở **DATASET**, tick một hoặc nhiều nhóm rồi nhấn **EXPORT CROP CÁC NHÓM ĐÃ TICK**. Danh sách tick này dùng chung với trang Train.
4. Trang Train tự chuyển task sang `classify` và dùng thư mục crop vừa tạo.
5. Chọn `yolo11n-cls.pt`, sau đó bắt đầu train.

Để train nhiều thuộc tính mà không lặp thao tác:

1. Trong trang **TRAIN**, tick một hoặc nhiều nhóm thuộc tính. Đây là cùng lựa chọn đang hiển thị tại Dataset.
2. Có thể dùng **Chọn tất cả** hoặc **Bỏ chọn**.
3. Nhấn **TRAIN CÁC NHÓM ĐÃ TICK**. Tick một nhóm thì train đúng một nhóm; tick nhiều nhóm thì train tuần tự.
4. Ứng dụng tự export crop cho từng nhóm, kiểm tra mỗi nhóm có ít nhất hai giá trị có dữ liệu rồi train lần lượt.
5. Mỗi `best.pt` được đăng ký vào đúng nhóm. Sau cùng ứng dụng tạo `classification_models_<timestamp>.zip` trong `workspace/projects/<project_id>/bundles`.

File ZIP là **một gói quản lý nhiều classifier**, không phải một mạng neural có thể nạp trực tiếp vào Ultralytics hoặc RKNN. Mỗi nhóm có label space và softmax riêng. Cách này giữ kết quả đúng, cho phép bật/tắt từng thuộc tính và không đòi hỏi một kiến trúc multi-head riêng trên Radxa.

Khi bỏ tick **Bật Classification thuộc tính**, ứng dụng ẩn phần thuộc tính tại Gán nhãn, phần export crop tại Dataset, danh sách nhóm tại Train và các nút RKNN nhiều classifier. Trang Train chỉ còn các task định vị Detection/SEG/OBB/ORI và nút **BẮT ĐẦU TRAIN** thông thường.

Khi vận hành hai giai đoạn, model Detection/SEG tìm vật trước; ứng dụng/Radxa crop từng vật rồi đưa crop qua classifier để dự đoán tình trạng, nắp hoặc OK/NG. Ứng dụng hiện đã chuyển được classifier sang RKNN một output; runtime Radxa vẫn cần bổ sung lớp suy luận Classification và bước gộp kết quả.

Khung **XUẤT RKNN CHO RADXA** chỉ phục vụ triển khai lên NPU Rockchip:

- Không cần nút lưu PT riêng: sau khi train thành công, `best.pt` đã tự được lưu vào `workspace/models`, đặt làm model Auto-Label hiện hành và lưu trong dự án.
- Với model định vị, chọn `best.pt` rồi nhấn **XUẤT RKNN · RK3588**.
- Với thuộc tính, tick các nhóm cần triển khai rồi nhấn **XUẤT RKNN CÁC NHÓM ĐÃ TICK**. Chọn thư mục một lần; ứng dụng tự chuyển tuần tự các classifier đã train.
- Sau khi có model định vị và ít nhất một classifier RKNN, nhấn **TẠO GÓI TRIỂN KHAI RADXA** để tạo thư mục model cùng `vision_bundle.json`.
- Nút **Dùng classifier** và dropdown chọn một nhóm đã được loại khỏi giao diện vì danh sách tick dùng chung đã thay thế chúng.
- File `.rknn` không được thêm vào kho Auto-Label.
- Ứng dụng tự nhận model Detection hay Segmentation và chọn layout DeltaX tương ứng.
- Image size khi xuất bắt buộc là `640`, khớp với `RKNNRuntime` và các scale 80/40/20 trên Radxa hiện tại.
- Sau khi train xong, ô model triển khai tự trỏ tới `weights/best.pt`. Có thể nhấn **Chọn best.pt…** để dùng một checkpoint khác.

Trên CPU nên thử 1–5 epoch và batch nhỏ để kiểm tra pipeline. Việc train chính nên chạy trên RTX 4060 Ti.

Kết quả nằm trong:

```text
workspace\projects\<project_id>\runs\candidate*
```

Gói classifier train hàng loạt nằm trong:

```text
workspace\projects\<project_id>\bundles\classification_models_*.zip
```

## 11. Dùng model đã train và triển khai

Tại **AUTO-LABEL**, chọn `best.pt`, chọn phạm vi rồi nhấn **CHẠY AUTO-LABEL** một lần. Ứng dụng chạy lần lượt toàn bộ ảnh thuộc phạm vi:

- bật **Chỉ ảnh chưa có nhãn**: bỏ qua ảnh đã có nhãn;
- tắt tùy chọn này: chạy trên toàn bộ ảnh;
- bật **Thay dự đoán AI cũ**: thay dự đoán AI cũ nhưng giữ nhãn manual và nhãn đã duyệt.

Auto-label đọc đúng đầu ra của model Detection, Segmentation, OBB hoặc Pose/ORI. Mọi dự đoán mới vẫn là bản nháp và cần người dùng duyệt.

Định dạng triển khai:

- `.pt`: checkpoint PyTorch gốc, thuận tiện train/chạy trên PC bằng Ultralytics; có thể chạy CPU hoặc NVIDIA CUDA.
- `.onnx`: phù hợp PC và nhiều runtime trung gian.
- `.rknn`: dành cho NPU Rockchip trên Radxa; `.pt` không tự dùng NPU Rockchip.

Ứng dụng đã có nút xuất RKNN cho Rock 5C/RK3588. Vì RKNN Toolkit build model trên Linux x86, ứng dụng gọi môi trường Docker riêng đã cố định:

- Python 3.10/Linux amd64;
- RKNN Toolkit 2.2.0;
- Ultralytics 8.4.6;
- đầu vào NCHW 640×640, chuẩn hóa `mean=0`, `std=255`;
- Detection: chín đầu ra theo ba tỉ lệ 80×80, 40×40 và 20×20;
- Segmentation: mười ba đầu ra gồm box, class, objectness, 32 mask coefficients ở ba tỉ lệ và mask prototype 32×160×160.

Đây không phải lệnh export RKNN tổng quát của Ultralytics: converter giữ các contract riêng cho **Detection**, **Segmentation** và **Classification**. OBB/ORI vẫn bị chặn để tránh tạo file nạp được nhưng bị bộ giải mã Studio đọc sai. Classification dùng output `[1, số lớp]` và không được đưa vào decoder YOLORKNN cũ.

Phần cần sửa trên Radxa được note tại [RADXA_CLASSIFICATION_INTEGRATION.md](RADXA_CLASSIFICATION_INTEGRATION.md).

Lần đầu xuất cần Docker Desktop đang chạy; image `deltax-rknn-converter:2.2.0-v3` được ứng dụng tự dựng khi cần. Các lần sau ứng dụng dùng lại image nên nhanh hơn. Trước khi hỏi nơi lưu file, ứng dụng kiểm tra Docker Linux Engine và báo rõ lỗi môi trường. Nếu gặp lỗi WSL `0x800705aa`, hãy lưu công việc, đóng bớt ứng dụng, khởi động lại Windows rồi chờ Docker Desktop báo Engine running. Nút **DỪNG XUẤT RKNN** phản hồi ngay và không hiện thông báo lỗi giả khi người dùng chủ động dừng. Sau khi hoàn tất:

1. Mở DeltaX Studio trên Radxa.
2. Vào **Vision AI Setting**.
3. Chọn/upload file `.rknn` vừa xuất.
4. Kiểm tra đúng thứ tự Class giữa dự án và Blockly/Tracking.
5. Test ảnh tĩnh rồi mới cho Robot chạy; không thay model sản xuất khi chưa so sánh sai số và confidence.

Hộp chọn model ở trang **AUTO-LABEL** chỉ nhận `.pt` và `.onnx` để chạy trên PC. `.rknn` là định dạng triển khai cho NPU Rockchip trên Radxa nên luôn lưu ngoài kho model và không xuất hiện trong Auto-Label.

Không dùng model ứng viên làm model auto-label chính cho đến khi đánh giá trên tập test và xác nhận tốt hơn model cũ.

## 11. Quy trình Active Learning khuyến nghị

1. Gán nhãn thủ công một tập nhỏ nhưng đa dạng.
2. Train model khởi đầu.
3. Auto-label dữ liệu mới.
4. Ưu tiên sửa ảnh confidence thấp, biến dạng mạnh, chồng lấn hoặc class hiếm.
5. Duyệt nhãn.
6. Tạo dataset version mới.
7. Train model ứng viên.
8. So sánh trên cùng tập test.
9. Chỉ thay model khi chỉ số và kiểm tra thực tế tốt hơn.

## 12. Sao lưu

Sao lưu toàn bộ thư mục:

```text
D:\DeltaX\SmartLabelStudio\workspace
```

Không chỉ sao lưu model. Dataset, project metadata và lịch sử phiên bản cần được giữ cùng nhau.

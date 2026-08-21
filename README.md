# DeltaX Smart Label Studio

Ứng dụng Windows độc lập để gán nhãn ảnh với sự hỗ trợ của AI. Dự án không điều khiển Robot và không thay đổi các chương trình Vision/Studio hiện có.

## Chức năng đã triển khai

- Dự án riêng, quản lý class và thuộc tính mở rộng.
- Nhập ảnh/thư mục, sao chép ảnh vào workspace và bỏ qua file trùng SHA-256.
- Tính nhanh độ sáng/độ tương phản khi nhập.
- Trình duyệt ảnh phân trang 50 thumbnail/lần, tự cuộn và làm nổi ảnh đang chọn khi dùng ảnh trước/sau; dự án video hàng nghìn ảnh không còn dựng toàn bộ widget lúc khởi động.
- Canvas zoom bằng chuột hoặc cụm điều khiển ở góc dưới phải, hiển thị phần trăm, căn giữa, vừa ảnh và kéo ảnh để quan sát vùng khuất.
- RECT có tám tay nắm sửa cạnh/góc và có thể kéo cả hộp; SEG/OBB/ORI đi kèm được biến đổi đồng bộ khi RECT đổi.
- Một đối tượng có thể lưu đồng thời RECT, SEG, OBB và ORI (hướng đầu–đuôi hai điểm).
- Quản lý nguồn nhãn `manual`, `yolo`, `sam2`, confidence và model version.
- Auto-label hàng loạt bằng Ultralytics YOLO trên CPU hoặc NVIDIA CUDA.
- Auto-label đọc đầu ra đúng task: boxes/RECT, masks/SEG, OBB và keypoints/ORI.
- SAM2 tùy chọn: tự phát hiện config thực sự có trong package, kiểm tra cặp checkpoint/config và chuyển `RECT → SEG`; có thể dùng `SEG → RECT` để trở về bounding box được giữ lại.
- Quản lý Class trực quan: thêm/xóa an toàn, đổi tên và chọn màu; tạo không giới hạn nhóm thuộc tính cùng lựa chọn riêng.
- Xóa ảnh khỏi dự án cùng toàn bộ nhãn, tọa độ, thuộc tính và trạng thái liên quan; không xóa ảnh nguồn ban đầu.
- Xóa an toàn toàn bộ ảnh của lần nhập thành công gần nhất bằng một lần xác nhận; hiển thị trước số ảnh, số nhãn, thời gian và nguồn rút gọn, đồng thời luôn giữ ảnh/video nguồn ban đầu.
- Lọc ảnh thông minh cho cả frame video và ảnh nhập/thư mục: mặc định chỉ quét lượt nhập mới nhất, có tùy chọn bao gồm dữ liệu cũ; dùng model đang hoạt động kết hợp OpenCV để nhóm ảnh nên giữ, ảnh gần trùng, ảnh trống và ảnh chất lượng kém; giữ một tỷ lệ negative sample, bảo vệ ảnh đã có nhãn/đã duyệt và cho duyệt lại trước khi xóa.
- Mỗi nhóm thuộc tính có tên, giá trị mặc định, cờ bắt buộc và mục đích `metadata`, `classification` hoặc quy tắc `OK/NG`.
- Dấu tick trong trang Gán nhãn là công tắc chế độ: tắt để train định vị Detection/SEG/OBB/ORI; bật để hiện thuộc tính và train Classification hai giai đoạn trên crop vật.
- Export Classification tự cắt từng vật theo RECT, chia train/val/test theo giá trị của một nhóm thuộc tính và dùng `yolo11n-cls.pt`.
- Có thể tick nhiều nhóm thuộc tính để ứng dụng tự export và train tuần tự; các `best.pt` được gom vào một gói ZIP kèm manifest nhưng vẫn giữ label space độc lập.
- Danh sách tick thuộc tính dùng chung giữa Dataset, Train và xuất RKNN; tick một nhóm cũng chạy bằng cùng luồng hàng loạt, không còn dropdown/nút train đơn trùng chức năng.
- Khi tắt Classification, toàn bộ điều khiển chỉ dành cho thuộc tính được ẩn và ứng dụng trở về luồng định vị Detection/SEG/OBB/ORI.
- Tooltip giải thích khi rê chuột lên nút chức năng.
- Trang **Dự án** chia công cụ thành ba khung theo luồng làm việc: **Nhập dữ liệu**, **Kiểm tra & dọn**, **Cấu hình nhãn**; cột công cụ tự cuộn ở cửa sổ thấp. Tooltip đổi theo loại project và giải thích chi tiết giới hạn của nhập ảnh/video, `CaptureManifestV1`, Hydro QA, lọc, xóa batch và quản lý thuộc tính.
- Trạng thái ảnh đầy đủ: duyệt, bỏ duyệt, từ chối và khôi phục.
- Thuộc tính `condition`, `occlusion`, trạng thái duyệt từng nhãn và từng ảnh.
- Kiểm tra lỗi cấu trúc nhãn.
- Tạo snapshot metadata dataset.
- Export COCO và bốn task YOLO: Detection/RECT, Segmentation/SEG, OBB và Pose/ORI.
- Khóa Train/Validation/Test bằng `split_assignment.json`; giữ nguyên capture group cũ, đưa nhóm mới vào Train và chỉ phân lại 70/15/15 khi người dùng chủ động tạo Benchmark mới.
- Có ba chiến lược train: phát triển với Val/Test cố định; Final Train+Val giữ Test; và Final 100% có xác nhận cảnh báo.
- Train YOLO trong tiến trình riêng; giao diện không bị khóa.
- Nút Train tự export dataset của dự án theo task hiện tại: định vị tạo YOLO `data.yaml`, Classification tạo crop theo các nhóm đã tick. Trang Dataset chỉ còn cần cho export thủ công/kiểm tra.
- Khi tách frame video, ứng dụng đọc tổng số frame, đề xuất khoảng lấy để tạo tối đa khoảng 500 ảnh và cảnh báo nếu lựa chọn dự kiến vượt ngưỡng này.
- Kiểm tra task dataset và kiến trúc model trước khi train RECT/SEG/OBB/ORI.
- Sau train, tự đăng ký `best.pt` mới nhất và chọn làm model Auto-label.
- Khung đánh giá tách rõ model và Dataset, mặc định dùng `best.pt` mới nhất trên tập test; hiển thị tổng và từng Class, đồng thời lưu JSON/confusion matrix/đường PR trong `runs/evaluations`.
- Sau train, `.pt` tự lưu vào kho nội bộ cho Auto-Label; trang Train chỉ cần thêm nút xuất `.rknn` ra vị trí người dùng chọn để nạp vào Radxa.
- Bộ chuyển RKNN Linux x86 cô lập bằng Docker, cố định RKNN Toolkit 2.2.0; hỗ trợ Detection 9 output, Segmentation 13 output và Classification softmax 1 output trên RK3588.
- Có thể xuất RKNN tuần tự cho mọi nhóm đã tick và tạo gói triển khai kèm `vision_bundle.json`; runtime Radxa chưa được sửa tự động.
- Tự nhận CUDA và hiển thị thông tin phần cứng/runtime.

## Khởi động nhanh

Máy hiện tại đã có các thư viện chính:

```bat
cd /d D:\DeltaX\SmartLabelStudio
python run.py
```

Hoặc chạy `setup.bat`, sau đó `run.bat`.

Đóng gói bản Windows bằng `build_windows.bat`. Model và workspace được giữ ngoài file EXE để có thể cập nhật, sao lưu và thay model độc lập.

## CPU và RTX 4060 Ti

- Máy không có GPU: chọn `auto` hoặc `cpu`. YOLO chạy CPU; SAM2 có thể rất chậm.
- Máy RTX 4060 Ti: cài NVIDIA Driver và bản PyTorch CUDA phù hợp từ trang PyTorch. Mở trang **PHẦN CỨNG** và xác nhận `CUDA NVIDIA: CÓ` trước khi chọn `cuda`.
- Train không chạy trong luồng giao diện. Có thể dừng job từ trang **TRAIN**.

## SAM2

SAM2 là thành phần tùy chọn, không cần thiết để dùng chức năng box/polygon hoặc auto-label YOLO.

Trong trang **AUTO-LABEL**, có thể nhấn **Tải SAM2 Small tương thích** để tải checkpoint chính thức phù hợp với package hiện tại, hoặc tự chọn một file `.pt`/`.pth`. Không để ô checkpoint trống và không chọn thư mục. Ứng dụng tự đọc config trong package. Với package đang có trên máy này, config là:

```text
sam2_hiera_s.yaml
```

Với dự án mới chưa có model, chọn Class và loại nhãn **RECT/SEG/OBB**, bật **SAM ON**, rồi bấm một điểm lên vật. SAM2 tạo mask từ điểm và ứng dụng tự chuyển sang hình học đã chọn; bấm vào vùng đã có nhãn chỉ chọn nhãn đó để tránh tạo trùng. Với **ORI**, SAM tách biên trước rồi yêu cầu bấm thêm một điểm về phía đầu/nắp.

Để tinh chỉnh nhãn có sẵn, chọn một box và nhấn **SAM2 → SEG**, sau đó dùng **SAM +/−**. SAM2 luôn dự đoán mask; ứng dụng chuyển mask thành polygon Segmentation. Nếu chỉ làm Object Detection, nhấn **SEG → RECT** để bỏ polygon và dùng lại bounding box trước đó. Checkpoint SAM2.1 phải đi cùng package/config SAM2.1; không dùng chéo với config SAM2 đời đầu. Nếu checkpoint thiếu hoặc sai, ứng dụng dừng trước khi nạp model và hiển thị hướng dẫn thay vì lỗi hệ thống.

## Dữ liệu

```text
workspace/
├── models/                         # model được đăng ký
└── projects/<project_id>/
    ├── project.json                # class, ảnh và annotation
    ├── images/                     # bản sao ảnh nguồn
    ├── versions/                   # snapshot dataset
    ├── exports/                    # COCO/YOLO
    ├── runs/                       # kết quả train
    ├── bundles/                    # gói nhiều classifier .pt + manifest
    └── cache/                      # embedding/thumbnail tương lai
```

File `.rknn` không được sao chép vào `workspace/models`. Khi xuất RKNN, ứng dụng luôn mở hộp thoại **Save As** để người dùng chọn thư mục triển khai riêng. File này được nạp vào Radxa bằng **DeltaX Studio → Vision AI Setting**.

File `project.json` được ghi qua file tạm rồi thay thế để giảm nguy cơ hỏng dữ liệu khi mất điện giữa lúc lưu.

## Nguyên tắc dữ liệu

- `class` mô tả loại vật: `Chai_trong`, `Chai_lo`, `Chai_xanh_la`.
- Biến dạng không tạo class mới; dùng `condition=nguyen_ven|bep_nhe|can_dep|vo_nat`.
- Nhãn AI chỉ là bản nháp.
- Mặc định chỉ ảnh `reviewed` được export.
- Không thay đổi thứ tự class đã được dùng để train.

`OK` (Good/Pass) là sản phẩm hoặc ảnh đạt yêu cầu kiểm tra. `NG` (No Good/Fail) là không đạt, ví dụ sai loại, thiếu nắp, hỏng hoặc nằm ngoài dung sai. Một nhóm `OK/NG` có thể được chọn để train Classification. Classifier được lưu riêng và không thay model định vị; Radxa vẫn cần bổ sung bước crop → classifier → đọc thuộc tính trước khi dùng kết quả này.

Chi tiết contract cần bổ sung trên Radxa nằm tại [docs/RADXA_CLASSIFICATION_INTEGRATION.md](docs/RADXA_CLASSIFICATION_INTEGRATION.md).

Xem hướng dẫn chi tiết tại [docs/HUONG_DAN_SU_DUNG.md](docs/HUONG_DAN_SU_DUNG.md).

## Hydroponic Slot Condition

Luồng Hydro được bổ sung bằng mẫu cấu hình trên chính hộp thoại **Dự án mới**, không tạo một loại project
hay một engine train thứ hai. Chọn `Hydroponic · mẫu Classification 10 slot`; project chai/robot cũ vẫn
giữ nguyên Classification theo crop annotation và RKNN/RK3588 như trước.

Trong project Hydro, hai thao tác chuyên biệt được đặt theo đúng giai đoạn sử dụng:

- Trang **Dự án** có **Nhập CaptureManifestV1**: kiểm tra checksum, lineage, hình học ROI/slot, ID trùng và đủ đúng 10
  slot trước khi nhập. Ảnh slot, full frame và hai ROI đều được sao chép vào project để provenance
  không còn phụ thuộc máy capture; export không chứa đường dẫn tuyệt đối.
- Trang **Kiểm duyệt** có **Kiểm tra Dataset Hydro**: báo ảnh hỏng/trùng/thiếu, nhãn mâu thuẫn, phân bố nhãn, leakage theo
  `plant_instance_id`, crop-cycle holdout ngay trong vùng kết quả bên dưới; chọn dòng lỗi rồi mở thẳng ảnh để sửa,
  không bật thêm cửa sổ QA.

Khi tạo project bằng mẫu Hydro, nhập **tên cây hiển thị** và `cropCode`; giá trị mặc định là
**Cải ngọt cọng xanh** (`cai_ngot`). Đây là định danh cây của vụ trồng và model bundle, không phải
một classifier nhận dạng loài cây. Hydro vẫn dùng Classification toàn ảnh slot với ba nhóm độc lập
`plant_presence` (hiển thị theo cây đã cấu hình), `yellow_leaf` và
`wilt`; công tắc Classification bị khóa ON để không vô tình quay về Detection/SEG. `uncertain` và
`not_applicable` không vào train. Khi cây không hiện diện, hai condition tự chuyển thành
`not_applicable`. `other_abnormal` chỉ là ghi chú phục vụ đánh nhãn, chưa được train.

Trang **Triển khai** của project Hydro xuất ba ONNX static batch 1 rồi tạo `HydroModelBundleV1`
với camera/geometry IDs, checksum, preprocessing và từng cặp ngưỡng low/high đã hiệu chỉnh. Studio
đồng thời tạo file `.zip` portable cạnh thư mục bundle để tải trực tiếp tại **HydroFlow → Cài đặt → AI → Model AI đang chạy**. Có hai
runtime đích: Windows ONNX Runtime CPU để kiểm thử toàn tuyến ở chế độ `shadow` (không kích hoạt
cảnh báo), và Jetson Nano TensorRT FP16. Khoảng giữa hai ngưỡng được runtime trả về `uncertain`;
TensorRT engine chỉ build/smoke-test trên Jetson. Các nút RKNN/Radxa cũ vẫn giữ nguyên cho project
thường và không hiện trong project Hydro.

Schema project là v2. Project v1 cũ được migrate trong bộ nhớ khi mở và chỉ ghi an toàn khi người
dùng lưu. Có thể đặt biến `SMARTLABEL_WORKSPACE` để chạy thử trên workspace tách biệt; nếu không đặt,
ứng dụng vẫn dùng thư mục `workspace` cũ nên toàn bộ dự án hiện có được giữ nguyên.

Để kiểm tra kỹ thuật toàn tuyến mà không giả vờ đây là model nông học đã đạt, có thể chạy
`python -m tools.hydro_pipeline_smoke --workspace workspace --manifest <manifest.json>`. Công cụ tạo
một project mới, không sửa project cũ; nó sinh các biến thể condition có đánh dấu
`pipeline_smoke_only`, chạy đúng importer/export/train/ONNX/bundle và chỉ cho phép bundle Windows
ở chế độ `shadow`.

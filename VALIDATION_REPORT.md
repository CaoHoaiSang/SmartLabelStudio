# Báo cáo kiểm tra — 2026-08-05

## Phạm vi

- Dự án mới: `D:\DeltaX\SmartLabelStudio`.
- Không sửa hoặc xóa dự án Vision Lab/vải hiện có.
- Dữ liệu demo: 126 ảnh.
- Model: YOLO Detection `best.pt`, ba class.

## Kết quả

| Kiểm tra | Kết quả |
|---|---|
| Compile toàn bộ module Python | Đạt |
| Khởi tạo giao diện CustomTkinter | Đạt |
| Nạp dự án demo | 126/126 ảnh |
| Loại ảnh trùng SHA-256 khi chạy bootstrap lần hai | 126 ảnh được bỏ qua đúng |
| Nạp model YOLO | Đúng task Detection, đúng 3 class |
| Auto-label CPU trên 126 ảnh | 148 detection, 0 lỗi, 14.61 giây |
| Lưu/đọc lại project | Đạt |
| Export YOLO Detection | Đạt unit test |
| Export COCO | Đạt unit test |
| Kiểm tra box ngoài ảnh | Đạt unit test |
| Hardware probe | CPU hoạt động; CUDA không có trên máy hiện tại |
| Checkpoint SAM2 trống/thư mục | Bị chặn trước khi nạp model; không còn `Permission denied` |
| Danh sách thumbnail và focus ảnh | Đạt với 126 ảnh; ảnh trước/sau chọn và cuộn đúng dòng |
| Zoom, phần trăm và pan ảnh | Đạt kiểm tra hồi quy |
| Đổi bộ lọc thumbnail sau lần nạp đầu | Khoảng 6–8 ms với 126 ảnh |
| Đổi trạng thái một ảnh | Khoảng 42 ms trong kiểm tra giao diện |
| Chỉnh RECT bằng kéo hộp/tám tay nắm | Đạt; hình học phụ biến đổi đồng bộ |
| Export OBB và ORI/Pose | Đạt kiểm tra định dạng và `data.yaml` |
| Auto-label đọc mask và keypoint theo task | Đạt unit test |
| Docker Linux x86 / RKNN Toolkit | Đạt · image `deltax-rknn-converter:2.2.0-v2` · amd64 |
| So cấu trúc với `Chai_Nhua.rknn` mẫu | Đạt · compiler 2.2.0 · input 640 · 9 output DET |
| Nạp model mới bằng RKNN Runtime trên Rock 5C | Đạt · target RK3588 |
| Suy luận bằng chính `YOLORKNN` của DeltaX | Đạt · model mẫu và model mới cùng phát hiện 1 chai |
| Xuất RKNN Segmentation | Đạt · 13 output · mask coefficients/prototype đúng layout |
| Chạy SEG bằng `SegRKNNPredictor` trên Rock 5C | Đạt · trả box và mask |

## Trạng thái demo

- 126 ảnh ở trạng thái `draft` để người dùng kiểm tra.
- 148 nhãn do YOLO đề xuất:
  - `Chai_trong`: 51
  - `Chai_lo`: 51
  - `Chai_xanh_la`: 46
- Không ảnh nào bị model bỏ trống ở ngưỡng confidence 0.25.
- Dữ liệu được chia thành 33 capture group dựa trên phút chụp để phục vụ split chống rò rỉ.

## Phần tùy chọn chưa thể xác nhận trên máy hiện tại

- CUDA/RTX 4060 Ti: cần chạy lại Hardware probe trên máy Công ty sau khi cài PyTorch CUDA.
- SAM2: adapter, giao diện box/điểm dương/điểm âm và chuyển mask sang polygon đã có; cần cài package SAM2 và checkpoint để chạy thực tế.
- Train dài: luồng train và dừng job đã được triển khai; không train model mới từ các nhãn AI chưa được người dùng duyệt.

## Kiểm tra hồi quy giao diện 2026-08-05

- Nút ảnh trước/sau đồng bộ đúng index, selection, scroll và focus của danh sách.
- Ảnh mở từ hàng đợi Active Learning hiển thị đúng tên file và focus trong danh sách.
- Nhãn đang chọn được nhớ riêng theo ảnh; dấu kiểm nhãn còn nguyên khi đi sang ảnh khác rồi quay lại.
- Duyệt → bỏ duyệt → từ chối → khôi phục trả đúng trạng thái `reviewed/draft/rejected/draft`.
- Cửa sổ quản lý nhận đúng 3 Class và các nhóm thuộc tính 4/3/3.
- Package trên máy là `samv2 0.0.4`, có bốn config SAM2 đời đầu. Hydra của package này tìm trực tiếp trong `sam2/configs`, nên ứng dụng hiện tự chọn tên đúng `sam2_hiera_s.yaml` thay cho đường dẫn SAM2.1 không tồn tại.
- Đã dựng thành công model `SAM2Base` trên CPU bằng config tự phát hiện; lỗi `Cannot find primary config` đã được tái hiện và loại bỏ.
- Nếu người dùng chọn checkpoint SAM2.1 trong khi package chỉ có SAM2 đời đầu, ứng dụng báo lỗi tương thích bằng tiếng Việt trước khi gọi Hydra.
- Ô checkpoint trống không còn bị `Path("")` diễn giải thành thư mục hiện tại. Cả giao diện và adapter đều yêu cầu một file `.pt`/`.pth` thật.
- Có nút tải checkpoint SAM2 Hiera Small chính thức, hiển thị tiến độ và chỉ thay file đích sau khi tải hoàn tất.
- Danh sách ảnh đã chuyển sang thumbnail với badge mềm `CHƯA NHÃN/NHÁP/ĐÃ DUYỆT/TỪ CHỐI`; ảnh đang chọn có focus riêng.
- Cụm zoom nổi ở góc dưới phải hiển thị phần trăm; hỗ trợ fit, căn giữa, lăn chuột và kéo ảnh.
- Thumbnail được giữ trong bộ nhớ và widget được tái sử dụng; bộ lọc không còn phá/tạo lại 126 dòng.
- Nút `SAM2 → SEG` thể hiện đúng đầu ra mask của SAM2; nút `SEG → RECT` đưa nhãn về bounding box cũ và có thể hoàn tác.
- Đã thêm bốn chế độ RECT, SEG, OBB và ORI. ORI được export/train dưới task Pose với hai keypoint.
- Trang Train kiểm tra sự khớp nhau giữa task dataset và kiến trúc model trước khi chạy.
- Nút disabled dùng nền/viền/chữ xám riêng; nút enabled giữ màu hành động và chữ sáng.
- Sau train thành công, `best.pt` mới nhất được đăng ký vào `workspace/models` và chọn cho Auto-label.
- `best.pt` được đăng ký nội bộ tự động; đã bỏ nút lưu PT trùng lặp. Nút triển khai chỉ xuất RKNN ra đường dẫn ngoài và không thể lẫn vào Auto-label.
- File kiểm chứng `Chai_Nhua_deltax.rknn` chạy trên Radxa với confidence 0,9946 trên ảnh thử; file mẫu trả 0,9893. Thời gian nạp + suy luận đầu tiên tương ứng khoảng 224 ms và 383 ms trong lần đo này.
- Model RKNN mới được kiểm tra bằng `/home/radxa/deltax_pp_sw/venv/bin/python3` và package `ultralytics_rknn-new` đang chạy thực tế; không thay model Studio hay dịch vụ sản xuất.
- SEG RKNN mới được so với checkpoint `.pt` trên cùng ảnh: ba detection trên ngưỡng khớp dưới khoảng 1–2 px và tạo mask hợp lệ. Hai detection PT sát ngưỡng 0,25 bị RKNN FP16 loại do confidence giảm nhẹ; cần hiệu chỉnh confidence bằng tập validation trước khi sản xuất.

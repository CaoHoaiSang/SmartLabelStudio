# Popup và nguồn ảnh SmartLabel — 23/09/2026

## Quyết định giao diện

- Giữ CustomTkinter5.2.2/Python3.10.11 hiện có trên Windows; không đổi framework,
  không cài dependency mới. Kiểm thử DPI bằng tính toán/widget, chưa nghiệm thu
  trên nhiều màn hình vật lý hoặc Linux/Nano.
- Nền navy `#0b151f`, thẻ `#142333`, viền `#294153`; điểm nhấn xanh ngọc.
- Segoe UI: nội dung tối thiểu 13 px logic, tiêu đề nhóm 15 px, tiêu đề popup 20 px.
  Nút/ô nhập tối thiểu 34 px, bo 8 px; thẻ bo 12 px. Màu cảnh báo và lỗi tách riêng.
- Popup nằm giữa cửa sổ sở hữu, giới hạn trong work area của **màn hình đang chứa
  SmartLabel**, có tính DPI và taskbar; không ép tất cả về màn hình chính.
- Tiêu đề, nội dung, hành động phân vùng rõ. Nội dung dài cuộn; footer được dành
  chỗ trước nội dung để nút đóng/xác nhận không bị đẩy ra ngoài màn hình.
- Fleet là cửa sổ con **không modal**: luôn thuộc SmartLabel, nâng một lần sau
  callback titlebar của CTk, không đặt always-on-top toàn hệ điều hành. Đóng
  cửa sổ không hủy job nhận ảnh do app sở hữu.
- Popup modal: Esc/X chạy đúng hàm đóng hiện có. Đang xử lý vẫn phải dừng/chờ
  worker; không bypass busy guard. Popup con đóng thì trả grab cho popup cha.
- Thông báo/trợ giúp/xác nhận/nhập chữ hoặc số dùng giao diện chung. X/Esc không
  đồng nghĩa xác nhận. Hộp chọn tệp/thư mục/màu vẫn là hộp chuẩn Windows.

## Danh sách ảnh và Dataset

Nguồn ảnh: **Giàn · Bổ trợ · Khách đóng góp · Bộ TEST**. Bốn nút dạng 2×2
dưới tiêu đề danh sách, không nén bốn tên vào segmented control 124 px. Trạng
thái chọn đi theo nguồn app đã chấp nhận, không tự đổi trước khi xử lý nhãn
chưa lưu hoặc kiểm quyền Fleet. Giá trị nội bộ `TEST` và các filter không đổi.

Hai tác vụ giữ trong **Dataset → Bộ kiểm định độc lập**, cùng hàng:

1. **Thu thập ảnh TEST** — chụp lô riêng, xem trước, lưu, chuyển sang gán nhãn.
2. **Bộ TEST ngoài** — tạo/nhập bộ ảnh đã duyệt, đánh giá checkpoint, duyệt bằng chứng.

Không đặt các tác vụ này ở Dự án: Dự án giữ tổng quan, Dataset phụ trách dữ
liệu phát triển/kiểm định. Nhóm tác vụ TEST ẩn với project không phải Hydro.

## Ngữ nghĩa thống kê — không chỉ đổi màu

Thẻ thuộc tính dùng chung bố cục: tiêu đề trái, chip Có/Không phải, lý do chưa
tính bên dưới. Không gộp ba nguồn thành một bộ train:

| Nguồn | Chip Có/Không tính gì? | Không tự làm |
|---|---|---|
| Giàn | Nhãn trên ảnh rọ đã duyệt; giữ chi tiết TRAIN/VAL/TEST hiện hữu | Không đổi split |
| Bổ trợ | Nhãn đã duyệt **và đang bật dùng TRAIN** | Không đưa vào VAL/TEST |
| Bộ TEST | Nhãn đã duyệt trong kho thu TEST riêng | Không gán nhãn từ khai báo rọ trống, không cộng vào TRAIN/VAL |

Bản benchmark đóng băng hoặc nhập ngoài được quản lý tại Bộ TEST ngoài,
không cộng lặp vào số ảnh thu thập. Nguồn lỗi/không khớp schema có thông báo,
không giả thành dữ liệu rỗng hợp lệ. Không chạy model hoặc đọc pixel để tính
các thống kê này. Dữ liệu/nhãn thật và cổng QA/checkpoint giữ nguyên.

## Kiểm chứng và giới hạn

Các test thêm tại `tests/test_dialog_design_system.py`: vị trí/DPI giả lập
1–2×, màn hình âm, chữ nguồn 2×2 ở sidebar hẹp, Fleet transient/no grab/no
topmost, popup lồng nhau, trợ giúp dài/cuộn, input sai/hủy, footer khi thu nhỏ,
thống kê TEST dựa vào nhãn chứ không bố trí. Các cửa sổ Tk được chạy trên
project tạm; không dùng dự án người dùng để thử ghi.
Thêm test trong `test_hydro_review_ui.py` cho nhóm tác vụ TEST theo project.
Bản cuối362/362test đạt463,296s (13test mới); compileall và diff check đạt.
Suite cũ còn cảnh báo timer Tk khi hủy root; không có test thất bại.

Công cụ chụp cửa sổ Windows trả `SetIsBorderRequired / 0x80004002`; đã thử
phục hồi một lần nhưng vẫn lỗi. Đây là rà soát source + ảnh người dùng cung
cấp + kiểm thử widget/geometry, **chưa phải nghiệm thu hình ảnh ứng dụng đang
mở hoặc nhiều màn hình vật lý**. Lưu công việc rồi mở lại SmartLabel để nạp
source mới. Không tự đóng app vì có thể còn nhãn chưa lưu.

Tham chiếu chính thức tra ngày 23/09/2026:
[TkDocs — Toplevel/ownership/grab](https://tkdocs.com/tutorial/windows.html),
[CustomTkinter — CTkToplevel](https://customtkinter.tomschimansky.com/documentation/windows/toplevel/).
Chỉ áp dụng vào CTk hiện cài; không nâng cấp framework để sửa bố cục.

# Popup và nguồn ảnh SmartLabel — 23/09/2026

## Quyết định giao diện

- Giữ CustomTkinter5.2.2/Python3.10.11 hiện có trên Windows; không đổi framework,
  không cài dependency mới. Kiểm thử DPI bằng tính toán/widget, chưa nghiệm thu
  trên nhiều màn hình vật lý hoặc Linux/Nano.
- Nền navy `#0a131c`, thẻ `#142333`, viền `#294153`; **mọi tiêu đề popup/nhóm
  popup dùng cyan `#22b9ee`** như Quản lý nhãn dự án. Màu trạng thái giữ riêng.
- Segoe UI: nội dung tối thiểu 13 px logic, tiêu đề nhóm 15 px, tiêu đề popup 20 px.
  Nút/ô nhập tối thiểu 34 px, bo 8 px; thẻ bo 12 px. Màu cảnh báo và lỗi tách riêng.
- Popup nằm giữa cửa sổ sở hữu, giới hạn trong work area của **màn hình đang chứa
  SmartLabel**, có tính DPI và taskbar; không ép tất cả về màn hình chính.
- Tiêu đề, nội dung, hành động phân vùng rõ. Nội dung dài cuộn; footer được dành
  chỗ trước nội dung để nút đóng/xác nhận không bị đẩy ra ngoài màn hình.
- `StudioToplevel` xác lập owner khi còn ẩn, dựng nội dung rồi mới hiện. Giữ
  titlebar chuẩn hệ điều hành; tắt riêng chu kỳ withdraw/update/revert màu
  titlebar của CTk5.2 trên lớp popup này để tránh hiện lại phía sau cửa sổ chính.
  Không gọi lại transient lúc cửa sổ đang hiện (Tk/Windows có thể làm nó ẩn).
- Fleet là cửa sổ con **không modal**: luôn thuộc SmartLabel, không đặt
  always-on-top toàn hệ điều hành. Đóng
  cửa sổ không hủy job nhận ảnh do app sở hữu.
- Popup modal: Esc/X chạy đúng hàm đóng hiện có. Đang xử lý vẫn phải dừng/chờ
  worker; không bypass busy guard. Popup con đóng thì trả grab cho popup cha.
- Thông báo/trợ giúp/xác nhận/nhập chữ hoặc số dùng giao diện chung. X/Esc không
  đồng nghĩa xác nhận. Hộp chọn tệp/thư mục/màu vẫn là hộp chuẩn Windows.

### Hiện hành: nền Hydro, ô nhập đen và phạm vi dropdown — 23/09

- Nền bao quanh và canvas của vùng cuộn popup dùng `#0a131c`, cùng màu với
  Thuộc tính toàn ảnh Hydro. Thẻ nội dung vẫn `#142333`; viền `#294153`.
  Khởi tạo StudioToplevel với đúng nền trước khi dựng con; không chỉ tô frame
  bên ngoài rồi để canvas Tk bên trong màu xám. Tiêu đề giữ cyan `#22b9ee`.
- `StudioEntry` dùng nền đen `#05090d`, viền mỏng, chữ sáng. Áp dụng cả ô tạo
  động khi thêm Class/giá trị; không đổi validation, trạng thái khóa hoặc nội dung.
  Kích thước ô ở màn hình chính giữ mặc định, popup giữ chiều cao34px.
- Dropdown **không thay toàn ứng dụng**. Các menu chung (project, bộ lọc, SAM,
  task/device/chiến lược train, phân tập) và thuộc tính bài định vị trở lại
  CTkOptionMenu gốc. Chỉ luồng Hydro cụ thể dùng StudioOptionMenu mới.
- Menu Hydro nền tối liền với nút mở, danh sách inset8px, hàng tối thiểu34px
  bo7px, lựa chọn hiện tại có nền và focus bàn phím có viền riêng. Tên dài
  xuống dòng; menu có cuộn, giữ chiều cao tối đa360px và nằm trong workarea.
  Giữ Enter/Esc/Tab/mũi tên, thêm Home/End/PageUp/PageDown. Không bind_all,
  không chạm clipboard, không cướp grab của popup cha sau khi đóng.
- Quản lý nhãn: toolbar dùng grid với cột hướng dẫn weight1, không lấy chính
  chiều rộng nội dung để co wraplength. Hướng dẫn mặc định gom một vùng ngang;
  mỗi tình trạng có tiêu đề/hành động, mặc định, bảng tên giá trị/ý nghĩa.
  Contract cố định trình bày ngắn; chi tiết mã vẫn thu gọn. Không đổi schema,
  ý nghĩa Có/Không, model, default/required hoặc điều kiện xóa/đổi tên.
- Thùng rác điều chỉnh chiều cao theo số dự án trong giới hạn320–600px,
  nền canvas đồng nhất; không thay hành vi khôi phục.

### Lịch sử: bổ sung sau phản hồi về mật độ bố cục — 23/09

- Đoạn mô tả xếp dọc phải `fill=x`; bỏ việc tự thu hẹp theo kích thước chữ.
  Bỏ qua Configure1px tạm thời và nhãn ẩn; fit khi Map. Không áp callback wrap
  mới cho các ô số liệu tổng quan: giữ cơ chế resize hiện có để tránh hàng
  nghìn lượt vẽ lại lúc app khởi tạo.
- Style chỉ configure font/kích thước nếu khác chuẩn, không vẽ lại toàn bộ
  widget không cần thiết. Đếm Class một lượt thay vì quét lại ảnh cho mỗi Class.
- Không thêm nhiều tầng thông báo hoặc bỏ các cảnh báo an toàn để giảm chiều cao.
  Gom hai nút trợ giúp ngưỡng trên một hàng; ngày gieo/số cây cạnh nhau; bộ lọc
  phân tập/vụ/chọn nhóm cùng hàng. Thẻ và control có khoảng đệm12–16px.
- Bản trước dùng `StudioOptionMenu` toàn ứng dụng (đã thu hẹp phạm vi ở mục hiện hành), giữ nguyên API CTkOptionMenu:
  nền navy, mũi tên riêng, menu tối cùng chiều rộng tối thiểu với ô chọn, inset8px,
  dấu chọn hiện tại, cuộn danh sách/tên dài; phím mũi tên/Enter/Esc/Tab.
  Nhấn ngoài/hết focus/ẩn owner/đổi values hoặc variable/hủy widget đều đóng
  mà không chọn nhầm. Grab chỉ cục bộ và trả về modal cha; không bind_all.
  Python3.10 unbind(funcid) xóa tất cả callback cùng sự kiện, nên chỉ gỡ dòng
  Tcl của callback popup; giữ nguyên callback resize/focus của CTk.
- Dự án đã xóa dùng cửa sổ riêng chung chuẩn: tên, số ảnh, nút khôi phục và
  trạng thái thùng rác trống. Không thêm xóa vĩnh viễn hoặc đổi cơ chế khôi phục.

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
**Phân tập cố định** và **Bộ kiểm định độc lập** nằm trong hai cột cùng hàng,
cùng chiều cao khi vùng nội dung đủ840px logic; hẹp hơn tự xếp dọc. Khi đổi
project không phải Hydro, nhóm phân tập chiếm toàn chiều rộng.

## Ngữ nghĩa thống kê — không chỉ đổi màu

Thẻ thuộc tính dùng chung bố cục: tiêu đề trái, chip Có/Không phải, lý do chưa
tính bên dưới. Không gộp ba nguồn thành một bộ train:
Mỗi nguồn có nền nhóm riêng: Giàn `#142a3c`, Bổ trợ `#132b31`, TEST `#1c243b`.

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

Đợt nền Hydro/label editor: toàn bộ377/377test đạt487,693s. Sau chỉnh hủy
idle-layout cuối, nhóm popup **27/27 đạt66,337s** trên mã cuối; không gọi lượt
377test trước đó là lượt đầy đủ378test. Thêm kiểm toolbar650/980/1100px,
canvas/input đen, menu native sau đổi project, cuộn hàng100 và đóng menu ngay.
Clipboard test được chặn bằng mock; không dùng clipboard người dùng làm fixture.

Các test thêm tại `tests/test_dialog_design_system.py`: vị trí/DPI giả lập
1–2×, màn hình âm, chữ nguồn 2×2 ở sidebar hẹp, Fleet transient/no grab/no
topmost, popup lồng nhau, trợ giúp dài/cuộn, input sai/hủy, footer khi thu nhỏ,
thống kê TEST dựa vào nhãn chứ không bố trí. Các cửa sổ Tk được chạy trên
project tạm; không dùng dự án người dùng để thử ghi.
Thêm test trong `test_hydro_review_ui.py` cho nhóm tác vụ TEST theo project.
Mốc trước phản hồi:362/362test đạt463,296s. Đợt sửa mật độ/dropdown thêm10test
về chiều rộng mô tả, style idempotent, inset, thùng rác/z-order, hai cột,
dropdown/grab/keyboard/cleanup và bảo toàn nút xóa thuộc tính khi thu nhỏ.
22/22test giao diện dùng chung và20/20test Hydro review đạt trước lượt toàn bộ.
Bản cuối **372/372test đạt392,383s**, compileall/diff check đạt. Lượt đầu371/372
phát hiện hồi quy redraw tổng quan, đã loại bỏ và chạy lại; không tăng timeout
hay sửa điều kiện bài kiểm tra xuất model. Suite vẫn có cảnh báo teardown Tk
đã có ở baseline (after/ThemeChanged), không có assertion thất bại ở bản cuối.
`tools/profile_dialog_layout.py` chạy project tạm: thời gian constructor quản lý
nhãn1964ms→590ms, mô tả96×119px→940×28px. Đây là một phép đo fixture có profiler,
không phải cam kết thời gian trên project thật hoặc toàn bộ độ trễ đến lúc vẽ xong.

Công cụ chụp cửa sổ Windows trả `SetIsBorderRequired / 0x80004002`; đã thử
phục hồi một lần nhưng vẫn lỗi. Đây là rà soát source + ảnh người dùng cung
cấp + kiểm thử widget/geometry, **chưa phải nghiệm thu hình ảnh ứng dụng đang
mở hoặc nhiều màn hình vật lý**. Lưu công việc rồi mở lại SmartLabel để nạp
source mới. Không tự đóng app vì có thể còn nhãn chưa lưu.

Tham chiếu chính thức tra ngày 23/09/2026:
[TkDocs — Toplevel/ownership/grab](https://tkdocs.com/tutorial/windows.html),
[CustomTkinter — CTkToplevel](https://customtkinter.tomschimansky.com/documentation/windows/toplevel/).
[Tk — wm/transient](https://www.tcl-lang.org/man/tcl9.0/TkCmd/wm.html) dùng để
đối chiếu khái niệm ownership; hành vi thực tế kiểm ở Tcl/Tk của Python3.10
đang cài, không suy ra tương thích Tk9.
Chỉ áp dụng vào CTk hiện cài; không nâng cấp framework để sửa bố cục.

Đợt nền/dropdown tiếp theo đối chiếu tài liệu chính thức ngày23/09/2026:
[CTkOptionMenu](https://customtkinter.tomschimansky.com/documentation/widgets/optionmenu/),
[CTkScrollableFrame](https://customtkinter.tomschimansky.com/documentation/widgets/scrollableframe/).
Source CTk5.2.2 thực cài xác nhận vùng cuộn có `_parent_canvas` riêng và chỉ
`configure(fg_color=...)` trên scroll widget mới cập nhật đủ các bề mặt.

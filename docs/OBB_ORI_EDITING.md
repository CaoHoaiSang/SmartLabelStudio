# OBB và hướng ORI — sửa luồng thao tác 08/10/2026

## Nguyên nhân

Không phải chỉ do thao tác của người dùng. Trước sửa, `Đặt hướng ORI`
luôn chuyển bộ chọn hình học sang ORI, nhưng canvas ORI chỉ vẽ bbox RECT,
không vẽ bốn góc OBB đang lưu. Dữ liệu OBB không bị xóa ở bước này; cách
hiển thị khiến người dùng thấy khung đổi. Kéo/chỉnh kích thước trước đó chỉ
được nối cho RECT, chưa có tay nắm hoặc thao tác xoay OBB/đổi đầu mũi tên.
Chuyển sang thao tác tay chưa vô hiệu hóa kết quả SAM điểm đang chạy.

## Quy trình gán nhãn gói mì

1. Chọn Class, chọn **OBB**, bật **SAM ON**, bấm lên vật và chờ SAM xong.
2. Nếu cần chỉnh khung: bấm **Chọn** hoặc bấm lại vật đã có nhãn. SAM chuyển
   OFF để thao tác tay, không tạo thêm nhãn trùng. Bật SAM ON lại khi muốn
   tạo nhãn vật mới.
3. Kéo bên trong khung để di chuyển; kéo ô trắng ở góc/cạnh để chỉnh kích
   thước. Kéo chấm trắng tròn nằm ngoài một cạnh để xoay OBB. Giữ **Shift**
   khi xoay để bám góc tuyệt đối theo nấc 15°. OBB không được phép đi ra
   ngoài ảnh khi xoay/đổi kích thước; giữ vị trí hợp lệ cuối cùng.
4. Nhấn **Đặt hướng ORI**. Khi đang xem OBB, vẫn giữ nguyên chế độ và khung
   OBB, không chuyển thành RECT. SAM OFF; bấm phía đầu/đuôi mong muốn.
5. **Bám trục khung** mặc định bật: mũi tên chọn chiều gần điểm bấm nhất
   trong bốn chiều của hai trục OBB. Hai chiều ngược nhau khác nhau, vì ORI
   mang hướng 360°, còn góc OBB không tự phân biệt đầu–đuôi. Nếu cần hướng
   không song song cạnh, tắt công tắc này. RECT không có OBB thì dùng trục X/Y.
6. Đặt hướng xong tự trở lại công cụ Chọn. Kéo **chấm vàng ở đầu mũi tên**
   để sửa hướng; khung OBB không thay đổi. Có thể bật/tắt bám trục khi sửa.
7. Khi di chuyển, xoay hoặc đổi kích thước khung OBB, các hình học đi kèm
   (SEG, bbox và ORI) biến đổi theo cùng vật. Bbox được tính lại bao ngoài
   OBB khi chỉnh kích thước/xoay. Sửa nhãn chuyển về nháp, cần duyệt lại.

Chọn lại RECT/SEG/OBB/ORI chỉ đổi cách xem, không xóa dữ liệu đã lưu. ORI
hiển thị khung OBB nếu vật đã có OBB; nhãn RECT thuần vẫn dùng khung RECT.
OBB có ORI hiển thị cả khung và mũi tên. Ctrl+Z/Ctrl+Y áp dụng cho chỉnh
khung/hướng; chuột phải hủy lượt kéo chưa thả. Space+kéo để pan ảnh, không
sửa nhãn. Cửa sổ đọc-only không cho sửa hình học.

## Phạm vi bảo toàn

Không đổi schema Project/Annotation, class, hợp đồng model, exporter OBB
(bốn góc), exporter ORI/Pose (bbox + hai keypoint), ngưỡng train, phân tập,
dữ liệu/project thật hoặc quyền Fleet/Hydro. Không train hoặc tải model mới.
Lựa chọn bám trục được lưu trong settings của app; mặc định mới không tự
đổi hướng của các nhãn cũ, chỉ áp dụng khi người dùng đặt/kéo hướng.

Kết quả SAM điểm/refine đến sau khi bắt đầu thao tác tay không được áp
dụng. Chạy SAM ON trên vật chưa có nhãn vẫn giữ luồng tạo nhiều vật liên
tiếp; chỉ khi chọn vật có sẵn/Chọn/Đặt ORI mới chuyển sang thao tác tay.

## Kiểm chứng

Bài kiểm thử dùng ảnh/vật tổng hợp, Tk thật và project tạm, không sửa ảnh mì
hay workspace của người dùng. Lượt baseline 16 ca: 12 failure, 1 error và
3 đạt; tái hiện chuyển view, SAM đến trễ và các thao tác chưa hỗ trợ.
Thêm kiểm bám bốn chiều trên nhiều góc, giữ chiều đầu–đuôi, tọa độ biên,
khung vuông góc/kích thước tối thiểu, undo/redo/hủy, read-only, pan/zoom,
RECT cũ, lưu rồi đọc lại và xuất đúng định dạng OBB/Pose hiện có.

Trạng thái full Windows và GitHub Actions được ghi riêng trong báo cáo
bàn giao; không coi fixture SAM là kiểm chất lượng mask trên gói mì thật.
Nhóm cuối 33/33 ca mới đạt tại Windows; lượt full đầu 600/600 đạt trong
489,289 giây. Sau bổ sung bảo toàn redo/lịch sử khi hủy kéo, đang chạy lại
full cuối và CI đúng commit; không dùng lượt full trước thay bằng chứng này.
Windows dùng bộ vector LF đã được giữ trong audit 07/10 để tránh CRLF của
checkout làm sai checksum; giữ nguyên parser/checksum/assertion và Git config.
Phiên app đã mở phải lưu việc và mở lại để Python nạp source mới; không
cưỡng bức đóng phiên đang gán nhãn.

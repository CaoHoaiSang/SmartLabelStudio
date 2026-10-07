# Điều hướng sau khi từ chối ảnh — 07/10/2026

Khi đổi trạng thái khiến ảnh đang xem không còn thuộc bộ lọc, SmartLabel
chọn ảnh phù hợp kế tiếp theo thứ tự nguồn. Nếu không còn ảnh phía sau,
chọn ảnh phù hợp gần nhất phía trước. Nếu bộ lọc không còn ảnh, xóa khung
xem và vô hiệu hóa các nút duyệt ảnh; không tự đổi bộ lọc.

Quy tắc dùng chung cho ảnh dự án (Giàn và dự án thông thường), Bổ trợ và
TEST. Trang danh sách, thumbnail được chọn và ảnh trên canvas đồng bộ theo
ảnh thay thế, kể cả khi ảnh nằm ở trang khác. Ở bộ lọc Tất cả, ảnh bị từ
chối vẫn thuộc danh sách nên giữ ảnh đang xem để có thể khôi phục ngay.

Nguyên nhân trước sửa: `_sync_image_list_to_current` chọn ảnh đầu trang
khi ảnh mất khỏi bộ lọc; `SupplementReviewView.finish_save` chọn ảnh đầu
danh sách. Hai luồng nay dùng `adjacent_visible_image_id` và thứ tự nguồn
có sẵn. TEST kế thừa adapter Bổ trợ, không thêm đường lưu riêng.

Không xóa ảnh hoặc nhãn khi từ chối, không thay schema/phân tập/dataset,
không đổi điều kiện train/QA/phát hành. Chỉnh nhãn inline vẫn giữ ảnh đang
sửa nếu mất khỏi bộ lọc; nút Ảnh trước/Ảnh sau và Duyệt + ảnh sau giữ cách
điều hướng hiện có. Lưu bất thành không chuyển ảnh trong luồng sidecar.

Kiểm hồi quy dùng ảnh và project tạm trong `test_hydro_review_ui.py`,
`test_supplement_review_ui.py` và `test_heldout_review_ui.py`: ảnh giữa/cuối,
bộ lọc trạng thái/thuộc tính, ranh giới trang, danh sách rỗng, Tất cả,
project thông thường và TEST cách ly khỏi TRAIN/VAL. Kết quả thực chạy và
CI đúng commit được ghi riêng trong báo cáo AI_KL ngày 07/10/2026.

Kiểm Tk local theo từng nhóm đạt 28/28 ảnh dự án, 25/25 Bổ trợ và 2/2
TEST; 10 ca mới bảo vệ các tình huống nêu trên. Các ca ảnh giữa/cuối đã
thất bại trên source trước sửa và đạt sau sửa. Compileall và diff check
đạt. Đây là kiểm thử ứng dụng với project tạm, chưa thao tác trên phiên
gán nhãn thật đang mở.

Ứng dụng đang mở giữ mã Python đã nạp. Lưu công việc và mở lại SmartLabel
sau cập nhật source để dùng hành vi mới; không tự đóng phiên đang gán nhãn.

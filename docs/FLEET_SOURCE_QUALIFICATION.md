# Kiểm tra nguồn ảnh Fleet — 21/09/2026

Nguồn **Khách đóng góp** vẫn dùng canvas, form nhãn và cơ chế lưu có quản lý
hiện hữu. Phân loại nguồn rõ hơn:

- **Giàn · Hydro qua Fleet**: nguồn gửi bằng Gateway đã xác thực; metadata
  rọ/vụ/cây, giống project, chất lượng và mốc thời gian qua kiểm tra cấu trúc.
- **Bổ trợ · điện thoại khách**: nguồn khách tự xác nhận, không giả ảnh Internet;
  chỉ TRAIN khi dataset được mở sau này, không dùng để đánh giá model.
- **Nguồn cần kiểm tra**: báo lý do cụ thể; cho lưu nháp/từ chối nhưng khóa Duyệt.

Ảnh cha không chia sẻ được ghi đúng như vậy; không báo ảnh cha bị mất, không
tạo ảnh giả hay nới validator ZIP Hydro. Ngày gieo/ngày lên NFT tách riêng,
chưa biết giữ null. Kiểm tra nguồn không chứng minh tuổi cây/nhãn là đúng thực
địa và không thay nghiệm thu chất lượng model.

Giữ ảnh/nhãn ở vùng quản lý Fleet để rút dữ liệu vẫn xóa được, kể cả khi app
đóng; không tự thêm vào project.images. Giàn ở đây là loại nguồn trong vùng
gán nhãn có quản lý, **chưa phải ảnh đã được nhận vào dataset Giàn cũ**.
`trainAllowed:false`; chưa xuất snapshot hoặc train từ nguồn này.

Nhóm chia tập tương lai giữ cả vụ cùng Gateway/thế hệ sở hữu/site/zone; cây
có nhóm chi tiết riêng. Điện thoại không biết vụ thì dùng nhóm bảo thủ toàn
zone, không coi mỗi ảnh là một cây độc lập. Duyệt không tự chia VAL/TEST.

Bộ nhận cũ hoặc dữ liệu thiếu bằng chứng chỉ mở nháp/từ chối; cập nhật bộ nhận
và mở lại phiên để lấy bằng chứng mới, không sửa JSON để vượt khóa. Bằng chứng
được kiểm lại trước/sau lưu, gồm giống/schema project, không dựa vào email.
Không yêu cầu làm lại project/nhãn. Lưu việc trước khi mở lại SmartLabel để
nạp source, không cưỡng bức tắt phiên đang làm việc.

## Kiểm tra trước dataset (không tạo dataset)

Trong hộp Nhận dữ liệu từ Fleet, dán mã đúng project còn hạn rồi chọn **Kiểm
tra nguồn và dữ liệu trước dataset**. Job nền giữ đích, đóng hộp không khóa
chuột/đổi đích. Báo cáo kiểm nguồn/nhãn nhị phân tường minh, ảnh trùng byte và
RGB đã giải mã với project hiện tại (kể cả ảnh mã hóa lại trùng VAL/TEST).
Nhãn partial hợp lệ chỉ tính cho thuộc tính đã có, không tự điền phần thiếu.

Kiểm quyền lại trực tuyến đầu/cuối, gia hạn lease khi cần; thay nhãn, project,
nguồn hay byte ảnh trong lúc kiểm tra thì bỏ kết quả. Không sửa nhãn, split,
ảnh hoặc tạo snapshot. Báo cáo `FleetDatasetReadinessV1` có liên kết đợt/
import/revision/group/hash và mốc kiểm; không chứa ticket/đường dẫn kho.
`sourceReady:true` **không phải quyền train**; vẫn có blocker snapshot và
withdrawal gate chưa hoàn tất. Chỉ kiểm project hiện tại và đợt đang chọn,
chưa quét project khác/snapshot cũ hoặc ảnh gần giống; không dùng để bảo đảm
toàn hệ thống hết rò dữ liệu. Hết mã/mất mạng cần chạy lại, không dùng cache.

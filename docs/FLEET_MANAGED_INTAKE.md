# Nhận dữ liệu từ Fleet — vùng chờ 4b2a, 20/09/2026

Trong project Hydro đã lưu, trang Dự án → **Nhận dữ liệu từ Fleet**. Mở
hộp thư bằng nút trong cửa sổ, chọn đợt được duyệt cho phát triển model,
xác nhận mã project đích và lấy mã nhập 5phút. Dán mã tại SmartLabel trên
máy Windows có bộ nhận Fleet đang chạy. Mã không lưu vào file/log; không
cần cấu hình credential Fleet/Blob trong SmartLabel.

Job nền giữ đích ban đầu, khóa đổi project/Train tới khi xử lý kết quả.
Đóng cửa sổ nhập không hủy job, không giữ modal grab; ứng dụng yêu cầu chờ
job kết thúc trước đóng. Lỗi/mất mạng có thể retry cùng project không trùng.
Phiên staff/hạn mã/quyền chủ/rút ảnh/receipt đều do Fleet kiểm tra lại.

Receiver hiện hữu ghi custody trước copy, kiểm ảnh thật và ghi bền vững
`fleet_inbox/<contributionId>/manifest.json` theo `FleetProjectImportV1`.
Không sửa project.json, project.images, nhãn, split hoặc Bổ trợ hiện hữu.
Nút nhập ảnh/thư mục thường chặn toàn bộ lượt chọn nếu có ảnh từ vùng chờ
hoặc kho Fleet được quản lý (kể cả đường dẫn liên kết), trước khi copy ảnh nào.
Không dùng cách nhập này để bỏ liên kết quyền/provenance. Bản sao thủ công
ngoài hệ thống không nằm trong cam kết quản lý.
Ảnh cha không chia sẻ được giữ đúng trạng thái, không dựng cha giả; nguồn
Hydro/điện thoại và metadata chưa biết giữ nguyên. AI/quality không là nhãn.

**Đây chỉ là vùng chờ, chưa vào giao diện gán nhãn và không dùng train/export.**
`trainAllowed:false`, `review_pending`; các dự án/dataset cũ tiếp tục độc lập.
Không đổi validator CaptureManifestV1/V2 hoặc ZIP Hydro. Không giả ảnh khách
thành ảnh Internet. Không tuyên bố đã hoàn tất đợt4.

Bộ nhận Windows chịu trách nhiệm xóa vùng chờ khi khách rút dữ liệu, kể cả
khi SmartLabel đóng. Hạn lưu30ngày từ nhận vẫn áp dụng cho vùng chờ. Theo
project vào thùng rác SmartLabel được; tự đổi tên/chuyển workspace/mất ổ
đĩa thì chờ xử lý, không ACK đã xóa. Tombstone chặn nhập lại và dọn ảnh
phục hồi tại đường dẫn quản lý; không kiểm soát bản sao thủ công bên ngoài.
Danh sách tại máy chỉ là metadata, không chứng minh quyền/train hiện tại.

Kiểm thử dùng project tạm: API/receiver/ảnh PNG/loopback/module Python thật,
Tk job/close/mất kết nối/retry, giữ nhãn và snapshot không chứa vùng chờ.
Không nhập dữ liệu thử vào workspace người dùng, không gửi ảnh Internet mới.
Để dùng giao diện mới: lưu việc đang làm, đóng rồi mở lại SmartLabel; không
tự đóng ứng dụng đang có việc của người dùng.

Bước tiếp: nguồn gán nhãn khách TRAIN-only, contract Hydro slot-only,
namespace nhóm chia tập, lineage dataset/model và đồng bộ rút quyền trước
export/train/phát hành. Chưa mở các bước đó chỉ vì đã có file trong vùng chờ.

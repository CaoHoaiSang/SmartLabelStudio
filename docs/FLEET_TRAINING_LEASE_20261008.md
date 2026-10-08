# Gia hạn quyền train có managed Fleet — 08/10/2026

Nguồn thật 1.626 Giàn + 108 Bổ trợ + 10 Fleet cần khoảng 23 giây để kiểm lại
snapshot trên máy Windows của chủ. Trước sửa, luồng train và watchdog cùng gọi
`renew_training` mà không khóa; watchdog thức sau 20 giây có thể gặp receiver
bận và tự dừng job dù quyền dữ liệu chưa mất. Fixture đồng bộ bằng Event đã tái
hiện yêu cầu chồng lấn; chưa dùng ảnh thật để train ở bước chẩn đoán.

`TrainingLease.renew()` tuần tự hóa yêu cầu bằng Lock, vẫn kiểm hạn cũ trước và
sau phản hồi, giữ token identity và fail-closed khi quyền hết/rút/mất xác minh.
Sau khi stop, không gửi thêm lượt gia hạn. Khi worker kết thúc, chờ lượt đang
chạy rời receiver (tối đa 65 giây, transport vẫn 60 giây) trước khi parent gọi
finish_train. Nếu thread không kết thúc, worker fail-closed; không báo thành công.
Không tăng thời hạn lease, không cấp grace khi offline, không thay dataset,
model, epoch, split hoặc contract wire.

Regression cô lập: hai luồng không gửi song song, stop không tạo request mới,
exit chờ request đang chạy, phản hồi muộn không hồi sinh lease hết hạn. Không
đọc hoặc sửa project/ảnh của người dùng trong test.

Xác minh Windows: 4/4 test concurrency đạt; nguyên suite 570/570 đạt trong
424,001 giây ở phiên desktop interactive. Lượt qua SSH trước đó có 16 fail,
3 error và 2 skip do môi trường UI; giữ log và chạy lại nguyên suite, không
nới/bỏ test. Test trì hoãn thống kê khi chưa mở Tổng quan cũng đạt.

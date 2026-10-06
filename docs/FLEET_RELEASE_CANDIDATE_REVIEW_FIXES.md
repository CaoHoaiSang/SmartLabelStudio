# Sửa kiểm định candidate Fleet — 06/10/2026

Base `116ff5605dc4e0ad1813ae0c55f1acfcceba231c`, nhánh
`fix/hydro-release-candidate-validation-20261006` trong worktree
`D:/SmartLabel_Worktrees/sol-hydro-release-candidate-20261005`.

## Lỗi và thay đổi

R07: ZIP có checksum đúng nhưng thiếu camera/geometry profile hoặc sai ánh xạ
nhãn vẫn được tạo candidate. Cổng mới kiểm đầy đủ metadata cần cho validator
Hydro: profile, geometry V3, tập model, attribute/outputLabels/positiveIndex/
negativeIndex, batch tĩnh, preprocessing, kích thước đầu vào và normalization.
Operational chưa kiểm định phải có xác nhận tường minh, checkpoint hashes,
thời điểm đọc được trên Nano Python 3.6 và contract hash đúng; model smoke/fixture
không được dùng cho chế độ này.

Thứ tự `present, absent` vẫn hợp lệ khi positiveIndex=0 và negativeIndex=1.
Chỉ số này chỉ đầu ra classifier, không phải số thứ tự ảnh. Không đổi chính sách
loại ảnh, xóa ảnh, nhãn, project, phân tập hoặc điều kiện train. Bản sửa cũ
`4126728` cho phép loại ảnh khỏi tập train không phải nguyên nhân R07.

Các tệp code/test đổi: `smartlabel/hydro_release_candidate.py`,
`tests/test_hydro_release_candidate_prepare.py`, `tests/test_hydro_export.py`.
Không thêm dependency hoặc thay schema candidate V1. Vẫn chỉ Python
`operational_policy.contract_hash` tính ba hash; bộ 33 vector A2 và manifest
SHA-256 `d01a0693119c105d80db0f2f14ed8d86867bcfaada1ec70d80eac566779048b8`
giữ nguyên.

Nguồn đối chiếu ngày 06/10/2026: validator nguồn Hydro tại commit
`c594afed352fa2b6d7ccdde74e692dc7874d8e68`, các tệp
`03_Edge_Server/ai_camera/hydro_ai_camera/model_bundle.py`, `label_schema.py`
và `operational_policy.py`. Không suy luận tính hợp lệ chỉ từ việc khớp hash.

## Kiểm thử cô lập

- Kiểm ngược: hai test mới thất bại trên code trước sửa, tổng cộng 15 subtest
  cho metadata không tương thích hoặc thiếu đồng ý vận hành.
- `python -m unittest discover -s tests -p "test_hydro_release_candidate*.py" -v`:
  33/33 đạt.
- `python -m unittest discover -s tests -p test_hydro_export.py -v`: 20/20 đạt,
  gồm gói ONNX tổng hợp do packager thật tạo, đảo thứ tự nhãn hợp lệ và project/
  split giữ nguyên byte.
- Full suite qua SSH Windows: 467 test, 446 đạt, 16 fail, 3 error, 2 skip có sẵn;
  278,137 giây. Không sửa hoặc bỏ assertion. Cả 19 lỗi thuộc bốn file GUI đã
  tái hiện đúng trên source/test sạch của base `116ff56`: 78 test, 59 đạt,
  16 fail, 3 error trong 115,112 giây. Các lỗi gồm mapping/stacking/kích thước
  cửa sổ và refresh thống kê khi đổi tab. Vì vậy không coi full local là đạt.
- CI dùng toàn bộ suite và Xvfb/Openbox hiện có; kết quả đúng HEAD và URL run
  được ghi riêng trong bảng bàn giao sau push. CI chưa xanh không phải hoàn tất.

## Phát hành và giới hạn

Đã có code và test fixture. Chưa thay ứng dụng đang chạy, phát hành model, tạo
khóa production hoặc chạy thiết bị. Metadata hợp lệ không chứng minh ONNX chạy
được trên phần cứng hoặc độ chính xác nhận diện; Hydro vẫn phải import, kiểm
tương thích, smoke test và xử lý rollback theo P3.

Rollout dự kiến: reviewer duyệt nhánh, CI đúng HEAD đạt, tích hợp cùng pin
SmartLabel mới của Fleet rồi cập nhật ứng dụng trong đợt phát hành riêng.
Rollback code: trở lại commit trước sửa; các ZIP bị từ chối cần sửa metadata/
xuất lại, không bỏ qua kiểm định. Candidate mới chỉ được ghi bên cạnh ZIP sau
khi kiểm tra thành công, không chỉnh dataset của người dùng.

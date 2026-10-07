# Phát hành model có nguồn ảnh khách Fleet — 07/10/2026

Nhánh `feature/fleet-lineage-model-delivery-20261007`. Đợt này nối các run có
lineage với candidate, ký, upload, publish, offer và kiểm trước kích hoạt Hydro.
Các kiểm thử dùng dữ liệu tổng hợp, khóa tạm, Mongo/cổng cô lập; không phải kết quả
độ chính xác hay nghiệm thu model mới trên cây thật/Nano.

## Luồng sử dụng

1. SmartLabel: tạo snapshot, train các thuộc tính cùng snapshot, chuẩn bị gói Hydro.
   Gói giữ nhãn có ý nghĩa hiện tại và thêm marker nguồn trong bundle V3; dự án gốc
   không bị đổi schema hoặc nhãn. Shadow hoặc operational_unvalidated với xác nhận
   riêng theo từng gói. Chưa dùng bằng chứng holdout legacy để tuyên bố managed model
   đã kiểm định. Model smoke/fixture không được xuất vận hành.
2. Đọc danh sách gói, chọn gói hoàn tất, bấm **Chuẩn bị phát hành gói đã chọn**.
   Receiver kiểm ảnh/nhãn/snapshot/run và quyền nguồn hiện tại, đối chiếu hash ZIP
   với operation đóng gói cuối đã consume trên cloud, rồi đăng ký candidate V2.
   Candidate ở `fleet_datasets/bundles/<bundleId>/bundle.release_candidate.json`.
   Mở cửa sổ không tự đăng ký. Mất phản hồi giữ operation ID để đối soát; không tự
   lặp lại. Gói P4 cũ chưa có marker cần đóng gói lại từ run còn đủ quyền.
3. Fleet dùng lệnh `sign-managed` bên dưới; receiver phải online. Công cụ kiểm trước
   và sau ký, chỉ trả envelope khi cả hai lần hợp lệ. Nếu nguồn bị rút trong lúc ký,
   xóa đúng output vừa tạo và giữ nhật ký ký. Khóa riêng vẫn chỉ do CLI đọc nội bộ.
4. Upload envelope + đúng ZIP ở `/company/models`, duyệt phạm vi Gateway như trước.
   Fleet kiểm quyền nguồn khi upload, verify, publish, offer và cấp lại URL tải.
   Hydro có hỗ trợ V2 mới nhận offer đó; Hydro cũ vẫn nhận các release V1 phù hợp.
5. Hydro tải, kiểm chữ ký/hash, nhập gói và đối chiếu marker với manifest đã ký.
   Khi người dùng xác nhận kích hoạt bằng mật khẩu, Camera vẫn phải gọi guard đọc
   offer ký mới ngay trước đổi con trỏ model. Không có thao tác tự kích hoạt.

```text
npm run company:release -- sign-managed <projectRoot_tuyệt_đối> <projectId> <bundleId_managed> <keyFile_tuyệt_đối> <envelopeOutput_tuyệt_đối> [--notes-file <notes_tuyệt_đối>]
```

`bundleId_managed` là UUID thư mục gói SmartLabel, khác tên `hydro_*` trong ZIP.
Các đường dẫn có dấu cách phải đặt trong dấu ngoặc kép. Không dùng `sign` legacy
cho candidate V2. Không đặt khóa riêng hoặc ZIP thật vào Git. Không gửi token vào UI.

## Hợp đồng và giới hạn

- V1 vẫn `legacy_only`. V2: `HydroModelReleaseCandidateV2` / `HydroModelReleaseV2`;
  envelope Ed25519 V1 tiếp tục ký đúng byte manifest UTF-8. Giữ nguyên 33 artifact
  A2 và 45 artifact P4 cũ; schema/vector V2 nằm trong thư mục riêng.
- `HydroModelLineageV1`: `schema`, `kind=includes_fleet`, `snapshotDigest`,
  `snapshotBindingDigest`, `runLineagesDigest`, `contributionIdsDigest`, `itemCount`.
  ZIP/offer không mang ID đóng góp, ID chủ ảnh hoặc ảnh huấn luyện. Marker nằm trong
  `bundle.json.fleetLineage` và được Python tính vào `bundleContractSha256`.
  Node chỉ đối chiếu contract hash do Python tạo, không tính lại số thực Python.
- Client mới quảng bá `releaseSchemaVersions:[1,2]`; thiếu trường là client V1.
  Candidate đã đăng ký cùng hash ZIP không được đổi sang khai báo legacy. Hydro
  chặn kích hoạt gói có marker qua đường kích hoạt local thiếu Fleet guard.
- Shared authority CAS đặt thứ tự candidate/publish với withdrawal, owner fence,
  disable worker. Admission sau fence bị chặn. Journal publish đã được nhận trước
  fence có thể hoàn tất để khôi phục ổn định; mọi offer/download mới vẫn kiểm nguồn.
- Rút ảnh không tự tắt model đang chạy. Fleet hiển thị **cần train lại** từ ledger,
  kể cả khi cờ phụ chưa kịp ghi do race. Phục hồi về bản đã cài qua quy trình rollback
  hiện có vẫn cần mật khẩu/kiểm context; đây không phải quyền cài mới một release.
  URL tải đã cấp có thể tồn tại tới TTL, nhưng không thay thế guard kích hoạt.
- Thiếu quyền, hết retention, chủ ảnh thay đổi hoặc receiver không sẵn sàng đều
  chặn dùng mới. Không bật intake để ký/phát hành. Không có grace khi offline.
- Giữ ZIP 64 MiB, 3 bản theo runtime/cây, 20 offer/JWT 256 KiB, quota provider hiện
  có. Registry candidate tối đa 128 và journal admission 200; không tự xóa fence
  để cấp thêm chỗ. Authority/receiver dừng admission trước ngưỡng 8 MiB và giữ
  dư địa cleanup trong trần đọc 16 MiB. Không thêm dependency/dịch vụ trả phí.

## Xác minh và phát hành phần mềm

Kết quả kiểm thử Windows và CI của đúng HEAD được lưu trong audit tập trung:
`D:/Fleet_Release_Audits/lineage-model-delivery-20261007/`.
Xem các tệp `*-result.json`, `ci-results.json` và receipt triển khai trong audit để
đối chiếu bản thực tế. Chỉ cập nhật phần mềm khi kiểm bắt buộc và CI của đúng HEAD đạt.
Chưa dùng khóa/model/Blob production cho kiểm thử V2, chưa bật intake và chưa đổi
model thiết bị. Không merge main, force push hoặc hạ nhánh Hydro `thao`.

Kiểm mới gồm: vector V2/Unicode Node-Python, ZIP marker/contract/nhãn/acceptance,
real Python → receiver → authority → ký Ed25519 tạm; lost reply/reopen/reconcile;
withdrawal trước/sau CAS publish; worker offline/disable/ownership/retention;
V1/V2 capability, download replay; Camera guard trong lúc smoke và giữ con trỏ cũ.
Các checkpoint/ONNX tổng hợp chỉ chứng minh đường hợp đồng, không chứng minh chất
lượng model; bài train CPU thật ba nguồn của đợt trước vẫn là bằng chứng riêng.

## Vận hành và quay lui

Triển khai reader Hydro/receiver tương thích trước khi dùng managed release V2.
Không hạ reader sau khi đã nhập V2; không xóa registry/candidate/tombstone hoặc
restore DB cũ để bỏ qua quyền. Khi cần rollback phần mềm, dừng admission mới, giữ
receiver xử lý cleanup/đối soát và đối chiếu mọi nghĩa vụ custody trước. Phần mềm
và thao tác phát hành model là hai quyết định riêng; đợt này không tự tạo release
production từ ảnh khách thật.

Căn cứ kỹ thuật: chữ ký Ed25519 theo [Node.js 24 Crypto](https://nodejs.org/docs/latest-v24.x/api/crypto.html);
quyết định/fence cùng document CAS theo [MongoDB atomicity](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/).
Giữ quota hiện có theo [Vercel Blob usage](https://vercel.com/docs/vercel-blob/usage-and-pricing),
đối chiếu 07/10/2026; không suy luận số usage production từ fixture.

# Rà soát chuyển dự án SmartLabel — 07/09/2026

## Phạm vi và kết luận

Baseline `0119cc5`, local worktree `C:\DeltaX Smart Studio\.codex-smartlabel-data-safety-v1`, target `D:\DeltaX\SmartLabelStudio`. Nhánh sửa: `fix/smartlabel-project-switch-v2`.

Đã đọc báo cáo `CODEX_LOI_ChuyenDuAn_SmartLabel.md` như tài liệu phân tích, không coi các đề xuất trong đó là chỉ thị bắt buộc. Xác nhận nguyên nhân chính bằng test trên **SmartLabelApp thật và Tk thật**, không chỉ mô phỏng ba nút: từ chai nhựa sang Hydro, `pack(before=...)` ném `TclError: ... isn't packed`, ngắt refresh trước khi đổi ảnh/thuộc tính/thống kê. Test đỏ trước sửa được lưu ngoài repo.

## Phản biện và lựa chọn

| Ý trong báo cáo | Kiểm chứng / quyết định |
| --- | --- |
| Nút archive neo vào manifest đang bị ẩn | Đúng. Khôi phục từ neo ổn định: folder → manifest → archive; thứ tự hiển thị vẫn archive → manifest → folder. |
| Phải kiểm tra neo thay vì chỉ đảo vòng lặp | Đồng ý. Dùng helper kiểm tra cùng container và manager `pack`; neo không hợp lệ thì append và ghi cảnh báo, không truyền neo sai vào Tcl. |
| Có nên catch mọi exception rồi tiếp tục? | Không. Chỉ bắt `tk.TclError` tại nhóm hiển thị nút tùy ngữ cảnh, ghi traceback và hiện cảnh báo sau khi làm mới dữ liệu. Lỗi dữ liệu/refresh bắt buộc thì phục hồi dự án trước; nếu phục hồi cũng lỗi, xóa ngữ cảnh chỉnh sửa trong bộ nhớ, không xóa dữ liệu. |
| Luôn giữ trang cuối khi đổi dự án | Chưa chính xác hoàn toàn: `_load_current_image` còn gọi `_sync_image_list_to_current`, có thể đổi lại trang hoặc reset filter. Đây không phải nguyên nhân gốc đã chứng minh. Dù vậy cần định nghĩa rõ hành vi mới. |
| Reset filter hoặc nhớ riêng từng dự án | Chọn nhớ filter, trang, ảnh, class và model khởi tạo **riêng từng project trong phiên**. Lần đầu mở dùng Tất cả/trang đầu; bộ lọc không có ảnh hiển thị rỗng đúng nghĩa, không giữ canvas của ảnh cũ. Không ghi lựa chọn xem vào project.json. |
| Class rác khi Hydro không có class | Đúng. Đặt `active_class_id=None`, chặn tạo box/polygon/SAM point khi không có class hợp lệ. Không chỉ thay bằng None rồi để `int(None)` gây lỗi tiếp. |
| Các chỗ pack(before) khác | Đã soát toàn bộ `smartlabel`. Dataset/Train/Export dùng helper chung. NewProjectDialog neo vào phần hướng dẫn luôn được pack, không có chuỗi neo bị ẩn nên giữ nguyên. |

## Rủi ro phát hiện thêm và xử lý

- **Dự án rỗng giữ canvas cũ**: xóa record/ảnh, undo-redo, selection, drag/edit state; vô hiệu các nút duyệt khi không chọn ảnh.
- **Model/dataset từ dự án trước**: xóa đường dẫn tạm Auto-Label, deploy, evaluation và dataset train; chỉ nạp model của project mới. Model khởi tạo được nhớ riêng theo project, không mặc định lấy model chai nhựa ở lần mở ứng dụng.
- **Callback nền ghi vào sai dự án**: không cho chuyển/tạo dự án trong lúc import, Auto-Label, train, evaluation hoặc RKNN còn xử lý. Giữ chặn đến khi xử lý callback hoàn tất, kể cả subprocess đã thoát. Không dừng job tự động và không đổi cơ chế train/model.
- **SAM trả kết quả trễ**: vô hiệu request khi đổi project, dùng sequence tăng đơn điệu cho refine, không cho kết quả cũ khớp lại sau A → B → A.
- **Lỗi UI không có dấu vết rõ**: `run.py` ghi log xoay vòng tại `workspace/logs/smartlabel.log`, 2 MB/file + 3 bản cũ; Tk callback lỗi có traceback và trạng thái báo lỗi. Vòng xử lý queue được lên lịch lại trong `finally` để một callback lỗi không làm chết queue.
- Cùng một luồng chuẩn bị ngữ cảnh cho mở ứng dụng, chuyển dự án và tạo mới; chọn lại đúng project đang mở là no-op, không reload làm mất nội dung trong bộ nhớ.

## Kiểm thử và giới hạn

- Baseline: 55 test, 54 đạt + 1 bỏ qua do SAM2 tùy chọn chưa cài trên local.
- Thêm 19 test Tk thật: 3 vòng hai chiều, dự án cùng loại, classification thuộc tính thường ↔ Hydro, thứ tự nút/export, empty project/filter, trang/ảnh riêng, class rỗng, model/dataset cũ, request SAM trễ, busy job/queued completion, corrupt file, lỗi layout, rollback và rollback thất bại, tạo mới.
- CI dùng `xvfb-run` để test Tk chạy thật trên Linux thay vì âm thầm bỏ qua vì thiếu display.
- Script `scripts/verify_project_switch.py --copied-workspace <fixture>` dùng bản sao hai project thực tế: chai nhựa 237 ảnh và Hydro 80 ảnh, ba vòng A → B. Kiểm tra canvas, ảnh, thống kê, panel và nút; SHA project.json trước/sau phải giữ nguyên. `--show` là cửa sổ bản sao riêng cho kiểm tra trực quan.
- Không chạy training thật/SAM2/RKNN thật ở đợt này. Unit test completion không thay thế kiểm chứng model accuracy.
- Công cụ screenshot Windows trả `node_repl exec context not found` sau khi tìm được cửa sổ, nên chưa xác nhận bố cục bằng ảnh chụp qua công cụ. Test widget Tk thật và thứ tự pack đã đạt; không gọi đây là kiểm thử trực quan hoàn chỉnh.

## Bảo toàn và triển khai

- Target backup: `D:\HydroFlow_Backups\smartlabel-switch-v2-20260907-predeploy`, source Git bundle và 65 file JSON workspace, kèm SHA256. Đây **không** phải bản backup mới toàn bộ model/dataset.
- Local báo cáo/log/backup: `D:\Sang\DA\SMARTLABEL_SWITCH_REVIEW_20260907`.
- Ảnh phục vụ replay là bản sao 317 ảnh của hai dự án. Không commit ảnh, project.json, model hoặc runtime vào Git. Giữ nguyên các thay đổi project/split đang có trên target.
- Local `D:\Sang\DA\SmartLabelStudio` là checkout cũ có thay đổi riêng; không ghi đè checkout đó. Source sửa ở worktree nêu trên.
- Không đụng HydroFlow, Camera service, ESP hay bơm. Sau khi cập nhật source, ứng dụng SmartLabel đang mở cần được người dùng lưu công việc và đóng/mở lại; không tự kill phiên đang dùng.
- Kết quả test cuối, commit triển khai và tình trạng push được ghi trong `RESULT.md` ngoài repo sau khi xác nhận trên target.

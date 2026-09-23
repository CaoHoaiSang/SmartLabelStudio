"""Explain crop-level holdout membership without changing locked assignments."""
from collections import Counter, defaultdict


def training_strategy_guidance():
    return (
        "Chế độ vận hành và mức kiểm định là hai việc riêng. Có thể xuất Vận hành thật khi chưa có TEST độc lập "
        "bằng cách chọn hồ sơ Chưa kiểm định và xác nhận cho từng gói. Hydro vẫn kiểm tra chất lượng ảnh, "
        "tương thích và hai lượt kiểm tra liên tiếp trước cảnh báo. Không coi đây là model đã kiểm định.\n\n"
        "• Final · Train+Val, giữ Test: gộp TRAIN và VAL để học, vẫn giữ TEST. Có thể dùng cho bản vận hành "
        "với xác nhận chưa kiểm định, hoặc với bằng chứng TEST độc lập đúng checkpoint/ngưỡng.\n"
        "• Final · Train 100%: học cả TEST cũ, nên TEST cũ không còn là bằng chứng độc lập. Muốn kiểm định "
        "checkpoint này cần bộ benchmark khác chưa dùng để học hoặc chọn model/ngưỡng. Mở Đánh giá model → "
        "TEST độc lập (chọn bộ…): chọn cả vụ Hydro mới hoặc nhập bộ đã duyệt, cố định ngưỡng, đánh giá đúng checkpoint và duyệt kết quả. "
        "Đổi checkpoint/ngưỡng/schema thì đánh giá lại; không tự coi phân tập hiện tại là bằng chứng.\n\n"
        "Không chuyển ảnh đã học sang TEST rồi dùng checkpoint cũ. QA phân tập cũng không phải độ chính xác model.\n\n"
        "Nếu chỉ kiểm thử gửi ảnh Gmail: dùng Hydro → Kiểm tra tự động → chọn rọ → Phóng to ảnh rọ → "
        "Gửi thử ảnh rọ qua Gmail. Xem trước và xác nhận người nhận; không cần đổi model sang Vận hành. "
        "Backend Hydro phải được cập nhật chức năng gửi thử ảnh."
    )


def holdout_diagnostics(project, assignments):
    cycles = defaultdict(Counter)
    for record in project.images:
        cycle = str(record.metadata.get("cropCycleId") or "").strip() or "unknown"
        group = str(record.metadata.get("plant_instance_id") or record.capture_group or record.id)
        split = assignments.get(group)
        cycles[cycle][split if split in {"train", "val", "test"} else "unassigned"] += 1
    development = {cycle for cycle, counts in cycles.items() if counts["train"] or counts["val"]}
    test = {cycle for cycle, counts in cycles.items() if counts["test"]}
    return {
        "cycles": [{"cropCycleId": cycle, **{s: counts[s] for s in ("train", "val", "test", "unassigned")}}
                   for cycle, counts in sorted(cycles.items())],
        "developmentCycles": sorted(development), "testCycles": sorted(test),
        "overlappingCycles": sorted(test & development),
        "independent": bool(test and test.isdisjoint(development) and "unknown" not in test),
    }


def describe_holdout(report):
    """Shared by dataset QA and package worker; all numbers come from current QA."""
    evidence = report.get("holdout", {})
    cycles = evidence.get("cycles", [])
    lines = ["TEST độc lập phải thuộc vụ không xuất hiện trong TRAIN hoặc VAL; có ảnh của hai vụ chưa đủ."]
    if cycles:
        lines.append(f"Phân tập hiện tại · {len(cycles)} vụ (số ảnh):")
        for row in cycles[:8]:
            title = row["cropCycleId"] if row["cropCycleId"] != "unknown" else "Chưa xác định vụ"
            lines.append(f"• {title}: TRAIN {row['train']} · VAL {row['val']} · TEST {row['test']}"
                         + (f" · chưa chia {row['unassigned']}" if row["unassigned"] else ""))
        if len(cycles) > 8:
            lines.append(f"Còn {len(cycles) - 8} vụ khác; xem chi tiết tại Dataset.")
        if evidence.get("overlappingCycles"):
            lines.append("Chưa đạt: vụ ở TEST cũng có ảnh trong TRAIN/VAL.")
        if not evidence.get("testCycles"):
            lines.append("Chưa đạt: chưa có ảnh được dành cho TEST.")
        if "unknown" in evidence.get("testCycles", []):
            lines.append("Chưa đạt: ảnh TEST chưa xác định được vụ.")
    else:
        lines.append("Chưa có thống kê vụ/phân tập trong báo cáo; chạy lại Kiểm tra Dataset Hydro.")
    lines.extend([
        "Ảnh từ nhóm mới nhập mặc định vào TRAIN để giữ nguyên phân tập đã khóa, không tự tạo TEST.",
        "Cách xử lý: mở Dataset → quản lý phân tập, dành trọn một vụ độc lập cho TEST và kiểm tra nhãn/QA. "
        "Trước khi đổi, đối chiếu dataset đã dùng để train và hiệu chỉnh checkpoint đang xuất. "
        "Ảnh/vụ đã dùng để học không trở thành holdout chỉ bằng cách chuyển sang TEST; cần train lại không dùng vụ đó hoặc thu vụ độc lập khác.",
        "Sau đó đánh giá từng model trên TEST. QA phân tập không phải phép đo độ chính xác model. "
        "Nếu chỉ thử luồng, có thể chủ động chọn Chạy thử (Shadow); hệ thống không tự hạ chế độ.",
        "Final Train+Val vẫn giữ TEST; Train 100% đã dùng TEST cũ để học. "
        "Xem 'TEST, Final Train và thử Email' trong cửa sổ cấu hình gói để chọn đúng luồng.",
    ])
    return "\n".join(lines)

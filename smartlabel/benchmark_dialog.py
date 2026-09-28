"""One project-owned workflow for external TEST import, evaluation and review."""
from copy import deepcopy
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Event
import tkinter as tk
from tkinter import filedialog
from . import studio_dialogs as messagebox
import customtkinter as ctk
from .ui_layout import StudioEntry
from .dropdown import StudioOptionMenu
from .ui_layout import StudioToplevel

from .benchmark_contract import (cycle_rows, export_benchmark, import_benchmark, list_benchmarks,
                                 benchmark_root, validate_benchmark, cycle_title, read_json, inside)
from .external_evaluation import evaluate_external, approve_evaluation, load_evaluation
from .hydro_labels import model_attributes
from .hydro_model_tools import threshold_defaults, file_hash
from .ui_layout import setup_dialog, dialog_header, dialog_section, dialog_footer, wrapped_label, MUTED


class ExternalBenchmarkDialog(StudioToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app, self.project, self.store = app, app.project, app.store
        self.busy, self.report_id = False, None
        self.events, self.cancel = Queue(), Event()
        self.controls = []
        self.title("Bộ TEST ngoài · Đánh giá đúng checkpoint")
        footer = dialog_footer(self)
        ctk.CTkButton(footer, text="Đóng", width=90, height=36, fg_color="#294153", command=self.close).pack(side="right")
        ctk.CTkButton(footer, text="Dừng tác vụ", width=120, height=36, fg_color="#294153", command=self.cancel.set).pack(side="right", padx=8)
        self.status = wrapped_label(footer, "Sẵn sàng", color=MUTED)
        self.status.pack(side="left", fill="x", expand=True, padx=(0, 10))
        dialog_header(self, "Bộ TEST ngoài", "Đánh giá và duyệt bằng chứng cho đúng checkpoint + bộ ngưỡng đã chốt")
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        source = dialog_section(body, "01  ·  Tạo hoặc nhập bộ TEST độc lập",
            "Ảnh đã duyệt từ vụ Hydro hoặc lô TEST riêng. Bộ TEST cách ly; không tự thêm vào TRAIN/VAL hay đổi phân tập.")
        self.cycles = cycle_rows(self.project, only_slots=True)
        self.cycle_list = tk.Listbox(source, height=4, selectmode=tk.EXTENDED, exportselection=False,
                                    font=("Segoe UI", 10), relief="flat", highlightthickness=0,
                                    bg="#0b151f", fg="#e7f3fb", selectbackground="#217fa9")
        self.cycle_list.pack(fill="x", pady=6)
        for row in self.cycles:
            self.cycle_list.insert(tk.END, f"{row['title']} · {row['images']} ảnh / {row['reviewed']} đã duyệt")
        actions = ctk.CTkFrame(source, fg_color="transparent"); actions.pack(fill="x", pady=6)
        self.button(actions, "Tạo bộ TEST từ vụ đã chọn…", self.export).pack(side="left", padx=(0, 8))
        self.button(actions, "Nhập bộ TEST ngoài…", self.select_import).pack(side="left")
        self.benchmark_menu = StudioOptionMenu(source, values=["Chưa nhập bộ TEST"], command=lambda _: self.clear_report(), height=36)
        self.benchmark_menu.pack(fill="x", pady=10); self.controls.append(self.benchmark_menu)
        model = dialog_section(body, "02  ·  Checkpoint và ngưỡng cố định",
            "Low: kết luận Không · High: kết luận Có · Khoảng giữa: Chưa chắc chắn")
        defaults, _ = threshold_defaults(self.project)
        self.thresholds = {}
        for attr in model_attributes(self.project):
            key = attr["id"]; row = ctk.CTkFrame(model, fg_color="#0b151f", corner_radius=8); row.pack(fill="x", pady=4)
            row.grid_columnconfigure(0, weight=1)
            path = Path(self.project.attribute_models.get(key, ""))
            identity = f"{path.name} · SHA256 {file_hash(path)[:12]}…" if path.is_file() else "Chưa chọn checkpoint"
            wrapped_label(row, attr["displayName"], bold=True).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
            wrapped_label(row, identity, size=12, color=MUTED).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
            bounds = ctk.CTkFrame(row, fg_color="transparent")
            bounds.grid(row=0, column=1, rowspan=2, padx=12, pady=10)
            entries = {}
            for col, (name, title) in enumerate((("lowThreshold", "Low"), ("highThreshold", "High"))):
                ctk.CTkLabel(bounds, text=title, font=("Segoe UI", 12), text_color=MUTED).grid(row=0, column=col)
                entry = StudioEntry(bounds, width=72); entry.insert(0, str(defaults[key][name])); entry.grid(row=1, column=col, padx=4)
                entries[name] = entry; self.controls.append(entry)
            self.thresholds[key] = entries
        self.attest = ctk.CTkCheckBox(model, text="Tôi xác nhận TEST chưa dùng để học, chọn model/ngưỡng,\nkể cả các checkpoint cha.", font=("Segoe UI", 13))
        self.attest.pack(anchor="w", pady=10); self.controls.append(self.attest)
        wrapped_label(model, "Kiểm tra ảnh trùng và vụ không chứng minh toàn bộ lịch sử train. Không dùng kết quả TEST để dò ngưỡng.", color="#dca75f").pack(fill="x")
        self.button(model, "Đánh giá checkpoint trên bộ TEST", self.evaluate).pack(anchor="w", pady=(12, 0))
        evidence = dialog_section(body, "03  ·  Xem và duyệt bằng chứng")
        self.report_menu = StudioOptionMenu(evidence, values=["Chưa có báo cáo"], command=self.select_report, height=36)
        self.report_menu.pack(fill="x", pady=6); self.controls.append(self.report_menu)
        self.result = ctk.CTkTextbox(evidence, height=175, font=("Consolas", 13), fg_color="#0b151f", corner_radius=8); self.result.pack(fill="x")
        self.button(evidence, "Duyệt kết quả cho checkpoint và ngưỡng này", self.approve).pack(anchor="w", pady=10)
        wrapped_label(evidence, "QA không phải cam kết độ chính xác. Cần xem số mẫu, lỗi bỏ sót/báo nhầm và độ phủ; mẫu ít có thể không đại diện.", color=MUTED).pack(fill="x")
        self.refresh()
        setup_dialog(self, app, 1000, 820, close=self.close)

    def button(self, parent, title, command):
        button = ctk.CTkButton(parent, text=title, command=command, height=36, corner_radius=8, font=("Segoe UI", 13))
        self.controls.append(button)
        return button

    def owned(self):
        return self.app.project is self.project

    def close(self):
        if self.busy:
            messagebox.showinfo("Đang xử lý", "Nhấn Dừng tác vụ rồi chờ kết thúc trước khi đóng.", parent=self)
            return
        self.grab_release(); self.destroy()

    def refresh(self):
        self.benchmarks = {}
        for identifier in list_benchmarks(self.store, self.project):
            try:
                manifest = read_json(inside(benchmark_root(self.store, self.project, identifier), "benchmark.json"))
                titles = sorted({cycle_title(row["source"]) for row in manifest["records"]})
                label = f"{identifier[10:22]} · {len(manifest['records'])} ảnh · {' / '.join(titles)}"
                self.benchmarks[label] = identifier
            except (ValueError, OSError):
                continue  # Corrupt managed data is never offered for evaluation.
        previous = self.benchmark_menu.get()
        values = list(self.benchmarks) or ["Chưa nhập bộ TEST"]
        self.benchmark_menu.configure(values=values); self.benchmark_menu.set(previous if previous in values else values[0])
        self.reports = {}
        for path in sorted((benchmark_root(self.store, self.project) / "evaluations").glob("evaluation_*.json")):
            try:
                report = load_evaluation(self.project, self.store, path.stem)
                label = f"{report['createdAt']} · {path.stem[11:23]} · TEST {report['benchmarkId'][10:22]}"
                self.reports[label] = path.stem
            except (ValueError, OSError):
                continue
        values = list(self.reports) or ["Chưa có báo cáo"]
        selected = next((label for label, identifier in self.reports.items() if identifier == self.report_id), values[-1])
        self.report_menu.configure(values=values); self.report_menu.set(selected)

    def clear_report(self):
        self.report_id = None
        self.result.delete("1.0", "end")

    def run(self, work, done):
        if self.busy or not self.owned() or not self.app._can_change_project():
            return
        self.busy = self.app.evaluation_running = True
        self.cancel.clear()
        for widget in self.controls: widget.configure(state="disabled")
        def worker():
            try: self.events.put(("done", work()))
            except Exception as error: self.events.put(("error", str(error)))
        try:
            self.thread = Thread(target=worker, daemon=True); self.thread.start()
        except Exception as error:
            self.busy = self.app.evaluation_running = False
            for widget in self.controls: widget.configure(state="normal")
            self.status.configure(text="Không khởi động được tác vụ")
            messagebox.showerror("Tác vụ nền", str(error), parent=self)
            return
        def poll():
            try:
                while True:
                    kind, value = self.events.get_nowait()
                    if kind == "progress":
                        self.status.configure(text=value); continue
                    self.busy = self.app.evaluation_running = False
                    for widget in self.controls: widget.configure(state="normal")
                    if not self.owned():
                        self.status.configure(text="Project đã đổi; không áp dụng kết quả."); return
                    if kind == "error":
                        self.status.configure(text="Chưa hoàn tất")
                        messagebox.showerror("Bộ TEST ngoài", value, parent=self)
                    else:
                        self.status.configure(text="Hoàn tất")
                        try:
                            done(value)
                        except Exception as error:
                            self.status.configure(text="Chưa hoàn tất bước tiếp nhận kết quả")
                            messagebox.showerror("Tiếp nhận kết quả", str(error), parent=self)
                    return
            except Empty: self.after(100, poll)
        self.after(100, poll)

    def progress(self, current, total, title):
        self.events.put(("progress", f"{title} · {current}/{total}"))

    def export(self):
        selected = {self.cycles[i]["key"] for i in self.cycle_list.curselection()}
        if not selected:
            messagebox.showinfo("Chọn vụ", "Chọn vụ đã duyệt để tạo bộ TEST. Không thay đổi TRAIN/VAL/TEST hiện tại.", parent=self); return
        path = filedialog.asksaveasfilename(parent=self, title="Đặt tên thư mục bộ TEST mới", initialfile="hydro_benchmark")
        if not path or not self.owned(): return
        snapshot = deepcopy(self.project)
        self.run(lambda: export_benchmark(snapshot, self.store, selected, path, progress=self.progress, cancel=self.cancel),
                 lambda result: messagebox.showinfo("Đã tạo bộ TEST", f"{result}\nNhập thư mục này ở project chứa checkpoint cần đánh giá.\n"
                     "Ảnh nguồn vẫn giữ phân tập cũ; không train thêm với vụ này nếu cần giữ tính độc lập.", parent=self))

    def select_import(self):
        path = filedialog.askdirectory(parent=self, title="Chọn bộ TEST có benchmark.json")
        if not path or not self.owned(): return
        snapshot = deepcopy(self.project)
        def preview(value):
            manifest, fingerprint = value
            titles = sorted({cycle_title(row["source"]) for row in manifest["records"]})
            if messagebox.askyesno("Nhập bộ TEST?", f"{manifest['cropCode']} · {len(manifest['records'])} ảnh đã duyệt\n"
                                   + "\n".join(titles) + "\n\nLưu bản sao riêng, không thêm vào dữ liệu train. Tiếp tục?", parent=self):
                self.run(lambda: import_benchmark(snapshot, self.store, path, expected_digest=fingerprint, cancel=self.cancel), lambda _: self.refresh())
        self.run(lambda: validate_benchmark(Path(path), snapshot, cancel=self.cancel), preview)

    def evaluate(self):
        identifier = self.benchmarks.get(self.benchmark_menu.get())
        if not identifier: return
        try:
            thresholds = {key: {name: float(entry.get()) for name, entry in entries.items()} for key, entries in self.thresholds.items()}
        except ValueError:
            messagebox.showerror("Ngưỡng không hợp lệ", "Nhập low/high bằng số thập phân 0–1.", parent=self); return
        snapshot, confirmed = deepcopy(self.project), bool(self.attest.get())
        self.clear_report()
        self.run(lambda: evaluate_external(snapshot, self.store, identifier, thresholds,
                 independence_confirmed=confirmed, progress=self.progress, cancel=self.cancel), self.show_evaluation)

    def show_evaluation(self, value):
        self.report_id, report = value
        lines = [f"TEST {report['benchmarkId'][10:22]} · {report['createdAt']}"]
        if report.get("evaluationScope", {}).get("kind") == "reserved_cohort":
            scope = report["evaluationScope"]
            lines.append("LÔ CÂY RIÊNG · Đánh giá theo ảnh, không xác minh danh tính từng cây.\n"
                + ("Cùng đợt gieo với dữ liệu phát triển; không phải kiểm định qua vụ khác.\n"
                   if scope["sameSowingBatchAsDevelopment"] else "Khác đợt gieo theo khai báo người thu thập.\n")
                + f"{scope['declaredPlantCount']} cây khai báo; các ảnh lặp không phải cây độc lập bổ sung.")
        for key, row in report["models"].items():
            m = row["operatingMetrics"]
            lines.append(f"\n{key} · checkpoint {row['checkpointSha256'][:12]} · ngưỡng {row['thresholds']}\n"
                         f"  Có {m['positiveSupport']} / Không {m['negativeSupport']} · chưa chắc {m['uncertain']}/{m['total']} · độ phủ {m['coverage']:.1%}\n"
                         f"  TP {m['tp']} · TN {m['tn']} · FP {m['fp']} · FN {m['fn']} (chỉ mẫu có quyết định)\n"
                         f"  Phát hiện đúng / toàn bộ mẫu Có: {m['positiveDetectionRateAll']:.1%}")
        self.result.delete("1.0", "end"); self.result.insert("1.0", "\n".join(lines)); self.refresh()

    def select_report(self, label):
        identifier = self.reports.get(label)
        if identifier:
            try: self.show_evaluation((identifier, load_evaluation(self.project, self.store, identifier)))
            except Exception as error: messagebox.showerror("Báo cáo", str(error), parent=self)

    def approve(self):
        if not self.report_id or not self.owned():
            messagebox.showinfo("Chưa chọn báo cáo", "Đánh giá hoặc mở một báo cáo trước khi duyệt.", parent=self); return
        if not messagebox.askyesno("Duyệt bằng chứng?", "Bạn đã xem lỗi bỏ sót, báo nhầm, độ phủ và số mẫu?\n"
                "Phê duyệt ghi nhận quyết định kỹ thuật, không chứng minh độ chính xác ngoài bộ TEST này.\n"
                "Sẽ lưu ngưỡng đã đánh giá; đổi model/ngưỡng/schema phải đánh giá lại. Không tự phát hành model.", parent=self): return
        identifier = self.report_id
        self.run(lambda: approve_evaluation(self.project, self.store, identifier, confirmed=True, cancel=self.cancel),
                 lambda _: self.status.configure(text="Đã duyệt bằng chứng · có thể mở Tạo gói Model Hydro"))

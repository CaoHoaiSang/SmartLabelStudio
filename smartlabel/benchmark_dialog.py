"""One project-owned workflow for external TEST import, evaluation and review."""
from copy import deepcopy
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Event
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from .benchmark_contract import (cycle_rows, export_benchmark, import_benchmark, list_benchmarks,
                                 benchmark_root, validate_benchmark, cycle_title, read_json, inside)
from .external_evaluation import evaluate_external, approve_evaluation, load_evaluation
from .hydro_labels import model_attributes
from .hydro_model_tools import threshold_defaults, file_hash


class ExternalBenchmarkDialog(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app, self.project, self.store = app, app.project, app.store
        self.busy, self.report_id = False, None
        self.events, self.cancel = Queue(), Event()
        self.controls = []
        self.title("Bộ TEST ngoài · Đánh giá đúng checkpoint")
        self.geometry("1080x820")
        self.minsize(900, 680)
        self.transient(app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.close)
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(body, text="1. Tạo hoặc nhập bộ TEST độc lập", font=("Arial", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(body, text="Ảnh đã duyệt từ vụ Hydro hoặc lô TEST riêng. Bộ TEST cách ly; không tự thêm vào TRAIN/VAL hay đổi phân tập.",
                     anchor="w").pack(fill="x")
        self.cycles = cycle_rows(self.project, only_slots=True)
        self.cycle_list = tk.Listbox(body, height=4, selectmode=tk.EXTENDED, exportselection=False,
                                    bg="#10212e", fg="#e7f3fb", selectbackground="#217fa9")
        self.cycle_list.pack(fill="x", pady=6)
        for row in self.cycles:
            self.cycle_list.insert(tk.END, f"{row['title']} · {row['images']} ảnh / {row['reviewed']} đã duyệt")
        actions = ctk.CTkFrame(body, fg_color="transparent"); actions.pack(fill="x")
        self.button(actions, "Tạo bộ TEST từ vụ đã chọn…", self.export).pack(side="left", padx=(0, 8))
        self.button(actions, "Nhập bộ TEST ngoài…", self.select_import).pack(side="left")
        self.benchmark_menu = ctk.CTkOptionMenu(body, values=["Chưa nhập bộ TEST"], command=lambda _: self.clear_report())
        self.benchmark_menu.pack(fill="x", pady=10); self.controls.append(self.benchmark_menu)
        ctk.CTkLabel(body, text="2. Cố định checkpoint và ngưỡng trước khi đánh giá", font=("Arial", 18, "bold")).pack(anchor="w")
        defaults, _ = threshold_defaults(self.project)
        self.thresholds = {}
        for attr in model_attributes(self.project):
            key = attr["id"]; row = ctk.CTkFrame(body); row.pack(fill="x", pady=2)
            path = Path(self.project.attribute_models.get(key, ""))
            identity = f"{path.name} · SHA256 {file_hash(path)[:12]}…" if path.is_file() else "Chưa chọn checkpoint"
            ctk.CTkLabel(row, text=f"{attr['displayName']} · {identity}").pack(side="left", padx=8)
            entries = {}
            for name, title in (("highThreshold", "High"), ("lowThreshold", "Low")):
                entry = ctk.CTkEntry(row, width=72); entry.insert(0, str(defaults[key][name])); entry.pack(side="right", padx=4)
                ctk.CTkLabel(row, text=title).pack(side="right")
                entries[name] = entry; self.controls.append(entry)
            self.thresholds[key] = entries
        self.attest = ctk.CTkCheckBox(body, text="Tôi xác nhận TEST chưa dùng để học, chọn model/ngưỡng, kể cả các checkpoint cha.")
        self.attest.pack(anchor="w", pady=10); self.controls.append(self.attest)
        ctk.CTkLabel(body, text="Kiểm tra ảnh trùng và vụ không chứng minh toàn bộ lịch sử train. Không dùng kết quả TEST để dò ngưỡng.",
                     text_color="#dca75f", anchor="w").pack(fill="x")
        self.button(body, "Đánh giá checkpoint trên bộ TEST", self.evaluate).pack(anchor="w", pady=8)
        ctk.CTkLabel(body, text="3. Xem và duyệt bằng chứng", font=("Arial", 18, "bold")).pack(anchor="w")
        self.report_menu = ctk.CTkOptionMenu(body, values=["Chưa có báo cáo"], command=self.select_report)
        self.report_menu.pack(fill="x", pady=6); self.controls.append(self.report_menu)
        self.result = ctk.CTkTextbox(body, height=175, font=("Consolas", 12)); self.result.pack(fill="x")
        self.button(body, "Duyệt kết quả cho đúng checkpoint và ngưỡng này", self.approve).pack(anchor="w", pady=8)
        ctk.CTkLabel(body, text="QA không phải cam kết độ chính xác. Cần xem số mẫu, lỗi bỏ sót/báo nhầm và độ phủ; mẫu ít có thể không đại diện.",
                     anchor="w").pack(fill="x")
        footer = ctk.CTkFrame(self, fg_color="transparent"); footer.pack(fill="x", padx=14, pady=(0, 12))
        self.status = ctk.CTkLabel(footer, text="Sẵn sàng", anchor="w"); self.status.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(footer, text="Dừng tác vụ", width=115, command=self.cancel.set).pack(side="right", padx=5)
        ctk.CTkButton(footer, text="Đóng", width=80, command=self.close).pack(side="right")
        self.refresh()

    def button(self, parent, title, command):
        button = ctk.CTkButton(parent, text=title, command=command)
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

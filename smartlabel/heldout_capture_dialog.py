"""Technician-only TEST acquisition. Hydro has no added menus or operating state."""
from copy import deepcopy
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event
from tkinter import filedialog, messagebox
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from .benchmark_dialog import ExternalBenchmarkDialog
from .benchmark_contract import import_benchmark, read_json, canonical
from . import heldout_collection as storage
from .heldout_camera import prepare_profiles, run_worker
from .ui_layout import center_dialog


class HeldoutCaptureDialog(ctk.CTkToplevel):
    # Same project ownership/cancellation machinery as evaluation jobs.
    run = ExternalBenchmarkDialog.run
    button = ExternalBenchmarkDialog.button
    owned = ExternalBenchmarkDialog.owned

    def __init__(self, app):
        super().__init__(app)
        self.app, self.project, self.store = app, app.project, app.store
        self.busy, self.events, self.cancel, self.controls = False, Queue(), Event(), []
        self.config, self.payload, self.frame, self.preview_image = None, None, None, None
        self.temp = TemporaryDirectory(prefix="smartlabel-heldout-")
        self.empty_vars, self.plant_entries = {}, {}
        self.title("Thu thập TEST · SmartLabel")
        self.geometry("1180x850"); self.minsize(1050, 740)
        center_dialog(self, app, 1180, 850)
        self.transient(app); self.grab_set(); self.protocol("WM_DELETE_WINDOW", self.close)
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(1, weight=1)
        banner = ctk.CTkLabel(self, text="BỘ KIỂM ĐỊNH RIÊNG  ·  Không ghi vào vụ Hydro  ·  Không dùng TRAIN/VAL",
            font=("Segoe UI", 16, "bold"), text_color="#61d5ba", anchor="w")
        banner.grid(row=0, column=0, columnspan=2, padx=18, pady=12, sticky="ew")
        left = ctk.CTkScrollableFrame(self, width=330); left.grid(row=1, column=0, sticky="nsew", padx=(12, 6))
        right = ctk.CTkScrollableFrame(self); right.grid(row=1, column=1, sticky="nsew", padx=(6, 12))
        self.label(left, "1. Lô cây dành riêng cho TEST", bold=True)
        self.lot_menu = ctk.CTkOptionMenu(left, values=["Chưa có lô"], command=self.lot_changed)
        self.lot_menu.pack(fill="x", pady=6); self.controls.append(self.lot_menu)
        self.lot_info = self.label(left, "")
        self.name_entry = self.entry(left, "Tên lô", "16 cây thùng xốp")
        self.date_entry = self.entry(left, "Ngày gieo thật (YYYY-MM-DD)", "")
        self.count_entry = self.entry(left, "Số cây trong lô", "16")
        self.same_batch = self.check(left, "Cùng đợt gieo với cây phát triển model")
        self.same_batch.select()
        self.reserved = self.check(left, "Toàn bộ cây chưa dùng phát triển model;\nchỉ dành lô này cho TEST")
        self.button(left, "Tạo lô TEST", self.create_lot).pack(fill="x", pady=8)
        self.label(left, "Không tạo mùa vụ giả. Vị trí thay đổi được; mã từng cây là tùy chọn.")
        self.label(left, "2. Cấu hình chụp", bold=True)
        self.button(left, "Nạp camera + ROI từ Hydro…", self.select_profiles).pack(fill="x", pady=6)
        self.profile_info = self.label(left, "Chỉ đọc bản sao cấu hình. Không ghi vào Hydro.")
        self.handoff = self.check(left, "Đã dừng riêng dịch vụ Camera và tắt cơ chế\ntự khởi động lại; đã bố trí cây TEST")
        self.label(left, "Không dừng backend/bơm. Chỉ bật Camera lại sau khi trả đúng cây vận hành.")
        self.session_entry = self.entry(left, "Tên lượt chụp (tùy chọn)", "Lượt 1 · 10 cây")
        self.button(left, "Chụp để xem trước", self.capture).pack(fill="x", pady=8)
        self.button(left, "Lưu đủ 10 ROI đã xem", self.save).pack(fill="x", pady=4)
        self.label(left, "Ảnh rọ trống vẫn được lưu. Khai báo bố trí không tự trở thành nhãn đã duyệt.")
        self.label(right, "Xem trước toàn giàn và vị trí ROI", bold=True)
        self.canvas = tk.Canvas(right, width=680, height=383, bg="#0b1820", highlightthickness=0)
        self.canvas.pack(fill="x", pady=8)
        self.canvas.bind("<Configure>", lambda _: self.draw_preview())
        self.quality_info = self.label(right, "Chưa chụp ảnh. Ảnh chỉ được lưu vào lô sau khi bạn xác nhận.")
        presets = ctk.CTkFrame(right, fg_color="transparent"); presets.pack(fill="x", pady=5)
        self.button(presets, "Lượt 1: 10 cây", lambda: self.preset(False)).pack(side="left", padx=(0, 8))
        self.button(presets, "Lượt 2: 6 cây + 4 trống", lambda: self.preset(True)).pack(side="left")
        self.label(right, "Đánh dấu đúng 4 vị trí để trống ở lượt 2; các vị trí được thay đổi mỗi ngày.")
        self.slot_panel = ctk.CTkFrame(right, fg_color="transparent"); self.slot_panel.pack(fill="x", pady=8)
        self.slot_panel.grid_columnconfigure((0, 1), weight=1)
        self.label(right, "3. Duyệt ảnh → tạo bộ TEST", bold=True)
        actions = ctk.CTkFrame(right, fg_color="transparent"); actions.pack(fill="x", pady=8)
        self.button(actions, "Gán nhãn TEST", self.review).pack(side="left", padx=(0, 8))
        self.button(actions, "Tạo & nhập bộ TEST đã duyệt…", self.export).pack(side="left")
        self.label(right, "Dùng form gán nhãn hiện có. Rọ không có cây: Có cây = Không; các dấu hiệu = Không áp dụng.\n"
                         "Cần cả mẫu Có/Không cho mỗi classifier. 16 cây khỏe chưa đủ kiểm định lá vàng và héo.")
        footer = ctk.CTkFrame(self, fg_color="transparent"); footer.grid(row=2, column=0, columnspan=2, sticky="ew", padx=15, pady=10)
        self.status = ctk.CTkLabel(footer, text="Sẵn sàng", anchor="w"); self.status.pack(side="left", expand=True, fill="x")
        ctk.CTkButton(footer, text="Dừng tác vụ", width=115, command=self.cancel.set).pack(side="right", padx=6)
        ctk.CTkButton(footer, text="Đóng", width=80, command=self.close).pack(side="right")
        self.refresh()
        saved = storage.root_for(self.store, self.project) / "acquisition_settings.json"
        if saved.is_file():
            try:
                self.config = read_json(saved)
                self.show_profiles()
            except (ValueError, OSError, KeyError):
                self.config = None

    def label(self, parent, text, bold=False):
        widget = ctk.CTkLabel(parent, text=text, anchor="w", justify="left", wraplength=320 if parent.cget("width") == 330 else 660,
                             font=("Segoe UI", 14, "bold" if bold else "normal"))
        widget.pack(fill="x", pady=(8 if bold else 3, 3)); return widget

    def entry(self, parent, title, value):
        self.label(parent, title)
        widget = ctk.CTkEntry(parent); widget.insert(0, value); widget.pack(fill="x", pady=2)
        self.controls.append(widget); return widget

    def check(self, parent, title):
        widget = ctk.CTkCheckBox(parent, text=title, font=("Segoe UI", 12)); widget.pack(anchor="w", pady=7)
        self.controls.append(widget); return widget

    def refresh(self):
        self.data, self.revision = storage.load_collection(self.store, self.project)
        self.lots = {f"{lot['name']} · {lot['lotId'][-6:]}": lot for lot in self.data["lots"]}
        old = self.lot_menu.get(); values = list(self.lots) or ["Chưa có lô"]
        self.lot_menu.configure(values=values); self.lot_menu.set(old if old in values else values[-1])
        self.show_lot()

    def show_lot(self):
        lot = self.lots.get(self.lot_menu.get())
        if lot:
            rows = [r for r in self.data["images"] if r["source"]["lotId"] == lot["lotId"]]
            self.lot_info.configure(text=f"Gieo {lot['sowingDate']} · {lot['declaredPlantCount']} cây khai báo\n"
                f"{len(rows)} ảnh · {sum(r['reviewStatus'] == 'reviewed' for r in rows)} đã duyệt · "
                + ("cùng đợt gieo" if lot['sameSowingBatchAsDevelopment'] else "khác đợt gieo theo khai báo"))

    def lot_changed(self, _=None):
        self.payload = self.frame = None; self.draw_preview(); self.show_lot()

    def create_lot(self):
        if self.busy or not self.owned(): return
        try:
            lot_id = storage.create_lot(self.store, self.project, self.name_entry.get(), self.date_entry.get(),
                int(self.count_entry.get()), reserved=bool(self.reserved.get()), same_sowing_batch=bool(self.same_batch.get()))
            self.refresh(); self.lot_menu.set(next(k for k, v in self.lots.items() if v["lotId"] == lot_id)); self.lot_changed()
        except (ValueError, OSError) as error:
            messagebox.showerror("Lô TEST", str(error), parent=self)

    def select_profiles(self):
        library = filedialog.askdirectory(parent=self, title="Chọn thư mục ai_camera của Hydro (thư viện đã cài)")
        if not library: return
        camera = filedialog.askopenfilename(parent=self, title="Chọn camera_profile.v1.json", filetypes=[("JSON", "*.json")])
        if not camera: return
        geometry = filedialog.askopenfilename(parent=self, title="Chọn geometry profile hoặc site_profile.v1.json (V2)", filetypes=[("JSON", "*.json")])
        if not geometry: return
        try: config = prepare_profiles(library, camera, geometry)
        except (ValueError, OSError) as error:
            messagebox.showerror("Cấu hình", str(error), parent=self); return
        def done(value):
            self.config = value
            root = storage.root_for(self.store, self.project)
            with storage.collection_lock(root):
                # Ensure TEST marker exists before any images can be written here.
                data, _ = storage.load_collection(self.store, self.project)
                storage.save_collection(root, data)
                path = root / "acquisition_settings.json"
                temporary = root / ".acquisition-settings.tmp"
                temporary.write_text(canonical(value), encoding="utf-8"); temporary.replace(path)
            self.payload = self.frame = None
            self.show_profiles(); self.refresh()
        self.run(lambda: run_worker(config, Path(self.temp.name) / "validation", cancel=self.cancel), done)

    def show_profiles(self):
        self.profile_info.configure(text=f"Camera: {self.config['camera']['profileId']}\nROI: {self.config['geometry']['profileId']}")
        for widget in self.slot_panel.winfo_children():
            if widget in self.controls: self.controls.remove(widget)
            widget.destroy()
        # Remove children from the job-control list before replacing their cards.
        self.controls = [w for w in self.controls if w.winfo_exists()]
        self.empty_vars, self.plant_entries = {}, {}
        for index, slot in enumerate(self.config["geometry"]["slots"]):
            key = slot["slotId"]
            card = ctk.CTkFrame(self.slot_panel); card.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)
            variable = tk.BooleanVar(value=False)
            checkbox = ctk.CTkCheckBox(card, text=f"{key} · Trống", variable=variable, font=("Segoe UI", 12), command=self.draw_preview)
            checkbox.pack(side="left", padx=8, pady=7)
            entry = ctk.CTkEntry(card, width=90, placeholder_text="Mã cây?"); entry.pack(side="right", padx=5)
            self.empty_vars[key] = variable; self.plant_entries[key] = entry
            self.controls.extend((checkbox, entry))

    def preset(self, second):
        for index, (key, value) in enumerate(self.empty_vars.items()):
            value.set(second and index >= 6)
            if value.get(): self.plant_entries[key].delete(0, "end")
        self.session_entry.delete(0, "end")
        self.session_entry.insert(0, "Lượt 2 · 6 cây + 4 trống" if second else "Lượt 1 · 10 cây")
        self.draw_preview()

    def capture(self):
        if not self.config or not self.lots.get(self.lot_menu.get()):
            messagebox.showinfo("Chuẩn bị", "Tạo/chọn lô và nạp cấu hình camera trước.", parent=self); return
        if self.payload and not messagebox.askyesno("Chụp lại?", "Bỏ bản xem trước chưa lưu để chụp ảnh mới?", parent=self): return
        import uuid
        destination = Path(self.temp.name) / uuid.uuid4().hex
        config, confirmed = deepcopy(self.config), bool(self.handoff.get())
        def done(meta):
            self.payload, self.frame = destination, meta
            self.preview_lot = self.lots[self.lot_menu.get()]["lotId"]
            self.refresh()
            self.preview_revision = self.revision
            self.draw_preview()
            self.quality_info.configure(text=f"{meta['capturedAt']} · 10 ROI · Chất lượng: {meta['qualityAssessment'].get('status', 'chưa rõ')}\n"
                "Kiểm tra ảnh và 4 vị trí trống nếu đây là lượt 2. Chưa lưu nhãn, chưa chạy model.")
        self.run(lambda: run_worker(config, destination, capture=True, confirmed=confirmed, cancel=self.cancel), done)

    def draw_preview(self):
        self.canvas.delete("all")
        if not self.payload or not self.frame: return
        with Image.open(self.payload / "full.png") as raw:
            width = max(200, self.canvas.winfo_width()); height = int(width * raw.height / raw.width)
            self.canvas.configure(height=height)
            self.preview_image = ImageTk.PhotoImage(raw.resize((width, height)))
        self.canvas.create_image(0, 0, image=self.preview_image, anchor="nw")
        scale = width / 1920
        for slot in self.frame["slots"]:
            rect = slot["rect"]; key = slot["slotId"]
            x, y, w, h = (rect[k] * scale for k in ("x", "y", "width", "height"))
            empty = self.empty_vars.get(key)
            color = "#b5a6ef" if empty and empty.get() else "#4ce0be"
            self.canvas.create_rectangle(x, y, x+w, y+h, outline=color, width=2)
            self.canvas.create_text(x+3, y+3, text=key, anchor="nw", fill=color, font=("Segoe UI", 10, "bold"))

    def save(self):
        if not self.payload: return
        lot = self.lots.get(self.lot_menu.get())
        if not lot or lot["lotId"] != self.preview_lot:
            messagebox.showerror("Lô thay đổi", "Chụp lại sau khi đổi lô.", parent=self); return
        empty = [k for k, v in self.empty_vars.items() if v.get()]
        if not messagebox.askyesno("Lưu ảnh TEST?", f"Lưu đủ 10 ROI: {10-len(empty)} vị trí có cây theo khai báo, {len(empty)} rọ trống.\n"
            "Khai báo không tự gán nhãn. Không ghi vào vụ Hydro hoặc dữ liệu train.", parent=self): return
        project, payload = deepcopy(self.project), self.payload
        codes = {k: v.get() for k, v in self.plant_entries.items()}
        revision, title = self.preview_revision, self.session_entry.get()
        def done(_):
            self.payload = self.frame = None; self.draw_preview(); self.refresh()
            self.status.configure(text="Đã lưu 10 ROI · mở Gán nhãn TEST để duyệt")
        self.run(lambda: storage.save_capture(self.store, project, lot["lotId"], payload,
            empty_slots=empty, plant_ids=codes, session_name=title, expected_revision=revision), done)

    def review(self):
        if not self.close(): return
        self.app.tabs.set("GÁN NHÃN"); self.app._show_label_workspace("TEST")

    def export(self):
        lot = self.lots.get(self.lot_menu.get())
        if not lot: return
        path = filedialog.asksaveasfilename(parent=self, title="Thư mục bộ TEST mới", initialfile="heldout_benchmark")
        if not path or not self.owned(): return
        confirmed = messagebox.askyesno("Xác nhận độc lập", "Toàn bộ lô này chưa dùng để train, chọn model hoặc ngưỡng, kể cả model cha?\n"
            "Kết quả tính theo ảnh; không coi ảnh lặp là cây độc lập và không giả thành vụ khác.\n"
            "Tạo bản đóng băng từ ảnh đã duyệt; nhãn/kho nguồn giữ nguyên.", parent=self)
        if not confirmed: return
        project = deepcopy(self.project)
        def work():
            storage.export_collection(self.store, project, lot["lotId"], path, confirmed=True, cancel=self.cancel)
            return import_benchmark(project, self.store, path, cancel=self.cancel)
        self.run(work, lambda _: messagebox.showinfo("Đã nhập bộ TEST", "Mở DATASET → Bộ TEST ngoài để đánh giá checkpoint và duyệt kết quả. Chưa tự phát hành model.", parent=self))

    def close(self):
        if self.busy:
            messagebox.showinfo("Đang xử lý", "Dừng tác vụ rồi chờ worker kết thúc trước khi đóng.", parent=self); return False
        if self.payload and not messagebox.askyesno("Ảnh chưa lưu", "Bỏ bản xem trước chưa lưu?", parent=self): return False
        self.grab_release(); self.destroy(); self.temp.cleanup()
        return True

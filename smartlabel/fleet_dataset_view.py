"""Non-modal Dataset/Train workflow. All worker completion stays owned by the app."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from threading import Event, Thread
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .fleet_intake import list_staged
from .hydro_labels import model_attributes
from .ui_layout import StudioToplevel, StudioEntry, setup_dialog, dialog_header, dialog_section, dialog_footer, wrapped_label, MUTED


class DatasetAction:
    def __init__(self, work):
        self.events = Queue()
        self.cancel = Event()
        self.training = None
        self.work = work
        self.thread = None

    def start(self):
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            result = self.work(self)
            self.events.put(('done', result, None))
        except Exception as exc:
            self.events.put(('done', None, str(exc)))

    def stop(self):
        self.cancel.set()
        if self.training:
            self.training.stop()

    def check(self):
        if self.cancel.is_set():
            raise ValueError('Đã dừng; kết quả đang xử lý được receiver giữ để đối soát.')


class FleetDatasetView(StudioToplevel):
    def __init__(self, app, project):
        super().__init__(app)
        self.app, self.project = app, project
        self.client = app.datasets.fleet_dataset(project)
        self.preview_value = self.snapshot = None
        self.selections, self.split_vars, self.snapshot_options = {}, {}, {}
        self.catalog_value = None
        self.closed = False
        self.generation = 0
        self.title('Snapshot dữ liệu khách')
        footer = dialog_footer(self)
        ctk.CTkButton(footer, text='Đóng', height=36, width=95, command=self.close).pack(side='right')
        self.stop_button = ctk.CTkButton(footer, text='Dừng tác vụ', height=36, state='disabled', command=self.stop)
        self.stop_button.pack(side='left')
        dialog_header(self, 'Snapshot dữ liệu khách', project.name)
        body = ctk.CTkScrollableFrame(self, fg_color='transparent')
        body.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        source = dialog_section(body, '01 · Nguồn và phân tập',
            'Chỉ ảnh đã duyệt được chọn. Giữ cả nhóm cùng vụ ở một tập; điện thoại chỉ vào TRAIN. Ảnh và nhãn Giàn cũ được giữ nguyên.')
        self.source_rows = ctk.CTkFrame(source, fg_color='transparent'); self.source_rows.pack(fill='x')
        try:
            rows = list_staged(self.client.root, project.id)
            for row in rows:
                var = tk.BooleanVar(self, True); self.selections[row['contributionId']] = var
                title = f"{'Hydro' if row['source'] == 'hydro_camera' else 'Điện thoại'} · {row['fileCount']} ảnh · {row['contributionId'][:8]}"
                ctk.CTkCheckBox(self.source_rows, text=title, variable=var, command=self.invalidate).pack(anchor='w', pady=4)
            if not rows: wrapped_label(self.source_rows, 'Chưa có đợt trong vùng chờ; nhận và duyệt ảnh trước.').pack(fill='x')
        except Exception as exc:
            wrapped_label(self.source_rows, str(exc)).pack(fill='x')
        self.supplements = tk.BooleanVar(self, True)
        ctk.CTkCheckBox(source, text='Gộp Bổ trợ đã bật và duyệt — chỉ TRAIN',
                        variable=self.supplements, command=self.invalidate).pack(anchor='w', pady=6)
        self.groups = ctk.CTkFrame(source, fg_color='transparent'); self.groups.pack(fill='x', pady=8)
        ctk.CTkButton(source, text='Xem trước và kiểm quyền', height=36, command=self.preview).pack(anchor='w')
        self.summary = wrapped_label(source, 'Chưa kiểm quyền. Mở cửa sổ không tự tạo snapshot.', color=MUTED)
        self.summary.pack(fill='x', pady=8)
        self.confirm = ctk.CTkButton(source, text='Tạo snapshot theo bản xem trước', height=36, state='disabled', command=self.register)
        self.confirm.pack(anchor='e')
        use = dialog_section(body, '02 · Export và train có quản lý',
            'Mỗi lượt kiểm quyền mới. Train cần đủ hai nhãn ở TRAIN và VAL; TEST giữ riêng. Nhãn đã duyệt chưa phải quyền train.')
        self.snapshot_menu = ctk.CTkOptionMenu(use, values=['Chưa chọn snapshot'], command=self.choose_snapshot)
        self.snapshot_menu.pack(fill='x', pady=4)
        ctk.CTkButton(use, text='Đọc snapshot, bản sao và run đã lưu', height=32, fg_color='#294153', command=self.load_catalog).pack(anchor='w', pady=6)
        ctk.CTkButton(use, text='Đối soát lượt trước', height=32, fg_color='#294153', command=self.reconcile).pack(anchor='w', pady=6)
        ctk.CTkButton(use, text='Đóng lượt đã bị chặn / chưa bắt đầu', height=32, fg_color='#294153', command=self.discard_pending).pack(anchor='w', pady=6)
        self.attributes = {a['displayName']: a['id'] for a in model_attributes(project)}
        self.attribute = ctk.CTkOptionMenu(use, values=list(self.attributes))
        self.attribute.pack(fill='x', pady=6)
        self.legacy = tk.BooleanVar(self, True)
        ctk.CTkCheckBox(use, text='Gộp ảnh Giàn đã duyệt theo phân tập đã lưu', variable=self.legacy).pack(anchor='w', pady=6)
        wrapped_label(use, 'Bổ trợ theo lựa chọn lúc tạo snapshot; sửa ảnh, nhãn hoặc nguồn thì cần tạo snapshot mới.', color=MUTED).pack(fill='x')
        self.model = StudioEntry(use, height=34); self.model.insert(0, 'yolo11n-cls.pt'); self.model.pack(fill='x', pady=6)
        wrapped_label(use, 'Model khởi tạo; có thể chọn đường dẫn checkpoint có lineage.', color=MUTED).pack(fill='x')
        params = ctk.CTkFrame(use, fg_color='transparent'); params.pack(fill='x')
        self.parameters = {}
        for column, (name, label, default) in enumerate([('epochs', 'Epoch', '50'), ('batch', 'Batch', '8'), ('image_size', 'Cỡ ảnh', '224')]):
            params.grid_columnconfigure(column, weight=1)
            cell = ctk.CTkFrame(params, fg_color='transparent'); cell.grid(row=0, column=column, sticky='ew', padx=4)
            ctk.CTkLabel(cell, text=label).pack(anchor='w')
            entry = StudioEntry(cell, height=34); entry.insert(0, default); entry.pack(fill='x'); self.parameters[name] = entry
        actions = ctk.CTkFrame(use, fg_color='transparent'); actions.pack(fill='x', pady=10)
        ctk.CTkButton(actions, text='Export có quản lý', height=36, command=self.export).pack(side='left', padx=(0, 8))
        ctk.CTkButton(actions, text='Train thuộc tính', height=36, command=self.train).pack(side='left')
        bundle = dialog_section(body, '03 · Gói model tại máy',
            'Dùng các run hoàn tất cùng snapshot. Gói giữ dấu nguồn và chính sách vận hành đã xác nhận. Chuẩn bị phát hành sẽ kiểm quyền lại; ký và phát hành thực hiện tại Fleet.')
        ctk.CTkButton(bundle, text='Chuẩn bị gói Hydro…', height=36, command=self.bundle).pack(anchor='w')
        self.bundle_menu = ctk.CTkOptionMenu(bundle, values=['Đọc danh sách gói trước'])
        self.bundle_menu.pack(fill='x', pady=6)
        self.bundle_options = {}
        ctk.CTkButton(bundle, text='Chuẩn bị phát hành gói đã chọn', height=36, command=self.prepare_release).pack(anchor='w')
        self.message = wrapped_label(body, 'Mọi kết quả từ danh sách cũ đều phải được kiểm quyền lại trước khi dùng.')
        self.message.pack(fill='x', padx=12, pady=8)
        setup_dialog(self, app, 880, 820, close=self.close, modal=False)

    def invalidate(self, *_):
        self.generation += 1
        self.preview_value = None
        self.confirm.configure(state='disabled')
        self.summary.configure(text='Lựa chọn đã đổi; cần xem trước và kiểm quyền lại.')

    def _launch(self, work, done):
        if self.closed or self.app.project is not self.project or self.app._project_job_busy():
            return False
        generation = self.generation
        action = DatasetAction(work)
        self.app.fleet_dataset_job = action
        self.stop_button.configure(state='normal')
        self.message.configure(text='Đang kiểm quyền và xử lý…')
        def poll():
            if getattr(self.app, 'fleet_dataset_job', None) is not action:
                return
            try:
                kind, result, error = action.events.get_nowait()
            except Empty:
                self.app.after(50, poll)
                return
            if kind == 'progress':
                if not self.closed and self.app.project is self.project and self.winfo_exists():
                    self.message.configure(text=result)
                self.app.after(50, poll)
                return
            self.app.fleet_dataset_job = None
            if self.closed or self.app.project is not self.project or not self.winfo_exists():
                return
            self.stop_button.configure(state='disabled')
            if self.generation != generation:
                self.message.configure(text='Lựa chọn đã đổi; kết quả cũ không thay lựa chọn mới. Xem trạng thái đã lưu để đối soát.')
                return
            if error:
                self.message.configure(text=error)
                return
            done(result)
        try:
            action.start()
            self.app.after(50, poll)
        except Exception:
            self.app.fleet_dataset_job = None
            self.stop_button.configure(state='disabled')
            raise
        return True

    def preview(self):
        ids = [key for key, var in self.selections.items() if var.get()]
        splits = {key: var.get().lower() for key, var in self.split_vars.items()}
        include_supplements = bool(self.supplements.get())
        # Save the current in-memory edits once, on this explicit user action.
        if self.app.project is not self.project or self.app._project_job_busy(): return
        self.app.store.save(self.project)
        def work(action):
            action.check(); self.client.bind(); action.check()
            return self.client.preview(ids, splits, include_supplements=include_supplements)
        def done(value):
            self.preview_value = value
            for widget in self.groups.winfo_children(): widget.destroy()
            self.split_vars = {}
            for group in value['summary']['groups']:
                line = ctk.CTkFrame(self.groups, fg_color='transparent'); line.pack(fill='x', pady=3)
                ctk.CTkLabel(line, text=f"Nhóm {group['groupId'][:10]} · {'Điện thoại' if group['sourceKind'] == 'phone_supplement' else 'Hydro'}").pack(side='left')
                var = tk.StringVar(self, group['split'].upper()); self.split_vars[group['groupId']] = var
                ctk.CTkOptionMenu(line, variable=var, values=['TRAIN'] if group['sourceKind'] == 'phone_supplement' else ['TRAIN', 'VAL', 'TEST'],
                                 command=self.invalidate, width=130).pack(side='right')
            summary = value['summary']
            self.summary.configure(text=f"Đã kiểm lúc {datetime.now():%H:%M:%S} · {summary['imageCount']} ảnh · "
                f"Hydro {summary['sources']['hydro_slot']}, điện thoại {summary['sources']['phone_supplement']}\n"
                f"TRAIN {summary['splits']['train']} · VAL {summary['splits']['val']} · TEST {summary['splits']['test']} · "
                f"{summary['excludedCount']} ảnh chưa duyệt/từ chối bị loại.\n"
                f"Giàn đã duyệt: {summary['legacyCount']} · Bổ trợ TRAIN: {summary.get('supplementCount', 0)}.")
            self.confirm.configure(state='normal'); self.message.configure(text='Kiểm lại nguồn và phân tập trước khi tạo snapshot.')
        self._launch(work, done)

    def register(self):
        if self.preview_value is None: return
        preview = deepcopy(self.preview_value)
        def done(value):
            self.snapshot = value
            label = value['snapshotBindingDigest'][:12]
            self.snapshot_options[label] = value['snapshotBindingDigest']
            self.snapshot_menu.configure(values=list(self.snapshot_options)); self.snapshot_menu.set(label)
            self.confirm.configure(state='disabled')
            self.message.configure(text='Đã tạo snapshot. Chỉ lưu tham chiếu; chưa tạo bản sao ảnh.')
        self._launch(lambda action: (action.check(), self.client.register(preview))[1], done)

    def choose_snapshot(self, label):
        key = self.snapshot_options.get(label)
        self.snapshot = {'snapshotBindingDigest': key} if key else None

    def load_catalog(self):
        def done(value):
            self.catalog_value = value
            self.bundle_options = {b['bundleId']: b['bundleId'] for b in value['bundles'] if b['state'] == 'complete'}
            bundle_labels = list(self.bundle_options) or ['Chưa có gói hoàn tất']
            self.bundle_menu.configure(values=bundle_labels); self.bundle_menu.set(bundle_labels[0])
            self.snapshot_options = {s['snapshotBindingDigest'][:12]: s['snapshotBindingDigest'] for s in value['snapshots'] if s['state'] == 'ready'}
            labels = list(self.snapshot_options) or ['Chưa có snapshot sẵn sàng']
            self.snapshot_menu.configure(values=labels); self.snapshot_menu.set(labels[0]); self.choose_snapshot(labels[0])
            self.message.configure(text=f"Đã đọc {len(value['snapshots'])} snapshot, {len(value['copies'])} bản sao, {len(value['runs'])} run. Đây là trạng thái lưu; quyền sẽ được kiểm lại khi dùng.")
        self._launch(lambda action: (action.check(), self.client.catalog())[1], done)

    def reconcile(self):
        def done(value):
            if value['schemaVersion'] == 'FleetDatasetSnapshotReadyV1':
                self.snapshot = value
                label = value['snapshotBindingDigest'][:12]
                self.snapshot_options[label] = value['snapshotBindingDigest']
                self.snapshot_menu.configure(values=list(self.snapshot_options)); self.snapshot_menu.set(label)
                self.message.configure(text='Đã đối soát snapshot của lượt trước; không tạo bản mới.')
            elif value['schemaVersion'] == 'FleetReleaseCandidateReceiptV1':
                self.message.configure(text='Đã đối soát candidate phát hành. Chưa ký hoặc upload model.')
            elif value['schemaVersion'] == 'FleetBundleFinishedV1':
                self.message.configure(text='Đã đối soát gói shadow của lượt trước: ' + value['bundleId'] + '\nĐọc danh sách gói để chọn Chuẩn bị phát hành.')
            else:
                self.message.configure(text='Đã đối soát bản sao của lượt trước: ' + value['path'] + '\nKhông tự mở train từ receipt này.')
        self._launch(lambda action: (action.check(), self.client.reconcile())[1], done)

    def discard_pending(self):
        self._launch(lambda action: (action.check(), self.client.discard_pending())[1],
            lambda state: self.message.configure(text='Đã đóng lượt trước (' + state + '). Chưa tạo lượt mới.'))

    def _selection(self):
        if not self.snapshot:
            self.message.configure(text='Tạo hoặc chọn snapshot trước.'); return None
        return self.snapshot['snapshotBindingDigest'], self.attributes[self.attribute.get()], bool(self.legacy.get())

    def export(self):
        selected = self._selection()
        if not selected: return
        key, attr, legacy = selected
        self._launch(lambda action: (action.check(), self.client.materialize(key, attr, include_legacy=legacy))[1],
                     lambda value: self.message.configure(text='Đã xuất vào vùng có quản lý: ' + value['path']))

    def train(self):
        selected = self._selection()
        if not selected: return
        try:
            options = {key: int(entry.get()) for key, entry in self.parameters.items()}
        except ValueError:
            self.message.configure(text='Epoch, batch và cỡ ảnh cần là số nguyên.'); return
        if not (1 <= options['epochs'] <= 1000 and 1 <= options['batch'] <= 256 and 32 <= options['image_size'] <= 1024):
            self.message.configure(text='Epoch 1–1000, batch 1–256, cỡ ảnh 32–1024.'); return
        key, attr, legacy = selected; model = self.model.get().strip()
        def work(action):
            from .training import TrainingConfig, TrainingJob
            action.check(); copy = self.client.materialize(key, attr, kind='train_data', include_legacy=legacy)
            action.check(); context = self.client.training_context(copy)
            config = TrainingConfig(model=model, data=copy['path'], project_dir=str(self.client.root / 'fleet_datasets' / 'runs'),
                task='classify', run_name=context['runId'], fleet_dataset=context, **options)
            codes = []
            action.training = TrainingJob(config, lambda line: action.events.put(('progress', line, None)), codes.append)
            action.check(); action.training._run()
            if codes != [0]: raise ValueError('Train chưa hoàn tất hoặc quyền đã mất; run chưa được dùng tạo gói.')
            return context['runId']
        self._launch(work, lambda run_id: self.message.configure(text='Train đã ghi lineage · ' + run_id + '\nDữ liệu QA không thay kết quả kiểm định thực địa.'))

    def bundle(self):
        selected = self._selection()
        if not selected or self.app._project_job_busy(): return
        self._launch(lambda action: (action.check(), self.client.catalog())[1],
                     lambda catalog: self._bundle_config(selected, catalog))

    def _bundle_config(self, selected, catalog):
        from .ui_components import ask_hydro_bundle_config
        from .hydro_model_tools import threshold_defaults
        choices = {}
        for run in catalog['runs']:
            if run['state'] == 'complete' and run['snapshotBindingDigest'] == selected[0]:
                choices[run['attributeId']] = run['runId']
        attrs = model_attributes(self.project)
        if set(choices) != {a['id'] for a in attrs}:
            self.message.configure(text='Cần đủ một run hoàn tất cho mỗi thuộc tính trên cùng snapshot.')
            return
        thresholds, sources = threshold_defaults(self.project)
        defaults = {'modelTitles': {a['id']: a['displayName'] + ' · run ' + choices[a['id']][:8] for a in attrs},
            'datasetVersion': selected[0][:16], 'sourceCommit': self.app._source_commit(),
            'cameraProfileIds': self.project.metadata.get('cameraProfileIds', []),
            'geometryProfileIds': self.project.metadata.get('geometryProfileIds', []),
            'thresholds': thresholds, 'thresholdSources': sources, 'runtimeTarget': 'windows_onnxruntime_cpu',
            'deploymentMode': 'shadow', 'cropDisplayName': self.project.metadata.get('cropDisplayName', ''), 'evaluationPolicy': 'unvalidated_pilot'}
        config = ask_hydro_bundle_config(self, defaults)
        if not config or self.closed or self.app.project is not self.project: return
        project = deepcopy(self.project)
        def work(action):
            from .fleet_hydro_export import build_fleet_hydro_package
            action.check()
            return build_fleet_hydro_package(self.client, project, list(choices.values()), config,
                lambda line: action.events.put(('progress', line, None)), action.cancel)
        self._launch(work, lambda result: self.message.configure(text='Đã tạo gói Hydro và lineage tại: ' + str(result['archive']) + '\nĐọc danh sách gói để chọn Chuẩn bị phát hành.'))

    def prepare_release(self):
        bundle_id = self.bundle_options.get(self.bundle_menu.get())
        if not bundle_id:
            self.message.configure(text='Đọc danh sách và chọn một gói hoàn tất trước.'); return
        self._launch(lambda action: (action.check(), self.client.prepare_release_candidate(bundle_id))[1],
            lambda value: self.message.configure(text='Đã tạo và đăng ký candidate: ' + bundle_id +
                '\nCó thể ký bằng công cụ Fleet. Quyền nguồn sẽ được kiểm lại trước ký, phát hành và cài đặt.'))

    def stop(self):
        action = getattr(self.app, 'fleet_dataset_job', None)
        if action: action.stop()
        self.message.configure(text='Đang dừng; đợi tiến trình đóng trước khi hoàn tất tác vụ.')

    def close(self):
        self.closed = True
        self.destroy()

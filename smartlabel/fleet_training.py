"""Managed classification worker. A watchdog owns the current process only."""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic

from .fleet_dataset import FleetDatasetClient, _safe_path
from .fleet_intake import FleetIntakeError


class TrainingLease:
    def __init__(self, client, context, receipt, *, fatal=None):
        self.client, self.context = client, context
        self.gate_id = receipt['gateTokenId']
        self.deadline = receipt['deadline']
        self.stop_event = Event()
        self.renew_lock = Lock()
        self.fatal = fatal or self._terminate_current_process
        self.thread = None

    @staticmethod
    def _terminate_current_process():
        # The lease belongs to this worker process, never an arbitrary PID from
        # the receiver. OS teardown closes image handles before deletion ACK.
        print('ĐÃ DỪNG · Không kiểm được quyền dữ liệu Fleet.', flush=True)
        os._exit(75)

    def check(self, *_):
        if monotonic() >= self.deadline:
            raise FleetIntakeError('Lease train đã hết hạn; không tiếp tục dùng ảnh.')

    def renew(self):
        # Main-thread checkpoints and the watchdog share one native receiver.
        # A full source proof may exceed the watchdog's 20-second interval.
        with self.renew_lock:
            if self.stop_event.is_set():
                return
            self.check()
            receipt = self.client.renew_training(self.context)
            if receipt['gateTokenId'] != self.gate_id:
                raise FleetIntakeError('Lease đổi lượt train; đang dừng.')
            self.check()  # A late renewal cannot bridge an expired local lease.
            self.deadline = receipt['deadline']

    def _watch(self):
        while not self.stop_event.wait(min(20, max(.05, self.deadline - monotonic() - 2))):
            try:
                self.renew()
            except Exception:
                self.fatal()
                return

    def __enter__(self):
        self.check()
        self.thread = Thread(target=self._watch, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        # Drain the one in-flight request (transport timeout: 60 s) before the
        # worker exits. Otherwise the parent's finish_train hits receiver_busy.
        self.thread.join(timeout=65)
        if self.thread.is_alive():
            self.fatal()
            raise FleetIntakeError('Chưa kết thúc lượt kiểm quyền; không báo train hoàn tất.')


def validate_managed_config(config):
    expected = {'model', 'data', 'project_dir', 'task', 'run_name', 'epochs', 'image_size',
                'batch', 'patience', 'device', 'validate', 'fleet_dataset'}
    if set(config) != expected or config['task'] != 'classify':
        raise FleetIntakeError('Luồng snapshot hiện hỗ trợ Classification với cấu hình tường minh.')
    context = config['fleet_dataset']
    client = FleetDatasetClient.for_training(context)
    _safe_path(config['data'], client.root / 'fleet_datasets' / 'copies' / context['copyId'])
    if config['run_name'] != context['runId']:
        raise FleetIntakeError('Tên run không khớp lượt train đã đăng ký.')
    _safe_path(config['project_dir'], client.root / 'fleet_datasets' / 'runs')
    for key, lower, upper in [('epochs', 1, 1000), ('image_size', 32, 1024), ('batch', 1, 256), ('patience', 0, 1000)]:
        if type(config[key]) is not int or not lower <= config[key] <= upper:
            raise FleetIntakeError('Thông số train ngoài giới hạn pilot.')
    if type(config['validate']) is not bool or not config['validate']:
        raise FleetIntakeError('Train snapshot giữ VAL theo nhóm; chưa hỗ trợ gộp holdout.')
    if not isinstance(config['device'], str) or not (config['device'] in {'cpu', 'auto', 'mps'} or config['device'].isdigit()):
        raise FleetIntakeError('Chỉ dùng một thiết bị cho train snapshot có quản lý.')
    return client


def run_managed_training(config):
    client = validate_managed_config(config)
    config = dict(config)
    if Path(config['model']).is_file():
        config['model'] = str(Path(config['model']).resolve())
    context = config['fleet_dataset']
    receipt = client.begin_training(context, config)  # Before importing/reading weights.
    target = Path(receipt['runPath'])
    with TrainingLease(client, context, receipt) as lease:
        # Isolated settings keep integrations from copying managed customer images
        # into experiment trackers. The user's machine settings are not modified.
        settings_dir = _safe_path(str(target / 'ultralytics-settings'), target / 'ultralytics-settings')
        settings_dir.mkdir()
        os.environ['YOLO_CONFIG_DIR'] = str(settings_dir)
        os.environ['YOLO_OFFLINE'] = 'true'
        os.environ['YOLO_AUTOINSTALL'] = 'false'
        initial_model = receipt['model']
        if receipt['modelSha256'] is not None:
            data = Path(initial_model).read_bytes()
            if hashlib.sha256(data).hexdigest() != receipt['modelSha256']:
                raise FleetIntakeError('Model khởi tạo đã đổi sau gate.')
            initial = target / 'initial.pt'
            with initial.open('xb') as stream: stream.write(data)
            initial_model = str(initial)
            del data
        # A symbolic pretrained name resolves only in this new run, never an
        # unrelated cached file with the same name in the application directory.
        os.chdir(target)
        from ultralytics import YOLO, settings
        settings.update({key: False for key in ('sync', 'clearml', 'comet', 'dvc', 'mlflow',
                        'neptune', 'raytune', 'tensorboard', 'wandb') if key in settings})
        settings.update({key: str(target / name) for key, name in
                         [('weights_dir', 'pretrained'), ('datasets_dir', 'unused-datasets'), ('runs_dir', 'unused-runs')]
                         if key in settings})
        lease.renew()
        model = YOLO(initial_model, task='classify')
        for event in ('on_pretrain_routine_start', 'on_train_batch_start', 'on_val_batch_start', 'on_model_save'):
            model.add_callback(event, lease.check)
        # No child dataloader processes, disk pixel caches or sample plots that
        # could survive the registered reader. VAL is required; TEST stays held out.
        lease.renew()
        model.train(data=receipt['data'], epochs=config['epochs'], imgsz=config['image_size'],
                    batch=config['batch'], patience=config['patience'], val=True, device=config['device'],
                    project=str(target.parent), name=target.name, exist_ok=True,
                    workers=0, cache=False, plots=False, save=True, save_period=-1, resume=False,
                    amp=False)
        lease.renew()
    print('TRAINING_COMPLETE · Chờ receiver ghi lineage của checkpoint.', flush=True)
    return 0

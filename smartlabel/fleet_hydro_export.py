"""Managed Hydro bundle; release registration remains a separate explicit action."""
from copy import deepcopy
from pathlib import Path
import shutil
from time import monotonic

from .fleet_dataset import _safe_path
from .fleet_intake import FleetIntakeError
from .hydro_labels import model_attributes
from .hydroponic import _export_jetson_onnx, _write_hydro_model_bundle, _sha256


def build_fleet_hydro_package(client, project, run_ids, config, progress, cancel):
    from .operational_policy import export_policy, acceptance, UNVALIDATED_OPERATIONAL
    pilot = export_policy(config)
    mode = config.get('deploymentMode')
    if mode not in {'shadow', 'operational'} or mode == 'operational' and not pilot:
        raise FleetIntakeError('Gói Fleet hỗ trợ shadow hoặc vận hành có xác nhận chưa kiểm định. Chưa có bằng chứng holdout cho lượt này.')
    if mode == 'operational' and any(token in str(project.metadata.get(key, ''))
            for key in ('validationStatus', 'trainingPurpose') for token in ('smoke', 'fixture')):
        raise FleetIntakeError('Model kiểm thử không được xuất để vận hành.')
    frozen = deepcopy(project)
    frozen.metadata['validationStatus'] = UNVALIDATED_OPERATIONAL if pilot else 'pilot_unvalidated'
    attrs = model_attributes(frozen)
    if set(config.get('thresholds', {})) != {a['id'] for a in attrs}:
        raise FleetIntakeError('Cần ngưỡng tường minh cho mọi nhóm model.')
    if cancel.is_set(): raise FleetIntakeError('Đã hủy tạo gói.')
    job = client.begin_bundle(run_ids, config)  # All run/ancestor sources online.
    target = Path(job['path'])
    def check():
        _safe_path(str(target), client.root / 'fleet_datasets' / 'bundles' / job['bundleId'])
        if cancel.is_set() or monotonic() >= job['deadline']:
            raise FleetIntakeError('Đã hủy hoặc gate hết hạn; chưa có gói hoàn tất.')
    completed = False
    finalizing = False
    try:
        if set(job['models']) != {a['id'] for a in attrs}:
            raise FleetIntakeError('Chọn đủ một run hoàn tất cho mỗi thuộc tính, cùng snapshot.')
        distribution = {}
        for attr in attrs:
            counts = job['trainCounts'][attr['id']]
            mapping = {v['id']: {'positive': 'present', 'negative': 'absent'}[v['meaning']]
                       for v in attr['values'] if v['meaning'] in {'positive', 'negative'}}
            if set(counts) != set(mapping): raise FleetIntakeError('Nhãn run không khớp schema đóng gói.')
            distribution[attr['id']] = {mapping[key]: number for key, number in counts.items()}
        check(); models, hashes = {}, {}
        for index, attr in enumerate(attrs, 1):
            check(); key = attr['id']
            progress(f'Chuyển ONNX {index}/{len(attrs)} · {attr["displayName"]}')
            # Work only inside receiver-reserved output. Source checkpoints stay
            # immutable; the converter writes beside its job-owned PT copy.
            folder = target / ('classifier_' + str(index)); folder.mkdir()
            source = Path(job['models'][key]); hashes[key] = _sha256(source)
            checkpoint = folder / 'model.pt'; shutil.copyfile(source, checkpoint)
            if _sha256(checkpoint) != hashes[key]: raise FleetIntakeError('Checkpoint thay đổi khi tạo gói.')
            models[key] = _export_jetson_onnx(checkpoint, folder / 'model.onnx', 224, 12)
        check()
        if any(_sha256(Path(job['models'][key])) != value for key, value in hashes.items()):
            raise FleetIntakeError('Checkpoint thay đổi khi tạo gói.')
        _write_hydro_model_bundle(frozen, target / 'bundle', models, config['thresholds'],
            dataset_version=config['datasetVersion'], source_commit=config['sourceCommit'],
            camera_profile_ids=config['cameraProfileIds'], geometry_profile_ids=config['geometryProfileIds'],
            input_size=224, runtime_target=config['runtimeTarget'], deployment_mode=mode,
            operational_acceptance=acceptance(hashes) if pilot else None,
            managed_label_distribution=distribution, managed_release_lineage=job['lineage'])
        check()
        finalizing = True
        result = client.finish_bundle(job)  # Fresh one-use gate over final ZIP hash.
        completed = True
        return {'archive': target / 'bundle.zip', 'lineage': target / 'fleet_lineage.json',
                'receipt': result, 'deliveryAllowed': False}
    finally:
        if not completed and not finalizing:
            check_root = _safe_path(str(target), client.root / 'fleet_datasets' / 'bundles' / job['bundleId'])
            # This job exclusively owns this new directory; reject links before
            # cleanup. No unrelated project or model source is a deletion target.
            for file in check_root.rglob('*'):
                _safe_path(str(file), file)
            shutil.rmtree(check_root)

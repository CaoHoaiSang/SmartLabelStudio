"""Explicit managed dataset operations through the credential-owning receiver.

A receipt is scope-bound metadata, never a reusable permission flag. Generic
export/train entry points continue to reject managed sources.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import re
from time import monotonic
from uuid import uuid4

from . import fleet_dataset_contract as contract
from .fleet_intake import FleetIntakeError, HASH, UUID, _project_root

MAX_WIRE = 64 * 1024
ERRORS = {
    'lineage_revoked': 'Có đợt đã rút hoặc quyền nguồn đã đổi; snapshot vô hiệu.',
    'lineage_snapshot_not_ready': 'Snapshot chưa sẵn sàng hoặc đã bị thu hồi.',
    'lineage_confirmation_changed': 'Ảnh, nhãn, nguồn hoặc phân tập đã đổi; hãy xem trước lại.',
    'lineage_snapshot_changed': 'Ảnh, nhãn, nguồn hoặc phân tập đã đổi; hãy tạo snapshot mới.',
    'lineage_locked_split_changed': 'Nhóm đã được khóa ở phân tập khác; giữ nguyên nhóm holdout.',
    'lineage_phone_train_only': 'Ảnh điện thoại chỉ được vào TRAIN.',
    'lineage_duplicate_image': 'Có ảnh trùng byte hoặc pixel với nguồn đã chọn, Giàn hoặc Bổ trợ.',
    'lineage_source_unqualified': 'Có ảnh chưa đủ điều kiện nguồn; kiểm lại phần duyệt nhãn.',
    'lineage_ancestor_missing': 'Snapshot thiếu nguồn tổ tiên của checkpoint; chưa được fine-tune.',
    'lineage_ancestor_revoked': 'Nguồn tổ tiên đã bị rút; không được dùng checkpoint cho lượt mới.',
    'lineage_val_class_missing': 'VAL cần đủ hai nhãn và nhóm độc lập; không tự dùng TEST thay VAL.',
    'lineage_train_class_missing': 'TRAIN cần ảnh đã duyệt cho cả hai nhãn của thuộc tính.',
    'lineage_registration_uncertain': 'Chưa đối soát được lượt đăng ký; không tự chạy lại.',
    'lineage_copy_already_started': 'Lượt này đã bắt đầu; không tự tạo lại bản sao.',
    'lineage_supplement_invalid': 'Bổ trợ có bản ghi chưa hợp lệ; kiểm ảnh đã bật, đã duyệt, đúng giống cây và chỉ TRAIN.',
    'lineage_supplement_changed': 'Ảnh hoặc bản kê Bổ trợ đã đổi; hãy xem trước và tạo snapshot mới.',
    'lineage_supplement_schema_changed': 'Ý nghĩa nhãn Bổ trợ khác dự án; cần duyệt lại.',
    'lineage_supplement_presence': 'Nhãn hiện diện cây của Bổ trợ mâu thuẫn; cần duyệt lại.',
    'lineage_supplement_parent_missing': 'Không tìm thấy ảnh gốc của Bổ trợ trong Giàn.',
    'lineage_supplement_parent_holdout': 'Ảnh gốc thuộc VAL/TEST; tắt biến thể Bổ trợ hoặc điều chỉnh nhóm có chủ đích.',
    'lineage_supplement_parent_invalid': 'Ảnh gốc đã đổi hoặc thiếu nguồn tổng hợp; cần xác minh và duyệt lại.',
    'lineage_supplement_attribution': 'Ảnh Bổ trợ từ nguồn ngoài cần đủ tác giả, giấy phép và thông tin trích nguồn.',
    'lineage_supplement_path': 'Bổ trợ cần ảnh PNG/JPEG trong kho Bổ trợ của dự án.',
    'lineage_supplement_fleet_parent': 'Biến thể từ ảnh khách chưa được đưa vào kho Bổ trợ riêng; phải giữ quản lý nguồn Fleet.',
    'lineage_label_excluded': 'Có nhãn đang bị loại khỏi train trong cấu hình thuộc tính; kiểm lại lựa chọn.',
    'lineage_train_already_started': 'Lượt train này đã bắt đầu; không chạy lại bằng receipt cũ.',
}


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise FleetIntakeError('Phản hồi snapshot không đúng hợp đồng; đang chặn.')
    return value


def _uuid(value):
    if not isinstance(value, str) or not UUID.fullmatch(value):
        raise FleetIntakeError('Mã lượt snapshot không hợp lệ.')
    return value


def _hash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise FleetIntakeError('Mã kiểm tra snapshot không hợp lệ.')
    return value


def _json(raw):
    if len(raw) > MAX_WIRE:
        raise FleetIntakeError('Phản hồi snapshot vượt giới hạn.')
    # Bounded before parsing; reject duplicate names, constants and deep objects.
    depth = 0
    quoted = escaped = False
    for char in raw.decode('utf-8'):
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif char == '"': quoted = True
        elif char in '[{':
            depth += 1
            if depth > 16: raise FleetIntakeError('Phản hồi snapshot quá sâu.')
        elif char in ']}': depth -= 1
    return json.loads(raw, object_pairs_hook=contract._pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('json_number')))


def _safe_path(value, expected):
    if not isinstance(value, str):
        raise FleetIntakeError('Đường dẫn managed không hợp lệ.')
    file, target = Path(value).absolute(), Path(expected).absolute()
    if file != target:
        raise FleetIntakeError('Đường dẫn không khớp vùng managed đã đăng ký.')
    for item in (file, *file.parents):
        try:
            if getattr(item.lstat(), 'st_file_attributes', 0) & 0x400:
                raise FleetIntakeError('Vùng managed chứa reparse point; đang chặn.')
        except FileNotFoundError:
            pass
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise FleetIntakeError('Vùng managed chứa liên kết; đang chặn.')
    return file


def config_digest(config):
    # Paths may contain Vietnamese. Hash exact UTF-8 settings, not wire canonical
    # ASCII identifiers. No credential or gate token is included in the settings.
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


class FleetDatasetClient:
    def __init__(self, project_root, project_id, *, port=17864):
        self.root = _project_root(Path(project_root), project_id)
        self.project_id = project_id
        if type(port) is not int or not 1 <= port <= 65535:
            raise FleetIntakeError('Cổng receiver không hợp lệ.')
        self.port = port
        self.binding = None
        self.checked_at = None
        self.pending_file = self.root / 'fleet_datasets' / 'client-pending.json'
        self.pending = self._read_pending()

    def _read_pending(self):
        path = _safe_path(str(self.pending_file), self.pending_file)
        if not path.exists(): return None
        if path.stat().st_size > MAX_WIRE: raise FleetIntakeError('Nhật ký đối soát vượt giới hạn.')
        value = _fields(_json(path.read_bytes()), ['action', 'payload'])
        if value['action'] not in {'register_snapshot', 'materialize', 'bundle', 'release_candidate'} or not isinstance(value['payload'], dict):
            raise FleetIntakeError('Nhật ký đối soát không hợp lệ.')
        _uuid(value['payload'].get('operationId' if value['action'] != 'bundle' else 'bundleId'))
        return value

    def _clear_pending(self):
        if self._read_pending() != self.pending:
            raise FleetIntakeError('Nhật ký đối soát đã đổi; chưa xóa trạng thái chờ.')
        self.pending_file.unlink()
        self.pending = None

    def _receipt(self):
        held = self.pending
        if held is None: raise FleetIntakeError('Không có lượt đang chờ đối soát.')
        identity = held['payload']['bundleId' if held['action'] == 'bundle' else 'operationId']
        value = _fields(self._call('receipt', {'operationId': identity}),
                        ['schemaVersion', 'operationId', 'state', 'result'])
        if value['schemaVersion'] != 'FleetDatasetOperationReceiptV1' or value['operationId'] != identity:
            raise FleetIntakeError('Receipt không khớp lượt đang đối soát.')
        return value

    def discard_pending(self):
        value = self._receipt()
        if value['state'] not in {'not_started', 'failed', 'blocked'}:
            raise FleetIntakeError('Lượt trước còn kết quả hoặc chưa rõ trạng thái; cần đối soát trước.')
        self._clear_pending()
        return value['state']

    def _call(self, action, payload):
        _project_root(self.root, self.project_id)
        body = json.dumps({'action': action, 'projectId': self.project_id,
                           'projectRoot': str(self.root), 'payload': payload}, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(body) > MAX_WIRE:
            raise FleetIntakeError('Snapshot vượt giới hạn 64 KiB.')
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=60)
        try:
            connection.request('POST', '/smartlabel/lineage', body,
                {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{self.port}', 'X-Fleet-Client': 'SmartLabel'})
            response = connection.getresponse()
            value = _json(response.read(MAX_WIRE + 1))
            if response.status != 200:
                code = value.get('error', '') if isinstance(value, dict) else ''
                raise FleetIntakeError(ERRORS.get(code, 'Không kiểm được quyền với Fleet; đang chặn thao tác.'))
            return value
        except (OSError, http.client.HTTPException, UnicodeError, ValueError) as error:
            if isinstance(error, FleetIntakeError): raise
            raise FleetIntakeError('Không kiểm được receiver/Fleet; đang chặn thao tác.') from None
        finally:
            connection.close()

    def _write(self, action, payload):
        saved = self._read_pending()
        if saved is not None: self.pending = saved
        if self.pending is not None:
            raise FleetIntakeError('Còn lượt chưa rõ kết quả. Chọn Đối soát lượt trước trước khi tạo bản mới.')
        # Keep the exact ID/body on all uncertain outcomes, including malformed
        # success responses. Validation clears this only after it has succeeded.
        self.pending = {'action': action, 'payload': json.loads(json.dumps(payload))}
        path = _safe_path(str(self.pending_file), self.pending_file)
        with path.open('x', encoding='utf-8') as handle:
            json.dump(self.pending, handle, ensure_ascii=False, allow_nan=False)
            handle.flush(); os.fsync(handle.fileno())
        return self._call(action, payload)

    def reconcile(self):
        if self.pending is None:
            raise FleetIntakeError('Không có lượt đang chờ đối soát trong cửa sổ này. Đọc lịch sử bản sao đã lưu.')
        held = self.pending
        value = self._receipt()
        if value['state'] == 'not_started' and held['action'] != 'bundle':
            # Explicit retry only, after the receiver has checked its durable
            # journal and the online authority. The original body/IDs are kept.
            result = self._call(held['action'], held['payload'])
        elif value['state'] == 'ready':
            result = value['result']
        else:
            raise FleetIntakeError('Lượt trước chưa sẵn sàng hoặc đã bị chặn; không tự chạy lại. Lịch sử được giữ để xử lý.')
        if held['action'] == 'register_snapshot':
            result = self._snapshot_receipt(result, held['payload']['snapshot'])
        elif held['action'] == 'materialize':
            result = self._copy_receipt(result, held['payload'])
        elif held['action'] == 'release_candidate':
            result = self._release_receipt(result, held['payload'])
        elif held['action'] == 'bundle':
            result = self._bundle_receipt(result, held['payload']['bundleId'])
        else:
            raise FleetIntakeError('Lượt này cần đối soát bằng lịch sử run/bundle.')
        self._clear_pending()
        return result

    def _binding(self, value):
        _fields(value, ['workerId', 'storageId', 'projectId'])
        _uuid(value['workerId']); _uuid(value['storageId'])
        if value['projectId'] != self.project_id or self.binding is not None and value != self.binding:
            raise FleetIntakeError('Binding không khớp project; chưa xác nhận thành công.')
        self.binding = dict(value)

    def bind(self):
        value = _fields(self._call('bind', {}), ['schemaVersion', 'projectBinding'])
        if value['schemaVersion'] != 'FleetDatasetBindingV1': raise FleetIntakeError('Binding không hợp lệ.')
        self._binding(value['projectBinding'])
        return self.binding

    def catalog(self):
        value = None
        for offset in range(0, 128, 32):
            page = _fields(self._call('catalog', {'offset': offset}),
                           ['schemaVersion', 'projectBinding', 'nextOffset', 'snapshots', 'copies', 'runs', 'bundles'])
            if page['schemaVersion'] != 'FleetDatasetCatalogV1' or page['nextOffset'] not in (None, offset + 32):
                raise FleetIntakeError('Danh sách snapshot không hợp lệ.')
            self._binding(page['projectBinding'])
            for key in ('snapshots', 'copies', 'runs', 'bundles'):
                if not isinstance(page[key], list) or len(page[key]) > 32:
                    raise FleetIntakeError('Trang danh sách vượt giới hạn.')
            if value is None:
                value = {key: page[key] for key in ('schemaVersion', 'projectBinding', 'snapshots', 'copies', 'runs', 'bundles')}
            else:
                for key in ('snapshots', 'copies', 'runs', 'bundles'): value[key].extend(page[key])
            if page['nextOffset'] is None: break
        else: raise FleetIntakeError('Danh sách vượt giới hạn.')
        for collection, maximum in [('snapshots', 80), ('copies', 128), ('runs', 128), ('bundles', 128)]:
            if not isinstance(value[collection], list) or len(value[collection]) > maximum:
                raise FleetIntakeError('Danh sách snapshot vượt giới hạn.')
        for row in value['snapshots']:
            _fields(row, ['snapshotBindingDigest', 'state', 'imageCount']); _hash(row['snapshotBindingDigest'])
            if row['state'] not in {'registering', 'ready', 'revoked'} or type(row['imageCount']) is not int or not 1 <= row['imageCount'] <= 80:
                raise FleetIntakeError('Snapshot có trạng thái chưa xác định.')
        for row in value['copies']:
            _fields(row, ['copyId', 'operationId', 'state', 'kind', 'snapshotBindingDigest'])
            _uuid(row['copyId']); _uuid(row['operationId']); _hash(row['snapshotBindingDigest'])
            if row['kind'] not in {'export','train_data'} or row['state'] not in {'registering','consuming','materializing','ready','aborted','withdrawal_pending','deleted'}:
                raise FleetIntakeError('Bản sao có trạng thái chưa xác định.')
        for row in value['runs']:
            _fields(row, ['runId', 'state', 'attributeId', 'snapshotBindingDigest']); _uuid(row['runId']); _hash(row['snapshotBindingDigest'])
            if row['state'] not in {'running', 'failed', 'complete'} or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', row['attributeId']):
                raise FleetIntakeError('Run có trạng thái chưa xác định.')
        for row in value['bundles']:
            _fields(row, ['bundleId', 'state']); _uuid(row['bundleId'])
            if row['state'] not in {'starting', 'building', 'complete'}: raise FleetIntakeError('Bundle có trạng thái chưa xác định.')
        return value

    def preview(self, contribution_ids, splits=None, *, include_supplements=False):
        if type(include_supplements) is not bool:
            raise FleetIntakeError('Lựa chọn Bổ trợ không hợp lệ.')
        payload = {'contributionIds': contribution_ids, 'splits': splits or {}}
        extra = ['includeSupplements'] if include_supplements else []
        if include_supplements: payload['includeSupplements'] = True
        value = _fields(self._call('preview', payload), ['schemaVersion', 'snapshot', 'splitRevision', 'summary'] + extra)
        if include_supplements and value['includeSupplements'] is not True:
            raise FleetIntakeError('Receiver chưa xác nhận lựa chọn Bổ trợ.')
        if value['schemaVersion'] != ('FleetDatasetPreviewV2' if include_supplements else 'FleetDatasetPreviewV1'): raise FleetIntakeError('Bản xem trước không hợp lệ.')
        contract.validate('snapshot', value['snapshot']); self._binding(value['snapshot']['projectBinding'])
        _hash(value['splitRevision'])
        _fields(value['summary'], ['imageCount', 'excludedCount', 'legacyCount', 'sources', 'splits', 'groups'] + (['supplementCount'] if include_supplements else []))
        if include_supplements and (type(value['summary']['supplementCount']) is not int or not 0 <= value['summary']['supplementCount'] <= 2000):
            raise FleetIntakeError('Số ảnh Bổ trợ không hợp lệ.')
        items = value['snapshot']['items']; summary = value['summary']
        if summary['imageCount'] != len(items) or any(type(summary[k]) is not int or summary[k] < 0 for k in ('imageCount','excludedCount','legacyCount')):
            raise FleetIntakeError('Số ảnh không khớp snapshot.')
        sources = {key:sum(i['sourceKind']==key for i in items) for key in ('hydro_slot','phone_supplement')}
        splits = {key:sum(i['split']==key for i in items) for key in ('train','val','test')}
        groups = list({i['groupId']:{key:i[key] for key in ('groupId','split','sourceKind')} for i in items}.values())
        if summary['sources'] != sources or summary['splits'] != splits or summary['groups'] != groups:
            raise FleetIntakeError('Nhóm/phân tập không khớp snapshot.')
        self.checked_at = monotonic()
        return value

    def register(self, preview, *, operation_id=None):
        snapshot = contract.validate('snapshot', preview['snapshot'])
        self._binding(snapshot['projectBinding'])
        payload = {'operationId': operation_id or str(uuid4()), 'snapshot': snapshot, 'splitRevision': _hash(preview['splitRevision'])}
        if preview.get('includeSupplements') is True: payload['includeSupplements'] = True
        value = self._snapshot_receipt(self._write('register_snapshot', payload), snapshot)
        self._clear_pending()
        return value

    def _snapshot_receipt(self, result, snapshot):
        value = _fields(result, ['schemaVersion', 'snapshotBindingDigest', 'snapshotDigest', 'projectBinding', 'state'])
        if (value['schemaVersion'] != 'FleetDatasetSnapshotReadyV1' or value['state'] != 'ready'
                or value['snapshotBindingDigest'] != contract.binding_digest(snapshot) or value['snapshotDigest'] != snapshot['snapshotDigest']):
            raise FleetIntakeError('Receipt không khớp snapshot đã xác nhận.')
        self._binding(value['projectBinding']); self.checked_at = monotonic()
        return value

    def materialize(self, snapshot_binding_digest, attribute_id, *, kind='export', include_legacy=True):
        payload = {'operationId': str(uuid4()), 'copyId': str(uuid4()), 'snapshotBindingDigest': _hash(snapshot_binding_digest),
                   'kind': kind, 'attributeId': attribute_id, 'includeLegacy': include_legacy}
        value = self._copy_receipt(self._write('materialize', payload), payload)
        self._clear_pending()
        return value

    def _copy_receipt(self, result, payload):
        value = _fields(result, ['schemaVersion', 'projectBinding', 'operationId', 'copyId', 'snapshotBindingDigest', 'subjectDigest',
             'gateTokenId', 'inventoryDigest', 'path', 'kind', 'state', 'trainCounts'])
        if (value['schemaVersion'] != 'FleetDatasetMaterializedV1' or value['state'] != 'ready'
                or any(value[key] != payload[key] for key in ('operationId','copyId','snapshotBindingDigest','kind'))):
            raise FleetIntakeError('Receipt bản sao không khớp lượt đang xử lý.')
        self._binding(value['projectBinding'])
        _uuid(value['gateTokenId']); _hash(value['inventoryDigest']); _hash(value['subjectDigest'])
        counts = value['trainCounts']
        if not isinstance(counts, dict) or len(counts) != 2 or any(not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', key) or type(count) is not int or not 0 <= count <= 2000 for key, count in counts.items()):
            raise FleetIntakeError('Số lượng nhãn không hợp lệ.')
        _safe_path(value['path'], self.root / 'fleet_datasets' / 'copies' / payload['copyId'])
        self.checked_at = monotonic()
        return value

    def training_context(self, copy):
        if copy.get('kind') != 'train_data': raise FleetIntakeError('Cần bản sao dành riêng cho train.')
        _safe_path(copy['path'], self.root / 'fleet_datasets' / 'copies' / _uuid(copy['copyId']))
        self._binding(copy['projectBinding'])
        return {'projectRoot': str(self.root), 'projectId': self.project_id, 'port': self.port,
                'copyId': copy['copyId'], 'runId': str(uuid4()), 'projectBinding': self.binding}

    @classmethod
    def for_training(cls, context):
        _fields(context, ['projectRoot', 'projectId', 'port', 'copyId', 'runId', 'projectBinding'])
        _uuid(context['copyId']); _uuid(context['runId'])
        client = cls(context['projectRoot'], context['projectId'], port=context['port'])
        client._binding(context['projectBinding'])
        return client

    def begin_training(self, context, config):
        self._validate_context(context)
        start = monotonic()
        value = _fields(self._call('begin_train', {'copyId': context['copyId'], 'runId': context['runId'],
            'jobPid': os.getpid(), 'model': config['model'], 'configDigest': config_digest(config)}),
            ['schemaVersion', 'runId', 'copyId', 'projectBinding', 'data', 'runPath', 'model', 'modelSha256', 'gateTokenId', 'expiresInMs'])
        if value['schemaVersion'] != 'FleetTrainingStartedV1': raise FleetIntakeError('Receipt train không hợp lệ.')
        self._scope_job(value, context, start); self._binding(value['projectBinding'])
        _safe_path(value['data'], self.root / 'fleet_datasets' / 'copies' / context['copyId'])
        _safe_path(value['runPath'], self.root / 'fleet_datasets' / 'runs' / context['runId'])
        if value['model'] != config['model'] or value['modelSha256'] is not None and hashlib.sha256(Path(value['model']).read_bytes()).hexdigest() != _hash(value['modelSha256']):
            raise FleetIntakeError('Model khởi tạo đã đổi.')
        return value

    def _scope_job(self, value, context, start):
        if (value['copyId'] != context['copyId'] or value['runId'] != context['runId']
                or type(value['expiresInMs']) is not int or not 0 < value['expiresInMs'] <= 300000):
            raise FleetIntakeError('Lease không khớp lượt train.')
        _uuid(value['gateTokenId'])
        value['deadline'] = start + value['expiresInMs'] / 1000
        if monotonic() >= value['deadline']: raise FleetIntakeError('Lease train đã hết hạn.')

    def _validate_context(self, context):
        other = self.for_training(context)
        if other.root != self.root or other.project_id != self.project_id or other.port != self.port:
            raise FleetIntakeError('Lượt train thuộc project khác.')
        self._binding(context['projectBinding'])

    def renew_training(self, context):
        self._validate_context(context); start = monotonic()
        value = _fields(self._call('lease', {'copyId': context['copyId'], 'runId': context['runId'], 'jobPid': os.getpid()}),
                        ['schemaVersion', 'runId', 'copyId', 'expiresInMs', 'gateTokenId'])
        if value['schemaVersion'] != 'FleetTrainingLeaseV1': raise FleetIntakeError('Lease train không hợp lệ.')
        self._scope_job(value, context, start)
        return value

    def finish_training(self, context, exit_code):
        self._validate_context(context)
        value = _fields(self._call('finish_train', {'copyId': context['copyId'], 'runId': context['runId'], 'exitCode': exit_code}),
                        ['schemaVersion', 'runId', 'state', 'lineage'])
        if value['schemaVersion'] != 'FleetTrainingFinishedV1' or value['runId'] != context['runId'] or value['state'] not in {'failed', 'complete'}:
            raise FleetIntakeError('Không xác nhận được kết quả train.')
        if value['state'] == 'complete':
            contract.validate('lineage', value['lineage'])
            if value['lineage']['runId'] != context['runId']: raise FleetIntakeError('Lineage không khớp lượt train.')
        return value

    def begin_bundle(self, run_ids, config):
        bundle_id = str(uuid4()); start = monotonic()
        value = _fields(self._write('bundle', {'bundleId': bundle_id, 'runIds': run_ids, 'configDigest': config_digest(config), 'releaseLineage': True}),
                        ['schemaVersion', 'bundleId', 'path', 'gateTokenId', 'expiresInMs', 'models', 'trainCounts', 'lineage'])
        if value['schemaVersion'] != 'FleetBundleStartedV2' or value['bundleId'] != bundle_id:
            raise FleetIntakeError('Receipt bundle không hợp lệ.')
        from .fleet_release_lineage import validate_release_lineage
        validate_release_lineage(value['lineage'])
        _safe_path(value['path'], self.root / 'fleet_datasets' / 'bundles' / bundle_id)
        _uuid(value['gateTokenId'])
        if type(value['expiresInMs']) is not int or not 0 < value['expiresInMs'] <= 300000: raise FleetIntakeError('Gate bundle đã hết hạn.')
        value['deadline'] = start + value['expiresInMs'] / 1000
        if monotonic() >= value['deadline']: raise FleetIntakeError('Gate bundle đã hết hạn.')
        if (not isinstance(value['models'], dict) or not 1 <= len(value['models']) <= 16
                or not isinstance(value['trainCounts'], dict) or set(value['trainCounts']) != set(value['models'])):
            raise FleetIntakeError('Số nhãn không khớp các run đã chọn.')
        for key, counts in value['trainCounts'].items():
            if not isinstance(counts, dict) or len(counts) != 2 or any(
                    not isinstance(k, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', k)
                    or type(n) is not int or not 1 <= n <= 2000 for k, n in counts.items()):
                raise FleetIntakeError('Run cần đủ hai nhãn TRAIN đã duyệt.')
        for key, model in value['models'].items():
            if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', key): raise FleetIntakeError('Model bundle không hợp lệ.')
            if not any(Path(model) == self.root / 'fleet_datasets' / 'runs' / run_id / 'weights' / 'best.pt' for run_id in run_ids):
                raise FleetIntakeError('Checkpoint nằm ngoài lượt train đã đăng ký.')
            _safe_path(model, model)
        return value

    def finish_bundle(self, job):
        if monotonic() >= job['deadline']: raise FleetIntakeError('Gate bundle đã hết hạn; chưa có gói hoàn tất.')
        value = self._bundle_receipt(self._call('finish_bundle', {'bundleId': job['bundleId']}), job['bundleId'])
        self._clear_pending()
        return value

    def _bundle_receipt(self, result, bundle_id):
        value = _fields(result, ['schemaVersion', 'bundleId', 'state', 'lineage'])
        if value['schemaVersion'] != 'FleetBundleFinishedV1' or value['bundleId'] != bundle_id or value['state'] != 'complete':
            raise FleetIntakeError('Chưa xác nhận bundle hoàn tất.')
        archive = _safe_path(str(self.root / 'fleet_datasets' / 'bundles' / bundle_id / 'bundle.zip'),
                             self.root / 'fleet_datasets' / 'bundles' / bundle_id / 'bundle.zip')
        sidecar = value['lineage']
        if (sidecar.get('kind') != 'includes_fleet' or sidecar.get('deliveryAllowed') is not False
                or sidecar.get('archiveSha256') != hashlib.sha256(archive.read_bytes()).hexdigest()):
            raise FleetIntakeError('Lineage bundle không khớp archive.')
        return value

    def prepare_release_candidate(self, bundle_id):
        from .fleet_release_lineage import validate_release_lineage
        from .hydro_release_candidate import _prepare_checked_candidate
        _uuid(bundle_id)
        # Read-only context before writing candidate metadata. Registration uses
        # a new source check and the durable operation journal below.
        self.bind()
        context = _fields(self._call('candidate_context', {'bundleId': bundle_id}),
                          ['schemaVersion', 'bundleId', 'archive', 'lineage'])
        if context['schemaVersion'] != 'FleetReleaseCandidateContextV1' or context['bundleId'] != bundle_id:
            raise FleetIntakeError('Gói phát hành không khớp lựa chọn.')
        validate_release_lineage(context['lineage'])
        archive = _safe_path(context['archive'], self.root / 'fleet_datasets' / 'bundles' / bundle_id / 'bundle.zip')
        candidate = _prepare_checked_candidate(archive, context['lineage'])
        payload = {'operationId': str(uuid4()), 'bundleId': bundle_id, 'candidate': candidate}
        value = self._release_receipt(self._write('release_candidate', payload), payload)
        self._clear_pending()
        return value

    def _release_receipt(self, result, payload):
        from .fleet_release_lineage import candidate_digest
        value = _fields(result, ['schemaVersion', 'operationId', 'candidateDigest', 'projectBinding', 'state'])
        if (value['schemaVersion'] != 'FleetReleaseCandidateReceiptV1' or value['state'] != 'registered'
                or value['operationId'] != payload['operationId']
                or value['candidateDigest'] != candidate_digest(payload['candidate'])):
            raise FleetIntakeError('Biên nhận phát hành không khớp candidate; cần đối soát.')
        self._binding(value['projectBinding'])
        return value

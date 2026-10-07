"""P4-A wire contract only. No I/O to Fleet, token verification or permission grant.

The caller must independently verify signatures and authoritative online state.
These parsers are deliberately not connected to export/train/release entry points.
"""
import hashlib
import json
import math
from pathlib import Path
import re

MAX_BYTES = 64 * 1024
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'contracts/fleet-dataset-custody/schema.json').read_text(encoding='utf-8'))
KINDS = {'snapshot', 'check', 'custody', 'claims', 'tombstone', 'lineage'}


class DatasetContractError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise DatasetContractError(code)


def _integer(value):
    return type(value) in (int, float) and abs(value) <= 9007199254740991 and math.isfinite(value) and value == int(value)


def canonical(value, depth=0):
    """Bounded ASCII profile, not a general replacement for Hydro contract_hash."""
    _require(depth <= 16, 'json_depth')
    if isinstance(value, dict):
        _require(all(isinstance(k, str) and all(32 <= ord(c) <= 126 for c in k) for k in value), 'json_key')
        return '{' + ','.join(json.dumps(k) + ':' + canonical(value[k], depth+1) for k in sorted(value)) + '}'
    if isinstance(value, list):
        return '[' + ','.join(canonical(v, depth+1) for v in value) + ']'
    if isinstance(value, str):
        _require(value.isascii() and all(32 <= ord(c) <= 126 for c in value), 'json_string')
        return json.dumps(value, ensure_ascii=True)
    if value is None or type(value) is bool:
        return json.dumps(value)
    _require(_integer(value), 'json_number')
    return str(int(value))


def digest(value):
    return hashlib.sha256(canonical(value).encode('ascii')).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate_field')
        result[key] = value
    return result


def parse(kind, raw):
    _require(isinstance(raw, (str, bytes)), 'json_type')
    try:
        text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        _require(len(text.encode('utf-8')) <= MAX_BYTES, 'json_size')
        # Count nesting before asking the JSON parser to allocate containers.
        depth = 0
        quoted = escaped = False
        for c in text:
            if quoted:
                if escaped: escaped = False
                elif c == '\\': escaped = True
                elif c == '"': quoted = False
            elif c == '"': quoted = True
            elif c in '[{':
                depth += 1
                _require(depth <= 16, 'json_depth')
            elif c in ']}': depth -= 1
        value = json.loads(text, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(DatasetContractError('json_number')))
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        raise DatasetContractError('json_invalid') from None
    return validate(kind, value)


def _schema(value, spec):
    if '$ref' in spec:
        return _schema(value, SCHEMA['$defs'][spec['$ref'].split('/')[-1]])
    if 'const' in spec:
        _require(type(value) is type(spec['const']) and value == spec['const'], 'constant')
        return
    kind = spec['type']
    if kind == 'object':
        _require(isinstance(value, dict) and set(value) == set(spec['required']), 'fields')
        for key, rule in spec['properties'].items(): _schema(value[key], rule)
    elif kind == 'array':
        _require(isinstance(value, list) and spec['minItems'] <= len(value) <= spec['maxItems'], 'array_size')
        for row in value: _schema(row, spec['items'])
    elif kind == 'string':
        _require(isinstance(value, str), 'string_type')
        if 'enum' in spec: _require(value in spec['enum'], 'enum')
        else:
            _require(spec['minLength'] <= len(value) <= spec['maxLength'] and re.fullmatch(spec['pattern'], value) is not None, 'string_format')
    elif kind == 'integer':
        _require(_integer(value) and spec['minimum'] <= value <= spec['maximum'], 'integer')
    else:
        raise RuntimeError('Unsupported trusted schema keyword')


def _ordered_unique(values):
    _require(values == sorted(set(values)), 'order_or_duplicate')


def _items(value):
    items = value['items']
    _ordered_unique([row['contributionId'] for row in items])
    _require(len({row['importId'] for row in items}) == len(items), 'duplicate_import')


def validate(kind, value):
    _require(kind in KINDS, 'document_kind')
    encoded = canonical(value)
    _require(len(encoded) <= MAX_BYTES, 'json_size')
    _schema(value, SCHEMA['$defs'][kind])
    if kind == 'snapshot':
        rows = value['items']
        _ordered_unique([(r['contributionId'], r['assetId']) for r in rows])
        _require(len({r['imageSha256'] for r in rows}) == len(rows), 'duplicate_bytes')
        _require(len({r['pixelFingerprint'] for r in rows}) == len(rows), 'duplicate_pixels')
        groups, imports, revisions = {}, {}, {}
        for row in rows:
            _require(row['sourceKind'] != 'phone_supplement' or row['split'] == 'train', 'phone_train_only')
            _require(groups.setdefault(row['groupId'], row['split']) == row['split'], 'group_split')
            _require(imports.setdefault(row['contributionId'], row['importId']) == row['importId'], 'import_conflict')
            _require(revisions.setdefault(row['importId'], row['reviewRevision']) == row['reviewRevision'], 'review_conflict')
        _require(len(imports) <= 20 and len(set(imports.values())) == len(imports), 'import_limit')
        _require(value['snapshotDigest'] == digest(rows), 'snapshot_digest')
    elif kind in {'check', 'custody'}:
        _items(value)
        if kind == 'custody':
            _require(value['pathClass'] == {'export': 'managed_export', 'train_data': 'managed_train'}[value['kind']], 'copy_path_class')
    elif kind == 'claims':
        _require(0 < value['exp'] - value['iat'] <= 600, 'gate_ttl')
    elif kind == 'tombstone':
        _ordered_unique(value['snapshotDigests'])
        _ordered_unique(value['copyIds'])
    return json.loads(encoded)  # Detached value; never mutate the caller's object.


def binding_digest(snapshot):
    s = validate('snapshot', snapshot)
    return digest(['FleetDatasetBindingV1', s['projectBinding'], s['projectContextSha256'], s['snapshotDigest']])


def assert_check_matches(snapshot, request, locked_groups):
    """Structural binding and caller-provided split locks; not source QA or online authorization."""
    s, r = validate('snapshot', snapshot), validate('check', request)
    _require(isinstance(locked_groups, dict), 'locked_groups_required')
    for group, split in locked_groups.items():
        _schema(group, SCHEMA['$defs']['hash']); _schema(split, SCHEMA['$defs']['split'])
    pairs = sorted({(i['contributionId'], i['importId']) for i in s['items']})
    _require(r['items'] == [dict(contributionId=c, importId=i) for c,i in pairs], 'incomplete_lineage')
    _require(r['projectBinding'] == s['projectBinding'] and r['snapshotDigest'] == s['snapshotDigest']
             and r['snapshotBindingDigest'] == binding_digest(s), 'snapshot_binding')
    for row in s['items']:
        _require(row['groupId'] not in locked_groups or locked_groups[row['groupId']] == row['split'], 'locked_split_changed')


def assert_claims_match(claims, request, *, issuer, now):
    """Checks VERIFIED claims against an intent. Does not verify JWT, consume it or grant access."""
    c, r = validate('claims', claims), validate('check', request)
    _require(_integer(now) and c['iat'] <= now < c['exp'], 'gate_expired_or_future')
    _require(c['iss'] == issuer, 'gate_issuer')
    for field in ['operation', 'operationId', 'projectBinding', 'snapshotDigest', 'snapshotBindingDigest', 'subjectDigest']:
        _require(c[field] == r[field], 'gate_binding')
    _require(c['itemsDigest'] == digest(r['items']), 'gate_items')

"""Bounded public lineage carried in the signed release and bundle. Python 3.6+."""
import hashlib
import json
import re

FIELDS = {'schema', 'kind', 'snapshotDigest', 'snapshotBindingDigest',
          'runLineagesDigest', 'contributionIdsDigest', 'itemCount'}


def validate_release_lineage(value):
    if (not isinstance(value, dict) or set(value) != FIELDS
            or value['schema'] != 'HydroModelLineageV1' or value['kind'] != 'includes_fleet'
            or type(value['itemCount']) is not int or not 1 <= value['itemCount'] <= 80
            or any(not isinstance(value[k], str) or not re.fullmatch(r'[a-f0-9]{64}', value[k])
                   for k in ('snapshotDigest', 'snapshotBindingDigest', 'runLineagesDigest', 'contributionIdsDigest'))):
        raise ValueError('Thông tin nguồn model Fleet không hợp lệ.')
    return dict(value)


def candidate_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()

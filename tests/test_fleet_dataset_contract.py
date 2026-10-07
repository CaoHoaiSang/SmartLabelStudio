"""Synthetic Phase-A vectors; no network, customer workspace or training."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from smartlabel import fleet_dataset_contract as C

ROOT = Path(__file__).resolve().parents[1] / 'contracts/fleet-dataset-custody'
VECTORS = json.loads((ROOT / 'vectors.json').read_text(encoding='utf-8'))
S = VECTORS['samples']


class DatasetContractTests(unittest.TestCase):
    def test_artifacts_are_exact_bytes(self):
        manifest = json.loads((ROOT / 'artifact-manifest.json').read_text())
        self.assertIs(manifest['testOnly'], True)
        self.assertEqual([r['path'] for r in manifest['files']], ['schema.json', 'vectors.json'])
        for row in manifest['files']:
            self.assertEqual(hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest(), row['sha256'])

    def test_cross_language_canonical_vector(self):
        self.assertEqual(C.canonical(S['snapshot']['items']), VECTORS['canonicalItems'])
        self.assertEqual(C.digest(S['snapshot']['items']), S['snapshot']['snapshotDigest'])
        self.assertEqual(C.binding_digest(S['snapshot']), VECTORS['snapshotBindingDigest'])
        self.assertEqual(C.digest(S['check']['items']), VECTORS['itemsDigest'])

    def test_reject_duplicate_names_even_escaped(self):
        raw = json.dumps(S['snapshot'])
        for key in ['schemaVersion', '\\u0073chemaVersion']:
            with self.subTest(key=key), self.assertRaises(C.DatasetContractError):
                C.parse('snapshot', raw[:-1] + ',"' + key + '":"FleetDatasetSnapshotV1"}')

    def test_invalid_json_and_bounds(self):
        for raw in [b'\xff', '[]', 'null', '[NaN]', '{', ' '*65537, '['*33+']'*33]:
            with self.subTest(raw=str(raw)[:20]), self.assertRaises(C.DatasetContractError):
                C.parse('snapshot', raw)
        for value in [float('nan'), float('inf'), 9007199254740992, 1.1, 'line\n', {'bad\n':1}]:
            with self.subTest(value=str(value)), self.assertRaises(C.DatasetContractError):
                C.canonical(value)

    def test_return_is_detached_and_input_unchanged(self):
        source = copy.deepcopy(S['snapshot'])
        output = C.validate('snapshot', source)
        output['items'][0]['split'] = 'test'
        self.assertEqual(source, S['snapshot'])

    def test_snapshot_context_and_existing_holdout(self):
        C.assert_check_matches(S['snapshot'], S['check'], {})
        group = S['snapshot']['items'][0]['groupId']
        C.assert_check_matches(S['snapshot'], S['check'], {group:'train'})
        with self.assertRaises(C.DatasetContractError):
            C.assert_check_matches(S['snapshot'], S['check'], {group:'test'})
        # A correctly bound Hydro group may retain its previous holdout split.
        snap, req = copy.deepcopy(S['snapshot']), copy.deepcopy(S['check'])
        snap['items'][0]['split'] = 'test'; snap['snapshotDigest'] = C.digest(snap['items'])
        req['snapshotDigest'] = snap['snapshotDigest']; req['snapshotBindingDigest'] = C.binding_digest(snap)
        C.assert_check_matches(snap, req, {group:'test'})

    def test_check_cannot_omit_sources_or_rebind_project(self):
        for mutate in [lambda r:r['items'].pop(), lambda r:r.update({'snapshotBindingDigest':'0'*64}),
                       lambda r:r['projectBinding'].update({'projectId':'project_other'})]:
            req=copy.deepcopy(S['check']); mutate(req)
            with self.assertRaises(C.DatasetContractError): C.assert_check_matches(S['snapshot'],req,{})
        snap=copy.deepcopy(S['snapshot']); snap['projectContextSha256']='0'*64
        with self.assertRaises(C.DatasetContractError): C.assert_check_matches(snap,S['check'],{})

    def test_claims_bind_operation_identity_and_exact_lifetime(self):
        c, req = S['claims'], S['check']
        C.assert_claims_match(c, req, issuer=c['iss'], now=c['iat'])
        C.assert_claims_match(c, req, issuer=c['iss'], now=c['exp']-1)
        for now in [c['iat']-1,c['exp'],True]:
            with self.assertRaises(C.DatasetContractError): C.assert_claims_match(c,req,issuer=c['iss'],now=now)
        for key in ['operation','operationId','snapshotDigest','snapshotBindingDigest','subjectDigest']:
            changed=copy.deepcopy(req)
            changed[key] = 'bundle' if key=='operation' else ('00000000-0000-4000-8000-000000000099' if key=='operationId' else '0'*64)
            with self.subTest(key=key),self.assertRaises(C.DatasetContractError):
                C.assert_claims_match(c,changed,issuer=c['iss'],now=c['iat'])
        for key in ['workerId','storageId','projectId']:
            changed=copy.deepcopy(req)
            changed['projectBinding'][key] = 'project_other' if key=='projectId' else '00000000-0000-4000-8000-000000000099'
            with self.subTest(key=key),self.assertRaises(C.DatasetContractError):
                C.assert_claims_match(c,changed,issuer=c['iss'],now=c['iat'])
        with self.assertRaises(C.DatasetContractError): C.assert_claims_match(c,req,issuer='https://other.invalid',now=c['iat'])
        changed=copy.deepcopy(req); changed['items'].pop()
        with self.assertRaises(C.DatasetContractError): C.assert_claims_match(c,changed,issuer=c['iss'],now=c['iat'])

    def test_contract_acceptance_cannot_open_legacy_training(self):
        from smartlabel.fleet_boundaries import reject_fleet_metadata
        from smartlabel.fleet_intake import FleetIntakeError
        snapshot=C.validate('snapshot',S['snapshot'])
        with self.assertRaises(FleetIntakeError): reject_fleet_metadata(snapshot)
        with self.assertRaises(FleetIntakeError): reject_fleet_metadata({'fleetLineage':C.validate('lineage',S['lineage'])})


def vector_test(vector):
    def check(self):
        raw=json.dumps(vector['value'],ensure_ascii=True)
        if vector['valid']:
            self.assertEqual(C.parse(vector['kind'],raw),vector['value'])
        else:
            with self.assertRaises(C.DatasetContractError): C.parse(vector['kind'],raw)
    return check


for _v in VECTORS['vectors']:
    setattr(DatasetContractTests,'test_vector_'+_v['name'],vector_test(_v))

if __name__ == '__main__': unittest.main()

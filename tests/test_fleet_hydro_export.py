from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
import zipfile

from smartlabel.fleet_hydro_export import build_fleet_hydro_package
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore
from smartlabel.fleet_intake import FleetIntakeError
from smartlabel.hydro_release_candidate import prepare_fleet_release_candidate


class FleetBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=ProjectStore(Path(self.temp.name)/'workspace');self.project=self.store.create_project('Managed fixture',task='classify')
        apply_hydroponic_slot_template(self.project);self.store.save(self.project)
        self.root=self.store.project_dir(self.project);self.managed=self.root/'fleet_datasets';self.managed.mkdir()
        (self.managed/'.fleet-storage-v1.json').write_text('{}');(self.managed/'model-index.json').write_text('{"schemaVersion":"FleetModelIndexV1","sha256":[]}')
        self.keys=['plant_presence','yellow_leaf','wilt'];self.runs=[str(uuid4()) for _ in self.keys];self.models={}
        for key,run in zip(self.keys,self.runs):
            file=self.managed/'runs'/run/'weights'/'best.pt';file.parent.mkdir(parents=True);file.write_bytes(('synthetic-'+key).encode());self.models[key]=str(file)
        self.bundle_id=str(uuid4());self.output=self.managed/'bundles'/self.bundle_id
        self.lineage = {'schema':'HydroModelLineageV1','kind':'includes_fleet','snapshotDigest':'a'*64,
            'snapshotBindingDigest':'b'*64,'runLineagesDigest':'c'*64,'contributionIdsDigest':'d'*64,'itemCount':2}
        self.client=Mock();self.client.root=self.root
        def begin(*_):
            self.output.mkdir(parents=True)
            return {'lineage':self.lineage,'bundleId':self.bundle_id,'path':str(self.output),'models':self.models,'trainCounts':{k:{'present':2,'absent':3} for k in self.keys},'deadline':monotonic()+60,'gateTokenId':str(uuid4())}
        def finish(job):
            sidecar={'kind':'includes_fleet','archiveSha256':hashlib.sha256((self.output/'bundle.zip').read_bytes()).hexdigest(),'deliveryAllowed':False}
            (self.output/'fleet_lineage.json').write_text(json.dumps(sidecar))
            return {'state':'complete','lineage':sidecar}
        self.client.begin_bundle.side_effect=begin;self.client.finish_bundle.side_effect=finish
        self.config={'deploymentMode':'shadow','runtimeTarget':'windows_onnxruntime_cpu','datasetVersion':'fixture','sourceCommit':'fixture',
                     'cameraProfileIds':['camera-fixture'],'geometryProfileIds':['geometry-fixture'],
                     'thresholds':{key:{'lowThreshold':.2,'highThreshold':.8} for key in self.keys}}
        self.before=deepcopy(self.project.to_dict())

    @staticmethod
    def convert(source,target,*_):
        import onnx
        from onnx import helper,TensorProto
        model=helper.make_model(helper.make_graph([helper.make_node('Constant',[],['scores'],value=helper.make_tensor('v',TensorProto.FLOAT,[1,2],[.25,.75]))],
            'synthetic',[helper.make_tensor_value_info('images',TensorProto.FLOAT,[1,3,224,224])],[helper.make_tensor_value_info('scores',TensorProto.FLOAT,[1,2])]),opset_imports=[helper.make_opsetid('',12)])
        model.ir_version=7;helper.set_model_props(model,{'names':"{0:'absent',1:'present'}"});onnx.save(model,target);return target

    def build(self):
        with patch('smartlabel.fleet_hydro_export._export_jetson_onnx',side_effect=self.convert):
            return build_fleet_hydro_package(self.client,self.project,self.runs,self.config,lambda _:None,Event())

    def test_local_bundle_keeps_hydro_zip_compatible_and_lineage_outside_but_candidate_stays_closed(self):
        result=self.build();self.assertFalse(result['deliveryAllowed']);self.assertTrue(result['lineage'].is_file())
        with zipfile.ZipFile(result['archive']) as archive:
            self.assertIsNone(archive.testzip());self.assertNotIn('fleet_lineage.json',archive.namelist())
            manifest=json.loads(archive.read('bundle.json'))
            self.assertEqual(manifest['labelDistribution'],{k:{'present':2,'absent':3} for k in self.keys})
        with self.assertRaises(FleetIntakeError):prepare_fleet_release_candidate(result['archive'],self.project,self.store)
        self.assertEqual(self.project.to_dict(),self.before)
        for key,file in self.models.items():self.assertEqual(Path(file).read_bytes(),('synthetic-'+key).encode())

    def test_uncertain_final_gate_keeps_unconfirmed_package_for_reconciliation(self):
        self.client.finish_bundle.side_effect=FleetIntakeError('withdrawn')
        with self.assertRaises(FleetIntakeError):self.build()
        self.assertTrue(self.output.exists());self.assertFalse((self.output/'fleet_lineage.json').exists())
        self.assertTrue(all(Path(file).exists() for file in self.models.values()))

    def test_operational_never_opens_a_local_or_delivery_gate(self):
        self.config['deploymentMode']='operational'
        with self.assertRaises(FleetIntakeError):self.build()
        self.client.begin_bundle.assert_not_called();self.assertFalse(self.output.exists())

    def test_missing_binary_managed_counts_cannot_create_a_package(self):
        begin=self.client.begin_bundle.side_effect
        def missing(*args):
            job=begin(*args);job['trainCounts']['wilt']['present']=0;return job
        self.client.begin_bundle.side_effect=missing
        with self.assertRaisesRegex(ValueError,'verified binary'): self.build()
        self.assertFalse(self.output.exists())
        self.client.finish_bundle.assert_not_called()

    def test_managed_candidate_matches_zip_marker_and_is_idempotent_but_legacy_path_stays_closed(self):
        from smartlabel.hydro_release_candidate import _prepare_checked_candidate, load_release_candidate
        result=self.build()
        candidate=_prepare_checked_candidate(result['archive'],self.lineage)
        self.assertEqual(candidate['schema'],'HydroModelReleaseCandidateV2')
        self.assertEqual(candidate['lineage'],self.lineage)
        self.assertEqual(candidate,_prepare_checked_candidate(result['archive'],self.lineage))
        path=result['archive'].with_name('bundle.release_candidate.json')
        self.assertEqual(load_release_candidate(path),candidate)
        with self.assertRaises(ValueError):_prepare_checked_candidate(result['archive'],{**self.lineage,'itemCount':1})
        with self.assertRaises(ValueError):_prepare_checked_candidate(result['archive'])
        path.write_text(json.dumps({**candidate,'datasetVersion':'changed'}),encoding='utf-8')
        with self.assertRaises(ValueError):_prepare_checked_candidate(result['archive'],self.lineage)

    def test_operational_requires_package_specific_ack_and_embeds_matching_contract(self):
        from smartlabel.hydro_release_candidate import _prepare_checked_candidate
        self.config.update(deploymentMode='operational',evaluationPolicy='unvalidated_pilot')
        with self.assertRaises(ValueError):self.build()
        self.client.begin_bundle.assert_not_called()
        self.config['pilotAcknowledged']=True
        candidate=_prepare_checked_candidate(self.build()['archive'],self.lineage)
        self.assertEqual(candidate['validationStatus'],'operational_unvalidated')
        self.assertEqual(candidate['deploymentMode'],'operational')
        self.assertIsNone(candidate['evaluationEvidenceSha256'])

    def test_operational_smoke_fixture_project_is_blocked_before_export(self):
        self.config.update(deploymentMode='operational',evaluationPolicy='unvalidated_pilot',pilotAcknowledged=True)
        self.project.metadata['trainingPurpose']='smoke_fixture'
        with self.assertRaises(FleetIntakeError):self.build()
        self.client.begin_bundle.assert_not_called()

    def test_candidate_lost_registration_reply_survives_reopen_and_requires_exact_receipt(self):
        from smartlabel.fleet_dataset import FleetDatasetClient
        from smartlabel.fleet_release_lineage import candidate_digest
        result=self.build()
        binding={'workerId':str(uuid4()),'storageId':str(uuid4()),'projectId':self.project.id}
        client=FleetDatasetClient(self.root,self.project.id)
        held={}
        def call(action,payload):
            if action=='bind':return {'schemaVersion':'FleetDatasetBindingV1','projectBinding':binding}
            if action=='candidate_context':return {'schemaVersion':'FleetReleaseCandidateContextV1','bundleId':self.bundle_id,'archive':str(result['archive']),'lineage':self.lineage}
            self.assertEqual(action,'release_candidate');held.update(payload)
            raise FleetIntakeError('reply lost after registration')
        with patch.object(client,'_call',side_effect=call):
            with self.assertRaises(FleetIntakeError):client.prepare_release_candidate(self.bundle_id)
        self.assertTrue(client.pending_file.exists())
        receipt={'schemaVersion':'FleetReleaseCandidateReceiptV1','operationId':held['operationId'],
                 'candidateDigest':candidate_digest(held['candidate']),'projectBinding':binding,'state':'registered'}
        reopened=FleetDatasetClient(self.root,self.project.id)
        envelope={'schemaVersion':'FleetDatasetOperationReceiptV1','operationId':held['operationId'],'state':'ready','result':receipt}
        with patch.object(reopened,'_call',return_value={**envelope,'result':{**receipt,'candidateDigest':'0'*64}}):
            with self.assertRaises(FleetIntakeError):reopened.reconcile()
        self.assertTrue(reopened.pending_file.exists())
        with patch.object(reopened,'_call',return_value=envelope) as read:
            self.assertEqual(reopened.reconcile(),receipt)
            self.assertEqual(read.call_args.args[0],'receipt')
        self.assertFalse(reopened.pending_file.exists())

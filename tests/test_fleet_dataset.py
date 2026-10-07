from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from smartlabel.fleet_dataset import FleetDatasetClient, _json, _safe_path
from smartlabel.fleet_intake import FleetIntakeError
from smartlabel.fleet_training import TrainingLease, validate_managed_config, run_managed_training
from smartlabel.fleet_boundaries import require_legacy_model, require_legacy_training_data
from smartlabel.hydroponic import apply_hydroponic_slot_template, export_jetson_onnx
from smartlabel.project_store import ProjectStore
from smartlabel.training import TrainingConfig, TrainingJob


class ManagedDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / 'workspace')
        self.project = self.store.create_project('Synthetic managed', task='classify')
        apply_hydroponic_slot_template(self.project); self.store.save(self.project)
        self.root = self.store.project_dir(self.project)
        self.client = FleetDatasetClient(self.root, self.project.id, port=19991)
        self.binding = {'workerId': str(uuid4()), 'storageId': str(uuid4()), 'projectId': self.project.id}
        self.context = {'projectRoot': str(self.root), 'projectId': self.project.id, 'port':19991,
                        'copyId': str(uuid4()), 'runId': str(uuid4()), 'projectBinding': self.binding}
        self.config = TrainingConfig(model='yolo11n-cls.pt', data=str(self.root/'fleet_datasets'/'copies'/self.context['copyId']),
            project_dir=str(self.root/'fleet_datasets'/'runs'), run_name=self.context['runId'], task='classify',
            fleet_dataset=self.context).__dict__

    def test_constructing_adapter_has_no_binding_or_copy_side_effect(self):
        before = (self.root/'project.json').read_bytes()
        self.assertFalse((self.root/'fleet_datasets').exists())
        self.assertEqual((self.root/'project.json').read_bytes(), before)

    def test_fixed_loopback_transport_no_redirect_credentials_or_unknown_response(self):
        connection = Mock(); response = connection.getresponse.return_value
        response.status = 200; response.read.return_value = json.dumps({'schemaVersion':'FleetDatasetBindingV1','projectBinding':self.binding}).encode()
        with patch('smartlabel.fleet_dataset.http.client.HTTPConnection', return_value=connection) as factory:
            self.assertEqual(self.client.bind(), self.binding)
        factory.assert_called_once_with('127.0.0.1', 19991, timeout=60)
        args = connection.request.call_args.args
        self.assertEqual(args[:2], ('POST','/smartlabel/lineage'))
        self.assertEqual(args[3], {'Content-Type':'application/json','Origin':'http://127.0.0.1:19991','X-Fleet-Client':'SmartLabel'})
        self.assertNotIn('Authorization', args[3]); connection.close.assert_called_once()
        response.status = 302
        with patch('smartlabel.fleet_dataset.http.client.HTTPConnection', return_value=connection):
            with self.assertRaises(FleetIntakeError): self.client.bind()
        self.assertFalse((self.root/'fleet_datasets').exists())

    def test_strict_json_duplicate_fields_depth_size_and_constants(self):
        for raw in [b'{"x":1,"x":2}', b'['*17+b'0'+b']'*17, b' '*65537, b'{"x":NaN}']:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError): _json(raw)

    def test_unknown_binding_wrong_project_and_receiver_offline_fail_closed(self):
        for binding in [{**self.binding,'projectId':'project_other'}, {**self.binding,'extra':True}]:
            with patch.object(self.client,'_call',return_value={'schemaVersion':'FleetDatasetBindingV1','projectBinding':binding}):
                with self.assertRaises(FleetIntakeError): self.client.bind()
        with patch('smartlabel.fleet_dataset.http.client.HTTPConnection', side_effect=OSError('offline')):
            with self.assertRaises(OSError): self.client.bind()
        self.assertFalse((self.root/'fleet_datasets').exists())

    def test_materialization_wrong_copy_scope_rejected(self):
        (self.root/'fleet_datasets').mkdir()
        value = dict(schemaVersion='FleetDatasetMaterializedV1',projectBinding=self.binding,operationId=str(uuid4()),copyId=str(uuid4()),
            snapshotBindingDigest='a'*64,subjectDigest='b'*64,gateTokenId=str(uuid4()),inventoryDigest='c'*64,path=str(self.root),kind='export',state='ready',trainCounts={'absent':1,'present':1})
        with patch.object(self.client,'_call',return_value=value):
            with self.assertRaises(FleetIntakeError): self.client.materialize('a'*64,'yellow_leaf')
        with self.assertRaises(FleetIntakeError): _safe_path(str(self.root), self.root/'fleet_datasets')

    def test_managed_config_cannot_select_generic_data_or_multidevice_resume(self):
        for changes in [{'data':str(self.root)}, {'task':'detect'}, {'device':'0,1'}, {'validate':False}, {'resume':True}, {'run_name':'different'}]:
            with self.subTest(changes=changes), self.assertRaises(FleetIntakeError): validate_managed_config({**self.config,**changes})
        self.assertEqual(validate_managed_config(self.config).binding, self.binding)

    def test_no_gate_no_weight_import_or_run_output(self):
        with patch.object(FleetDatasetClient,'begin_training',side_effect=FleetIntakeError('offline')):
            with self.assertRaises(FleetIntakeError): run_managed_training(self.config)
        self.assertFalse((self.root/'fleet_datasets').exists())

    def test_lease_no_offline_grace_no_clock_skew_revival_and_no_new_job(self):
        client = Mock(); token = str(uuid4()); receipt={'gateTokenId':token,'deadline':monotonic()+60}
        lease = TrainingLease(client,self.context,receipt,fatal=Mock())
        client.renew_training.side_effect = FleetIntakeError('withdrawn')
        with self.assertRaises(FleetIntakeError): lease.renew()
        client.begin_training.assert_not_called()
        lease.deadline = monotonic()-1
        client.renew_training.reset_mock()
        with self.assertRaises(FleetIntakeError): lease.renew()
        client.renew_training.assert_not_called()
        lease.deadline=monotonic()+30; client.renew_training.side_effect=None
        client.renew_training.return_value={'gateTokenId':str(uuid4()),'deadline':monotonic()+60}
        with self.assertRaises(FleetIntakeError): lease.renew()

    def test_parent_waits_for_child_exit_before_lineage_and_does_not_claim_failed_receipt(self):
        process=Mock();process.stdout=[];process.wait.return_value=0;process.pid=123
        client=Mock();client.finish_training.return_value={'state':'failed'}
        done=[]
        with patch('smartlabel.training.best_ultralytics_device',return_value='cpu'), \
             patch('smartlabel.training.subprocess.Popen',return_value=process), \
             patch.object(FleetDatasetClient,'for_training',return_value=client), \
             patch('smartlabel.fleet_training.validate_managed_config'):
            # The stream is a context manager like Popen.stdout.
            from contextlib import nullcontext
            process.stdout=nullcontext([])
            TrainingJob(TrainingConfig(**self.config),lambda _:None,done.append)._run()
        process.wait.assert_called_once()
        client.finish_training.assert_called_once_with(self.context,0)
        self.assertEqual(done,[1])

    def test_generic_model_and_dataset_paths_stay_blocked_even_if_flags_changed(self):
        managed=self.root/'fleet_datasets';managed.mkdir();(managed/'.fleet-storage-v1.json').write_text('{}');(managed/'model-index.json').write_text('{"schemaVersion":"FleetModelIndexV1","sha256":[]}')
        model=managed/'best.pt';model.write_bytes(b'fixture')
        (managed/'dataset.json').write_text('{"trainAllowed":true}')
        for function,arg in [(require_legacy_model,model),(require_legacy_training_data,managed)]:
            with self.assertRaises(FleetIntakeError): function(arg)
        with self.assertRaises(FleetIntakeError): export_jetson_onnx(model,self.root/'output.onnx')
        self.assertFalse((self.root/'output.onnx').exists())
        legacy=self.root/'legacy.pt';legacy.write_bytes(b'legacy')
        require_legacy_model(legacy)
        legacy.with_suffix('.pt.fleet_lineage.json').write_text('{}')
        with self.assertRaises(FleetIntakeError): require_legacy_model(legacy)

    def test_bundle_withdrawn_before_gate_creates_no_output(self):
        from smartlabel.fleet_hydro_export import build_fleet_hydro_package
        client=Mock();client.begin_bundle.side_effect=FleetIntakeError('withdrawn')
        config={'deploymentMode':'shadow','thresholds':{key:{} for key in ['plant_presence','yellow_leaf','wilt']}}
        with self.assertRaises(FleetIntakeError): build_fleet_hydro_package(client,self.project,[str(uuid4())],config,lambda _:None,Event())
        self.assertFalse((self.root/'fleet_datasets').exists())
        client.finish_bundle.assert_not_called()

    def test_known_checkpoint_copied_into_legacy_workspace_is_still_blocked(self):
        import hashlib
        managed=self.root/'fleet_datasets';managed.mkdir()
        original=b'known fleet checkpoint';copied=self.root/'renamed.pt';copied.write_bytes(original)
        (managed/'model-index.json').write_text(json.dumps({'schemaVersion':'FleetModelIndexV1','sha256':[hashlib.sha256(original).hexdigest()]}))
        with self.assertRaises(FleetIntakeError): require_legacy_model(copied)
        other=self.store.create_project('Legacy other')
        target=self.store.project_dir(other)/'renamed.pt';target.write_bytes(original)
        with self.assertRaises(FleetIntakeError): require_legacy_model(target)
        target.write_bytes(b'unrelated legacy checkpoint');require_legacy_model(target)

    def copy_receipt(self, payload):
        return dict(schemaVersion='FleetDatasetMaterializedV1',projectBinding=self.binding,
            **{k:payload[k] for k in ('operationId','copyId','snapshotBindingDigest','kind')},
            subjectDigest='b'*64,gateTokenId=str(uuid4()),inventoryDigest='c'*64,
            path=str(self.root/'fleet_datasets'/'copies'/payload['copyId']),state='ready',trainCounts={'absent':1,'present':1})

    def test_lost_copy_reply_survives_reopen_and_reconciles_without_second_copy(self):
        (self.root/'fleet_datasets').mkdir()
        with patch.object(self.client,'_call',side_effect=FleetIntakeError('reply lost')):
            with self.assertRaises(FleetIntakeError): self.client.materialize('a'*64,'yellow_leaf')
        held=deepcopy(self.client.pending)
        reopened=FleetDatasetClient(self.root,self.project.id,port=19991)
        self.assertEqual(reopened.pending,held)
        with patch.object(reopened,'_call') as call:
            with self.assertRaises(FleetIntakeError): reopened.materialize('a'*64,'yellow_leaf')
            call.assert_not_called()
        receipt=dict(schemaVersion='FleetDatasetOperationReceiptV1',operationId=held['payload']['operationId'],
                     state='ready',result=self.copy_receipt(held['payload']))
        with patch.object(reopened,'_call',return_value=receipt) as call:
            self.assertEqual(reopened.reconcile()['copyId'],held['payload']['copyId'])
            self.assertEqual(call.call_args.args[0],'receipt');self.assertEqual(call.call_count,1)
        self.assertFalse(reopened.pending_file.exists())

    def test_explicit_reconcile_retry_keeps_original_ids_and_wrong_receipt_keeps_journal(self):
        (self.root/'fleet_datasets').mkdir()
        with patch.object(self.client,'_call',side_effect=FleetIntakeError('offline')):
            with self.assertRaises(FleetIntakeError): self.client.materialize('a'*64,'yellow_leaf')
        held=deepcopy(self.client.pending)
        response=dict(schemaVersion='FleetDatasetOperationReceiptV1',operationId=held['payload']['operationId'],state='not_started',result=None)
        with patch.object(self.client,'_call',side_effect=[response,self.copy_receipt(held['payload'])]) as call:
            self.client.reconcile()
            self.assertEqual(call.call_args_list[1].args,('materialize',held['payload']))
        with patch.object(self.client,'_call',side_effect=FleetIntakeError('offline')):
            with self.assertRaises(FleetIntakeError): self.client.materialize('a'*64,'yellow_leaf')
        response['operationId']=str(uuid4())
        with patch.object(self.client,'_call',return_value=response):
            with self.assertRaises(FleetIntakeError):self.client.reconcile()
        self.assertTrue(self.client.pending_file.exists())
        response['operationId']=self.client.pending['payload']['operationId'];response['state']='uncertain'
        with patch.object(self.client,'_call',return_value=response):
            with self.assertRaises(FleetIntakeError):self.client.discard_pending()
        response['state']='blocked'
        with patch.object(self.client,'_call',return_value=response): self.client.discard_pending()
        self.assertFalse(self.client.pending_file.exists())

    def test_catalog_reads_bounded_pages_and_does_not_silently_drop_history(self):
        rows=[dict(copyId=str(uuid4()),operationId=str(uuid4()),state='ready',kind='export',snapshotBindingDigest='a'*64) for _ in range(65)]
        def page(action,payload):
            self.assertEqual(action,'catalog');offset=payload['offset']
            return dict(schemaVersion='FleetDatasetCatalogV1',projectBinding=self.binding,nextOffset=offset+32 if offset+32<len(rows) else None,
                        snapshots=[],copies=rows[offset:offset+32],runs=[],bundles=[])
        with patch.object(self.client,'_call',side_effect=page) as call:
            self.assertEqual(self.client.catalog()['copies'],rows);self.assertEqual(call.call_count,3)

    def supplement_preview(self):
        from smartlabel import fleet_dataset_contract as contract
        item = dict(contributionId=str(uuid4()), assetId=str(uuid4()), importId='2'*64, imageSha256='a'*64,
                    pixelFingerprint='b'*64, reviewRevision='c'*64, labelSha256='d'*64, groupId='e'*64,
                    split='train', sourceKind='hydro_slot')
        snapshot = dict(schemaVersion='FleetDatasetSnapshotV1', projectBinding=self.binding,
                        projectContextSha256='f'*64, items=[item], snapshotDigest=contract.digest([item]))
        return dict(schemaVersion='FleetDatasetPreviewV2', snapshot=snapshot, splitRevision='1'*64, includeSupplements=True,
                    summary=dict(imageCount=1, excludedCount=0, legacyCount=3, supplementCount=2,
                                 sources=dict(hydro_slot=1, phone_supplement=0), splits=dict(train=1, val=0, test=0),
                                 groups=[{key:item[key] for key in ('groupId','split','sourceKind')}]))

    def test_supplement_selection_is_explicit_and_preserved_in_pending_registration(self):
        value = self.supplement_preview()
        with patch.object(self.client, '_call', return_value=value) as call:
            result = self.client.preview([value['snapshot']['items'][0]['contributionId']], include_supplements=True)
            self.assertIs(call.call_args.args[1]['includeSupplements'], True)
            self.assertEqual(result['summary']['supplementCount'], 2)
        (self.root/'fleet_datasets').mkdir()
        with patch.object(self.client, '_call', side_effect=FleetIntakeError('lost reply')):
            with self.assertRaises(FleetIntakeError): self.client.register(result)
        reopened = FleetDatasetClient(self.root, self.project.id, port=19991)
        self.assertIs(reopened.pending['payload']['includeSupplements'], True)
        self.assertEqual(reopened.pending['payload']['snapshot'], value['snapshot'])

    def test_supplement_preview_does_not_fall_back_on_missing_old_or_malformed_response(self):
        for mutate in [lambda v:v.pop('includeSupplements'), lambda v:v.update(includeSupplements=False),
                       lambda v:v.update(schemaVersion='FleetDatasetPreviewV1'), lambda v:v['summary'].pop('supplementCount'),
                       lambda v:v['summary'].update(supplementCount=True), lambda v:v['summary'].update(supplementCount=2001)]:
            value = self.supplement_preview(); mutate(value)
            with patch.object(self.client, '_call', return_value=value):
                with self.assertRaises(FleetIntakeError): self.client.preview([], include_supplements=True)
        with patch.object(self.client, '_call') as call:
            with self.assertRaises(FleetIntakeError): self.client.preview([], include_supplements='true')
            call.assert_not_called()

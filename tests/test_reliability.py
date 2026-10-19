import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import update_transaction as tx
import system_update as runner
import publish_cloud_main_source as api
import cloud_update_request as cloud
from verify_live_report import equivalent

class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'work').mkdir()
    def tearDown(self): self.temp.cleanup()
    def make_outputs(self,base,label):
        for name in ('data','reports','site'):
            (base/name).mkdir(parents=True,exist_ok=True)
            (base/name/'value').write_text(label)
        (base/'fantasy5_full_history.csv').write_text(label)
    def values(self):
        return [(self.root/n/'value').read_text() for n in ('data','reports','site')]+[(self.root/'fantasy5_full_history.csv').read_text()]
    def test_success_promotes_all_outputs(self):
        self.make_outputs(self.root,'old');stage=self.root/'work/stage-good';self.make_outputs(stage,'new')
        tx.promote(stage,self.root)
        self.assertEqual(self.values(),['new']*4)
        self.assertFalse((self.root/'work/promotion.json').exists())
    def test_failure_at_every_move_restores_last_good(self):
        for step in range(1,5):
            with self.subTest(step=step):
                self.make_outputs(self.root,'old');stage=self.root/f'work/stage-{step}';self.make_outputs(stage,'new')
                with self.assertRaises(OSError): tx.promote(stage,self.root,fail_after=step)
                self.assertEqual(self.values(),['old']*4)
    def test_process_crash_journal_restores_all(self):
        self.make_outputs(self.root,'old');stage=self.root/'work/stage-crash';self.make_outputs(stage,'new')
        backup=self.root/'work/rollback-crash';backup.mkdir()
        entries=[{'name':n,'existed':True} for n in ('data','reports','site','fantasy5_full_history.csv')]
        tx.atomic_json(self.root/'work/promotion.json',{'phase':'moving','stage':str(stage),'backup':str(backup),'entries':entries})
        os.replace(self.root/'data',backup/'data');os.replace(stage/'data',self.root/'data')
        self.assertTrue(tx.recover(self.root));self.assertEqual(self.values(),['old']*4)
        self.assertFalse(tx.recover(self.root))
    def test_committed_journal_preserves_new_outputs(self):
        self.make_outputs(self.root,'new');stage=self.root/'work/stage-finished';stage.mkdir()
        backup=self.root/'work/rollback-finished';self.make_outputs(backup,'old')
        tx.atomic_json(self.root/'work/promotion.json',{'phase':'committed','stage':str(stage),'backup':str(backup),'entries':[{'name':n,'existed':True} for n in ('data','reports','site','fantasy5_full_history.csv')]})
        tx.recover(self.root);self.assertEqual(self.values(),['new']*4)
    def test_concurrent_process_is_rejected_and_lock_releases(self):
        path=self.root/'work/update.lock'
        code='from update_transaction import UpdateLock,UpdateBusy\nimport sys\ntry:\n with UpdateLock(sys.argv[1]): pass\nexcept UpdateBusy: sys.exit(75)'
        with tx.UpdateLock(path):
            child=subprocess.run([sys.executable,'-c',code,str(path)],cwd=ROOT)
            self.assertEqual(child.returncode,75)
        with tx.UpdateLock(path): pass
    def test_abrupt_exit_releases_os_lock(self):
        path=self.root/'work/update.lock'
        code='from update_transaction import UpdateLock\nimport os,sys\nlock=UpdateLock(sys.argv[1]);lock.__enter__();os._exit(3)'
        self.assertEqual(subprocess.run([sys.executable,'-c',code,str(path)],cwd=ROOT).returncode,3)
        with tx.UpdateLock(path): pass
    def test_cleanup_refuses_outside_workspace(self):
        with self.assertRaises(ValueError):tx.safe_remove(self.root/'site',self.root)
        with self.assertRaises(ValueError):tx.safe_remove(self.root/'work',self.root)
    def test_missing_output_never_replaces_current_report(self):
        self.make_outputs(self.root,'old');stage=self.root/'work/stage-missing';stage.mkdir()
        with self.assertRaises(RuntimeError):tx.promote(stage,self.root)
        self.assertEqual(self.values(),['old']*4)
    def test_calculation_failure_cannot_modify_live_outputs(self):
        self.make_outputs(self.root,'old');stage=self.root/'work/stage-worker';stage.mkdir()
        with patch.object(tx,'prepare_stage',return_value=stage),patch.object(tx.subprocess,'run',return_value=Mock(returncode=1)):
            with self.assertRaises(RuntimeError):tx.isolated_update(self.root)
        self.assertEqual(self.values(),['old']*4)
        self.assertTrue(json.loads((self.root/'work/update_status.json').read_text())['last_good_report_preserved'])
    def test_bad_json_never_passes_audit(self):
        (self.root/'reports').mkdir();(self.root/'reports/latest_analysis.json').write_text('{broken')
        with patch.object(runner,'ROOT',self.root):
            with self.assertRaises(json.JSONDecodeError):runner.audit(Mock())
    def test_float_tolerance_does_not_accept_changed_predictions(self):
        self.assertTrue(equivalent([1.0792260884481768],[1.0792260884481766]))
        self.assertFalse(equivalent({'ranking':[2,3]},{'ranking':[3,2]}))
        self.assertFalse(equivalent({'score':65.6},{'score':65.7}))
    def test_cloud_entry_only_dispatches_verified_workflow(self):
        with patch.object(cloud,'request_json',return_value={}) as call:
            cloud.request_update('test-token')
        self.assertEqual(call.call_count,1)
        self.assertIn('/dispatches',call.call_args.args[0])
        self.assertEqual(call.call_args.kwargs['data'],{'ref':'main'})
    def test_network_failure_retries_reads_but_not_writes(self):
        import urllib.error
        with patch.object(api.urllib.request,'urlopen',side_effect=urllib.error.URLError('offline')) as call,patch.object(api.time,'sleep'):
            with self.assertRaises(urllib.error.URLError):api.request_json('repos/test','test-token')
            self.assertEqual(call.call_count,3)
        with patch.object(api.urllib.request,'urlopen',side_effect=urllib.error.URLError('offline')) as call:
            with self.assertRaises(urllib.error.URLError):api.request_json('repos/test','test-token',data={},method='POST')
            self.assertEqual(call.call_count,1)
    def test_worker_cannot_overwrite_production_directly(self):
        child=subprocess.run([sys.executable,'system_update.py','--worker'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertNotEqual(child.returncode,0)
        self.assertIn(b'isolated update workspace',child.stderr)
    def audit_fixture(self):
        a=json.loads((ROOT/'reports/latest_analysis.json').read_text(encoding='utf-8-sig'))
        from ensemble50 import number_percentages
        a['ensemble50']['number_percentages']=number_percentages(a['ensemble50']['modules'])
        for name in ('reports','site'):(self.root/name).mkdir(exist_ok=True)
        for name in ('reports/latest_analysis.json','site/latest_analysis.json'):
            (self.root/name).write_text(json.dumps(a),encoding='utf-8')
        text=' '.join(['ensemble50-required','top15-six-groups','full39-six-groups','適用日期',a['target_draw_date']]+[p['name'] for p in a['ensemble50']['packs']])
        for name in ('index.html','prediction.html','latest_battle_report.html'):(self.root/'site'/name).write_text(text,encoding='utf-8')
        game=Mock();game.latest_allowed_draw_date.return_value=a['latest_draw']['draw_date'];game.next_date.return_value=a['target_draw_date'];game.iso_local.return_value='test';game.source_is_confirmed.return_value=True
        return a,game
    def run_audit(self,game):
        with patch.object(runner,'ROOT',self.root),contextlib.redirect_stdout(io.StringIO()):return runner.audit(game)
    def test_valid_outputs_pass(self):
        a,game=self.audit_fixture();self.assertEqual(self.run_audit(game)['status'],'passed')
    def test_tampered_single_number_percentage_blocks_publication(self):
        a,game=self.audit_fixture();a['ensemble50']['number_percentages']['numbers'][0]['ranking_score_percent']+=1
        for name in ('reports/latest_analysis.json','site/latest_analysis.json'):(self.root/name).write_text(json.dumps(a),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'單號百分比'):self.run_audit(game)
    def test_stale_data_is_rejected(self):
        a,game=self.audit_fixture();game.latest_allowed_draw_date.return_value='2099-01-01'
        with self.assertRaisesRegex(RuntimeError,'開獎資料落後'):self.run_audit(game)
    def test_unconfirmed_source_is_rejected(self):
        a,game=self.audit_fixture();game.source_is_confirmed.return_value=False
        with self.assertRaisesRegex(RuntimeError,'來源標記'):self.run_audit(game)
    def test_claimed_50_modules_cannot_hide_missing_module(self):
        a,game=self.audit_fixture();a['ensemble50']['modules'].pop()
        for name in ('reports/latest_analysis.json','site/latest_analysis.json'):(self.root/name).write_text(json.dumps(a),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'模組內容缺漏'):self.run_audit(game)
    def test_mobile_drift_is_rejected(self):
        a,game=self.audit_fixture();a['target_draw_date']='2000-01-01';(self.root/'site/latest_analysis.json').write_text(json.dumps(a),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'JSON不一致'):self.run_audit(game)
    def test_corrupt_hit_statistics_are_rejected(self):
        a,game=self.audit_fixture();a['ensemble50']['full39_six_combinations']['groups'][0]['backtest_hits_at_least']['2']=61
        for name in ('reports/latest_analysis.json','site/latest_analysis.json'):(self.root/name).write_text(json.dumps(a),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'回測命中統計無效'):self.run_audit(game)
    def test_nonfinite_json_is_rejected(self):
        a,game=self.audit_fixture();a['ensemble50']['full39_six_combinations']['groups'][0]['model_score']=float('nan')
        (self.root/'reports/latest_analysis.json').write_text(json.dumps(a),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Invalid JSON numeric'):self.run_audit(game)
    def test_deep_mode_preserves_full_review_configuration(self):
        with patch.dict(os.environ,{},clear=True):
            runner.runtime_defaults('deep')
            self.assertEqual(os.environ['TIANTIANLE_CORE_BACKTEST_ROUNDS'],'120')
            self.assertEqual(os.environ['TIANTIANLE_GROUP_BACKTEST_LONG'],'240')
    def test_legacy_publisher_has_no_second_publication_path(self):
        import publish_mobile_site_only as legacy
        with patch.object(cloud,'main') as request:legacy.main()
        request.assert_called_once()
    def test_duplicate_extra_number_cannot_pass_as_six_numbers(self):
        a,game=self.audit_fixture();g=a['ensemble50']['full39_six_combinations']['groups'][0];g['numbers'].append(g['numbers'][0])
        for name in ('reports/latest_analysis.json','site/latest_analysis.json'):(self.root/name).write_text(json.dumps(a),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'號碼格式錯誤'):self.run_audit(game)
    def test_boolean_is_not_a_lottery_number(self):
        a,game=self.audit_fixture();a['ensemble50']['full39_six_combinations']['groups'][0]['numbers'][0]=True
        for name in ('reports/latest_analysis.json','site/latest_analysis.json'):(self.root/name).write_text(json.dumps(a),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'號碼格式錯誤'):self.run_audit(game)

if __name__=='__main__':unittest.main()

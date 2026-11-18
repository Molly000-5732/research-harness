import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'my-harness-ui'))
import workspace as ws
import research_experiments as rx

CODE='''from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
def build_models(seed):
    return {"baseline": LogisticRegression(C=1.0, max_iter=1000, random_state=seed), "ablation": SVC(C=10.0, kernel="rbf", gamma="scale"), "improved": SVC(C=10.0, kernel="rbf", gamma="scale")}
'''

class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=ws.DATA
        ws.DATA=Path(self.temp.name)
    def tearDown(self):
        ws.DATA=self.old
        self.temp.cleanup()
    def test_required_plan_fields(self):
        data={'items':[{'plan':{k: ['a'] if k in ['metrics','risks'] else [{'title':'step','detail':'operation'}]*5 if k=='steps' else 'specific value' for k in rx.PLAN_LABELS}}]}
        result=rx.validate_plan(data)
        self.assertEqual(result['schemaVersion'],'research-plan-v2')
        del data['items'][0]['plan']['baseline']
        with self.assertRaises(ValueError):rx.validate_plan(data)
    def test_fixed_protocol_overrides_model_comparison_and_keeps_draft(self):
        plan={k: ['a'] if k in ['metrics','risks'] else [{'title':'step','detail':'operation'}]*5 if k=='steps' else 'draft' for k in rx.PLAN_LABELS}
        plan['acceptance']='wrong comparison: improved vs ablation threshold'
        output=rx.validate_plan({'items':[{'plan':plan}]},rx.PROTOCOL)
        item=output['items'][0]
        self.assertIn('improved − baseline',item['plan']['acceptance'])
        self.assertIn('wrong comparison',item['modelDraft']['acceptance'])
        self.assertIn('LogisticRegression',item['plan']['baseline'])
        self.assertEqual(output['executionProtocol']['id'],'digits-noise-v1')
    def test_protocol_is_not_selected_by_field_text(self):
        p=ws.create('digits-noise-v1')
        with self.assertRaisesRegex(ValueError,'自动执行协议'):rx.start(ws,'',p['id'])
    def test_plan_format_repair_once_preserves_protocol(self):
        p=rx.example(ws)
        p['jobs'].append({'id':'b'*12,'stage':'plan','status':'running','events':[]})
        ws.save(p)
        fields={k: ['a'] if k in ['metrics','risks'] else [{'title':'step','detail':'operation'}]*5 if k=='steps' else 'draft' for k in rx.PLAN_LABELS}
        valid={'summary':'fixture','items':[{'title':'plan','content':'draft','plan':fields,'references':[]}]}
        with patch.object(ws,'model',side_effect=['{invalid json',json.dumps(valid)]) as model:
            ws.worker('fixture',p['id'],'b'*12,'plan')
            self.assertEqual(model.call_count,2)
        saved=ws.load(p['id'])
        self.assertEqual(saved['jobs'][-1]['status'],'completed')
        self.assertIn('improved − baseline',saved['outputs']['plan']['items'][0]['plan']['acceptance'])
    def test_stale_results_cannot_validate_new_plan(self):
        p=ws.create('test project')
        p['outputs']['experiment']={'stale':False}
        p['resultSources']=[{'text':'old result','stale':False,'inputFingerprint':rx.fingerprint(p)}]
        self.assertTrue(ws.result_context(p))
        rx.invalidate(p);p['resultsInvalidated']=True;p['results']='old aggregate'
        self.assertEqual(ws.result_context(p),'')
    def test_artifact_path_rejects_unlisted_file(self):
        p=ws.create('test project')
        for name in ['../.env','.env','project.json']:
            with self.assertRaises(ValueError):rx.artifact(ws,p['id'],'a'*12,name)
    def test_cancelled_generation_cannot_submit_or_execute(self):
        p=rx.example(ws)
        p['outputs'].update(plan={'runId':'p1','stale':False},experiment={'runId':'e1','stale':False})
        p['selections']['plan']='plan-1';ws.save(p)
        entered=threading.Event();release=threading.Event()
        def delayed(*args):
            entered.set();release.wait(5)
            return json.dumps({'code':CODE})
        with patch.object(rx,'capabilities',return_value={'digits':True}),patch.object(ws,'model',side_effect=delayed),patch.object(rx,'execute') as execute:
            rx.start(ws,'fixture',p['id'])
            self.assertTrue(entered.wait(5))
            ws.mutate(p['id'],'cancel',{})
            release.set()
            end=time.monotonic()+5
            while time.monotonic()<end:
                latest=ws.load(p['id'])
                if latest['jobs'][-1]['events']:break
                time.sleep(.05)
            # The first event precedes the delayed model; allow its thread to observe cancellation.
            time.sleep(.15)
            execute.assert_not_called()
            self.assertEqual(ws.load(p['id'])['experimentRuns'],[])
            self.assertEqual(ws.load(p['id'])['jobs'][-1]['status'],'cancelled')
    @unittest.skipUnless(rx.capabilities()['digits'],'optional experiment dependencies missing')
    def test_evaluator_rejects_unrestricted_code(self):
        directory=Path(self.temp.name)
        (directory/'models.py').write_text('import os\nos.system("echo should_not_run")',encoding='utf-8')
        (directory/'protocol.json').write_text(json.dumps(rx.PROTOCOL),encoding='utf-8')
        r=subprocess.run([sys.executable,'-I',str(rx.ASSETS/'evaluate_digits.py'),'--source','models.py','--protocol','protocol.json'],cwd=directory,capture_output=True,text=True,encoding='utf-8')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('should_not_run',r.stdout)
    @unittest.skipUnless(rx.capabilities()['digits'],'optional experiment dependencies missing')
    def test_real_training_repair_download_and_metric_guard(self):
        p=rx.example(ws)
        p['outputs'].update(plan={'runId':'p1','stale':False},experiment={'runId':'e1','stale':False})
        p['selections']['plan']='plan-1';ws.save(p)
        generated=[json.dumps({'code':'import os\ndef build_models(seed):\n    return {}'}),json.dumps({'code':CODE})]
        with patch.object(ws,'model',side_effect=generated):
            answer=rx.start(ws,'unused-fixture',p['id'])
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                latest=ws.load(p['id'])
                if latest['jobs'][-1]['status']!='running':break
                time.sleep(.1)
            self.assertEqual(latest['jobs'][-1]['status'],'completed',latest['jobs'][-1])
        record=latest['experimentRuns'][-1]
        self.assertEqual(len(record['result']['runs']),9)
        self.assertEqual(len(record['provenance']['attempts']),2)
        self.assertTrue(ws.result_context(latest))
        self.assertTrue(rx.artifact(ws,p['id'],answer['jobId'],'metrics.csv').is_file())
        (ws.folder(p['id'])/'experiments'/answer['jobId']/'metrics.csv').write_text('modified',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'完整性'):rx.artifact(ws,p['id'],answer['jobId'],'metrics.csv')
        tampered=copy.deepcopy(record['result']);tampered['runs'][0]['noisyAccuracy']=0.0
        with self.assertRaises(ValueError):rx.validate_metrics(tampered)
        rx.invalidate(latest);latest['resultsInvalidated']=True
        self.assertEqual(ws.result_context(latest),'')

if __name__=='__main__':unittest.main()

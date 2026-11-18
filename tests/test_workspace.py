import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).parents[1]/"my-harness-ui"))

spec = importlib.util.spec_from_file_location('workspace', Path(__file__).parents[1]/'my-harness-ui'/'workspace.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=w.DATA
        w.DATA=Path(self.temp.name)
        self.p=w.create('isolated project')
    def tearDown(self):
        w.DATA=self.old
        self.temp.cleanup()
    def test_project_boundaries(self):
        other=w.create('second project')
        w.mutate(self.p['id'],'upload',{'name':'a.txt','base64':base64.b64encode(b'project one only').decode(),'kind':'literature'})
        self.assertEqual(w.load(other['id'])['files'],[])
        with self.assertRaises(ValueError):w.folder('../outside')
    def test_evidence_quote_guard(self):
        self.p['papers']=[{'id':'P1','core':True,'abstract':'A real observed limitation.'}]
        valid={'summary':'summary','items':[{'title':'q','content':'content','references':[{'paperId':'P1','quote':'real observed limitation','level':'abstract'}]}]}
        self.assertTrue(w.validate_output(valid,self.p,'questions'))
        valid['items'][0]['references'][0]['quote']='invented finding'
        with self.assertRaises(ValueError):w.validate_output(valid,self.p,'questions')
        valid['items'][0]['references'][0]={'paperId':'P2','quote':''}
        with self.assertRaises(ValueError):w.validate_output(valid,self.p,'questions')
    def test_selection_invalidates_downstream(self):
        self.p['outputs']={'questions':{'items':[{'id':'questions-1'}]},'painpoints':{'items':[],'stale':False}}
        w.save(self.p)
        p=w.mutate(self.p['id'],'select',{'stage':'questions','itemId':'questions-1'})
        self.assertTrue(p['outputs']['painpoints']['stale'])
    def test_requires_real_results(self):
        self.p['outputs']['experiment']={'stale':False}
        w.save(self.p)
        with self.assertRaisesRegex(ValueError,'真实实验结果'):w.start('',self.p['id'],'validation')
    def test_restart_marks_interrupted(self):
        self.p['jobs']=[{'id':'test','status':'running'}]
        w.save(self.p)
        w.recover()
        self.assertEqual(w.load(self.p['id'])['jobs'][0]['status'],'failed')
    def test_nonempty_single_plan(self):
        with self.assertRaises(ValueError):w.validate_output({'summary':'x','items':[]},self.p,'plan')

if __name__=='__main__':unittest.main()

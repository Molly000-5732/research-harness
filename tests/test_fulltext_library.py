import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'my-harness-ui'))
import workspace as ws
import fulltext_library as ft

class FulltextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=ws.DATA;ws.DATA=Path(self.temp.name)
        self.p=ws.create('underwater research test')
        self.paper={'id':'Dtest','title':'Underwater Robot Grasping Perception','url':'https://example.org/paper','core':True,'doi':'','authors':[],'year':2024,'venue':'fixture','source':'fixture'}
        self.p['papers']=[self.paper];ws.save(self.p)
        self.text='[第1页]\nUnderwater Robot Grasping Perception\n\n'+('Visual servo control uses robust camera observations for underwater grasping. '*50)+'\n\n[第2页]\n## Methods\n\n'+('Refractive calibration corrects geometric distortion in the camera model. '*50)+'\n\n## Results\n\n'+('The fixture reports only supplied observations and does not imply a scientific result. '*40)
    def tearDown(self):ws.DATA=self.old;self.temp.cleanup()
    def store(self):
        ft.store_document(ws,self.p['id'],self.paper,self.text,self.text.encode(),'.md',self.paper['url'],'fixture')
        return ws.load(self.p['id'])
    def test_api_and_local_targets_rejected(self):
        for url in ['https://api.crossref.org/works','https://api.openalex.org/works','http://localhost/test','http://127.0.0.1/a.pdf','https://example.org/api/search','file:///a.pdf']:
            with self.subTest(url=url),self.assertRaises(ValueError):ft.safe_url(url,resolve=False)
        self.assertEqual(ft.safe_url('https://example.org/paper.pdf',resolve=False),'https://example.org/paper.pdf')
    def test_headless_json_blocks_merge_without_discarding_data(self):
        self.assertEqual(ws.parse_json('{"summary":"s"}\n{"items":[1]}'),{'summary':'s','items':[1]})
        with self.assertRaises(ValueError):ws.parse_json('{"summary":"a"}\n{"summary":"b"}')
        with self.assertRaises(ValueError):ws.parse_json('{"summary":"a"}not json')
    def test_review_report_can_have_nine_sections(self):
        result={'summary':'review','items':[{'title':'section','content':'analysis','references':[]} for _ in range(9)]}
        self.assertEqual(len(ws.validate_output(result,self.p,'validation')['items']),9)
        with self.assertRaises(ValueError):ws.validate_output(result,self.p,'questions')
    def test_metadata_is_not_fulltext(self):
        self.assertEqual(ft.coverage(self.p)['fulltextPapers'],0)
        with self.assertRaises(ValueError):ft.evidence(self.p,'robot grasping')
    def test_fragment_not_counted_as_fulltext(self):
        self.p['files']=[{'id':'a','kind':'literature','paperId':'Dtest','name':'abstract.txt','text':self.text,'contentLevel':'fragment'}]
        self.assertEqual(ft.segments(self.p),[])
    def test_saved_fulltext_and_project_isolation(self):
        p=self.store();self.assertEqual(ft.coverage(p)['fulltextPapers'],1)
        other=ws.create('different research')
        self.assertEqual(ft.segments(other),[])
        self.assertEqual(ft.file_text(p,p['files'][0]),self.text)
    def test_retrieval_uses_text_beyond_preview(self):
        p=self.store();rows=ft.select(p,'refractive calibration geometric distortion')
        self.assertIn('Refractive calibration',rows[0]['quote'])
        self.assertEqual(rows[0]['page'],2)
    def test_quote_and_page_are_bound_to_segment(self):
        p=self.store();row=ft.select(p,'refractive')[0]
        ref={'paperId':'Dtest','segmentId':row['id'],'quote':row['quote'][:90],'page':999}
        ft.verify_reference(p,ref)
        self.assertEqual(ref['page'],2);self.assertEqual(ref['level'],'fulltext')
        ref['quote']='This sentence was invented and does not exist.'
        with self.assertRaises(ValueError):ft.verify_reference(p,ref)
    def test_wrong_document_identity_rejected(self):
        self.assertTrue(ft.identity(self.paper,self.text))
        self.assertFalse(ft.body_quality(self.paper,'completely unrelated medical trial '*500,pdf=True))
    def test_search_snippet_is_not_complete_body(self):
        self.assertFalse(ft.body_quality(self.paper,'Underwater Robot Grasping Perception abstract snippet'))
    def test_download_deduplication(self):
        self.store();p=self.store();self.assertEqual(len(p['files']),1)
    def test_cancelled_download_does_not_commit(self):
        self.p['jobs']=[{'id':'j','status':'cancelled'}];ws.save(self.p)
        with self.assertRaises(RuntimeError):ft.store_document(ws,self.p['id'],self.paper,self.text,self.text.encode(),'.md',self.paper['url'],'fixture','j')
        self.assertEqual(ws.load(self.p['id'])['files'],[])
    def test_plugin_docs_cannot_supply_fake_search_source(self):
        def fake(*args,**kwargs):
            kwargs['trace'].extend([
                {'type':'tool_call','tool':'skill','callId':'s'},
                {'type':'tool_result','callId':'s','status':'completed','result':'https://example.org/fake'},
                {'type':'tool_call','tool':'web_search','callId':'w'},
                {'type':'tool_result','callId':'w','status':'completed','result':'https://example.org/real'}])
            return json.dumps({'papers':[{'title':'Fake paper','url':'https://example.org/fake'}]})
        with patch.object(ws,'model',side_effect=fake),self.assertRaises(ValueError):ft.discover(ws,'fixture',self.p['id'],'j')

if __name__=='__main__':unittest.main()

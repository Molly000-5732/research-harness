import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import HarnessManager
from server import make_server
from storage import Storage
from test_core import FakeSDK


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Storage(root / 'app.db')
        self.manager = HarnessManager(self.store, root / 'home', sdk_factory=FakeSDK)
        self.server = make_server(0, self.store, self.manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.manager.close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                                         headers=headers)
        with urllib.request.urlopen(request) as result:
            return result.read()

    def create(self):
        return json.loads(self.request('/api/projects', {'field': 'Noise research'}))['project']

    def test_field_creates_distinct_workspace_and_initializes_background(self):
        first, second = self.create(), self.create()
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['directory'], second['directory'])
        self.assertTrue(Path(first['directory']).is_dir())
        state = json.loads(self.request(f"/api/projects/{first['id']}/research"))
        self.assertEqual(state['background'], 'Noise research')
        self.assertTrue(state['stages']['questions']['ready'])
        self.assertFalse(state['stages']['plan']['ready'])

    def test_named_project_uses_selected_workspace_and_waits_for_background(self):
        workspace = self.store.path.parent / 'chosen-workspace'
        workspace.mkdir()
        project = json.loads(self.request('/api/projects', {
            'name': 'User chosen name', 'directory': str(workspace),
        }))['project']
        self.assertEqual(project['name'], 'User chosen name')
        self.assertEqual(Path(project['directory']), workspace.resolve())
        state = json.loads(self.request(f"/api/projects/{project['id']}/research"))
        self.assertEqual(state['background'], '')
        self.assertFalse(state['stages']['questions']['ready'])
        duplicate = json.loads(self.request('/api/projects', {
            'name': 'Another name', 'directory': str(workspace),
        }))['project']
        self.assertEqual(duplicate['id'], project['id'])
        self.assertEqual(duplicate['name'], project['name'])
        for directory in ('relative-path', str(workspace / 'does-not-exist')):
            with self.assertRaises(urllib.error.HTTPError) as failure:
                self.request('/api/projects', {'name': 'Invalid', 'directory': directory})
            self.assertEqual(failure.exception.code, 400)
            failure.exception.close()

    def test_large_attachment_roundtrip_and_file_boundary(self):
        project = self.create()
        path = f"/api/projects/{project['id']}/files"
        raw = ('column,value\n' * 15000).encode()
        result = json.loads(self.request(path, {'kind': 'results', 'name': 'results.csv',
                                                'base64': base64.b64encode(raw).decode()}))['file']
        listed = json.loads(self.request(path))['files']
        self.assertEqual(listed[0]['path'], result['path'])
        downloaded = self.request(path + '/' + urllib.parse.quote(result['path'], safe=''))
        self.assertEqual(downloaded, raw)
        for relative in ('../outside.json', '.env', 'C:/outside.json'):
            with self.assertRaises(urllib.error.HTTPError) as failure:
                self.request(path + '/' + urllib.parse.quote(relative, safe=''))
            self.assertEqual(failure.exception.code, 400)
            failure.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request(path, {'kind': 'results', 'name': 'unsafe.exe', 'base64': 'YWJj'})
        self.assertEqual(failure.exception.code, 400)
        failure.exception.close()

    def test_creation_and_upload_keep_origin_protection(self):
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request('/api/projects', {'field': 'Noise'}, origin='https://other.example')
        self.assertEqual(failure.exception.code, 403)
        failure.exception.close()

        project = self.create()
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request(f"/api/projects/{project['id']}/files", {'kind': 'literature', 'name': 'x.txt', 'base64': '%%%%'})
        self.assertEqual(failure.exception.code, 400)
        failure.exception.close()

    def test_workspace_plan_open_and_submit_reads_latest_file(self):
        project = self.create()
        research = self.server.research
        for stage in ('questions', 'painpoints', 'plan'):
            sid = research.session(project['id'], stage)
            with self.store.connect() as db:
                inputs = research.snapshot(db, project['id'])['stages'][stage]['inputs']
            self.store.create_run(stage, sid, 'Generate', inputs)
            self.store.finish(stage, 'completed', 'AI draft')
            if stage != 'plan':
                research.confirm(project['id'], stage, {'run_id':stage, 'content':stage+' confirmed'})
        document = Path(project['directory']) / 'plan.md'
        document.write_text('Old AI plan', encoding='utf-8')
        endpoint = f"/api/projects/{project['id']}/research/plan"
        with patch('project_files.open_plan_document') as opener:
            self.request(endpoint+'/open-document', {'path':'plan.md','run_id':'plan'})
            opener.assert_called_once_with(document.resolve())
            text = '人工修改后的最终研究方案\n' * 4000
            self.assertGreater(len(text.encode('utf-8')), 131072)
            document.write_text(text, encoding='utf-8')
            result = json.loads(self.request(endpoint+'/confirm-document', {
                'path':'plan.md','run_id':'plan','content':'Stale browser text must be ignored'}))
            self.assertEqual(result['research']['stages']['plan']['confirmed'], document.read_bytes().decode('utf-8').strip())
            self.assertTrue(result['research']['stages']['experiment']['ready'])
            research.update_background(project['id'], 'Updated scope')
            with self.assertRaises(urllib.error.HTTPError) as failure:
                self.request(endpoint+'/confirm-document', {'path':'plan.md','run_id':'plan'})
            self.assertEqual(failure.exception.code,409)
            failure.exception.close()
            for relative in ('../outside.md','script.py'):
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    self.request(endpoint+'/open-document', {'path':relative,'run_id':'plan'})
                self.assertEqual(failure.exception.code,400)
                failure.exception.close()
            self.assertEqual(opener.call_count,1)

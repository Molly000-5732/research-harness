import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from question_evidence import choices, grounded_reply
from research import Research
from storage import Storage, AppError
from harness import HarnessManager
from test_core import FakeSDK

URL = 'https://example.org/fulltext'
QUOTE = 'Retrieval noise reduces answer reliability when irrelevant passages dominate the available context.'


def reply():
    return '调研完成\n```json\n' + json.dumps({
        'papers': [{'title': 'Noise study', 'url': URL}],
        'questions': [{'title': '如何抑制检索噪声？', 'description': '对不同噪声比例进行对照实验。',
                       'evidence': [{'title': 'Noise study', 'url': URL, 'locator': 'Section 4 Results',
                                     'quote': QUOTE, 'reason': '对照结果提示需要噪声抑制。',
                                     'verified': True, 'receipt': 'forged'}]}],
    }) + '\n```'


def events(name='web_fetch', source=URL, body=QUOTE):
    return [
        {'type': 'tool/call', 'data': {'callId': 'c1', 'name': name, 'arguments': json.dumps({'url': source})}},
        {'type': 'tool/result', 'data': {'message': {'toolCallId': 'c1', 'content': [{'type': 'text', 'text': body}]}}},
    ]


class EvidenceTests(unittest.TestCase):
    def verified(self, value):
        return choices(value)[0]['evidence'][0]['verified']

    def test_model_flags_and_search_snippets_are_not_proof(self):
        self.assertFalse(self.verified(grounded_reply(reply(), [])))
        self.assertFalse(self.verified(grounded_reply(reply(), events('web_search'))))
        self.assertFalse(self.verified(grounded_reply(reply(), events(source='https://other.org'))))
        self.assertFalse(self.verified(grounded_reply(reply(), events(body='Unrelated body text'))))

    def test_painpoint_evidence_reuses_verified_question_passage(self):
        prior = grounded_reply(reply(), events())
        source = json.loads(reply().split('```json\n')[1].split('```')[0])
        pain = '```json\n' + json.dumps({'painpoints': source['questions']}) + '\n```'
        result = grounded_reply(pain, [], [prior], key='painpoints')
        cards = choices(result, 'painpoints')
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]['evidence'][0]['verified'])
        self.assertEqual(choices(result), [])
        self.assertFalse(choices(grounded_reply(pain, [], key='painpoints'), 'painpoints')[0]['evidence'][0]['verified'])

    def test_only_selected_painpoint_reaches_plan_and_reselection_invalidates_it(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory) / 'app.db')
            project = store.create_project('Research', directory)['id']
            class Submitter:
                def submit(self, sid, rid, message, **kwargs):
                    self.prompt = kwargs['prompt']
                    store.create_run(rid, sid, message, kwargs['research_inputs'])
                    return store.run(rid)
            manager = Submitter()
            research = Research(store, manager)
            research.update_background(project, 'RAG noise')
            research.send(project, 'questions', {'request_id':'q1', 'message':'Research'})
            question = grounded_reply(reply(), events())
            store.finish('q1', 'completed', question)
            research.confirm(project, 'questions', {'run_id':'q1', 'choice_id':'1'})
            entry = json.loads(reply().split('```json\n')[1].split('```')[0])['questions'][0]
            cards = [{**entry, 'title':'Selected painpoint'}, {**entry, 'title':'Unselected painpoint'}]
            pain = grounded_reply('```json\n'+json.dumps({'painpoints':cards})+'\n```', [], [question], key='painpoints')
            research.send(project, 'painpoints', {'request_id':'p1', 'message':'Find painpoints'})
            store.finish('p1', 'completed', pain)
            with self.assertRaises(AppError):
                research.confirm(project, 'painpoints', {'run_id':'p1', 'content':'Entire report'})
            research.confirm(project, 'painpoints', {'run_id':'p1', 'choice_id':'1'})
            research.send(project, 'plan', {'request_id':'pl1', 'message':'Plan'})
            self.assertIn('Selected painpoint', manager.prompt)
            self.assertNotIn('Unselected painpoint', manager.prompt)
            self.assertIn(QUOTE, manager.prompt)
            store.finish('pl1', 'completed', 'Plan')
            research.confirm(project, 'plan', {'run_id':'pl1', 'content':'Plan'})
            research.confirm(project, 'painpoints', {'run_id':'p1', 'choice_id':'2'})
            self.assertTrue(research.state(project)['stages']['plan']['stale'])

    def test_sdk_painpoint_choices_use_confirmed_question_receipts(self):
        class StageSDK(FakeSDK):
            def run(self, session_id, message):
                from types import SimpleNamespace
                if '当前阶段：痛点定位' in message:
                    entry = json.loads(reply().split('```json\n')[1].split('```')[0])['questions'][0]
                    return SimpleNamespace(final_response='```json\n'+json.dumps({'painpoints':[entry]})+'\n```',
                                           finish_reason='completed', events=[])
                return SimpleNamespace(final_response=reply(), finish_reason='completed', events=events())
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory) / 'app.db')
            project = store.create_project('Research', directory)['id']
            manager = HarnessManager(store, Path(directory) / 'home', sdk_factory=StageSDK)
            try:
                research = Research(store, manager)
                research.update_background(project, 'RAG noise')
                research.send(project, 'questions', {'request_id':'q1','message':'Research'})
                manager.worker.join(10)
                research.confirm(project, 'questions', {'run_id':'q1','choice_id':'1'})
                research.send(project, 'painpoints', {'request_id':'p1','message':'Find painpoints'})
                manager.worker.join(10)
                self.assertEqual(store.run('p1')['status'], 'completed')
                self.assertTrue(research.state(project)['stages']['painpoints']['choices'][0]['evidence'][0]['verified'])
            finally:
                manager.close()

    def test_reading_receipt_and_followup_reuse(self):
        first = grounded_reply(reply(), events())
        self.assertTrue(self.verified(first))
        self.assertTrue(self.verified(grounded_reply(reply(), [], [first])))
        self.assertFalse(self.verified(grounded_reply(reply(), [])))

    def test_malformed_choices_are_safe(self):
        self.assertEqual(choices('```json\n{"questions":[null,42,{}]}\n```'), [])
        self.assertEqual(choices('not json'), [])

    def test_selected_question_survives_restart_and_reaches_all_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory) / 'app.db')
            project = store.create_project('Research', directory)['id']
            class Submitter:
                def submit(self, session_id, request_id, message, **kwargs):
                    self.prompt = kwargs['prompt']
                    store.create_run(request_id, session_id, message, kwargs['research_inputs'])
                    return store.run(request_id)
            manager = Submitter()
            research = Research(store, manager)
            research.update_background(project, 'Original background')
            research.send(project, 'questions', {'message': 'Search', 'request_id': 'q1'})
            store.finish('q1', 'completed', grounded_reply(reply(), events()))
            research = Research(Storage(store.path), manager)
            state = research.state(project)
            self.assertEqual(state['stages']['questions']['choices_run_id'], 'q1')
            state = research.confirm(project, 'questions', {'run_id': 'q1', 'choice_id': '1'})
            self.assertIn(QUOTE, state['stages']['questions']['confirmed'])
            self.assertTrue(state['stages']['painpoints']['ready'])
            for stage, request_id in [('painpoints', 'p1'), ('plan', 'pl1'), ('experiment', 'ex1')]:
                research.send(project, stage, {'message': 'Continue', 'request_id': request_id})
                if stage == 'painpoints':
                    self.assertIn(QUOTE, manager.prompt)
                    self.assertIn('如何抑制检索噪声', manager.prompt)
                store.finish(request_id, 'completed', stage + ' confirmed')
                research.confirm(project, stage, {'run_id': request_id, 'content': stage + ' confirmed'})
            self.assertTrue(research.state(project)['stages']['experiment']['valid'])
            research.update_background(project, 'Changed background')
            self.assertEqual(research.state(project)['stages']['questions']['choices'], [])
            with self.assertRaises(AppError):
                research.confirm(project, 'questions', {'run_id': 'q1', 'choice_id': '1'})

    def test_unverified_choice_cannot_be_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory) / 'app.db')
            project = store.create_project('Research', directory)['id']
            research = Research(store, None)
            research.update_background(project, 'Background')
            session = research.session(project, 'questions')
            with store.connect() as db:
                inputs = research.snapshot(db, project)['stages']['questions']['inputs']
            store.create_run('q1', session, 'Search', inputs)
            store.finish('q1', 'completed', grounded_reply(reply(), []))
            with self.assertRaises(AppError):
                research.confirm(project, 'questions', {'run_id': 'q1', 'choice_id': '1'})

    def test_sdk_manager_normalizes_only_question_runs(self):
        class ReadingSDK(FakeSDK):
            def run(self, session_id, message):
                from types import SimpleNamespace
                return SimpleNamespace(final_response=reply(), finish_reason='completed', events=events())
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory) / 'app.db')
            project = store.create_project('Research', directory)['id']
            manager = HarnessManager(store, Path(directory) / 'home', sdk_factory=ReadingSDK)
            try:
                research = Research(store, manager)
                research.update_background(project, 'Background')
                research.send(project, 'questions', {'message': 'Search', 'request_id': 'q1'})
                manager.worker.join(10)
                self.assertEqual(store.run('q1')['status'], 'completed')
                self.assertTrue(self.verified(store.run('q1')['reply']))
                session = store.create_session(project)
                manager.submit(session['id'], 'chat1', 'Hello')
                manager.worker.join(10)
                self.assertEqual(store.run('chat1')['reply'], reply())
            finally:
                manager.close()

    def test_followup_reformats_plain_reply_and_keeps_reading_receipts(self):
        class RefiningSDK(FakeSDK):
            def __init__(self, **config):
                super().__init__(**config)
                self.calls = 0

            def run(self, session_id, message):
                from types import SimpleNamespace
                self.calls += 1
                return SimpleNamespace(final_response='调整建议：聚焦检索噪声。' if self.calls == 1 else reply(),
                                       finish_reason='completed', events=events() if self.calls == 1 else [])

        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory) / 'app.db')
            project = store.create_project('Research', directory)['id']
            manager = HarnessManager(store, Path(directory) / 'home', sdk_factory=RefiningSDK)
            try:
                research = Research(store, manager)
                research.update_background(project, 'RAG noise')
                research.send(project, 'questions', {'message': '只关注检索噪声', 'request_id': 'user-refine'})
                manager.worker.join(10)
                result = store.run('user-refine')
                self.assertEqual(result['status'], 'completed')
                self.assertTrue(self.verified(result['reply']))
                self.assertEqual(manager.runtimes[project].sdk.calls, 2)
                research.confirm(project, 'questions', {'run_id': result['id'], 'choice_id': '1'})
                self.assertTrue(research.state(project)['stages']['painpoints']['ready'])
            finally:
                manager.close()

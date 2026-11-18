"""Stage handoffs must use confirmed revisions while preserving session history."""

from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import Research, research_papers
from harness import ProjectRuntime
from storage import AppError, Storage


class ResearchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Storage(Path(temp.name) / "app.db")
        self.project = self.store.create_project("Research", temp.name)["id"]
        self.research = Research(self.store, self)

    def submit(self, session_id, request_id, message, *, prompt, research_inputs, experiment):
        self.prompt = prompt
        self.experiment = experiment
        self.store.create_run(request_id, session_id, message, research_inputs)
        return self.store.run(request_id)

    def stage_run(self, stage, request_id, reply):
        self.research.send(self.project, stage, {"request_id": request_id, "message": "Continue"})
        self.store.finish(request_id, "completed", reply, finish_reason="completed")

    def confirm(self, stage, request_id, text):
        return self.research.confirm(self.project, stage, {"run_id": request_id, "content": text})

    def test_stage_sessions_persist_and_use_confirmed_handoffs(self):
        self.research.update_background(self.project, "Original background")
        paper_reply = 'Draft\n```json\n{"papers":[{"title":"Paper A","abstract":"Abstract A","analysis":"Analysis A","url":"https://example.org/paper"}]}\n```'
        self.stage_run("questions", "q1", paper_reply)
        self.stage_run("questions", "q2", "Refined question")
        state = self.confirm("questions", "q2", "Approved question")
        self.assertEqual(state["papers"][0]["title"], "Paper A")
        self.stage_run("painpoints", "p1", "Initial painpoint")
        self.assertTrue(all(value in self.prompt for value in ("Approved question", "Paper A", "Abstract A", "Analysis A")))
        self.assertNotIn("Refined question", self.prompt)
        self.confirm("painpoints", "p1", "Approved painpoint")
        self.stage_run("plan", "pl1", "Initial plan")
        self.assertIn("Approved painpoint", self.prompt)
        self.assertNotIn("Paper A", self.prompt)
        self.confirm("plan", "pl1", "Approved plan")
        self.stage_run("experiment", "exp", "Analysis")
        self.assertTrue(self.experiment)
        self.assertIn("Approved plan", self.prompt)
        ids = {stage: item["session_id"] for stage, item in self.research.state(self.project)["stages"].items()}
        restarted = Research(Storage(self.store.path), self)
        self.assertEqual(len(set(ids.values())), 4)
        self.assertEqual(restarted.session(self.project, "questions"), ids["questions"])
        self.assertEqual(len(self.store.session(ids["questions"])["messages"]), 4)
        self.assertEqual(self.store.list_sessions(self.project), [])

    def test_reconfirmation_invalidates_downstream_revisions(self):
        self.research.update_background(self.project, "Original background")
        with self.assertRaises(AppError):
            self.stage_run("plan", "invalid", "")
        self.stage_run("questions", "q1", "Question")
        self.confirm("questions", "q1", "Question A")
        self.stage_run("painpoints", "p1", "Painpoint")
        self.confirm("painpoints", "p1", "Confirmed painpoint")
        state = self.confirm("questions", "q1", "Question B")
        self.assertTrue(state["stages"]["painpoints"]["stale"])
        self.assertEqual(state["stages"]["painpoints"]["confirmed"], "Confirmed painpoint")
        self.assertFalse(state["stages"]["plan"]["ready"])
        with self.assertRaises(AppError):
            self.confirm("painpoints", "p1", "Old run")

    def test_bibliography_accepts_http_sources_and_deduplicates(self):
        flags = research_papers('```json\n{"papers":['
            '{"title":"Unsafe","url":"javascript:alert(1)"},'
            '{"title":"Source","url":"https://example.org"},'
            '{"title":"Duplicate","url":"https://example.org"}]}\n```')
        self.assertEqual(flags, [{"title": "Source", "url": "https://example.org", "abstract": "", "analysis": ""}])

    def test_followup_uses_current_draft_and_discards_old_background_draft(self):
        self.research.update_background(self.project, 'Underwater docking')
        self.stage_run('questions', 'q1', 'Current docking questions with literature evidence')
        self.research.send(self.project, 'questions', {'request_id': 'q2', 'message': '只关注末端精度'})
        self.assertIn('Current docking questions with literature evidence', self.prompt)
        self.assertIn('只关注末端精度', self.prompt)
        self.assertIn('Underwater docking', self.prompt)
        self.store.finish('q2', 'completed', 'Refined docking questions')
        self.research.update_background(self.project, 'New project scope')
        self.research.send(self.project, 'questions', {'request_id': 'q3', 'message': '重新调研'})
        self.assertNotIn('Refined docking questions', self.prompt)

    def test_experiment_approval_binds_the_reviewed_call(self):
        answered = []
        client = SimpleNamespace(respond=lambda request_id, result: answered.append((request_id, result)))
        manager = SimpleNamespace(home=self.store.path.parent, model="test",
                                  sdk_factory=lambda **kwargs: SimpleNamespace(client=client))
        runtime = ProjectRuntime(manager, self.store.project(self.project))
        runtime.current_run = "experiment"
        runtime.experiment_session = "session"
        runtime.add_notice = lambda message: None
        request = SimpleNamespace(id=7, payload={"toolName": "pwsh", "callId": "call"})
        published = threading.Event()
        from unittest.mock import patch
        original_wait = threading.Event.wait

        def notify_when_ready(event, timeout=None):
            if timeout == 300:
                published.set()
            return original_wait(event, timeout)

        with patch.object(threading.Event, "wait", notify_when_ready):
            thread = threading.Thread(target=runtime.review_approval, args=(request,))
            thread.start()
            try:
                self.assertTrue(published.wait(5))
                approval = runtime.approval("experiment")
                decision = {"id": approval["id"], "outcome": "allowed-once"}
                with self.assertRaises(AppError):
                    runtime.approval("experiment", decision)
                runtime.on_notification(SimpleNamespace(method="session.event", payload={
                    "sessionId": "session", "event": {"type": "tool/call", "data": {
                        "name": "pwsh", "callId": "call", "arguments": '{"command":"Write-Output 1"}',
                    }},
                }))
                self.assertIn("Write-Output 1", runtime.approval("experiment")["arguments"])
                runtime.approval("experiment", decision)
            finally:
                with runtime.approval_lock:
                    if runtime.pending_approval:
                        runtime.pending_approval["wake"].set()
                thread.join(5)
        self.assertEqual(answered, [(7, {"outcome": "allowed-once"})])

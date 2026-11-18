"""Keyless regression checks for storage, requests, SDK lifecycle and HTTP."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deepseek_harness import DeepSeekHarness
from harness import HarnessManager, ProjectHarness, safe_error
from server import DataLock, make_server
from storage import AppError, Storage


class FakeSDK:
    """Small public-interface double with history surviving runtime restarts."""

    history = {}
    instances = []
    gate = None
    failure = False

    def __init__(self, **config):
        self.config = config
        self.client = self
        self.requests = queue.Queue()
        self.responses = []
        self.closed = False
        self.resumed = []
        self.instances.append(self)

    def start(self):
        if self.failure:
            raise RuntimeError("测试运行时启动失败")

    def start_session(self, session_id):
        self.history.setdefault(session_id, [])
        return SimpleNamespace(run=lambda message: self.run(session_id, message))

    def resume_session(self, session_id):
        if session_id not in self.history:
            raise RuntimeError("历史不存在")
        self.resumed.append(session_id)
        return self.start_session(session_id)

    def run(self, session_id, message):
        if self.gate:
            self.gate.wait(5)
        if message == "question":
            self.config["on_user_question"](SimpleNamespace(questions=[{"question": "继续吗？"}]), threading.Event())
        self.history[session_id].append(message)
        return SimpleNamespace(final_response=" | ".join(self.history[session_id]), finish_reason="completed", events=[])

    def next_request(self):
        item = self.requests.get()
        if item is None:
            raise RuntimeError("closed")
        return item

    def respond(self, request_id, result):
        self.responses.append((request_id, result))

    def respond_error(self, request_id, **error):
        self.responses.append((request_id, error))

    def close(self):
        if not self.closed:
            self.closed = True
            self.requests.put(None)
        if self.gate:
            self.gate.set()


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Storage(self.root / "app.sqlite3")
        self.project = self.store.create_project("Project", str(self.root))
        self.session = self.store.create_session(self.project["id"])
        FakeSDK.history = {}
        FakeSDK.instances = []
        FakeSDK.gate = None
        FakeSDK.failure = False
        self.manager = HarnessManager(self.store, self.root / "home", sdk_factory=FakeSDK)

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def send(self, request_id="r1", message="hello", session=None):
        run = self.manager.submit((session or self.session)["id"], request_id, message)
        self.manager.worker.join(5)
        self.assertFalse(self.manager.worker.is_alive())
        return self.store.run(run["id"])

    def test_project_path_validation_and_duplicate(self):
        self.assertEqual(self.store.create_project("Again", str(self.root))["id"], self.project["id"])
        for directory in ("relative", str(self.root / "missing"), str(self.root / "app.sqlite3")):
            with self.assertRaises(AppError):
                self.store.create_project("Invalid", directory)

    def test_multiturn_isolation_and_restart(self):
        self.assertEqual(self.send(message="sentinel")["status"], "completed")
        self.assertEqual(self.send("r2", "recall")["reply"], "sentinel | recall")
        other = self.store.create_session(self.project["id"])
        self.assertEqual(self.send("r3", "isolated", other)["reply"], "isolated")
        self.assertEqual(len(FakeSDK.instances), 1)
        self.manager.close()
        self.manager = HarnessManager(self.store, self.root / "home", sdk_factory=FakeSDK)
        self.assertEqual(self.send("r4", "after restart")["reply"], "sentinel | recall | after restart")
        self.assertIn(self.session["id"], FakeSDK.instances[-1].resumed)
        self.assertEqual(len(self.store.session(self.session["id"])["messages"]), 6)

    def test_duplicate_and_conflicting_request(self):
        self.send()
        self.manager.submit(self.session["id"], "r1", "hello")
        self.assertEqual(len(self.store.session(self.session["id"])["messages"]), 2)
        with self.assertRaises(AppError) as error:
            self.manager.submit(self.session["id"], "r1", "different")
        self.assertEqual(error.exception.status, 409)

    def test_full_sdk_configuration(self):
        self.send()
        config = FakeSDK.instances[0].config
        self.assertEqual(config["profile"], "sdk")
        self.assertEqual(config["cwd"], self.project["directory"])
        self.assertEqual(config["shutdown_timeout_seconds"], 30)
        self.assertTrue(config["approval_requests"])
        if os.name == "nt":
            self.assertEqual(config["runtime_cwd"], str(Path("C:/")))

    def test_shutdown_releases_worker_and_request_thread(self):
        FakeSDK.gate = threading.Event()
        self.manager.submit(self.session["id"], "r1", "wait")
        self.manager.close()
        self.assertFalse(self.manager.worker.is_alive())
        for runtime in self.manager.runtimes.values():
            self.assertTrue(runtime.sdk.closed)
            self.assertFalse(runtime.approvals.is_alive())

    def test_busy_requests_are_not_persisted(self):
        FakeSDK.gate = threading.Event()
        self.manager.submit(self.session["id"], "r1", "wait")
        with self.assertRaises(AppError) as error:
            self.manager.submit(self.session["id"], "r2", "busy")
        self.assertEqual(error.exception.status, 409)
        self.assertIsNone(self.store.find_run("r2"))
        FakeSDK.gate.set()
        self.manager.worker.join(5)

    def test_runtime_start_failure_is_visible_and_retryable(self):
        FakeSDK.failure = True
        self.assertEqual(self.send()["status"], "error")
        self.assertIn("启动失败", self.store.run("r1")["error"])
        self.assertEqual(self.store.session(self.session["id"])["session"]["started"], 0)
        FakeSDK.failure = False
        self.assertEqual(self.send("r2")["status"], "completed")

    def test_missing_persisted_history_is_reported(self):
        self.send()
        self.manager.close()
        FakeSDK.history.clear()
        self.manager = HarnessManager(self.store, self.root / "home", sdk_factory=FakeSDK)
        self.assertIn("历史不存在", self.send("r2")["error"])

    def test_question_cancellation_is_recorded(self):
        run = self.send(message="question")
        self.assertIn("取消", run["notices"][0])
        self.assertIn("继续吗", run["notices"][0])

    def test_approval_rejection_is_recorded(self):
        self.send()
        runtime = self.manager.runtimes[self.project["id"]]
        runtime.current_run = "r1"
        sdk = FakeSDK.instances[-1]
        sdk.requests.put(SimpleNamespace(id=7, method="approval/request", payload={"toolName": "plugin_manager"}))
        sdk.requests.put(None)
        runtime.approvals.join(5)
        self.assertEqual(sdk.responses, [(7, {"outcome": "rejected"})])
        self.assertIn("plugin_manager", self.store.run("r1")["notices"][0])

    def test_recovery_marks_pending_runs(self):
        self.store.create_run("pending", self.session["id"], "test")
        self.store.recover()
        self.assertEqual(self.store.run("pending")["status"], "interrupted")

    def test_transcript_and_run_status_share_a_snapshot(self):
        self.store.create_run("atomic", self.session["id"], "hello")
        connect = self.store.connect

        @contextmanager
        def concurrent_connection():
            with connect() as db:
                def finish_during_read(sql):
                    if "SELECT * FROM runs" in sql:
                        with connect() as writer:
                            writer.execute("UPDATE runs SET status='completed', reply='answer' WHERE id='atomic'")
                            writer.execute("""INSERT INTO messages
                                (session_id, run_id, role, content, created_at)
                                VALUES (?, 'atomic', 'assistant', 'answer', 'now')""", (self.session["id"],))
                db.set_trace_callback(finish_during_read)
                yield db

        with patch.object(self.store, "connect", concurrent_connection):
            snapshot = self.store.session(self.session["id"])
        self.assertEqual(snapshot["runs"][0]["status"], "queued")
        self.assertEqual(len(snapshot["messages"]), 1)
        self.assertEqual(len(self.store.session(self.session["id"])["messages"]), 2)

    def test_closed_official_sdk_cannot_reopen(self):
        sdk = ProjectHarness(dsh_home=str(self.root / "home"), cwd=str(self.root))
        with patch.object(DeepSeekHarness, "start") as start, patch.object(DeepSeekHarness, "close"):
            sdk.start()
            sdk.close()
            with self.assertRaises(RuntimeError):
                sdk.start()
            start.assert_called_once()

    def test_missing_project_directory(self):
        folder = self.root / "workspace"
        folder.mkdir()
        project = self.store.create_project("Missing", str(folder))
        session = self.store.create_session(project["id"])
        folder.rmdir()
        with self.assertRaises(AppError) as error:
            self.manager.submit(session["id"], "missing", "hello")
        self.assertEqual(error.exception.status, 409)

    def test_credentials_are_redacted(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-private-credential"}):
            self.assertNotIn("test-private-credential", safe_error("failed test-private-credential"))

    def test_data_directory_exclusion(self):
        lock = DataLock(self.root)
        try:
            with self.assertRaises(RuntimeError):
                DataLock(self.root)
        finally:
            lock.close()

    def test_http_validation_and_async_result(self):
        server = make_server(0, self.store, self.manager)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, body=None, origin=None):
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            data = None if body is None else json.dumps(body).encode()
            with urllib.request.urlopen(urllib.request.Request(base + path, data, headers)) as response:
                return response.status, json.load(response)

        try:
            self.assertEqual(request("/api/projects")[0], 200)
            for body in ({}, [], {"message": "hello"}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/chat", body)
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as error:
                request("/api/chat", {}, "https://example.com")
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as error:
                request("/api/sessions/missing")
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
            status, result = request("/api/chat", {"session_id": self.session["id"], "request_id": "http", "message": "hello"})
            self.assertEqual(status, 202)
            self.manager.worker.join(5)
            self.assertEqual(request("/api/runs/http")[1]["run"]["status"], "completed")
            self.assertEqual(len(request("/api/sessions/" + self.session["id"])[1]["messages"]), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()

"""Official SDK runtimes and serialized background user tasks."""

import os
from pathlib import Path
import re
import threading

from deepseek_harness import DeepSeekHarness

from storage import AppError, required_text


def safe_error(error):
    text = str(error)
    for name, value in os.environ.items():
        if value and any(part in name.upper() for part in ("API_KEY", "TOKEN", "SECRET")):
            text = text.replace(value, "[redacted]")
    return re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[redacted]", text)[-6000:]


class ProjectHarness(DeepSeekHarness):
    """Serialize SDK startup/shutdown and prevent a late run reopening a closed runtime."""

    def __init__(self, **config):
        super().__init__(**config)
        self.lifecycle_lock = threading.Lock()
        self.closed = False

    def start(self):
        with self.lifecycle_lock:
            if self.closed:
                raise RuntimeError("项目运行时已关闭，任务已中断。")
            super().start()

    def close(self):
        with self.lifecycle_lock:
            self.closed = True
            super().close()


class ProjectRuntime:
    def __init__(self, manager, project):
        self.manager = manager
        self.sessions = {}
        self.lock = threading.Lock()
        self.approvals = None
        self.current_run = None
        # The 0.2.2rc2 packaged Windows VFS resolves native modules under C:\snapshot.
        # Keep the process there while SDK initialization sets the project workspace.
        runtime_cwd = str(Path("C:/")) if os.name == "nt" else project["directory"]
        self.sdk = manager.sdk_factory(
            profile="sdk", dsh_home=str(manager.home),
            cwd=project["directory"], runtime_cwd=runtime_cwd,
            provider="deepseek-official", model=manager.model,
            shutdown_timeout_seconds=30,
            approval_requests=True, on_user_question=self.on_question,
            env={"DSH_PERMISSION_MODE": "workspace-write"},
        )

    def start(self):
        with self.lock:
            self.sdk.start()
            self.approvals = threading.Thread(target=self.reject_approvals, daemon=True)
            self.approvals.start()

    def add_notice(self, message):
        if self.current_run:
            self.manager.storage.notice(self.current_run, message)

    def reject_approvals(self):
        while True:
            try:
                request = self.sdk.client.next_request()
            except Exception:
                # SDK close releases this blocking queue with a transport error.
                return
            try:
                if request.method == "approval/request":
                    tool = request.payload.get("toolName", "未知工具")
                    self.add_notice(f"已拒绝需要人工批准的操作（{tool}）。当前版本尚未提供审批界面。")
                    self.sdk.client.respond(request.id, {"outcome": "rejected"})
                else:
                    self.sdk.client.respond_error(request.id, code=-32601, message="Unsupported client request")
            except Exception as error:
                # A failed answer must not leave the model waiting indefinitely.
                try:
                    self.add_notice("审批应答失败：" + safe_error(error))
                finally:
                    self.sdk.close()
                return

    def on_question(self, request, cancelled):
        questions = "；".join(question.get("question", "") for question in request.questions)
        self.add_notice("AI 请求用户回答问题，本版本已取消该交互。" + safe_error(questions))
        return {"cancelled": True}

    def get_session(self, session):
        session_id = session["id"]
        if session_id not in self.sessions:
            if session["started"]:
                self.sessions[session_id] = self.sdk.resume_session(session_id)
            else:
                self.sessions[session_id] = self.sdk.start_session(session_id)
        return self.sessions[session_id]

    def close(self):
        with self.lock:
            self.sdk.close()
        if self.approvals and self.approvals is not threading.current_thread():
            self.approvals.join()


class HarnessManager:
    def __init__(self, storage, home, model="deepseek-v4-flash", sdk_factory=ProjectHarness):
        self.storage = storage
        self.home = Path(home).resolve()
        self.model = model
        self.sdk_factory = sdk_factory
        self.runtimes = {}
        self.lock = threading.Lock()
        self.active = None
        self.worker = None
        self.closing = False

    def submit(self, session_id, request_id, message):
        session_id = required_text(session_id, "会话 ID", 100)
        request_id = required_text(request_id, "请求 ID", 100)
        message = required_text(message, "消息内容")
        with self.lock:
            existing = self.storage.find_run(request_id)
            if existing:
                if existing["session_id"] != session_id or existing["message"] != message:
                    raise AppError(409, "该请求 ID 已用于不同的消息。")
                return existing
            if self.closing:
                raise AppError(503, "服务正在关闭。")
            if self.active:
                raise AppError(409, "已有任务正在执行，请等待完成。")
            session = self.storage.session(session_id)["session"]
            project = self.storage.project(session["project_id"])
            if not Path(project["directory"]).is_dir():
                raise AppError(409, "项目目录已失效，请恢复原目录后继续。")
            self.storage.create_run(request_id, session_id, message)
            self.active = request_id
            self.worker = threading.Thread(target=self.execute, args=(project, session, request_id, message))
            self.worker.start()
            return self.storage.run(request_id)

    def execute(self, project, session, request_id, message):
        runtime = None
        try:
            self.storage.mark_running(request_id)
            runtime = self.runtimes.get(project["id"])
            if runtime is None:
                runtime = ProjectRuntime(self, project)
                runtime.start()
                with self.lock:
                    if self.closing:
                        raise RuntimeError("服务正在关闭，任务已中断。")
                    self.runtimes[project["id"]] = runtime
            runtime.current_run = request_id
            handle = runtime.get_session(session)
            self.storage.mark_started(session["id"])
            result = handle.run(message)
            reason = result.finish_reason
            if reason == "completed":
                self.storage.finish(request_id, "completed", result.final_response, finish_reason=reason)
            else:
                details = [event.get("data", {}).get("reason") for event in result.events
                           if event.get("type") == "turn/end"]
                diagnostic = safe_error(details[-1]) if details else reason or "unknown"
                self.storage.finish(request_id, "error", result.final_response,
                                    f"任务未完成：{diagnostic}", reason)
        except Exception as error:
            self.storage.finish(request_id, "error", error=safe_error(error))
            if runtime:
                with self.lock:
                    self.runtimes.pop(project["id"], None)
                runtime.close()
        finally:
            if runtime:
                runtime.current_run = None
            with self.lock:
                self.active = None

    def close(self):
        with self.lock:
            self.closing = True
            runtimes = list(self.runtimes.values())
        for runtime in runtimes:
            runtime.close()
        if self.worker:
            self.worker.join()

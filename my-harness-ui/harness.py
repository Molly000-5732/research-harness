"""Official SDK runtimes and serialized background user tasks."""

import os
import json
from pathlib import Path
import re
import threading
import uuid

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
        self.experiment_session = None
        self.approval_lock = threading.Lock()
        self.pending_approval = None
        self.tool_calls = {}
        self.closing = False
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
                    if self.experiment_session and request.payload.get("sessionId") == self.experiment_session:
                        self.review_approval(request)
                    else:
                        self.add_notice(f"已拒绝需要人工批准的操作（{tool}）。请在实验验证页处理实验审批。")
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

    def review_approval(self, request):
        wake = threading.Event()
        pending = {
            "id": uuid.uuid4().hex, "run_id": self.current_run,
            "tool": safe_error(request.payload.get("toolName", "未知工具")),
            "reason": safe_error(request.payload.get("reason") or ""),
            "call_id": request.payload.get("callId"),
            "wake": wake, "outcome": "cancelled",
        }
        with self.approval_lock:
            self.pending_approval = pending
            if self.closing:
                wake.set()
        try:
            wake.wait(300)
            with self.approval_lock:
                outcome = pending["outcome"]
                wake.set()
            self.sdk.client.respond(request.id, {"outcome": outcome})
            labels = {"allowed-once": "已批准一次", "rejected": "已拒绝", "cancelled": "未批准，操作已取消"}
            self.add_notice(f"{labels[outcome]}：{pending['tool']}")
        finally:
            with self.approval_lock:
                self.pending_approval = None

    def approval(self, run_id, decision=None):
        with self.approval_lock:
            pending = self.pending_approval
            if not pending or pending["run_id"] != run_id or pending["wake"].is_set():
                if decision is not None:
                    raise AppError(409, "审批已结束，请刷新任务状态。")
                return None
            tool_name, arguments = self.tool_calls.get(pending["call_id"], ("", ""))
            if tool_name != pending["tool"]:
                arguments = ""
            if decision is None:
                return {**{key: pending[key] for key in ("id", "tool", "reason")}, "arguments": arguments}
            if decision.get("id") != pending["id"] or decision.get("outcome") not in ("allowed-once", "rejected"):
                raise AppError(409, "审批请求已变化，或审批决定无效。")
            if decision["outcome"] == "allowed-once" and not arguments:
                raise AppError(409, "暂未取得工具参数，当前可拒绝该请求。")
            pending["outcome"] = decision["outcome"]
            pending["wake"].set()

    def on_notification(self, notification):
        if notification.method != "session.event":
            return
        event = notification.payload.get("event") or {}
        data = event.get("data") or {}
        if event.get("type") == "tool/call" and notification.payload.get("sessionId") == self.experiment_session:
            arguments = data.get("arguments")
            if isinstance(arguments, str) and data.get("callId"):
                with self.approval_lock:
                    self.tool_calls[data["callId"]] = (
                        data.get("name"), safe_error(arguments) if len(arguments) <= 6000 else "",
                    )

    def record_experiment(self, result):
        tools = {}
        for event in result.events:
            data = event.get("data", {})
            if event.get("type") == "tool/call":
                tools[data.get("callId")] = data.get("name", "工具")
                if data.get("name") in ("bash", "pwsh"):
                    self.add_notice(f"{data['name']} · 执行参数\n" + safe_error(data.get("arguments", "")))
            elif event.get("type") == "tool/result":
                message = data.get("message") or {}
                tool = tools.get(message.get("toolCallId"), "工具")
                parts = message.get("content") or []
                output = "\n".join(part.get("text", "") for part in parts if part.get("type") == "text")
                status = "工具报错" if message.get("isError") else "返回结果"
                self.add_notice(safe_error(f"{tool} · {status}\n{output[-1800:]}"))

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
        with self.approval_lock:
            self.closing = True
            if self.pending_approval:
                self.pending_approval["wake"].set()
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
        self.lock = threading.RLock()
        self.active = None
        self.worker = None
        self.closing = False

    def submit(self, session_id, request_id, message, *, prompt=None, research_inputs=None, experiment=False):
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
            self.storage.create_run(request_id, session_id, message, research_inputs)
            self.active = request_id
            self.worker = threading.Thread(target=self.execute,
                                           args=(project, session, request_id, prompt or message, experiment))
            self.worker.start()
            return self.storage.run(request_id)

    def execute(self, project, session, request_id, message, experiment=False):
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
            runtime.experiment_session = session["id"] if experiment else None
            handle = runtime.get_session(session)
            self.storage.mark_started(session["id"])
            if experiment:
                result = handle.run(message, on_notification=runtime.on_notification)
                runtime.record_experiment(result)
            else:
                result = handle.run(message)
            final_reply = result.final_response
            if result.finish_reason == "completed":
                with self.storage.connect() as db:
                    structured_run = db.execute(
                        """SELECT research_runs.inputs, research_sessions.stage FROM research_runs JOIN research_sessions
                           ON research_sessions.session_id=? WHERE research_runs.run_id=?
                           AND research_sessions.stage IN ('questions', 'painpoints')""", (session["id"], request_id),
                    ).fetchone()
                    previous = [row["reply"] for row in db.execute(
                        """SELECT reply FROM runs JOIN research_runs ON runs.id=research_runs.run_id
                           WHERE session_id=? AND status='completed' AND research_runs.inputs=?""",
                        (session["id"], structured_run["inputs"]),
                    )] if structured_run else []
                if structured_run and structured_run["stage"] == "painpoints":
                    revision = json.loads(structured_run["inputs"]).get("questions")
                    with self.storage.connect() as db:
                        source = db.execute("""SELECT runs.reply FROM research_confirmations JOIN runs
                            ON runs.id=research_confirmations.run_id WHERE research_confirmations.id=?""", (revision,)).fetchone()
                        if source:
                            previous.append(source["reply"])
                if structured_run:
                    from question_evidence import grounded_reply, choices, payload
                    evidence_events = list(result.events)
                    stage_key = structured_run["stage"]
                    if not payload(result.final_response, stage_key):
                        self.storage.notice(request_id, "正在整理为可选择的条目及文献依据。")
                        result = handle.run(f"当前阶段为{stage_key}，请将本轮成果完整整理为可选择的独立条目。末尾附JSON代码块，包含{stage_key}数组，各项包含title、description和evidence，evidence各项包含title、url、locator、quote、reason。保留实际阅读或前序已核对的原文证据，不得编造；不修改工作区文件、不执行实验、不重新进行无关调研。证据不足时明确说明并返回空数组。")
                        evidence_events.extend(result.events)
                    reply = grounded_reply(result.final_response, evidence_events, previous, key=stage_key)
                    if not any(any(e["verified"] for e in q["evidence"]) for q in choices(reply, stage_key)):
                        self.storage.notice(request_id, "尚无可核对的正文证据。请继续对话，让 Harness 打开论文正文并补充原文出处。")
                    final_reply = reply
            reason = result.finish_reason
            if reason == "completed":
                self.storage.finish(request_id, "completed", final_reply, finish_reason=reason)
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
                runtime.experiment_session = None
                with runtime.approval_lock:
                    runtime.tool_calls.clear()
            with self.lock:
                self.active = None

    def approval(self, run_id, decision=None):
        with self.lock:
            for runtime in self.runtimes.values():
                if runtime.current_run == run_id:
                    return runtime.approval(run_id, decision)
        if decision is not None:
            raise AppError(409, "审批已结束，请刷新任务状态。")

    def close(self):
        with self.lock:
            self.closing = True
            runtimes = list(self.runtimes.values())
        for runtime in runtimes:
            runtime.close()
        if self.worker:
            self.worker.join()

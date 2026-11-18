"""Local project index and UI transcript, separate from Harness session storage."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid


class AppError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def required_text(value, label, limit=16000):
    if not isinstance(value, str) or not value.strip():
        raise AppError(400, f"请提供{label}。")
    if len(value) > limit:
        raise AppError(400, f"{label}最多允许 {limit} 个字符。")
    return value.strip()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    directory TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    title TEXT NOT NULL, started INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    message TEXT NOT NULL, status TEXT NOT NULL,
                    reply TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    finish_reason TEXT, notices TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL, finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(run_id, role)
                );
                CREATE INDEX IF NOT EXISTS sessions_by_project ON sessions(project_id, updated_at);
                CREATE INDEX IF NOT EXISTS messages_by_session ON messages(session_id, id);
                CREATE INDEX IF NOT EXISTS runs_by_session ON runs(session_id, created_at);
                CREATE TABLE IF NOT EXISTS research_projects (
                    project_id TEXT PRIMARY KEY REFERENCES projects(id),
                    background TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_sessions (
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    stage TEXT NOT NULL, session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
                    PRIMARY KEY(project_id, stage)
                );
                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id), inputs TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_confirmations (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    run_id TEXT NOT NULL REFERENCES runs(id), content TEXT NOT NULL,
                    papers TEXT NOT NULL, inputs TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            db.execute("""UPDATE runs SET status='interrupted', finished_at=?,
                       error='服务已重启，上次执行结果待确认。请检查后再继续会话。'
                       WHERE status IN ('queued', 'running')""", (timestamp(),))

    def list_projects(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at DESC")]

    def create_project(self, name, directory):
        name = required_text(name, "项目名称", 100)
        path = Path(required_text(directory, "项目绝对目录", 4096)).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise AppError(400, "项目目录必须是已存在的本机绝对目录。")
        canonical = os.path.normcase(str(path.resolve()))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM projects WHERE directory=?", (canonical,)).fetchone()
            if existing:
                return dict(existing)
            project_id = uuid.uuid4().hex
            db.execute("INSERT INTO projects VALUES (?, ?, ?, ?)",
                       (project_id, name, canonical, timestamp()))
            return dict(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def project(self, project_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise AppError(404, "项目不存在。")
            return dict(row)

    def list_sessions(self, project_id):
        self.project(project_id)
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT * FROM sessions WHERE project_id=?
                   AND id NOT IN (SELECT session_id FROM research_sessions)
                   ORDER BY updated_at DESC""", (project_id,))]

    def create_session(self, project_id):
        self.project(project_id)
        session_id = "session-" + uuid.uuid4().hex
        now = timestamp()
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, 0, ?, ?)",
                       (session_id, project_id, "新会话", now, now))
        return self.session(session_id)["session"]

    def session(self, session_id):
        with self.connect() as db:
            # Messages and run status must describe the same committed snapshot.
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise AppError(404, "会话不存在。")
            messages = [dict(item) for item in db.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,))]
            runs = [self.decode_run(item) for item in db.execute(
                "SELECT * FROM runs WHERE session_id=? ORDER BY created_at", (session_id,))]
            return {"session": dict(row), "messages": messages, "runs": runs}

    @staticmethod
    def decode_run(row):
        result = dict(row)
        result["notices"] = json.loads(result["notices"])
        return result

    def find_run(self, request_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (request_id,)).fetchone()
            return self.decode_run(row) if row else None

    def run(self, request_id):
        result = self.find_run(request_id)
        if result is None:
            raise AppError(404, "任务不存在。")
        return result

    def create_run(self, request_id, session_id, message, research_inputs=None):
        now = timestamp()
        with self.connect() as db:
            db.execute("INSERT INTO runs (id, session_id, message, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
                       (request_id, session_id, message, now))
            if research_inputs is not None:
                db.execute("INSERT INTO research_runs VALUES (?, ?)", (request_id, research_inputs))
            db.execute("INSERT INTO messages (session_id, run_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
                       (session_id, request_id, message, now))
            db.execute("""UPDATE sessions SET updated_at=?,
                       title=CASE WHEN title='新会话' THEN ? ELSE title END WHERE id=?""",
                       (now, " ".join(message.split())[:36], session_id))

    def mark_started(self, session_id):
        with self.connect() as db:
            db.execute("UPDATE sessions SET started=1 WHERE id=?", (session_id,))

    def mark_running(self, request_id):
        with self.connect() as db:
            db.execute("UPDATE runs SET status='running' WHERE id=?", (request_id,))

    def notice(self, request_id, message):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT notices FROM runs WHERE id=?", (request_id,)).fetchone()
            notes = json.loads(row["notices"])
            if message not in notes:
                notes.append(message)
                db.execute("UPDATE runs SET notices=? WHERE id=?", (json.dumps(notes, ensure_ascii=False), request_id))

    def finish(self, request_id, status, reply="", error="", finish_reason=None):
        now = timestamp()
        with self.connect() as db:
            run = db.execute("SELECT session_id FROM runs WHERE id=?", (request_id,)).fetchone()
            db.execute("UPDATE runs SET status=?, reply=?, error=?, finish_reason=?, finished_at=? WHERE id=?",
                       (status, reply, error, finish_reason, now, request_id))
            if reply:
                db.execute("INSERT INTO messages (session_id, run_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                           (run["session_id"], request_id, reply, now))
            db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, run["session_id"]))

"""Local Research Harness HTTP service, backed by the official Python SDK."""

import argparse
import json
import mimetypes
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from dotenv import load_dotenv

from harness import HarnessManager, safe_error
from storage import AppError, Storage


ROOT = Path(__file__).resolve().parent
ASSETS = {"/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css"}


class DataLock:
    """Prevent two application processes from recovering the same local database."""

    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / "app.lock").open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("该数据目录已有服务正在使用，请使用现有服务或指定其他 --data-dir。")

    def close(self):
        self.file.close()


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_payload(status, payload, "application/json; charset=utf-8")

    def send_payload(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            # Results are already durable when a browser navigates away.
            pass

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            path = urlsplit(self.path).path
            if method == "GET" and path in ASSETS:
                asset = ROOT / ASSETS[path]
                content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
                self.send_payload(200, asset.read_bytes(), content_type + "; charset=utf-8")
                return
            data = self.read_json() if method == "POST" else {}
            status, result = self.api(method, path.strip("/").split("/"), data)
            self.respond(status, result)
        except AppError as error:
            self.respond(error.status, {"error": str(error)})
        except Exception as error:
            self.respond(500, {"error": safe_error(error)})

    def read_json(self):
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            raise AppError(403, "请从本地服务页面发送请求。")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 131072:
                raise ValueError("请求长度应在 1 至 131072 字节之间。")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("请求内容必须是 JSON 对象。")
            return data
        except (ValueError, UnicodeError) as error:
            raise AppError(400, str(error)) from error

    def api(self, method, parts, data):
        store = self.server.storage
        if parts == ["api", "projects"]:
            if method == "GET":
                return 200, {"projects": store.list_projects()}
            return 201, {"project": store.create_project(data.get("name"), data.get("directory"))}
        if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "sessions":
            if method == "GET":
                return 200, {"sessions": store.list_sessions(parts[2])}
            return 201, {"session": store.create_session(parts[2])}
        if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "sessions"]:
            return 200, store.session(parts[2])
        if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "runs"]:
            return 200, {"run": store.run(parts[2])}
        if method == "POST" and parts == ["api", "chat"]:
            run = self.server.manager.submit(data.get("session_id"), data.get("request_id"), data.get("message"))
            return 202, {"run": run}
        raise AppError(404, "接口不存在。")


def make_server(port, storage, manager):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.storage = storage
    server.manager = manager
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("harness_root", nargs="?", type=Path,
                        help="兼容旧启动命令，仅用于定位该目录下的 .env")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--data-dir", type=Path, default=ROOT.parent / ".research-harness")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", default="deepseek-v4-flash")
    args = parser.parse_args()
    env_file = args.env_file
    if env_file is None:
        env_file = (args.harness_root / ".env") if args.harness_root else ROOT.parent / ".env"
    if args.env_file and not env_file.is_file():
        parser.error("--env-file 指定的文件不存在。")
    load_dotenv(env_file.resolve(), override=False)
    data_dir = args.data_dir.resolve()
    try:
        data_lock = DataLock(data_dir)
    except RuntimeError as error:
        parser.error(str(error))
    manager = None
    server = None
    try:
        store = Storage(data_dir / "app.sqlite3")
        manager = HarnessManager(store, data_dir / "dsh-home", args.model)
        server = make_server(args.port, store, manager)
        store.recover()
        print(f"Research Harness running at http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.server_close()
        if manager:
            manager.close()
        data_lock.close()


if __name__ == "__main__":
    main()

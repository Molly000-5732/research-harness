"""Serve the local HTML form and run one Harness headless task per request."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import sys
import hashlib
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parent))
import workspace as ws
import harness_runtime
import research_experiments as rx
import fulltext_library as ft


PAGE = Path(__file__).with_name("index.html")
RUN_LOCK = threading.Lock()


def run_task(root, message):
    command = harness_runtime.command(root)
    with subprocess.Popen(
        command, cwd=root, env=harness_runtime.environment(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    ) as process:
        try:
            output, errors = process.communicate(message, timeout=300)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise TimeoutError("Harness 执行超过 300 秒，已停止本次任务。")
    if process.returncode:
        raise RuntimeError(errors.strip()[-6000:] or output.strip()[-6000:] or "Harness 执行失败。")
    if not output.strip():
        raise RuntimeError("Harness 已退出，但没有返回文本。")
    return output.strip()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/projects':
            items=ws.projects()
            for p in items:p['coverage']=ft.coverage(p)
            self.send_json(200, items)
            return
        if path == '/api/health':
            self.send_json(200, {'status': 'ok', 'harness': str(self.server.harness_root)})
            return
        if path == '/api/capabilities':
            self.send_json(200, rx.capabilities())
            return
        if path.startswith('/api/projects/'):
            try:
                parts = path.strip('/').split('/')
                pid = parts[2]
                if len(parts) == 5 and parts[3] == 'library-files':
                    project=ws.load(pid)
                    file=next((f for f in project['files'] if f['id']==parts[4]),None)
                    if not file or Path(file['stored']).name!=file['stored']:raise ValueError('文件不存在')
                    payload=(ws.folder(pid)/'literature'/file['stored']).read_bytes()
                    if file.get('sha256') and hashlib.sha256(payload).hexdigest()!=file['sha256']:
                        raise ValueError('原始文献文件已改变，请重新入库')
                    self.send_response(200)
                    self.send_header('Content-Type','application/pdf' if file['stored'].endswith('.pdf') else 'text/plain; charset=utf-8')
                    self.send_header('Content-Length',str(len(payload)))
                    self.end_headers();self.wfile.write(payload)
                elif len(parts) == 4 and parts[3] == 'library':
                    project=ws.load(pid)
                    self.send_json(200,{'coverage':ft.coverage(project),'segments':ft.select(project,project['field'])})
                elif len(parts) == 6 and parts[3] == 'artifacts':
                    target = rx.artifact(ws, pid, parts[4], parts[5])
                    payload = target.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Disposition', f'attachment; filename="{target.name}"')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                elif len(parts) == 4 and parts[3] == 'export':
                    payload = ws.export(pid).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                    self.send_header('Content-Disposition', 'attachment; filename="research-report.md"')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    project=ws.load(pid);project['coverage']=ft.coverage(project)
                    self.send_json(200, project)
            except (ValueError, OSError) as error:
                self.send_json(404, {'error': str(error)})
            return
        if path in ['/app.js', '/experiment-ui.js', '/library-ui.js', '/style.css']:
            payload = PAGE.with_name(path[1:]).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path != "/":
            self.send_json(404, {"error": "页面不存在。"})
            return
        payload = PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path in ['/api/projects', '/api/examples/digits'] or self.path.startswith('/api/projects/'):
            try:
                if self.headers.get('Origin') and self.headers['Origin'] != f"http://{self.headers.get('Host')}":
                    self.send_json(403, {'error':'请从本地页面操作'})
                    return
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 22 * 1024 * 1024:
                    raise ValueError('请求过大或为空')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('请求应为对象')
                if self.path == '/api/examples/digits':
                    result = rx.example(ws)
                elif self.path == '/api/projects':
                    result = ws.create(data.get('field', ''))
                else:
                    parts = self.path.strip('/').split('/')
                    if len(parts) != 4:
                        raise ValueError('接口不存在')
                    pid, action = parts[2:]
                    if action == 'start':
                        result = ws.start(self.server.harness_root, pid, data.get('stage'))
                    elif action == 'run':
                        result = ws.run_experiment(pid)
                    elif action == 'auto-run':
                        result = rx.start(ws, self.server.harness_root, pid)
                    elif action == 'fetch-fulltext':
                        result=ft.start_fetch(ws,self.server.harness_root,pid,data.get('paperId'))
                    elif action == 'sync-library':
                        result=ft.sync_folder(ws,pid)
                    elif action == 'folder':
                        target = (ws.folder(pid)/'literature' if data.get('section')=='literature' else ws.folder(pid)).resolve()
                        if os.name == 'nt':
                            os.startfile(str(target))
                        result = {'path': str(target)}
                    else:
                        result = ws.mutate(pid, action, data)
                self.send_json(200, result)
            except (ValueError, OSError, KeyError, ImportError) as error:
                self.send_json(400, {'error': ws.clean_error(error)})
            return
        if self.path != "/api/chat":
            self.send_json(404, {"error": "接口不存在。"})
            return
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            self.send_json(403, {"error": "请从本地服务页面发送请求。"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                raise ValueError("请求长度应在 1 至 65536 字节之间。")
            data = json.loads(self.rfile.read(size))
            message = data.get("message") if isinstance(data, dict) else None
            if not isinstance(message, str) or not message.strip():
                raise ValueError("请输入任务文本。")
        except (ValueError, UnicodeError) as error:
            self.send_json(400, {"error": str(error)})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self.send_json(409, {"error": "已有任务正在执行，请等待完成。"})
            return
        try:
            reply = run_task(self.server.harness_root, message)
            self.send_json(200, {"reply": reply})
        except TimeoutError as error:
            self.send_json(504, {"error": str(error)})
        except (OSError, RuntimeError) as error:
            self.send_json(502, {"error": str(error)})
        finally:
            RUN_LOCK.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("harness_root", nargs="?", type=Path,
                        default=PAGE.parent.parent / "deepseek-harness-master")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    root = args.harness_root.resolve()
    try:
        harness_runtime.entry(root)
    except ValueError as error:
        parser.error(str(error))
    if not shutil.which("node"):
        parser.error("找不到 Node.js，请安装 Node.js >=24.9。")
    class LocalServer(ThreadingHTTPServer):
        allow_reuse_address = False
    server = LocalServer(("127.0.0.1", args.port), Handler)
    server.harness_root = root
    ws.recover()
    print(f"Harness UI running at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

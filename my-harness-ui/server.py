"""Serve the local HTML form and run one Harness headless task per request."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PAGE = Path(__file__).with_name("index.html")
RUN_LOCK = threading.Lock()


def run_task(root, message):
    command = [
        shutil.which("node"), "--import", "tsx/esm", "apps/cli/src/bin.ts",
        "--profile", "headless", "--approval-policy", "never", "-",
    ]
    with subprocess.Popen(
        command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
    if not (root / "apps/cli/src/bin.ts").is_file():
        parser.error(f"找不到 Harness CLI 入口，请检查目录 {root}")
    if not shutil.which("node"):
        parser.error("找不到 Node.js，请安装 Node.js >=24.9。")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.harness_root = root
    print(f"Harness UI running at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

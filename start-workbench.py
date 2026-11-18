"""Portable launcher: configured checkout, or first-run bootstrap."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent

def main():
    config_path = ROOT / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    configured = os.environ.get('HARNESS_ROOT') or config.get('harness_root')
    if not configured:
        from bootstrap import main as bootstrap_main
        return bootstrap_main()
    root = Path(configured).expanduser()
    if not root.is_absolute():
        root = ROOT / root
    sys.path.insert(0, str(ROOT / 'my-harness-ui'))
    import harness_runtime
    harness_runtime.entry(root)
    port = int(config.get('port', 8001))
    url = f'http://127.0.0.1:{port}/'
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + 'api/health', timeout=2) as response:
            if response.status == 200:
                print('Research Harness is already running: ' + url)
                return 0
    except OSError:
        pass
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    interpreter = str(python) if python.exists() else sys.executable
    print('Open ' + url + ' ; Ctrl+C stops the server.', flush=True)
    return subprocess.call([interpreter, str(ROOT / 'my-harness-ui/server.py'), str(root), '--port', str(port)], cwd=ROOT)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        raise SystemExit(1)

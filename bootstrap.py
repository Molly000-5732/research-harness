"""Portable first-run setup and launcher. No credentials are shipped."""
import argparse
import getpass
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent
VERSION = '0.2.2-rc.1'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--configure', action='store_true')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--skip-key', action='store_true', help='Install without an interactive credential prompt')
    parser.add_argument('--install-experiments', action='store_true', help='Install optional CPU benchmark dependencies')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise RuntimeError('Python >=3.10 is required: https://www.python.org/downloads/')
    vpython = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        if not vpython.exists():
            print('Creating a local Python environment...', flush=True)
            venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
        return subprocess.call([str(vpython), str(Path(__file__).resolve()), *sys.argv[1:]])
    node = shutil.which('node')
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not node or not npm:
        raise RuntimeError('Install Node.js >=24.9 (with npm): https://nodejs.org/')
    number = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
    if tuple(int(x) for x in number.split('.')[:2]) < (24, 9):
        raise RuntimeError('Node.js >=24.9 is required')
    config_path = ROOT / 'config.json'
    if not config_path.exists():
        config_path.write_text(json.dumps({'harness_root':'', 'port':8001}, indent=2), encoding='utf-8')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    configured = os.environ.get('HARNESS_ROOT') or config.get('harness_root')
    runtime = Path(configured).expanduser() if configured else ROOT / 'runtime'
    if not runtime.is_absolute():
        runtime = ROOT / runtime
    runtime = runtime.resolve()
    runtime.mkdir(exist_ok=True, parents=True)
    if not importlib.util.find_spec('pypdf'):
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(ROOT/'requirements.txt')], check=True)
    if args.install_experiments:
        if sys.version_info < (3, 11):
            raise RuntimeError('CPU experiment dependencies require Python >=3.11; the basic website supports >=3.10')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(ROOT/'requirements-experiments.txt')], check=True)
        print('Experiment dependencies installed in: ' + sys.executable)
        return 0
    sys.path.insert(0, str(ROOT / 'my-harness-ui'))
    import harness_runtime
    try:
        harness_runtime.entry(runtime)
    except ValueError:
        if configured:
            raise RuntimeError('Configured Harness directory is invalid; edit config.json')
        print('Installing official DeepSeek Harness. Internet is required...', flush=True)
        templates = ROOT / 'runtime-manifest'
        for name in ['package.json', 'package-lock.json']:
            if not (runtime / name).exists() and (templates / name).exists():
                shutil.copy2(templates / name, runtime / name)
        if (runtime / 'package-lock.json').exists():
            subprocess.run([npm, 'ci', '--no-audit', '--no-fund'], cwd=runtime, check=True)
        else:
            subprocess.run([npm, 'install', '--no-audit', '--no-fund', '--save-exact', '@deepseek-ai/dsh@'+VERSION], cwd=runtime, check=True)
        harness_runtime.entry(runtime)
    env_path = runtime / '.env'
    if not args.skip_key and (args.configure or (args.setup and not env_path.exists() and not os.environ.get('DEEPSEEK_API_KEY'))):
        if not sys.stdin.isatty():
            print('No interactive terminal. Run CONFIGURE.cmd later to enter your key.')
            return 0
        print('Use YOUR OWN DeepSeek API key. Input is hidden; Enter skips configuration.')
        key = getpass.getpass('DEEPSEEK_API_KEY: ').strip()
        if key:
            if '\n' in key or '\r' in key:
                raise ValueError('Invalid API key format')
            env_path.write_text('DEEPSEEK_API_KEY='+key+'\n', encoding='utf-8')
            print('Saved locally. Do not send the runtime/.env file to anyone.')
    if args.setup or args.configure:
        print('Setup finished. Run START.cmd (Windows) or ./start.sh (macOS/Linux).')
        return 0
    port = int(config.get('port',8001))
    sample = ROOT / 'examples' / 'demo-project.json'
    data = ROOT / 'data'
    if sample.exists() and not any(data.glob('*/project.json')):
        project = json.loads(sample.read_text(encoding='utf-8'))
        destination = data / project['id']
        destination.mkdir(parents=True, exist_ok=True)
        for name in ['literature', 'runs', 'experiments', 'exports']:
            (destination / name).mkdir(exist_ok=True)
        # The public demo ships its benchmark artifacts so downloads work without a model key.
        from research_experiments import FILES
        for record in project.get('experimentRuns', []):
            run_id = record.get('id', '')
            if record.get('kind') != 'benchmark' or len(run_id) != 12 or any(c not in '0123456789abcdef' for c in run_id):
                continue
            artifact_source = ROOT / 'examples' / 'artifacts' / run_id
            artifact_target = destination / 'experiments' / run_id
            artifact_target.mkdir(exist_ok=True)
            for filename in record.get('files', []):
                if filename in FILES and (artifact_source / filename).is_file():
                    shutil.copy2(artifact_source / filename, artifact_target / filename)
        (destination / 'project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding='utf-8')
    url = f'http://127.0.0.1:{port}/'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url+'api/health', timeout=2) as response:
            if response.status == 200:
                print('Already running: '+url)
                if not args.no_open:
                    webbrowser.open(url)
                return 0
    except OSError:
        pass
    if not env_path.exists() and not os.environ.get('DEEPSEEK_API_KEY'):
        print('No key configured. Website can open; model tasks require CONFIGURE.cmd.')
    if not args.no_open:
        threading.Timer(2, lambda: webbrowser.open(url)).start()
    print('Open '+url+' ; Ctrl+C stops the server.', flush=True)
    return subprocess.call([sys.executable, str(ROOT/'my-harness-ui'/'server.py'), str(runtime), '--port', str(port)], cwd=ROOT)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print('ERROR: '+str(error), file=sys.stderr)
        raise SystemExit(1)

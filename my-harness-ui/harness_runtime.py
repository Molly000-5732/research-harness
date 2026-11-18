"""Launch either an existing Harness source checkout or its official npm release."""
import json
import os
from pathlib import Path
import shutil
import threading
import urllib.parse

APP = Path(__file__).resolve().parent.parent
PROFILE_LOCK = threading.Lock()


def prepare_profile():
    with PROFILE_LOCK:
        profile = APP / 'local-state/harness/profiles/research-workbench'
        vendor = APP / 'vendor/academic-research-skills'
        if not (vendor / 'lib/startup.js').is_file():
            raise ValueError('科研技能插件缺失，请使用完整安装包')
        target = profile / 'node_modules/dsh-academic-research-skills'
        if not (target / 'lib/startup.js').exists():
            shutil.copytree(vendor, target, dirs_exist_ok=True)
        manifest = {'name':'research-workbench-profile','private':True,'dependencies':{'dsh-academic-research-skills':'file:'+str(vendor)},'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-headless','dsh-academic-research-skills']}}}
        def update(path,text):
            if not path.exists() or path.read_text(encoding='utf-8')!=text:
                temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(text,encoding='utf-8');temp.replace(path)
        update(profile/'package.json',json.dumps(manifest,indent=2))
        update(profile/'cordis.yml','[]\n')
        update(profile/'cordis.patch.yml',(APP/'my-harness-ui/research_profile.patch.yml').read_text(encoding='utf-8'))
        return profile


def entry(root):
    root = Path(root)
    source = root / 'apps/cli/src/bin.ts'
    if source.is_file():
        return ['--import', 'tsx/esm', 'apps/cli/src/bin.ts']
    package = root / 'node_modules/@deepseek-ai/dsh'
    manifest = package / 'package.json'
    if manifest.is_file():
        info = json.loads(manifest.read_text(encoding='utf-8'))
        binary = info.get('bin', {})
        relative = binary if isinstance(binary, str) else binary.get('dsh', '')
        target = (package / relative).resolve()
        if target.is_relative_to(package.resolve()) and target.is_file():
            return [str(target)]
    raise ValueError('未找到 Harness。请先运行首次安装脚本，或在 config.json 中指定已构建的源码目录。')


def command(root, json_events=False, web=False):
    node = shutil.which('node')
    if not node:
        raise ValueError('请先安装 Node.js >=24.9')
    prepare_profile()
    return [node, *entry(root), '--profile', 'research-workbench', *([] if web else ['--patch', str(APP / 'my-harness-ui/research_analysis.patch.yml')]), '--approval-policy', 'never', *(['--json'] if json_events else []), '-']


def environment(root):
    env = dict(os.environ)
    path = Path(root) / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key.strip() in ['DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL']:
                value = value.strip().strip('"').strip("'")
                if value:
                    env[key.strip()] = value
    env['DSH_HOME'] = str(APP / 'local-state/harness')
    if env.get('DEEPSEEK_BASE_URL') and not (urllib.parse.urlsplit(env['DEEPSEEK_BASE_URL']).hostname or '').endswith('.deepseek.com'):
        raise ValueError('此科研配置只允许DeepSeek官方API地址；请检查DEEPSEEK_BASE_URL')
    # Never inherit desktop sessions or provider selections into research jobs.
    for key in ['DSH_PROFILE_DIR', 'DSH_PROFILE', 'DSH_SESSION_ID', 'DSH_WEB_URL']:
        env.pop(key, None)
    return env

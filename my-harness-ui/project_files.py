"""Local attachment transport; reading and executing documents stays with SDK tools."""
import base64
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import uuid
import subprocess
import sys

from storage import AppError

EXTENSIONS = {'.pdf', '.html', '.txt', '.md', '.csv', '.json', '.png', '.jpg', '.jpeg', '.py', '.log'}
SKIP = {'node_modules', 'venv', '__pycache__'}
MAX_BYTES = 10 * 1024 * 1024


def resolve_file(project, relative):
    root = Path(project['directory']).resolve()
    rel = Path(relative)
    if rel.is_absolute() or any(p.startswith('.') or p in SKIP for p in rel.parts):
        raise AppError(400, '文件路径无效。')
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or target == root or target.suffix.lower() not in EXTENSIONS:
        raise AppError(400, '文件路径或类型无效。')
    return target


def files(project):
    root = Path(project['directory']).resolve()
    result = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in SKIP
                         and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            item = Path(directory) / name
            if item.is_symlink() or name.startswith('.') or item.suffix.lower() not in EXTENSIONS:
                continue
            relative = item.relative_to(root).as_posix()
            literature = item.suffix.lower() == '.pdf' or any(
                part.lower() in {'lit', 'literature', 'papers'} for part in item.relative_to(root).parts[:-1])
            kind = 'literature' if literature and not relative.startswith('research-files/results/') else 'results'
            result.append({'path': relative, 'name': name, 'kind': kind, 'bytes': item.stat().st_size})
            if len(result) >= 300:
                return result
    return result


def read_plan_document(project, relative):
    if not isinstance(relative, str) or not relative:
        raise AppError(400, '请先选择工作区中的完整方案文档。')
    target = resolve_file(project, relative)
    if target.suffix.lower() not in {'.md', '.txt'}:
        raise AppError(400, '方案文档需为 Markdown 或 TXT 文件。')
    if not target.is_file():
        raise AppError(404, '完整方案文档不存在，请检查工作区。')
    before = target.stat()
    if before.st_size > 512 * 1024:
        raise AppError(400, '方案文档过大，请先精简或拆分。')
    raw = target.read_bytes()
    after = target.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AppError(409, '方案文档正在写入，请保存完成后再刷新。')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeError as error:
        raise AppError(400, '请将方案文档保存为 UTF-8 编码后重试。') from error
    if not content.strip() or len(content.strip()) > 60000:
        raise AppError(400, '最终方案不能为空，且最多允许60000个字符。')
    metadata = {'path': target.relative_to(Path(project['directory']).resolve()).as_posix(),
                'name': target.name, 'bytes': len(raw), 'characters': len(content),
                'sha256': hashlib.sha256(raw).hexdigest(),
                'modified_at': datetime.fromtimestamp(after.st_mtime, timezone.utc).isoformat()}
    return target, content, metadata


def open_plan_document(target):
    """Explicit UI action: open a text document; never execute project scripts."""
    if os.name == 'nt':
        try:
            os.startfile(str(target), 'edit')
        except OSError:
            try:
                os.startfile(str(target))
            except OSError:
                subprocess.Popen(['notepad.exe', str(target)])
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(target)])


def upload(project, data):
    kind = data.get('kind')
    if kind not in ('literature', 'results'):
        raise AppError(400, '请选择文献或实验结果。')
    name = data.get('name')
    if not isinstance(name, str) or not name.strip():
        raise AppError(400, '缺少文件名。')
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', name.strip())[-100:]
    if Path(name).suffix.lower() not in EXTENSIONS:
        raise AppError(400, '文件类型不支持。')
    encoded = data.get('base64')
    if not isinstance(encoded, str) or len(encoded) > (MAX_BYTES * 4 // 3 + 8):
        raise AppError(400, '附件不得超过10MB。')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise AppError(400, '附件编码无效。') from error
    if not raw or len(raw) > MAX_BYTES:
        raise AppError(400, '附件为空或超过10MB。')
    relative = f'research-files/{kind}/{uuid.uuid4().hex[:10]}-{name}'
    target = resolve_file(project, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(raw)
    return {'path': relative, 'name': target.name, 'kind': kind, 'bytes': len(raw)}

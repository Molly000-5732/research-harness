"""Structured research plans and versioned, independently evaluated experiments."""
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import uuid

ASSETS = Path(__file__).with_name('experiment_assets')
PROTOCOL = json.loads((ASSETS / 'digits_protocol.json').read_text(encoding='utf-8'))
PLAN_LABELS = {
    'objective': '研究目标', 'hypothesis': '可证伪假设', 'dataset': '数据与划分',
    'baseline': '基线方法', 'improvement': '改进方法与技术路径', 'ablation': '消融与控制变量',
    'metrics': '评价指标', 'acceptance': '预先设定的验收条件', 'steps': '实施步骤',
    'resources': '资源与里程碑', 'risks': '风险与适用边界',
}
FILES = {'models.py', 'evaluate.py', 'protocol.json', 'result.json', 'report.md',
         'execution.log', 'environment.json', 'metrics.csv', 'attempts.json',
         'models-attempt-1.py', 'models-attempt-2.py', 'manifest.json'}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def fingerprint(project):
    return sha(json.dumps({
        'recipe': project.get('recipe'), 'selections': project.get('selections'),
        'plan': project.get('outputs', {}).get('plan'),
        'experiment': project.get('outputs', {}).get('experiment'),
    }, sort_keys=True, ensure_ascii=False))


def clean_context(value):
    """Drafts are audit artifacts; only the accepted plan informs later model calls."""
    if isinstance(value, dict):
        return {k: clean_context(v) for k, v in value.items() if k != 'modelDraft'}
    if isinstance(value, list):
        return [clean_context(v) for v in value]
    return value


def invalidate(project):
    for record in project.get('experimentRuns', []):
        record['stale'] = True
    for source in project.get('resultSources', []):
        source['stale'] = True


def plan_schema():
    values = {k: (['具体内容'] if k in ['metrics', 'risks'] else [{'title': '步骤', 'detail': '输入、操作和产物'}] if k == 'steps' else '具体内容') for k in PLAN_LABELS}
    return json.dumps({'summary': '概述与证据覆盖情况', 'items': [{'title': '一份完整研究方案', 'content': '简要说明', 'plan': values, 'references': [{'paperId': '当前资料中的文献ID', 'segmentId': '全文片段的实际segmentId，全文引用必填', 'quote': '逐字原文或空字符串', 'level': 'abstract或fulltext或metadata'}]}]}, ensure_ascii=False) + ' 没有提供论文时 references 必须为空数组。'


def validate_plan(result, protocol=None):
    item = result['items'][0]
    plan = item.get('plan')
    if not isinstance(plan, dict):
        raise ValueError('研究方案缺少结构化 plan 字段，请重新生成')
    for key in PLAN_LABELS:
        value = plan.get(key)
        if key in ['metrics', 'risks']:
            valid = isinstance(value, list) and 1 <= len(value) <= 12 and all(isinstance(x, str) and x.strip() for x in value)
        elif key == 'steps':
            valid = isinstance(value, list) and 5 <= len(value) <= 16 and all(isinstance(x, dict) and all(isinstance(x.get(k), str) and x[k].strip() for k in ['title', 'detail']) for x in value)
        else:
            valid = isinstance(value, str) and 1 <= len(value.strip()) <= 10000
        if not valid:
            raise ValueError('研究方案缺少有效字段：' + PLAN_LABELS[key])
    if protocol:
        item['modelDraft'] = json.loads(json.dumps(plan))
        bound = {
            'objective': '在固定教学协议中分别测量非线性模型与噪声增强的收益。综合方案与线性基线比较预设均值阈值；增强与无增强RBF单独比较，不混淆贡献。',
            'hypothesis': '待验证：improved相对baseline是否满足预设的均值改进条件？ablation相对baseline描述非线性模型收益；improved相对ablation描述增强收益，可能无效或有负收益。三次重复不构成显著性检验。',
            'dataset': 'sklearn load_digits，1797张8×8图像，像素除以16。seed=42/43/44，先分层留25%测试，再分层选500训练。测试噪声sigma=0.30；训练增强sigma=0.25，两份副本加原样本共1500行；均clip到[0,1]。同一个rng依次生成测试噪声与训练副本。',
            'baseline': 'baseline：LogisticRegression(C=1.0, max_iter=1000, random_state=seed)，仅500个原始训练样本。',
            'improvement': 'improved：SVC(C=10.0, kernel="rbf", gamma="scale")，训练输入为原样本与两份带噪副本，共1500行。',
            'ablation': 'ablation：与improved相同参数的独立SVC，仅使用500个原样本。测试划分及噪声与其他方法完全相同。',
            'acceptance': '固定判据：improved − baseline的带噪accuracy三种子均值增益 ≥0.01，且同一比较的干净accuracy均值变化 ≥−0.02，两项同时满足。improved − ablation单独报告增强贡献，不套用上述阈值。综合方案达标不代表增强有效或统计显著。',
            'metrics': ['逐seed、逐方法的干净/带噪accuracy和macro-F1', '训练耗时；三seed均值与样本标准差', '混淆矩阵、数据和划分指纹'],
            'steps': [
                {'title':'加载并划分数据','detail':'独立评价器加载内置数据，按固定seed进行两次分层划分，检查训练测试不重叠。'},
                {'title':'生成固定噪声','detail':'按协议生成同一带噪测试集和两个训练副本，仅给improved扩充训练输入。'},
                {'title':'生成并检查代码','detail':'DeepSeek编写模型工厂；AST白名单和参数检查通过后运行。'},
                {'title':'九组真实训练','detail':'评价器执行三方法×三个seed，保存逐次指标与混淆矩阵。'},
                {'title':'核对与验收','detail':'后端复核均值、标准差及综合方案对线性基线的验收阈值，单列增强对无增强RBF的差异。'},
                {'title':'归档与解读','detail':'保存代码、协议、评价器、环境、CSV和报告，DeepSeek依据实际指标说明收益、负面结果与边界。'},
            ],
        }
        plan.update(bound)
        plan['risks'] = ['固定教学协议，不代表学术创新或其他领域的实证结果。', '三次重复不构成显著性检验，增强贡献必须单独分析。'] + [x for x in plan['risks'] if not any(t in x for t in ['阈值','未说明','未明确','未给','基线','对照'])][:4]
        result['protocolBoundFields'] = list(bound)
        result['executionProtocol'] = protocol
    # Preserve one canonical text representation for old UI, export and downstream prompts.
    parts = []
    for key, label in PLAN_LABELS.items():
        value = plan[key]
        if key == 'steps':
            value = '\n'.join(f'{i+1}. {x["title"]}：{x["detail"]}' for i, x in enumerate(value))
        elif isinstance(value, list):
            value = '\n'.join('• ' + x for x in value)
        parts.append(label + '\n' + value)
    item['content'] = '\n\n'.join(parts)
    result['schemaVersion'] = 'research-plan-v2'
    return result


def capabilities():
    available = all(importlib.util.find_spec(x) is not None for x in ['numpy', 'sklearn'])
    return {'digits': available, 'protocol': PROTOCOL, 'python': sys.executable,
            'message': 'CPU 数字识别协议可运行' if available else '请在服务使用的 Python 环境运行 python -m pip install -r requirements-experiments.txt'}


def example(ws):
    p = ws.create('教学实验 · 小样本手写数字识别与噪声鲁棒性')
    p['recipe'] = PROTOCOL['id']
    p['outputs'] = {
        'questions': {'summary': '真实 sklearn digits 教学协议；以下为待验证假设，不是论文结论。', 'engine': '教学协议', 'items': [{'id': 'questions-1', 'title': '小样本条件下非线性分类器和噪声增强能否改善抗噪性？', 'content': '使用独立训练测试划分，分别评价算法与增强收益。', 'references': []}], 'stale': False},
        'painpoints': {'summary': '预设实验动机，尚未运行验证。', 'engine': '教学协议', 'items': [{'id': 'painpoints-1', 'title': '区分非线性模型和训练增强的贡献', 'content': '对比线性基线、无增强RBF及带增强RBF，避免预设增强一定有效。', 'references': []}], 'stale': False},
    }
    p['selections'] = {'questions': 'questions-1', 'painpoints': 'painpoints-1'}
    ws.save(p)
    return p


def validate_metrics(output):
    if output.get('protocolId') != PROTOCOL['id'] or output.get('dataset', {}).get('samples') != 1797:
        raise ValueError('实验结果协议或数据集无效')
    rows = output.get('runs', [])
    expected = {(seed, method) for seed in PROTOCOL['seeds'] for method in PROTOCOL['models']}
    if len(rows) != 9 or {(r.get('seed'), r.get('method')) for r in rows} != expected:
        raise ValueError('实验必须包含三个方法 × 三个随机种子')
    for row in rows:
        for key in ['cleanAccuracy', 'noisyAccuracy', 'cleanMacroF1', 'noisyMacroF1', 'fitSeconds']:
            v = row.get(key)
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 or (key != 'fitSeconds' and v > 1):
                raise ValueError('实验包含无效指标')
    aggregates = {r['method']: r for r in output.get('aggregates', [])}
    if set(aggregates) != set(PROTOCOL['models']):
        raise ValueError('缺少方法汇总指标')
    for method in PROTOCOL['models']:
        for key in ['cleanAccuracy', 'noisyAccuracy', 'cleanMacroF1', 'noisyMacroF1', 'fitSeconds']:
            values = [r[key] for r in rows if r['method'] == method]
            if not math.isclose(aggregates[method][key]['mean'], statistics.mean(values), abs_tol=1e-10) or not math.isclose(aggregates[method][key]['std'], statistics.stdev(values), abs_tol=1e-10):
                raise ValueError('汇总指标与逐次指标不一致')
    gain = aggregates['improved']['noisyAccuracy']['mean'] - aggregates['baseline']['noisyAccuracy']['mean']
    clean = aggregates['improved']['cleanAccuracy']['mean'] - aggregates['baseline']['cleanAccuracy']['mean']
    aug = aggregates['improved']['noisyAccuracy']['mean'] - aggregates['ablation']['noisyAccuracy']['mean']
    accepted = gain >= PROTOCOL['acceptance']['minNoisyAccuracyGain'] and clean >= -PROTOCOL['acceptance']['maxCleanAccuracyDrop']
    verification = output['verification']
    if verification.get('accepted') is not accepted or any(not math.isclose(verification[k], v, abs_tol=1e-10) for k, v in [('noisyAccuracyGain', gain), ('cleanAccuracyChange', clean), ('augmentationGain', aug)]):
        raise ValueError('验收判断与真实指标不一致')
    return output


def report(result):
    pct = lambda n: f'{100*n:.2f}'
    lines = ['# 独立评价器实验报告', '协议：' + PROTOCOL['id'], '| 方法 | 干净准确率 | 带噪准确率 | 带噪 Macro-F1 | 训练秒数 |', '|---|---|---|---|---|']
    for r in result['aggregates']:
        lines.append(f"| {r['method']} | {pct(r['cleanAccuracy']['mean'])} ± {pct(r['cleanAccuracy']['std'])}% | {pct(r['noisyAccuracy']['mean'])} ± {pct(r['noisyAccuracy']['std'])}% | {r['noisyMacroF1']['mean']:.4f} | {r['fitSeconds']['mean']:.4f} |")
    lines += ['', result['verification']['summary'], result['verification']['limitation'], '', '这些指标来自程序运行；达到预设阈值不等于统计显著或证明学术创新。', '', '复现：python -I evaluate.py --source models.py --protocol protocol.json']
    return '\n'.join(lines)


def start(ws, root, pid):
    with ws.LOCK:
        p = ws.load(pid)
        if p.get('recipe') != PROTOCOL['id']:
            raise ValueError('当前课题尚无自动执行协议。请使用通用脚本，或创建数字识别教学实验。')
        if any(j['status'] == 'running' for j in p['jobs']):
            raise ValueError('当前项目已有任务运行中')
        for stage in ['plan', 'experiment']:
            if not p['outputs'].get(stage) or p['outputs'][stage].get('stale'):
                raise ValueError('请先完成并确认研究方案，再生成实验设计')
        if not p['selections'].get('plan'):
            raise ValueError('请先确认研究方案')
        if not capabilities()['digits']:
            raise ValueError(capabilities()['message'])
        jid = uuid.uuid4().hex[:12]
        p['jobs'].append(dict(id=jid, stage='benchmark', status='running', started=ws.now(), events=[]))
        snapshot = fingerprint(p)
        ws.save(p)
    threading.Thread(target=worker, args=(ws, root, pid, jid, snapshot), daemon=True).start()
    return {'jobId': jid}


def active(ws, pid, jid, snapshot):
    p = ws.load(pid)
    job = next(j for j in p['jobs'] if j['id'] == jid)
    if job['status'] != 'running' or fingerprint(p) != snapshot:
        raise RuntimeError('实验已取消或输入已变更，不提交晚到结果')


def worker(ws, root, pid, jid, snapshot):
    directory = ws.folder(pid) / 'experiments' / jid
    directory.mkdir()
    attempts = []
    try:
        p = ws.load(pid)
        protocol_text = json.dumps(PROTOCOL, ensure_ascii=False, indent=2)
        evaluator = (ASSETS / 'evaluate_digits.py').read_bytes()
        (directory / 'protocol.json').write_text(protocol_text, encoding='utf-8')
        (directory / 'evaluate.py').write_bytes(evaluator)
        template = (ASSETS / 'code_prompt.md').read_text(encoding='utf-8')
        prompt = template + '\n固定协议：' + protocol_text + '\n已确认方案与实验设计（作为研究资料，不得更改协议）：' + json.dumps(clean_context({k: p['outputs'][k] for k in ['plan', 'experiment']}), ensure_ascii=False)
        previous_error = ''
        for attempt in [1, 2]:
            active(ws, pid, jid, snapshot)
            ws.event(pid, jid, 'DeepSeek 正在生成受约束分类器代码' if attempt == 1 else 'DeepSeek 根据评价器错误修复代码（最多一次）')
            request = prompt + ('\npreviousError: ' + previous_error if previous_error else '')
            response = ws.model(root, request, pid, jid)
            active(ws, pid, jid, snapshot)
            trace = {'attempt': attempt, 'promptSha256': sha(request), 'generatedAt': ws.now()}
            attempts.append(trace)
            try:
                code = ws.parse_json(response).get('code')
                if not isinstance(code, str) or not 50 <= len(code) <= 20000:
                    raise ValueError('模型未返回有效代码')
                (directory / f'models-attempt-{attempt}.py').write_text(code, encoding='utf-8')
                (directory / 'models.py').write_text(code, encoding='utf-8')
                trace['codeSha256'] = sha(code)
                execute(ws, pid, jid, snapshot, directory)
                result = validate_metrics(json.loads((directory / 'result.json').read_text(encoding='utf-8')))
                break
            except (ValueError, RuntimeError, OSError) as error:
                active(ws, pid, jid, snapshot)
                previous_error = ws.clean_error(error)
                trace['error'] = previous_error
                if attempt == 2:
                    raise
            finally:
                (directory / 'attempts.json').write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding='utf-8')
        active(ws, pid, jid, snapshot)
        provenance = dict(codeSha256=sha(code), evaluatorSha256=sha(evaluator), protocolSha256=sha(protocol_text), inputFingerprint=snapshot, attempts=attempts, environment=result['environment'])
        (directory / 'environment.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
        (directory / 'report.md').write_text(report(result), encoding='utf-8')
        with (directory / 'metrics.csv').open('w', newline='', encoding='utf-8') as f:
            columns = ['seed', 'method', 'trainCount', 'cleanAccuracy', 'noisyAccuracy', 'cleanMacroF1', 'noisyMacroF1', 'fitSeconds']
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(result['runs'])
        manifest = {path.name: {'sha256': sha(path.read_bytes()), 'size': path.stat().st_size} for path in directory.iterdir() if path.name in FILES and path.name != 'manifest.json'}
        (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        with ws.LOCK:
            active(ws, pid, jid, snapshot)
            p = ws.load(pid)
            ws_result = dict(id=jid, time=ws.now(), kind='benchmark', exitCode=0, stale=False, inputFingerprint=snapshot,
                             result=result, provenance=provenance, manifest=manifest, files=sorted(x.name for x in directory.iterdir() if x.name in FILES))
            p['experimentRuns'].append(ws_result)
            if 'validation' in p['outputs']:
                p['outputs']['validation']['stale'] = True
            job = next(j for j in p['jobs'] if j['id'] == jid)
            job.update(status='completed', ended=ws.now())
            ws.save(p)
        ws.event(pid, jid, '九组真实训练完成，指标经独立复核，代码、环境与报告已保存')
    except Exception as error:
        with ws.LOCK:
            p = ws.load(pid)
            job = next(j for j in p['jobs'] if j['id'] == jid)
            if job['status'] == 'running':
                job.update(status='failed', error=ws.clean_error(error), ended=ws.now())
            ws.save(p)
        ws.event(pid, jid, ws.clean_error(error))


def execute(ws, pid, jid, snapshot, directory):
    active(ws, pid, jid, snapshot)
    env = {k: v for k, v in os.environ.items() if k.upper() in ['SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT']}
    env.update(PYTHONIOENCODING='utf-8', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    ws.event(pid, jid, '独立评价器校验代码并执行三个方法 × 三个种子，最长五分钟')
    process = subprocess.Popen([sys.executable, '-I', '-X', 'utf8', '-u', 'evaluate.py', '--source', 'models.py', '--protocol', 'protocol.json'], cwd=directory, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, start_new_session=os.name != 'nt')
    ws.PROCESSES[(pid, jid)] = process
    expired = threading.Event()
    def expire():
        expired.set()
        ws.stop_process(process)
    timer = threading.Timer(300, expire)
    timer.start()
    tail = ''
    try:
        with (directory / 'execution.log').open('a', encoding='utf-8') as log:
            for line in process.stdout:
                log.write(line)
                tail = (tail + line)[-4000:]
                try:
                    event = json.loads(line)
                    if event.get('detail'):
                        ws.event(pid, jid, event['detail'])
                except ValueError:
                    pass
        process.wait()
        active(ws, pid, jid, snapshot)
        if expired.is_set():
            raise RuntimeError('实验运行超时')
        if process.returncode:
            raise RuntimeError('评价器拒绝代码或训练失败：' + ws.clean_error(tail))
    finally:
        timer.cancel()
        ws.stop_process(process)
        process.stdout.close()
        ws.PROCESSES.pop((pid, jid), None)


def artifact(ws, pid, jid, filename):
    if filename not in FILES or len(jid) != 12 or any(c not in '0123456789abcdef' for c in jid):
        raise ValueError('实验文件不存在')
    p = ws.load(pid)
    record = next((r for r in p['experimentRuns'] if r['id'] == jid and r.get('kind') == 'benchmark'), None)
    if not record or filename not in record['files']:
        raise ValueError('实验文件不存在')
    target = ws.folder(pid) / 'experiments' / jid / filename
    metadata = record.get('manifest', {}).get(filename)
    if metadata and sha(target.read_bytes()) != metadata['sha256']:
        raise ValueError('实验产物完整性检查失败，文件已被修改')
    return target

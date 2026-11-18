/* Run: node test_markdown.cjs <path-to-jsdom-package> (development-only dependency). */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require(process.argv[2] || 'jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'outside-only', url: 'http://127.0.0.1:8003/' });
for (const name of ['vendor/marked.umd.js', 'vendor/purify.min.js', 'markdown.js']) {
  dom.window.eval(fs.readFileSync(path.join(root, name), 'utf8'));
}
const project = {id: 'abc123', directory: String.raw`C:\Users\Monika\Research`};
const files = [{path: 'smoke-result.json', name: 'smoke-result.json'},
  {path: 'results space.csv', name: 'results space.csv'}];
function render(value) {
  const target = dom.window.document.createElement('div');
  target.innerHTML = dom.window.researchMarkdown.render(value, {project, files});
  return target;
}
const formatted = render('## 实际执行与真实输出\n\n1. **预检**：运行 `python smoke.py`\n\n| 指标 | 值 |\n|---|---|\n| n | 3 |\n| 均值 | 0.4333 |\n\n```python\nprint("**不是加粗**")\n```');
assert.equal(formatted.querySelector('h2').textContent, '实际执行与真实输出');
assert.equal(formatted.querySelector('strong').textContent, '预检');
assert.equal(formatted.querySelectorAll('tbody tr').length, 2);
assert.equal(formatted.querySelector('td').textContent, 'n');
assert.match(formatted.querySelector('pre code').textContent, /\*\*不是加粗\*\*/);
assert.equal(formatted.querySelector('ol li code').textContent, 'python smoke.py');
const absolute = render(String.raw`[结果文件](C:\Users\Monika\Research\smoke-result.json)`);
assert.equal(absolute.querySelector('a').getAttribute('href'), '/api/projects/abc123/files/smoke-result.json');
assert.equal(absolute.querySelector('a').getAttribute('download'), 'smoke-result.json');
assert.equal(absolute.textContent.trim(), '结果文件');
const relative = render('[数据](results%20space.csv)');
assert.equal(relative.querySelector('a').getAttribute('download'), 'results space.csv');
const realProject = {id: 'abc123', directory: String.raw`C:\Users\Monika\Desktop\科研工作台\workbench\.research-harness\projects\abc`};
const realLink = dom.window.researchMarkdown.render(String.raw`[结果](C:\Users\Monika\Desktop\科研工作台\workbench\.research-harness\projects\abc\smoke-result.json)`, {project: realProject, files});
assert.match(realLink, /download="smoke-result.json"/);
const external = render('[论文](https://arxiv.org/html/2505.06914v1)');
assert.equal(external.querySelector('a').getAttribute('rel'), 'noopener noreferrer');
const malicious = render('<script>window.pwned=true</script><img src="https://other.example/x" onerror="window.pwned=true"><a href="javascript:alert(1)">bad</a>\n\n[x](javascript:alert(1))\n\n[外部文件](file:///C:/private.txt)\n\n[越界](../outside.json)');
assert.equal(malicious.querySelectorAll('script,img,[onerror],a[href]').length, 0);
assert.equal(dom.window.pwned, undefined);
const otherProject = render('[其他项目](/api/projects/other/files/smoke-result.json)');
assert.equal(otherProject.querySelector('a[href]'), null);
console.log('Markdown rendering, tables, code, file links and unsafe-content checks PASS');
dom.window.close();

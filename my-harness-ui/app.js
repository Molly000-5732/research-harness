const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const steps = [['questions','问题调研','研究领域、核心文献与候选问题','⌕'],['painpoints','痛点定位','现有方法的局限与证据','◇'],['plan','方案规划','研究思路与具体技术路径','▱'],['experiment','实验验证','实验设计、运行与结果分析','♧']];
const labels = Object.fromEntries(steps.map(s => [s[0],s[1]]));
const prompts = {
  questions:'请搜索并读取相关论文正文，基于全文证据提出3—5个待选择的研究问题，提供原文、章节位置、文献来源及推断依据。',
  painpoints:'请根据已确认的问题及其文献证据进一步调研，提出具体痛点，区分已知事实与待验证判断。',
  plan:'请根据背景、已确认的问题和痛点，规划具体研究思路、技术路径、假设、基线、数据、指标、消融实验和验收条件。',
  experiment:'请根据已确认方案拟定实验设计与执行步骤，先说明环境、数据、脚本、指标和预期产物，本轮暂不执行。'
};
const active = r => r && ['queued','running'].includes(r.status);
const statusNames = {queued:'等待执行',running:'执行中',completed:'已完成',error:'失败 · 可重试',interrupted:'执行中断 · 结果待核对'};
let list=[], project=null, research=null, sessions={}, files=[], view='overview', version=0, polling=false, sending=false, pendingConfirmation=null, planDocumentBusy=false;
function stored(key, fallback=null) { try { return JSON.parse(localStorage.getItem('sdk-workbench.'+key)) ?? fallback; } catch { return fallback; } }
function save(key,value) { try { localStorage.setItem('sdk-workbench.'+key,JSON.stringify(value)); } catch {} }
function toast(message) { $('#toast').textContent=message; $('#toast').style.display='block'; setTimeout(()=>$('#toast').style.display='none',7000); }
async function api(path,body) {
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json(); if(!response.ok) throw Error(result.error||`请求失败 (${response.status})`); return result;
}
const route = suffix => `/api/projects/${project.id}/research${suffix||''}`;
const current = () => sessions[view];
const markdown = value => window.researchMarkdown.render(value, {project, files});
const lastRun = stage => sessions[stage]?.runs.at(-1);
const busy = () => sending || Object.values(sessions).some(s=>s.runs.some(active));
function badge(stage) {
  const item=research.stages[stage], run=lastRun(stage);
  const text=active(run)?statusNames[run.status]:run?.status==='error'?'失败 · 可重试':item.stale?'需重新生成':item.valid?'已确认':item.ready?'待开展':!research.background?'等待研究背景':'等待前序阶段';
  const color=active(run)?'running':item.stale||run?.status==='error'?'error':item.valid?'ok':'';
  return `<span class="badge ${color}">${esc(text)}</span>`;
}
function sidebar() {
  $('#projects').innerHTML=list.map(p=>`<button data-project="${esc(p.id)}" class="${p.id===project?.id?'active':''}">▱ ${esc(p.name)}</button>`).join('');
  $('#nav').innerHTML=[['overview','研究总览','▦'],...steps.map(s=>[s[0],s[1],s[3]]),['literature','文献库','▤'],['history','研究记录','◷']].map(([k,t,i])=>`<button data-view="${k}" class="${view===k?'active':''}">${i}　${t}</button>`).join('');
}
function overview() {
  return `<div class="grid">${steps.map(([k,t,d],i)=>`<article class="card" data-view="${k}" tabindex="0" role="button"><div class="topline"><div class="number">0${i+1}</div><span>↗</span></div><h2>${t}</h2><p class="muted">${d}</p>${badge(k)}</article>`).join('')}</div>${!research.background?'<p class="warning">请在下方填写研究领域、目标和已有资料，并保存背景后开始问题调研。</p>':''}
  <section class="section"><h2>当前研究任务</h2>${steps.map(([k,t])=>`<div class="task"><span class="task-dot">${research.stages[k].valid?'✓':'○'}</span>${t}<span class="right">${badge(k)}</span></div>`).join('')}</section>
  <section class="section"><h2>项目资源</h2><div class="task">${research.papers.length} 篇已确认文献<span class="right">${files.filter(f=>f.kind==='literature').length} 份补充文献资料</span></div><div class="task">${(sessions.experiment?.runs||[]).filter(r=>r.status==='completed').length} 次实验阶段任务<span class="right">${files.filter(f=>f.kind==='results').length} 份结果与代码文件</span></div><p class="muted small">项目目录：${esc(project.directory)}</p><details ${research.background?'':'open'}><summary>${research.background?'编辑研究背景':'填写研究背景'}</summary><textarea id="background">${esc(stored(`background.${project.id}`,research.background))}</textarea><div class="actions"><button data-action="save-background" ${busy()?'disabled':''}>保存背景</button></div></details></section>${jobPanel()}`;
}
function jobPanel() {
  const runs=Object.entries(sessions).flatMap(([stage,s])=>s.runs.map(r=>({...r,stage}))).sort((a,b)=>a.created_at.localeCompare(b.created_at));
  const r=runs.at(-1); if(!r)return '';
  return `<section class="section"><div class="topline"><h2>当前研究任务 · ${labels[r.stage]}</h2><span class="badge ${r.status==='completed'?'ok':active(r)?'running':'error'}">${esc(statusNames[r.status])}</span></div>${r.error?`<p class="warning">${esc(r.error)}</p>`:''}${r.notices.length?`<details><summary>查看工具执行记录（${r.notices.length}条）</summary>${r.notices.slice(-6).map(n=>`<div class="progress">${esc(n)}</div>`).join('')}</details>`:''}${active(r)?'<p class="muted small">官方 Harness 正在执行，切换页面后任务仍会继续。</p>':''}</section>`;
}
function evidence(entry) {
  return `<div><a href="${esc(entry.url)}" target="_blank" rel="noopener noreferrer">${esc(entry.title||entry.url)}</a> <span class="badge ${entry.verified?'ok':''}">${entry.verified?'原文片段已核对':'原文待核对'}</span><p>位置：${esc(entry.locator)}</p><div class="quote">${esc(entry.quote)}</div><p>${esc(entry.reason)}</p></div>`;
}
function results(stage) {
  const item=research.stages[stage], run=lastRun(stage);
  let html=item.stale?'<p class="warning">上游内容已改变，历史结果仍可查看，请重新调研并确认后再进入下一阶段。</p>':'';
  if(stage==='questions'||stage==='painpoints') {
    const choices=item.choices||[];
    if(!choices.length)html+=`<div class="card empty">${stage==='questions'?'基于论文正文证据的候选问题':'分条痛点、说明与文献依据'}会显示在这里，可通过下方对话继续补充要求。${stage==='painpoints'&&run?.status==='completed'&&run.reply?'<div class="actions"><button data-action="structure-painpoints">将已有成果整理为痛点卡片</button></div>':''}</div>`;
    html+=choices.map(q=>`<article class="card ${item.valid&&item.confirmed.startsWith(q.title)?'selected':''}"><h3>${esc(q.title)}</h3><div class="markdown">${markdown(q.description)}</div><details class="refs"><summary>文献依据（${q.evidence.length} 条 · ${q.evidence.filter(e=>e.verified).length} 条已核对）</summary>${q.evidence.map(evidence).join('')}</details><div class="actions"><button data-choice="${esc(q.id)}" ${busy()||!item.ready||!q.evidence.some(e=>e.verified)?'disabled':''} class="${item.valid&&item.confirmed.startsWith(q.title)?'primary':''}">${item.valid&&item.confirmed.startsWith(q.title)?'✓ 已确认':(stage==='painpoints'?'选择这个痛点':'选择这个问题')}</button></div></article>`).join('');
    if(stage==='painpoints'&&!choices.length&&run?.reply)html+=`<details class="card"><summary>查看原始痛点报告（待分条整理）</summary><div class="markdown">${markdown(run.reply)}</div></details>`;
  } else if(run?.reply) {
    html+=`<article class="card"><span class="badge ok">DeepSeek Harness · 官方 SDK</span><div class="markdown">${markdown(run.reply)}</div>${stage==='plan'?planDocumentActions():run.status==='completed'&&item.ready&&item.draft_current?`<div class="actions"><button data-action="confirm" class="primary" ${busy()?'disabled':''}>${stage==='painpoints'?'选择这个痛点':stage==='plan'?'选择这份方案':'保存实验结论'}</button></div>`:''}</article>`;
  } else html+='<div class="card empty">执行后，DeepSeek 的分析内容会保存在这里。</div>';
  if(item.revisions.length)html+=`<details class="card"><summary>${item.valid?'查看已确认内容与历史版本':'查看历史确认内容'}</summary>${item.revisions.map(r=>`<details><summary>${esc(new Date(r.created_at).toLocaleString())}</summary><div class="markdown">${markdown(r.content)}</div></details>`).join('')}</details>`;
  return html;
}
function planSource() {
  const item=research.stages.plan,run=lastRun('plan');
  if(run?.status==='completed'&&run.reply&&item.draft_current)return run;
  const confirmed=item.valid?item.revisions[0]:null;
  return confirmed?{id:confirmed.run_id,reply:item.confirmed}:null;
}
function linkedPlanFile(source) {
  if(!source)return null;
  return files.filter(file=>/\.(md|txt)$/i.test(file.name)&&/方案|plan|proposal/i.test(file.name)&&source.reply.includes(file.name))
    .sort((a,b)=>source.reply.indexOf(a.name)-source.reply.indexOf(b.name))[0]||null;
}
function planDocumentActions() {
  const source=planSource(),file=linkedPlanFile(source),item=research.stages.plan;
  if(!file)return '<p class="muted small">AI 回复尚未关联完整方案文件。可在下方对话要求将完整方案保存为工作区 Markdown 文档。</p>';
  return `<p class="muted small">完整方案文档：${esc(file.path)}。在本地修改并保存后，点击刷新提交，实验验证将读取你修改后的完整版本。</p><div class="actions"><button data-action="open-plan-document" ${busy()||planDocumentBusy?'disabled':''}>打开完整方案文档</button><button class="primary" data-action="refresh-submit-plan" ${!item.ready||busy()||planDocumentBusy?'disabled':''}>${planDocumentBusy?'正在处理…':'刷新文档并提交到实验验证'}</button></div>`;
}
function conversation() {
  const snapshot=current(), ready=research.stages[view].ready;
  const draft=stored(`draft.${project.id}.${view}`,'');
  const messages=snapshot?.messages||[];
  const history=messages.map(m=>{
    const run=snapshot.runs.find(r=>r.id===m.run_id);
    const automatic=m.role==='user'&&(run?.id.startsWith('action-')||Object.values(prompts).includes(m.content));
    const body=m.role==='assistant'?`<div class="markdown">${markdown(['questions','painpoints'].includes(view)?m.content.replace(/\x60\x60\x60json\s*[\s\S]*?\x60\x60\x60/gi,'').trim():m.content)}</div>`:`<div class="content">${esc(m.content)}</div>`;
    if(automatic)return `<details class="card"><summary>工作台默认任务指令（点击操作时发送）</summary>${body}</details>`;
    return `<article class="card"><span class="badge ${m.role==='user'?'':'ok'}">${m.role==='user'?'你的追加需求':'DeepSeek Harness'}</span>${body}</article>`;
  }).join('');
  return `<section class="section"><h2>继续对话 · ${labels[view]}</h2><p class="muted small">在这里输入进一步的需求，模型会结合当前主题和已有成果进行调整。调整后的成果显示在上方，确认后可继续下一阶段。</p><form id="stage-chat"><label for="message">你的追加需求</label><textarea id="message" maxlength="16000" placeholder="${view==='questions'?'例如：只关注末端对接精度，重新调整候选问题，并保留说明和文献依据。':'输入你希望补充调研或修改的内容…'}" required ${!ready||busy()?'disabled':''}>${esc(draft)}</textarea><div class="actions"><button class="primary" ${!ready||busy()?'disabled':''}>${busy()?'正在执行…':'发送需求并调整'}</button><span class="muted small">${ready?'仅点击发送后提交你的输入':!research.background?'请先保存研究背景':'请先确认前一阶段成果'}</span></div></form>${messages.length?`<details class="conversation-history"><summary>查看历史对话（${messages.filter(m=>m.role==='assistant').length}轮）</summary><div class="stage-messages">${history}</div></details>`:''}</section>`;
}
function approvalPanel() {
  const approval=current()?.approval; if(!approval)return '';
  return `<section class="card"><h3>工具审批 · ${esc(approval.tool)}</h3><p>${esc(approval.reason)}</p><pre>${esc(approval.arguments||'正在等待可审阅的工具参数。')}</pre><div class="actions"><button class="primary" data-approval="allowed-once" ${approval.arguments?'':'disabled'}>批准一次</button><button data-approval="rejected">拒绝</button></div></section>`;
}
function uploadForm(kind) {
  return `<div class="upload"><input type="file" id="file-${kind}" accept=".pdf,.html,.txt,.md,.csv,.json,.py,.png,.jpg,.jpeg"><button data-upload="${kind}" ${busy()?'disabled':''}>上传${kind==='literature'?'全文资料':'实验结果'}</button></div>`;
}
function fileRows(kind) {
  return files.filter(f=>!kind||f.kind===kind).map(f=>`<div class="file-row"><a href="/api/projects/${project.id}/files/${encodeURIComponent(f.path)}" download="${esc(f.name)}">▤ ${esc(f.name)}</a> <span class="muted small">${(f.bytes/1024).toFixed(1)} KB · ${esc(f.path)}</span></div>`).join('');
}
function experimentPanel() {
  const enabled=research.stages.experiment.ready&&!busy();
  return `<section class="section"><h2>实验运行</h2><p class="muted">官方 Harness 将在项目目录使用文件和 Shell 工具实际执行已确认方案。需要审批的操作会在上方展示参数，由你决定是否批准。</p><textarea id="script" class="code" placeholder="可选：粘贴需要保存或执行的 Python 脚本">${esc(stored(`script.${project.id}`,''))}</textarea><div class="actions"><button data-action="save-script" ${enabled?'':'disabled'}>保存脚本 · Harness</button><button class="primary" data-action="run" ${enabled?'':'disabled'}>运行实验 · Harness</button></div><h2>导入实际结果</h2><p class="muted small">上传外部实验结果后，让 Harness 实际读取并核对；结果分析与执行使用同一持久会话。</p>${uploadForm('results')}<div class="actions"><button data-action="validate" ${enabled?'':'disabled'}>分析实际结果 · DeepSeek</button><button data-action="refresh-files">刷新项目产物</button></div>${fileRows('results')}</section>`;
}
function stageView() {
  const item=research.stages[view], index=steps.findIndex(s=>s[0]===view), previous=steps[index-1]?.[0];
  return `${previous&&research.stages[previous].confirmed?`<details><summary>已确认的${labels[previous]}</summary><div class="markdown">${markdown(research.stages[previous].confirmed)}</div></details>`:''}<div class="actions"><button class="primary" data-action="start" ${!item.ready||busy()?'disabled':''}>${lastRun(view)?'重新生成':'开始'}${view==='questions'?'全文证据与问题分析':view==='experiment'?'实验设计':labels[view]} · DeepSeek</button>${badge(view)}${view==='questions'?'<button data-view="literature">查看 / 补充文献</button>':''}</div>${!item.ready?`<p class="warning">${!research.background?'请先在研究总览填写并保存研究背景。':'请先确认前一阶段成果。'}</p>`:''}${view==='questions'?'<p class="muted small">官方 Harness SDK 搜索 → 读取论文正文 → 核对原文证据 → 生成候选研究问题。可通过下方对话进一步调研。</p>':''}${approvalPanel()}${results(view)}${view==='experiment'?experimentPanel():''}${jobPanel()}${conversation()}`;
}
function literature() {
  return `<div class="card"><h3>项目文献库</h3><p class="muted">${research.papers.length} 篇已确认文献 · ${files.filter(f=>f.kind==='literature').length} 份补充全文资料</p><p class="muted small">搜索、论文正文读取和工具调用统一使用官方 DeepSeek Harness Python SDK。原文片段已核对不等于整篇论文已完整下载。</p><div class="actions"><button class="primary" data-action="research-papers" ${busy()?'disabled':''}>检索与阅读全文 · DeepSeek</button></div></div><div class="card"><h3>补充全文</h3><p class="muted small">支持 PDF、TXT、Markdown。上传资料保存在项目目录，由 Harness 文件工具读取，不经过独立的文献搜索服务。</p>${uploadForm('literature')}${fileRows('literature')}</div>${research.papers.map(p=>`<article class="card"><h3><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.title)} ↗</a></h3><p class="content">${esc(p.abstract||'摘要未取得')}</p><div class="markdown muted">${markdown(p.analysis)}</div></article>`).join('')}`;
}
function history() {
  return Object.entries(sessions).flatMap(([stage,s])=>s.runs.map(r=>({...r,stage}))).sort((a,b)=>b.created_at.localeCompare(a.created_at)).map(r=>`<article class="card"><div class="topline"><h3>${labels[r.stage]}</h3><span class="badge ${r.status==='completed'?'ok':active(r)?'running':'error'}">${esc(statusNames[r.status])}</span></div><p class="muted small">${esc(new Date(r.created_at).toLocaleString())}</p><p class="content">${esc(r.message)}</p>${r.error?`<p class="warning">${esc(r.error)}</p>`:''}<details><summary>成果与执行记录</summary><div class="markdown">${markdown(r.reply)}</div>${r.notices.map(n=>`<div class="progress">${esc(n)}</div>`).join('')}</details></article>`).join('')||'<div class="empty">尚无任务记录。</div>';
}
function render() {
  const focused=document.activeElement, id=focused?.id, position=focused?.selectionStart;
  sidebar();
  if(!project||!research){$('#main').innerHTML='<div class="empty"><h1>从一个研究领域开始</h1><p>用文献找到问题，用证据定位痛点，再用实验验证想法。</p><button class="primary" data-action="new">＋ 创建第一个研究项目</button></div>';return;}
  const title=view==='overview'?'研究总览':view==='literature'?'文献库':view==='history'?'研究记录':labels[view];
  $('#main').innerHTML=`<div class="topline"><h1>${title}</h1>${view==='overview'?'<div class="actions"><button data-action="directory">查看项目目录</button><button data-action="export">导出研究报告 ↗</button></div>':''}</div><p class="sub">${esc(project.name)}</p>${view==='overview'?overview():view==='literature'?literature():view==='history'?history():stageView()}`;
  if(id&&['message','script','background'].includes(id)&&$('#'+id)&&!$('#'+id).disabled){$('#'+id).focus({preventScroll:true});if(position!=null)$('#'+id).setSelectionRange(position,position);}
}
async function loadProject(id) {
  const token=++version;
  const item=list.find(p=>p.id===id); if(!item)return;
  const result=await api(`/api/projects/${id}/research`);
  const sessionData=await Promise.all(Object.entries(result.stages).filter(([,s])=>s.session_id).map(async([stage,s])=>[stage,await api(`/api/sessions/${s.session_id}`)]));
  const resource=await api(`/api/projects/${id}/files`);
  if(token!==version)return;
  project=item;research=result;sessions=Object.fromEntries(sessionData);files=resource.files;view='overview';save('project',id);render();window.scrollTo({top:0});
}
async function navigate(next) {
  if(!project)return;
  const token=++version,id=project.id;
  if(labels[next]) {
    const stage=await api(`/api/projects/${id}/research/${next}/session`,{});
    const data=await api(`/api/sessions/${stage.session_id}`);
    const latestResearch=await api(`/api/projects/${id}/research`);
    if(token!==version)return;
    research=latestResearch;sessions[next]=data;
  }
  if(token!==version)return;view=next;save(`view.${id}`,view);render();window.scrollTo({top:0});
}
async function refresh() {
  if(!project)return;
  const token=version,id=project.id;
  const next=await api(`/api/projects/${id}/research`);
  const loaded=await Promise.all(Object.entries(next.stages).filter(([,s])=>s.session_id).map(async([stage,s])=>[stage,await api(`/api/sessions/${s.session_id}`)]));
  const nextSessions=Object.fromEntries(loaded);
  for(const [stage,s] of Object.entries(nextSessions)) {
    const run=s.runs.at(-1);
    if(active(run))s.approval=(await api(`/api/runs/${run.id}/approval`)).approval;
  }
  const resource=await api(`/api/projects/${id}/files`);
  if(token!==version)return;
  const changed=JSON.stringify([research,sessions,files])!==JSON.stringify([next,nextSessions,resource.files]);
  research=next;sessions=nextSessions;files=resource.files;if(changed)render();
}
async function send(message,{source='user'}={}) {
  if(!message.trim()||!labels[view]||busy())return;
  const id=project.id,stage=view,token=version;
  const key=`pending.${id}.${stage}`,old=stored(key);
  const request=old?.message===message?old:{request_id:(source==='action'?'action-':'user-')+crypto.randomUUID(),message};
  save(key,request);sending=true;render();
  try {
    await api(`/api/projects/${id}/research/${stage}/chat`,request);save(key,null);if(source==='user')save(`draft.${id}.${stage}`,'');
    if(token===version)await refresh();
  } finally {sending=false;if(token===version)render();}
}
function openConfirm() {
  const run=lastRun(view);if(!run)return;
  pendingConfirmation={path:route(`/${view}/confirm`),runId:run.id,projectId:project.id};
  $('#confirm-title').textContent='确认'+labels[view];$('#confirm-content').value=run.reply;$('#confirm-dialog').showModal();
}
function exportReport() {
  const content=`# ${project.name}\n\n${research.background}\n\n`+steps.map(([stage,title])=>`## ${title}\n\n${research.stages[stage].confirmed||'尚未确认'}\n`).join('\n');
  const url=URL.createObjectURL(new Blob([content],{type:'text/markdown;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='研究报告.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
document.addEventListener('input',event=>{
  if(!project)return;
  if(event.target.id==='message')save(`draft.${project.id}.${view}`,event.target.value);
  if(event.target.id==='script')save(`script.${project.id}`,event.target.value);
  if(event.target.id==='background')save(`background.${project.id}`,event.target.value);
});
document.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.matches('article[data-view]'))event.target.click();});
document.addEventListener('submit',async event=>{
  if(event.target.id!=='stage-chat')return;event.preventDefault();try{await send($('#message').value.trim());}catch(error){toast(error.message);}
});
document.addEventListener('click',async event=>{
  const el=event.target.closest('button,[data-view]');if(!el||el.disabled)return;
  try {
    if(el.dataset.project){await loadProject(el.dataset.project);return;}
    if(el.dataset.view){await navigate(el.dataset.view);return;}
    const action=el.dataset.action;
    if(el.id==='new'||action==='new'){$('#create-error').hidden=true;$('#create').showModal();return;}
    if(el.id==='dismiss'){$('#create').close();return;}
    if(el.id==='confirm-dismiss'){$('#confirm-dialog').close();return;}
    if(action==='start'){await send(prompts[view],{source:'action'});return;}
    if(el.dataset.choice){const stage=view;await api(route(`/${stage}/confirm`),{run_id:research.stages[stage].choices_run_id,choice_id:el.dataset.choice});await refresh();toast(stage==='painpoints'?'已确认选定痛点及文献依据，可进入方案规划':'已确认问题及文献依据，可进入痛点定位');return;}
    if(action==='confirm'){openConfirm();return;}
    if(action==='open-plan-document'||action==='refresh-submit-plan') {
      const source=planSource(),file=linkedPlanFile(source);
      if(!source||!file)throw Error('请先生成并保存完整方案文档');
      const id=project.id,token=version;planDocumentBusy=true;render();
      try {
        const operation=action==='open-plan-document'?'open-document':'confirm-document';
        const result=await api(`/api/projects/${id}/research/plan/${operation}`,{run_id:source.id,path:file.path});
        if(operation==='confirm-document') {
          if(project?.id===id&&version===token){research=result.research;await navigate('experiment');}
          toast('已重新读取工作区文档并提交最终方案，已进入实验验证');
        } else toast('已请求在本地应用打开方案文档。修改后请保存，再点击刷新提交');
      } finally {planDocumentBusy=false;render();}
      return;
    }
    if(action==='structure-painpoints'){await send('请仅将上一轮已有的痛点分析整理为3—5个独立可选择的痛点条目。保留各条的说明、真实原文引用、位置、来源和阅读边界。返回完整painpoints JSON数组，不重新搜索、不编写或运行实验、不修改工作区文件。',{source:'action'});return;}
    if(el.dataset.approval){const r=lastRun(view),a=current().approval;await api(`/api/runs/${r.id}/approval`,{id:a.id,outcome:el.dataset.approval});await refresh();return;}
    if(action==='save-background'){await api(route(),{background:$('#background').value});save(`background.${project.id}`,null);await refresh();return;}
    if(action==='directory'){toast(project.directory);return;}
    if(action==='export'){exportReport();return;}
    if(action==='refresh-files'){await refresh();toast('项目产物已刷新');return;}
    if(action==='research-papers'){await navigate('questions');await send(prompts.questions,{source:'action'});return;}
    if(action==='save-script'){const script=$('#script').value;if(!script.trim())throw Error('请先填写脚本');await send('请使用文件工具把以下 Python 脚本保存到项目目录 experiment.py，暂不执行。\n```python\n'+script+'\n```',{source:'action'});return;}
    if(action==='run'){const script=$('#script').value;await send(script.trim()?'请审阅以下脚本，使用 Harness 原生文件与 Shell 工具保存并实际执行，核对输出，说明与已确认方案的关系。若无法执行说明原因。\n```python\n'+script+'\n```':'请使用 Harness 原生文件与 Shell 工具实际执行已确认的实验方案，核对真实输出，记录环境、指标、错误与产物路径。缺少前提时明确说明，不编造结果。',{source:'action'});return;}
    if(action==='validate'){await send('请使用原生文件工具读取当前项目的实际实验产物和 research-files/results 中的上传结果，核对指标与已确认方案、基线和验收条件，区分已验证结果、局限和待验证结论。不要编造数据。',{source:'action'});return;}
    if(el.dataset.upload){const kind=el.dataset.upload,file=$('#file-'+kind).files[0];if(!file)throw Error('请先选择文件');if(file.size>10*1024*1024)throw Error('附件不得超过10MB');el.disabled=true;const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});await api(`/api/projects/${project.id}/files`,{name:file.name,base64,kind});await refresh();toast('文件已保存到项目目录，可通过对话让 Harness 阅读');return;}
  }catch(error){toast(error.message);el.disabled=false;}
});
$('#create-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  $('#create-error').hidden=true;
  try {
    const name=$('#project-name').value.trim();
    const directory=$('#project-directory').value.trim().replace(/^"(.*)"$/, '$1');
    const data=await api('/api/projects',{name,directory});
    if(list.some(item=>item.id===data.project.id)||data.project.name!==name) {
      throw Error(`该工作区已绑定项目“${data.project.name}”。请取消后从左侧打开原项目，或换一个文件夹创建新项目。`);
    }
    list=(await api('/api/projects')).projects;
    $('#create').close();$('#create-form').reset();await loadProject(data.project.id);
    toast('已绑定项目工作区，请填写研究背景后开始调研');
  } catch(error) {$('#create-error').textContent=error.message;$('#create-error').hidden=false;}
  finally {button.disabled=false;}
});
$('#confirm-form').addEventListener('submit',async event=>{
  event.preventDefault();const target=pendingConfirmation;if(!target)return;const button=event.submitter;button.disabled=true;
  try{await api(target.path,{run_id:target.runId,content:$('#confirm-content').value});$('#confirm-dialog').close();if(project.id===target.projectId)await refresh();toast('阶段成果已确认');}catch(error){toast(error.message);}finally{button.disabled=false;}
});
setInterval(async()=>{if(!project||polling||sending)return;polling=true;try{await refresh();$('#health').textContent='本地已连接';}catch(error){$('#health').textContent='连接中断';}finally{polling=false;}},2500);
async function initialize(){list=(await api('/api/projects')).projects;const id=stored('project');const item=list.find(p=>p.id===id)||list[0];if(item){await loadProject(item.id);const next=stored(`view.${item.id}`,'overview');if(labels[next]||['history','literature'].includes(next))await navigate(next);}else render();$('#health').textContent='本地已连接';}
initialize().catch(error=>{$('#health').textContent='服务未连接';toast(error.message);});

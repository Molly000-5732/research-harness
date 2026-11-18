const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require(process.argv[2]||'jsdom');
const root=path.resolve(__dirname,'..');
const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{runScripts:'outside-only',url:'http://127.0.0.1:8003/'});
const w=dom.window;w.scrollTo=()=>{};w.researchMarkdown={render:text=>String(text)};
const stages=['questions','painpoints','plan','experiment'];
const snapshots=Object.fromEntries(stages.map(stage=>[stage,{session:{id:stage},messages:[],runs:[]}]));
snapshots.plan.runs.push({id:'plan-1',status:'completed',reply:'实施流程：分析、设计、验证。[完整方案](研究方案-v1.md)',created_at:'2026-11-18',notices:[]});
const research={background:'Topic',papers:[],stages:Object.fromEntries(stages.map(stage=>[stage,
 {session_id:stage,ready:stage!=='experiment',valid:false,stale:false,draft_current:true,revisions:[],confirmed:'',choices:[]}]))};
const posts=[];let diskText='Original AI file',reject=false;
w.fetch=async(url,options={})=>{
 const body=options.body?JSON.parse(options.body):null;if(body)posts.push({url,body});let value;
 if(url==='/api/projects')value={projects:[{id:'project',name:'Research',directory:'C:/research'}]};
 else if(url.endsWith('/research'))value=research;
 else if(url.endsWith('/files'))value={files:[{path:'研究方案-v1.md',name:'研究方案-v1.md',kind:'results',bytes:100}]};
 else if(url.startsWith('/api/sessions/'))value=snapshots[url.split('/').at(-1)];
 else if(url.endsWith('/session'))value={session_id:url.split('/').at(-2)};
 else if(url.endsWith('/open-document'))value={document:{path:body.path}};
 else if(url.endsWith('/confirm-document')){
  assert.equal(body.content,undefined);assert.equal(body.run_id,'plan-1');assert.equal(body.path,'研究方案-v1.md');
  if(reject)return {ok:false,json:async()=>({error:'上游内容已变化'})};
  research.stages.plan.confirmed=diskText;research.stages.plan.valid=true;research.stages.experiment.ready=true;
  value={research,document:{path:body.path}};
 } else throw Error('Unexpected request '+url);
 return {ok:true,json:async()=>structuredClone(value)};
};
const tick=()=>new Promise(resolve=>setTimeout(resolve,20));
const $=selector=>w.document.querySelector(selector);
(async()=>{
 w.eval(fs.readFileSync(path.join(root,'app.js'),'utf8'));await tick();
 $('nav [data-view="plan"]').click();await tick();
 assert.equal($('#final-plan'),null);assert.equal($('#plan-editor'),null);
 assert.match($('main').textContent,/实施流程：分析、设计、验证/);
 $('[data-action="open-plan-document"]').click();await tick();
 assert.equal(posts.filter(p=>p.url.endsWith('/confirm-document')).length,0);
 diskText='Human edited final plan, saved outside the browser';
 reject=true;$('[data-action="refresh-submit-plan"]').click();await tick();
 assert.equal($('main h1').textContent,'方案规划');assert.match($('#toast').textContent,/上游内容已变化/);
 reject=false;$('[data-action="refresh-submit-plan"]').click();await tick();
 assert.equal(research.stages.plan.confirmed,diskText);assert.equal($('main h1').textContent,'实验验证');
 assert.equal(posts.filter(p=>p.url.endsWith('/experiment/chat')).length,0);
 console.log('Compact plan card, open-document request and fresh disk-file handoff PASS');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>w.close());

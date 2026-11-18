const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require(process.argv[2] || 'jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'index.html'), 'utf8'),
  {runScripts: 'outside-only', url: 'http://127.0.0.1:8003/'});
const w = dom.window;
w.scrollTo = () => {};
w.researchMarkdown = {render: text => String(text)};
const stages = ['questions','painpoints','plan','experiment'];
const initial = '请搜索并读取相关论文正文，基于全文证据提出3—5个待选择的研究问题，提供原文、章节位置、文献来源及推断依据。';
const snapshots = Object.fromEntries(stages.map(stage=>[stage, {session:{id:stage}, messages:[], runs:[]} ]));
snapshots.questions.messages.push({role:'user',content:initial,run_id:'legacy-id'});
snapshots.questions.runs.push({id:'legacy-id',message:initial,status:'completed',reply:'',notices:[],created_at:'2026-11-18'});
const research = {background:'Underwater docking',papers:[],stages:Object.fromEntries(stages.map(stage=>[stage,
  {session_id:stage,ready:true,valid:false,stale:false,draft_current:true,confirmed:'',revisions:[],choices:[]}]))};
const requests=[];
w.fetch = async (url,options={}) => {
  let value;
  const match=url.match(/\/research\/(\w+)\/(session|chat)$/);
  if(url==='/api/projects')value={projects:[{id:'project',name:'Docking',directory:'C:/docking'}]};
  else if(url.endsWith('/research'))value=research;
  else if(url.endsWith('/files'))value={files:[]};
  else if(url.startsWith('/api/sessions/'))value=snapshots[url.split('/').at(-1)];
  else if(match&&match[2]==='session')value={session_id:match[1]};
  else if(match&&match[2]==='chat'){
    const request=JSON.parse(options.body);requests.push({stage:match[1],...request});
    snapshots[match[1]].runs.push({id:request.request_id,status:'completed',reply:'Updated stage result',notices:[],created_at:'2026-11-18'});
    value={run:{id:request.request_id}};
  } else throw Error('Unexpected request '+url);
  return {ok:true,json:async()=>structuredClone(value)};
};
const tick=()=>new Promise(resolve=>setTimeout(resolve,15));
const $=selector=>w.document.querySelector(selector);
(async()=>{
  w.eval(fs.readFileSync(path.join(root,'app.js'),'utf8'));
  await tick();
  for(const stage of stages){
    $(`nav [data-view="${stage}"]`).click();await tick();
    assert.equal($('#message').value,'');
    assert.ok(!$('.conversation-history') || ($('#stage-chat').compareDocumentPosition($('.conversation-history'))&4));
    if(stage==='questions'){
      assert.match($('.stage-messages').textContent,/工作台默认任务指令/);
      assert.ok(!$('.stage-messages').textContent.includes('你的追加需求'));
      assert.equal($('.conversation-history').open,false);
    }
    const requirement=`Revise ${stage} for terminal docking precision`;
    $('#message').value=requirement;$('#message').dispatchEvent(new w.Event('input',{bubbles:true}));
    assert.equal(requests.length,stages.indexOf(stage)); // typing never submits
    $('#stage-chat').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick();
    assert.equal(requests.at(-1).message,requirement);
    assert.equal(requests.at(-1).stage,stage);
    assert.match(requests.at(-1).request_id,/^user-/);
    assert.equal($('#message').value,'');
  }
  $('nav [data-view="questions"]').click();await tick();
  $('#message').value='Keep my unsent refinement';$('#message').dispatchEvent(new w.Event('input',{bubbles:true}));
  $('[data-action="start"]').click();await tick();
  assert.match(requests.at(-1).request_id,/^action-/);
  assert.equal($('#message').value,'Keep my unsent refinement');
  console.log('All four stage inputs, collapsed history, explicit send and draft preservation PASS');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>w.close());

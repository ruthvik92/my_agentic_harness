const GLib = imports.gi.GLib;
const System = imports.system;
function check(value, message) { if (!value) throw new Error(message); }
class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.handlers = {};
    this.value = ''; this.style = {}; this.hidden = false; this.classes = new Set(); this.parentElement={};
    this.classList = {
      add: name => this.classes.add(name), remove: name => this.classes.delete(name),
      contains: name => this.classes.has(name),
      toggle: name => { if (this.classes.delete(name)) return false; this.classes.add(name); return true; }
    };
  }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(child=>child.textContent).join(''); }
  get options() { return this.children; }
  appendChild(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
  querySelectorAll(tag) { return this.children.filter(child => child.tag === tag); }
  setAttribute(name, value) { this.attrs[name] = value; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(event, fn) { this.handlers[event] = fn; }
  focus() {}
}
const nodes = {}, stored = new Map([['threadId','first']]);
globalThis.window = globalThis;
globalThis.document = {
  getElementById: id => nodes[id] ||= new Element(), createElement: tag => new Element(tag),
  querySelectorAll: () => [], querySelector: () => null
};
globalThis.Option = class extends Element { constructor(text,value) { super('option'); this.textContent=text; this.value=value; } };
globalThis.localStorage = {getItem:key => stored.get(key) || null, setItem:(key,value) => stored.set(key,value), removeItem:key => stored.delete(key)};
globalThis.setTimeout = () => 1; globalThis.clearTimeout = () => {};
const node = id => document.getElementById(id);
node('execution-mode').appendChild(new Option('Default',''));
const threads = [
  {thread_id:'first',title:'First saved chat',messages:[{role:'user',content:'q'},{role:'assistant',content:'a',mode:'coding',job_id:'coding-job',workspace:'/sandbox/ws_mock',git_workspace:{candidate_commit:'commit',base_branch:'main',workspace_id:'ws_mock',branch:'agent/ws_mock',worktree:'/sandbox/ws_mock/project'}},{role:'user',content:'review'},{role:'assistant',kind:'review',content:'I cannot run tests'}],image:'saved-image',mime:'image/png'},
  {thread_id:'second',title:'Second saved chat',messages:[{role:'user',content:'q2'},{role:'assistant',content:'a2'}],image:null}
];
let holdSecond = false, releaseSecond = null, jobRunning = false, submitted = null, completedReview = false;
let fakeLoop=null, loopSubmissions=0;
const usageReport = count => ({totals:{
  measured_local_input:count, measured_local_output:0, measured_local_total:count,
  measured_openai_input:count, measured_openai_output:0, measured_openai_total:count,
  measured_review_tokens:count, estimated_net_saved_percent:null
},baseline_models:[],assumptions:'mock usage'});
let holdUsage = false, releaseUsage = null;
globalThis.fetch = async (url, options) => {
  const path = url.replace('/api',''); let value;
  if (path === '/info') value = {default_profile:'coder.yaml',allowed_roots:['/repo'],data_root:'/private/runtime'};
  else if (path === '/configs') value = {profiles:[{name:'coder.yaml',kind:'agent',valid:true,mode:'coding',tools:['run_command'],provider:'ollama',model:'local'}]};
  else if (path === '/models') value = {models:[],verifier:{enabled:true,models:[{id:'openai:test',model:'test',provider:'openai',capabilities:[],selectable:true}]}};
  else if (path === '/threads') value = threads;
  else if (path.endsWith('/workspace-review')) { submitted = {path,body:JSON.parse(options.body)}; value = {job_id:'job'}; }
  else if (path.endsWith('/repair-review')) { submitted = {path,body:JSON.parse(options.body)}; value = {job_id:'repair-job'}; }
  else if (path.endsWith('/loops/mock-loop/stop')) {fakeLoop.status='stopped';value=fakeLoop;}
  else if (path.endsWith('/loops')) {
    if(options?.method==='POST'){
      loopSubmissions++;submitted={path,body:JSON.parse(options.body)};
      fakeLoop={loop_id:'mock-loop',workspace_id:'ws_mock',status:'running',stage:'local',local_attempts:1,paid_attempts:0,paid_tokens:0,active_job_id:'loop-job',limits:{max_local_cycles:12,max_paid_reviews:5,paid_token_budget:100000},history:[],live_usage:{measured_local_total:123,measured_openai_total:0}};
      value=fakeLoop;
    }else value=fakeLoop?[fakeLoop]:[];
  }
  else if (path.endsWith('/diagnostics')) value = {run_id:'run_original_attempt',summary:'Model-turn limit reached: 30/30 model requests'};
  else if (path.endsWith('/workspaces')) value = {workspaces:[]};
  else if (path.endsWith('/events')) value = [{run_id:'run_original_attempt',run_seq:1,event_type:'execution.finished',actor:'executor',data:{}}];
  else if (path.endsWith('/usage') || path === '/usage') {
    if (path === '/threads/first/usage' && holdUsage) {
      holdUsage = false;
      await new Promise(resolve => { releaseUsage = resolve; });
    }
    value = usageReport(path === '/usage' ? 999 : path === '/threads/first/usage' ? 123 : 456);
  }
  else if (path.startsWith('/jobs/')) value = {status:completedReview?'completed':'running',model:'local',kind:'answer',answer:'Synthetic review complete'};
  else if (path.startsWith('/threads/')) {
    const id = path.split('/')[2];
    if (id === 'second' && holdSecond) await new Promise(resolve => { releaseSecond = resolve; });
    value = {...threads.find(thread => thread.thread_id === id)};
    if (jobRunning) value.pending_job = 'job';
  } else throw new Error('Unexpected endpoint '+path);
  return {ok:true,json:async () => value};
};
const html = imports.byteArray.toString(GLib.file_get_contents(ARGV[0])[1]);
const dir = GLib.path_get_dirname(ARGV[0]);
for (const asset of ['thread-controls.js','config-controls.js','workspace-results.js','workspace-reviews.js']) {
  (0,eval)(imports.byteArray.toString(GLib.file_get_contents(dir+'/'+asset)[1]));
}
const inline = html.match(/<script nonce="NONCE_VALUE">([\s\S]*?)<\/script>/)[1];
(0,eval)(inline.replace('initialize();','globalThis.ready = initialize();'));
async function main() {
  await ready;
  function descendants(parent) { return parent.children.flatMap(child=>[child,...descendants(child)]); }
  function candidatePanels() { return descendants(node('transcript')).filter(child=>child.tag==='legend' && child.textContent==='Verify this candidate'); }
  check(candidatePanels().length===1,'real chat and workspace widgets must render exactly one candidate review form');
  check(submitted===null,'rendering a candidate must never start paid review');
  const codingReply=threads[0].messages.find(item=>item.mode==='coding');
  codingReply.job_status='failed';codingReply.error='stopped';render();
  check(candidatePanels().length===0,'failed attempts must not offer review of an old candidate');
  codingReply.job_status='completed';delete codingReply.error;render();
  check(candidatePanels().length===1,'completed coding result must offer candidate review');
  if(globalThis.checkLoopControls){
    if(globalThis.checkCompletionControls){
      showLoopOptions({workspace_id:'ws_mock',git_workspace:{worktree:'/worktree'}},'completion');
      node('loop-local').value='12';node('loop-minutes').value='60';node('loop-tokens').value='100000';
      node('loop-paid').value='5';node('loop-consent').checked=true;node('run-limit-minutes').value='9';
      node('n-last-chats').value='3';
      check(node('loop-paid').hidden,'completion hides paid configuration');
      await node('loop-start').handlers.click();
      check(loopSubmissions===1 && submitted.body.mode==='completion','completion binds explicit mode');
      check(submitted.body.authorize_paid===false && submitted.body.max_paid_reviews===0,'completion never authorizes paid calls');
      check(!submitted.body.reviewer_model_id && submitted.body.run_limit_minutes===9,'runtime override propagates without a reviewer');
      check(submitted.body.n_last_chats===3,'history choice propagates into loop submission');
      fakeLoop.status='complete';await refreshLoops();
      check(node('loop-status').textContent.includes('Complete — checks passed; not reviewer-approved.'),'completion label is distinct');
      print('Local completion controls and runtime checks passed');return;
    }
    showLoopOptions({workspace_id:'ws_mock',git_workspace:{worktree:'/worktree'}});
    for(const [id,value] of [['loop-paid','5'],['loop-local','12'],['loop-minutes','60'],['loop-tokens','100000']])node(id).value=value;
    node('loop-consent').checked=false;
    await node('loop-start').handlers.click();check(loopSubmissions===0,'paid loop must require explicit authorization');
    node('workspace-input').value='';node('continue-workspace').value='';node('loop-consent').checked=true;
    await node('loop-start').handlers.click();
    check(loopSubmissions===1 && submitted.body.max_paid_reviews===5 && submitted.body.workspace_id==='ws_mock','loop must bind workspace and default five paid attempts');
    check(!('workspace' in submitted.body) && submitted.body.authorize_paid===true,'no manual paths or implicit consent');
    check(stored.get('currentJobId')==='loop-job','must track the actual current stage');
    await node('loop-start').handlers.click();check(loopSubmissions===1,'busy loop cannot start twice');
    const panel=node('loop-status').children[0];
    check(panel.children.some(n=>(n.textContent||'').includes('local 123')),'loop must show measured usage');
    await panel.children.find(n=>n.textContent==='Stop loop after current stage').handlers.click();
    check(fakeLoop.status==='stopped','stop remains available during an active stage');
    fakeLoop.status='tests_passed_unverified';await refreshLoops();
    check(node('loop-status').children[0].children[0].textContent.includes('not verifier-approved'),'local-only success must not claim verifier approval');
    print('Browser loop consent, five-review default, workspace binding, usage and stop checks passed');return;
  }
  check(node('local-token-meter').textContent.includes('123 tokens'), 'header must show current chat rather than global usage');
  check(node('verifier-token-meter').textContent.includes('Review: 123 tokens'), 'review usage must be scoped to current chat');
  check(node('all-local-token-meter').textContent.includes('All chats · Local models') && node('all-local-token-meter').textContent.includes('999 tokens'), 'all-chat local card must remain visible with cumulative usage');
  check(node('all-verifier-token-meter').textContent.includes('All chats · OpenAI / verifier') && node('all-verifier-token-meter').textContent.includes('Review: 999 tokens'), 'all-chat verifier card must retain cumulative usage');
  check(node('local-token-meter').textContent.includes('Current chat · Local models'), 'current chat cards must label their scope');
  check(node('verifier-token-meter').textContent.includes('Current chat · OpenAI / verifier'), 'current verifier card must label its scope');
  check(node('all-usage').textContent.includes('999'), 'all-chat totals must remain available in details');
  check(!node('history-sidebar').hidden, 'paired user must see sidebar');
  check(node('history-list').children.length === 2, 'must load saved chats');
  check(node('history-list').children[0].attrs['aria-current'] === 'page', 'restore stored active chat');
  check(node('preview').src === 'data:image/png;base64,saved-image', 'restore saved image');
  check(node('storage-location').textContent.includes('/private/runtime/control/agent.db'),'must identify actual data root and ledger');
  await trace();
  check(node('trace').textContent.includes('run_original_attempt'),'readable timeline must identify the selected attempt');
  check(node('trace').textContent.includes('Model-turn limit reached: 30/30'),'timeline uses readable diagnostics instead of raw ledger JSON');
  check(node('review-mode').value === 'workspace', 'coding candidate must default to workspace verification even after advisory replies');
  check(!node('primary-review-fields').hidden && node('verify-btn').textContent.includes('run tests'), 'main action must expose tests and identify executable review');
  node('review-mode').value='conversation';node('review-mode').handlers.change();
  check(node('primary-review-fields').hidden && node('verify-btn').textContent.includes('conversation only'), 'advisory review requires explicit scope selection');
  node('review-mode').value='workspace';node('review-mode').handlers.change();
  check(!node('verify-btn').disabled, 'coding profile must allow saved answer review: '+node('verifier-note').textContent);
  node('history-toggle').handlers.click();
  check(node('history-toggle').attrs['aria-expanded'] === 'true', 'mobile toggle must expose expanded state');
  holdUsage = true;
  const staleUsage = refreshUsage();
  check(releaseUsage !== null, 'old usage request must be held for race check');
  holdSecond = true;
  const switching = selectThread('second');
  check(node('history-new').disabled && node('history-list').children.every(b=>b.disabled), 'navigation must lock during thread load');
  clearConversation(); check(stored.get('threadId') === 'first', 'new chat must not interrupt loading');
  releaseSecond(); await switching;
  check(stored.get('threadId') === 'second', 'switch must store selected chat');
  check(node('history-list').children[1].attrs['aria-current'] === 'page', 'switch must mark active chat');
  check(node('history-toggle').attrs['aria-expanded'] === 'false', 'selecting chat closes mobile history');
  check(node('preview-container').classList.contains('hidden'), 'image-free chat must clear prior image');
  check(node('local-token-meter').textContent.includes('456 tokens'), 'switching chats must update the header totals');
  node('history-new').handlers.click();
  check(node('local-token-meter').textContent.includes('0 tokens'), 'new chat must immediately reset local usage');
  check(node('verifier-token-meter').textContent.includes('Review: 0 tokens'), 'new chat must immediately reset review usage');
  check(node('all-local-token-meter').textContent.includes('999 tokens'), 'new chat must preserve all-chat counters');
  check(node('all-verifier-token-meter').textContent.includes('Review: 999 tokens'), 'new chat must preserve all-chat review usage');
  releaseUsage(); await staleUsage;
  check(node('local-token-meter').textContent.includes('0 tokens'), 'late previous-chat usage must not overwrite new chat');
  check(!stored.has('threadId') && node('transcript').children.length === 0, 'new chat must clear transcript and selection');
  check(node('history-list').children.length === 2, 'new chat must preserve history');
  check(node('verify-btn').disabled, 'new chat must disable paid review');
  holdSecond = false;
  await selectThread('first');
  node('primary-review-command').value='python -m pytest test_specific.py -v';
  node('primary-review-directory').value='nested';
  await node('verify-btn').handlers.click();
  check(submitted?.path==='/threads/first/workspace-review', 'main review button must queue executable workspace review');
  check(submitted.body.answer_job_id==='coding-job' && submitted.body.test_command.includes('test_specific.py') && submitted.body.working_directory==='nested', 'must bind coding answer and visible test options');
  check(node('history-new').disabled && node('history-list').children.every(b=>b.disabled), 'pending job must lock navigation');
  await selectThread('second'); clearConversation();
  check(stored.get('threadId') === 'first', 'active job must preserve current thread');
  const beforeRepair=submitted;
  await repairWorkspaceReview({job_id:'review-job',workspace_review:{target:{candidate_commit:'commit'}}});
  check(submitted===beforeRepair,'active job must prevent a duplicate repair submission');
  for (let i=0; i<20; i++) await Promise.resolve();
  completedReview = true;
  await poll();
  completedReview = false;
  node('config-select').value='coder.yaml';
  window.ConfigControls.mode=()=>'coding';
  const extraContext='Focus on F2 and F3.\nPreserve the current branch.';
  await repairWorkspaceReview({job_id:'review-job',workspace_review:{target:{candidate_commit:'commit'}}},extraContext);
  check(submitted.path==='/threads/first/repair-review','repair must use the authenticated repair endpoint: '+node('error-banner').textContent);
  check(submitted.body.additional_context===extraContext,'repair composer instructions reach the API');
  check(submitted.body.review_job_id==='review-job' && submitted.body.candidate_commit==='commit','repair stays bound to the saved review and candidate');
  check(!('workspace' in submitted.body) && !('branch' in submitted.body),'client cannot choose a replacement workspace or branch');
  print('Browser history restoration, new chat, navigation lock and review checks passed');
}
const loop = new GLib.MainLoop(null, false);
main().then(()=>loop.quit(), error=>{printerr(error.message+'\n'+error.stack);globalThis.failed=true;loop.quit();});
loop.run();
if (globalThis.failed) System.exit(1);

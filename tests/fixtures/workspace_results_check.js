const GLib = imports.gi.GLib;
const System = imports.system;
function check(value, message) { if (!value) throw new Error(message); }
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.attributes = {}; this.handlers = {}; }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, handler) { this.handlers[key] = handler; }
  focus() { this.focused = true; }
  select() { this.selected = true; }
}
globalThis.window = {};
globalThis.document = {createElement: tag => new Element(tag), execCommand: () => true};
globalThis.navigator = {};
const source = imports.byteArray.toString(GLib.file_get_contents(ARGV[0])[1]);
(0, eval)(source);
function panel(result) {
  const root = new Element('main'); window.WorkspaceResults.append(root, result); return root;
}
function controls(root) {
  const children = root.children[0].children;
  return {input: children.find(n => n.tag === 'input'), button: children.find(n => n.tag === 'button'), status: children.find(n => n.tag === 'span')};
}
async function main() {
  const sessions=new Element('main');let continued=null;
  const workspace={container:{name:'local-agent-ws_stable',state:'running',activity:'IDLE'},workspace_id:'ws_stable',git_workspace:{repository:'/repo',worktree:'/worktree',run_id:'run_current',state:'editing'},ledger:'/state/control/agent.db',trace_directory:'/state/control/runs',attempts:[{status:'failed',run_id:'run_previous',model:'local',job_directory:'/state/phone/jobs/job',error:'patch mismatch',failure_details:[{tool:'patch_file',path:'project/a.py',exit_code:1,cause:'one exact match'}]}]};
  window.WorkspaceResults.sessions(sessions,{workspaces:[workspace]},{continue:value=>continued=value,error:message=>{throw new Error(message);}});
  const sessionPanel=sessions.children[0];
  check(sessionPanel.children.some(n=>(n.textContent || '').includes('idle keeper (no agent command running)')),'idle Docker must not imply an active model');
  check(sessionPanel.children.find(n=>n.tag==='details').open,'latest failed attempt expands automatically');
  check(sessionPanel.children.some(n=>(n.textContent||'').includes('/state/control/agent.db')),'workspace panel identifies ledger');
  const follow=sessionPanel.children.find(n=>n.textContent==='Continue this workspace');
  follow.disabled=true;follow.handlers.click();check(!continued,'busy continue must not change workspace');
  follow.disabled=false;follow.handlers.click();check(continued===workspace,'continue binds workspace without manual ID');
  check(sessionPanel.children.some(n=>n.tag==='details'&&n.children.some(c=>c.textContent==='patch mismatch')),'failed attempt remains visible');
  function all(node){return [node,...(node.children || []).flatMap(all)];}
  const attached={original_task:'Keep <script>literal</script>',unresolved_checks:[{status:'failed'}]};
  for(const workspace of [undefined,null,'']) {
    const failed=panel({mode:'coding',job_status:'failed',workspace,task_context:attached});
    check(failed.children.length===1,'failed reply without workspace must still render context');
    const viewer=failed.children[0];
    check(viewer.tag==='details' && viewer.children[0].textContent==='Previous task context attached','context remains expandable after timeout');
    check(viewer.children[1].textContent===JSON.stringify(attached,null,2),'attached context uses literal text');
    check(!all(failed).some(n=>n.tag==='input'),'missing workspace must not fabricate an edited path');
  }
  const completed=panel({mode:'coding',workspace:'/data/ws',task_context:attached});
  check(all(completed).filter(n=>n.textContent==='Previous task context attached').length===1,'successful reply shows context once');
  check(all(completed).some(n=>n.tag==='input'),'workspace controls remain present with context');
  const diagnostic={job_id:'a'.repeat(32),run_id:'run_failure',workspace_id:'ws_stable',status:'budget_exhausted',summary:'Model-turn limit reached: 30/30',model:'local',provider:'ollama',counts:{model_requests:30,tool_calls:2,failed_tools:1},limits:{max_model_turns:30},usage:{input_tokens:500,output_tokens:20},actions:[{tool:'run_command',status:'failed',command:['python','-m','pytest'],exit_code:1,cause:'<script>failure</script>',execution_id:'exec_'+'b'.repeat(32),output_available:true,preview_truncated:true}]};
  const timeline=new Element('div');let requests=[];
  globalThis.fetch=async path=>{requests.push(path);return {ok:true,json:async()=>path.endsWith('/output') ? {text:'x'.repeat(10000)+'END OF FAILURE',retained_bytes:10014,capture_limit_reached:false,capture_size_known:true} : []};};
  window.WorkspaceResults.timeline(timeline,diagnostic);
  check(requests.length===0,'raw events and full outputs load only on demand');
  check(all(timeline).some(n=>n.textContent===diagnostic.summary),'readable stop reason appears first');
  check(all(timeline).some(n=>n.textContent==='<script>failure</script>'),'failure stays literal text');
  check(!all(timeline).some(n=>n.tag==='script'),'model output cannot create executable markup');
  await all(timeline).find(n=>n.textContent==='Read full retained output').handlers.click();
  check(all(timeline).some(n=>n.tag==='pre'&&(n.textContent || '').endsWith('END OF FAILURE')),'full retained output includes tail beyond preview');
  check(requests[0].includes('/executions/exec_'),'full output uses owned execution endpoint');
  check(all(timeline).some(n=>(n.textContent || '').includes('legacy browser controller')),'advanced explanation identifies phone bookkeeping');
  await all(timeline).find(n=>n.textContent==='Load raw ledger').handlers.click();
  check(requests[1].endsWith('/events'),'raw ledger remains available under advanced details');
  const resourcePanel=new Element('div');
  window.WorkspaceResults.timeline(resourcePanel,{...diagnostic,actions:[{
    tool:'run_command',status:'process_limit',cause:'Docker process/thread limit reached (128 tasks)',
    resource_usage:{pids:{before:{max_events:428},after:{current:128,limit:128,max_events:429}}}
  }]});
  check(all(resourcePanel).some(n=>(n.textContent || '').includes('Tasks (processes + threads): 128 / 128')),'process limit measurements are visible');
  check(all(resourcePanel).some(n=>(n.textContent || '').includes('New rejected task creations: 1')),'historical task rejections are not presented as new');
  check(panel({mode: 'chat', workspace: '/unused'}).children.length === 0, 'chat must not display a coding workspace');
  check(panel({mode: 'coding'}).children.length === 0, 'missing result path must not fabricate a location');
  const root = panel({mode:'coding', workspace:'/data/ws_123/', source_workspace:'/source/<img onerror=bad>'});
  const c = controls(root);
  check(c.input.value === '/data/ws_123/project', 'must display project path, not sandbox root');
  check(c.input.readOnly, 'path must be readonly');
  check(root.children[0].children.some(n => n.textContent === 'Source folder: /source/<img onerror=bad>'), 'source path is literal text');
  check(!root.children[0].children.some(n => n.tag === 'a' || n.tag === 'img'), 'no executable path links or markup');
  let copied = null;
  navigator.clipboard = {writeText: async value => { copied = value; }};
  await c.button.handlers.click();
  check(copied === c.input.value && c.status.textContent === 'Path copied', 'secure clipboard must copy full path');
  delete navigator.clipboard;
  let legacy = false;
  document.execCommand = command => { legacy = command === 'copy'; return true; };
  await c.button.handlers.click();
  check(legacy && c.input.selected, 'LAN HTTP clipboard fallback must select and copy');
  document.execCommand = () => false;
  await c.button.handlers.click();
  check(c.status.textContent.includes('manually'), 'failed clipboard must explain manual copy');
  const old = controls(panel({mode:'coding', workspace:'/old/ws'}));
  check(old.input.value === '/old/ws/project', 'saved reply must work without source metadata');
  const branch = panel({mode:'coding', workspace:'/data/ws', job_id:'job123', diff_ref:'blob://diff',
    git_workspace:{branch:'agent/ws_123', base_branch:'main', base_commit:'base123',
      candidate_commit:'commit123', source_dirty:true, state:'ready_for_review', worktree:'/data/ws/project'}});
  const children = branch.children[0].children;
  check(children.some(n => n.textContent === 'Branch: agent/ws_123'), 'branch must be visible');
  check(children.some(n => n.textContent === 'Starting commit: base123'), 'base commit must be visible');
  check(children.some(n => (n.textContent || '').includes('pending changes')), 'pending edits must be explained');
  let requested;
  globalThis.fetch = async path => { requested = path; return {ok:true, json:async () => ({content:'<script>not HTML</script>\n+ code',truncated:false})}; };
  await children.find(n => n.textContent === 'View changes').handlers.click();
  check(requested === '/api/jobs/job123/diff', 'diff must use authenticated job endpoint');
  check(children.find(n => n.tag === 'pre').textContent.includes('<script>not HTML</script>'), 'diff must stay literal text');
  print('Workspace result rendering and clipboard checks passed');
}
const loop = new GLib.MainLoop(null, false);
main().then(() => loop.quit(), error => { printerr(error.stack); System.exit(1); });
loop.run();

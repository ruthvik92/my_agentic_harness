const GLib = imports.gi.GLib;
const System = imports.system;
function check(value, message) { if (!value) throw new Error(message); }
class Element {
  constructor(tag) { this.tag=tag;this.children=[];this.attrs={};this.handlers={};this.dataset={}; }
  appendChild(node) { this.children.push(node);return node; }
  setAttribute(name,value) { this.attrs[name]=value; }
  addEventListener(event,fn) { this.handlers[event]=fn; }
}
globalThis.document={createElement:tag=>new Element(tag)};
let confirmMerge=false;
globalThis.window={};
window.confirm=()=>confirmMerge;
(0,eval)(imports.byteArray.toString(GLib.file_get_contents(ARGV[0])[1]));
const actions=[], errors=[];
window.WorkspaceReviews.init({start:(...args)=>actions.push(['review',...args]),merge:item=>actions.push(['merge',item]),repair:item=>actions.push(['repair',item]),error:error=>errors.push(error)});
const result={job_id:'coding-job',git_workspace:{candidate_commit:'exact-commit',working_directory:'nested'}};
const panel=new Element('main');
window.WorkspaceReviews.appendRequest(panel,result);
check(actions.length===0,'rendering must not invoke paid review');
const fields=panel.children[0].children;
const directory=fields.find(node=>node.tag==='label').children[0];
const labels=fields.filter(node=>node.tag==='label');
const command=labels[1].children[0];
check(directory.value==='nested' && command.value==='auto','must show configurable test command and directory');
check(labels[1].textContent.includes('reviewer discovers'),'auto must explain that the reviewer discovers tests');
const review=fields.find(node=>node.tag==='button');
review.disabled=true;review.handlers.click();check(actions.length===0,'busy review must not invoke actions');
review.disabled=false;review.handlers.click();check(actions[0][0]==='review' && actions[0][1]===result,'explicit click must bind coding answer');
const report={status:'approved',target:{candidate_commit:'exact-commit',source_branch:'main',repository:'/source',working_directory:'.'},test_command:'pytest',checks:[{exit_code:0,status:'succeeded',output:'<script>plain text</script>'}],inspected_files_and_diff:true,review_copy_unchanged:true,checks_copy_unchanged:true};
function reportPanel(value) {
 const root=new Element('main');window.WorkspaceReviews.appendReport(root,{job_id:'review-job',workspace_review:value});return root.children[0];
}
const approved=reportPanel(report), merge=approved.children.find(node=>(node.textContent||'').startsWith('Merge reviewed'));
const discovered=reportPanel({...report,reviewer_tests:{status:'passed'},checks:[{argv:['node','tests/test_leaderboard.js'],cwd:'.',source:'reviewer_discovery',exit_code:0,status:'succeeded',output:'20 passed'}],observations:[{tool:'run_command',arguments:{argv:['node','tests/test_leaderboard.js'],cwd:'project'},exit_code:0,status:'succeeded',output:'<b>plain output</b>'}]});
check(discovered.children.some(node=>(node.textContent||'').includes('independent replay: passed')),'report must show replay status');
const commandDetails=discovered.children.filter(node=>node.tag==='details');
check(commandDetails.some(node=>node.children.some(child=>(child.textContent||'').includes('tests/test_leaderboard.js'))),'report must show the actual selected command');
check(commandDetails.some(node=>node.children.some(child=>child.tag==='pre' && child.textContent==='<b>plain output</b>')),'reviewer command output must render as text');
merge.handlers.click();check(actions.length===1,'merge requires explicit confirmation of the exact target');
confirmMerge=true;merge.handlers.click();check(actions[1][0]==='merge','confirmed action must request merge');
const rejected=reportPanel({...report,status:'changes_requested'});
check(!rejected.children.some(node=>(node.textContent||'').startsWith('Merge reviewed')),'failed review must not offer merge');
const repair=rejected.children.find(node=>node.textContent==='Fix with local model');
check(repair && repair.dataset.requiresReviewer!=='true','repair must work without a paid reviewer');
repair.disabled=true;repair.handlers.click();check(actions.length===2,'busy repair must not submit');
repair.disabled=false;repair.handlers.click();check(actions[2][0]==='repair' && actions[2][1].job_id==='review-job','repair must bind saved review');
check(!approved.children.some(node=>node.textContent==='Fix with local model'),'approved reviews do not need repair');
check(reportPanel({...report,status:'failed'}).children.some(node=>node.textContent==='Fix with local model'),'failed inspection can be repaired');
const merged=reportPanel({...report,merge:{status:'merged',branch:'main',commit:'exact-commit'}});
check(!merged.children.some(node=>(node.textContent||'').startsWith('Merge reviewed')),'merged report must show outcome without another merge action');
check(!reportPanel({...report,status:'changes_requested',merge:{status:'merged'}}).children.some(node=>node.textContent==='Fix with local model'),'merged report cannot start repair');
let request;
globalThis.fetch=async path=>{request=path;return {ok:true,json:async()=>report};};
async function main() {
 await approved.children.find(node=>node.textContent==='View saved review report').handlers.click();
 check(request==='/api/jobs/review-job/workspace-review','report must come from authenticated owned job route');
 check(approved.children.find(node=>node.tag==='pre').textContent.includes('exact-commit'),'report must render saved data as plain text');
 check(!errors.length,'widget must not report unexpected errors');
 print('Workspace review, report and merge controls checks passed');
}
const loop=new GLib.MainLoop(null,false);
main().then(()=>loop.quit(),error=>{printerr(error.message+'\n'+error.stack);globalThis.failed=true;loop.quit();});
loop.run();if(globalThis.failed)System.exit(1);

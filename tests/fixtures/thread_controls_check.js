const GLib = imports.gi.GLib;
function check(value, message) { if (!value) throw new Error(message); }
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.handlers = {}; }
  replaceChildren(...children) { this.children = children; }
  querySelectorAll(tag) { return this.children.filter(child => child.tag === tag); }
  setAttribute(name, value) { this.attrs[name] = value; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
}
globalThis.document = {createElement: tag => new Element(tag)};
globalThis.window = {};
(0, eval)(imports.byteArray.toString(GLib.file_get_contents(ARGV[0])[1]));
const controls = window.ThreadControls, list = new Element('nav'), selected = [];
const threads = [{thread_id:'first',title:'<img onerror=bad()> title'}, {thread_id:'second',title:'Another chat'}];
controls.renderThreads(list, threads, 'second', id => selected.push(id));
check(list.children[0].textContent === threads[0].title, 'titles must remain plain text');
check(list.children[1].attrs['aria-current'] === 'page', 'active chat must be marked');
list.children[0].handlers.click(); check(selected[0] === 'first', 'click must select saved thread ID');
controls.historyBusy(list, true);
list.children[1].handlers.click(); check(selected.length === 1, 'busy click must not switch chats');
check(list.children.every(node => node.disabled), 'busy must disable all chat buttons');
controls.renderThreads(list, threads, 'first', id => selected.push(id), true);
list.children[0].handlers.click(); check(selected.length === 1, 'refresh during job must retain busy lock');
controls.historyBusy(list, false); list.children[1].handlers.click();
check(selected[1] === 'second', 'idle must restore navigation');
controls.markThread(list, null);
check(list.children.every(node => !node.attrs['aria-current']), 'new chat must clear active marker');
controls.renderThreads(list, [], null, () => {});
check(list.children[0].textContent === 'No saved chats yet.', 'empty history needs explanation');
const verifier = {enabled:true}, thread = {messages:[{role:'assistant',content:'answer'}]};
const state = {paired:true,busy:false,selected:'openai:example'};
check(controls.reviewState(verifier, thread, state).enabled, 'saved answer must allow explicit review');
check(!controls.reviewState(verifier, {messages:[]}, state).enabled, 'empty saved chat must not allow review');
check(!controls.reviewState(verifier, thread, {...state,busy:true}).enabled, 'busy must block review');
check(!controls.reviewState(verifier, thread, {...state,paired:false}).enabled, 'unpaired must block review');
check(!controls.reviewState(verifier, thread, {...state,selected:''}).enabled, 'missing model must block review');
const disabled = controls.reviewState({enabled:false,reason:'Supply --verifier-agent'}, thread, state);
check(!disabled.enabled && disabled.note.includes('--verifier-agent'), 'show server configuration reason');
check(disabled.note.includes('billing'), 'explicit review must disclose billing');
print('Thread navigation and reviewer checks passed');
const localMeter = new Element('span'), paidMeter = new Element('span');
controls.renderMeter(localMeter, paidMeter, {totals:{measured_local_input:123,measured_local_output:45,measured_local_total:168,measured_openai_input:50,measured_openai_output:10,measured_review_tokens:60,unknown_openai_requests:1}});
check(localMeter.textContent.includes('168 tokens') && localMeter.textContent.includes('123 in + 45 out'), 'meter must show measured native local usage');
check(paidMeter.textContent.includes('partial') && paidMeter.textContent.includes('Review: 60 tokens'), 'meter must distinguish partial API data and verifier overhead');
const missingUsage = {totals:{estimated_net_saved_percent:null}, unavailable_jobs:1, baseline_models:[], assumptions:'Measured records only'};
controls.renderMeter(localMeter, paidMeter, missingUsage);
check(localMeter.textContent.includes('partial') && paidMeter.textContent.includes('partial'), 'missing run usage must not look complete');
const details = new Element('pre');
controls.renderUsage(details, missingUsage, 'Current chat');
check(details.textContent.includes('Usage unavailable for 1 saved attempts'), 'details must explain excluded usage records');

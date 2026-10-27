const GLib = imports.gi.GLib;
const System = imports.system;
function check(value, message) { if (!value) throw new Error(message); }
class Element {
  constructor() { this.children = []; this.value = ''; this.handlers = {}; this.hidden = false; }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text || ''; }
  get options() { return this.children; }
  appendChild(node) { this.children.push(node); }
  addEventListener(event, fn) { this.handlers[event] = fn; }
}
const nodes = {};
globalThis.document = {getElementById: id => (nodes[id] ||= new Element())};
globalThis.window = {};
globalThis.Option = class {
  constructor(text, value) { this.textContent = text; this.value = value; }
};
const node = id => document.getElementById(id);
node('execution-mode').appendChild(new Option('Use profile default', ''));
node('execution-mode').appendChild(new Option('Ephemeral', 'ephemeral'));
node('execution-mode').appendChild(new Option('Persistent', 'persistent'));
const profiles = [
  {name:'coder.yaml', mode:'coding', tools:['run_command'], execution:{execution_mode_default:'ephemeral'}},
  {name:'analog.yaml', mode:'circuit', tools:['render_pdf_region'], execution:{execution_mode_default:'persistent'}},
  {name:'browser.yaml', mode:'chat', tools:[]}
].map(p => ({...p, kind:'agent', valid:true, provider:'ollama', model:'local'}));
(0, eval)(imports.byteArray.toString(GLib.file_get_contents(ARGV[0])[1]));
async function main() {
  const controls = window.ConfigControls;
  controls.init(async () => ({profiles}), error => { throw new Error(error); });
  await controls.refresh('coder.yaml', ['/repo']);
  check(node('legacy-circuit-controls').hidden && node('netlist-btn').hidden && node('verify-btn').hidden, 'coder must hide legacy circuit actions/models');
  check(!node('execution-fields').hidden, 'coder must show execution selector');
  check(node('execution-mode').options[0].textContent.includes('ephemeral'), 'must show actual profile default');
  check(!('execution_mode' in controls.requestFields()), 'default must not override profile');
  node('execution-mode').value = 'persistent';
  check(controls.requestFields().execution_mode === 'persistent', 'persistent choice must enter the submitted request');
  controls.busy(true); check(node('execution-mode').disabled, 'busy mode must disable execution choice');
  controls.busy(false); check(!node('execution-mode').disabled, 'idle mode must enable choice');
  node('config-select').value = 'analog.yaml'; node('config-select').handlers.change();
  check(node('legacy-circuit-controls').hidden, 'PDF circuit workflow must not offer screenshot netlist controls');
  check(node('execution-mode').value === '', 'profile switch must clear previous override');
  check(node('execution-mode').options[0].textContent.includes('persistent'), 'analog default must be reflected');
  check(!node('circuit-fields').hidden && node('image-fields').hidden, 'analog must show PDF input');
  node('pdf-input').value = 'manual.pdf'; node('page-input').value = '1'; node('dpi-input').value = '300';
  check(!('execution_mode' in controls.requestFields()), 'profile persistent default must remain implicit');
  node('config-select').value = 'browser.yaml'; node('config-select').handlers.change();
  check(!node('legacy-circuit-controls').hidden, 'screenshot chat keeps its legacy optional actions');
  check(node('execution-fields').hidden, 'no-tools chat must hide execution choice');
  node('execution-mode').value = 'persistent';
  check(!('execution_mode' in controls.requestFields()), 'hidden stale execution choice must not leak into chat');
  node('config-select').value = 'coder.yaml'; node('config-select').handlers.change();
  check(node('execution-mode').value === '', 'returning to coder must use its default');
  print('Profile visibility and execution mode checks passed');
}
const loop = new GLib.MainLoop(null, false);
main().then(() => loop.quit(), error => { printerr(error.stack); System.exit(1); });
loop.run();

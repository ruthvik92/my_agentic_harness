const GLib = imports.gi.GLib;
const System = imports.system;
function check(value, message) { if (!value) throw new Error(message); }
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.attributes = {}; this.handlers = {}; }
  appendChild(node) { this.children.push(node); return node; }
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
  print('Workspace result rendering and clipboard checks passed');
}
const loop = new GLib.MainLoop(null, false);
main().then(() => loop.quit(), error => { printerr(error.stack); System.exit(1); });
loop.run();

globalThis.checkLoopControls=true;
const helperPath=imports.gi.GLib.path_get_dirname(ARGV[0])+'/../../../../tests/fixtures/browser_navigation_check.js';
(0,eval)(imports.byteArray.toString(imports.gi.GLib.file_get_contents(helperPath)[1]));

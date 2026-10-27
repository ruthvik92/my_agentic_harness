/* Server paths are copyable text, never file URLs or executable model markup. */
(function () {
  'use strict';
  function append(parent, result) {
    if (result.mode !== 'coding' || typeof result.workspace !== 'string' || !result.workspace) return;
    const panel = document.createElement('div');
    panel.className = 'workspace-result';
    const heading = document.createElement('strong');
    heading.textContent = 'Edited workspace'; panel.appendChild(heading);
    if (typeof result.source_workspace === 'string' && result.source_workspace) {
      const source = document.createElement('p');
      source.textContent = 'Source folder: ' + result.source_workspace;
      panel.appendChild(source);
    }
    const label = document.createElement('p');
    label.textContent = 'Edited project on the harness computer:';
    panel.appendChild(label);
    const input = document.createElement('input');
    input.type = 'text'; input.readOnly = true;
    input.value = result.workspace.replace(/\/+$/, '') + '/project';
    input.setAttribute('aria-label', 'Edited project path');
    input.style.width = '100%'; panel.appendChild(input);
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = 'Copy path';
    const status = document.createElement('span');
    status.setAttribute('aria-live', 'polite');
    button.addEventListener('click', async function () {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(input.value);
        } else {
          // Clipboard API is unavailable over ordinary LAN HTTP.
          input.focus(); input.select();
          if (!document.execCommand('copy')) throw new Error('manual copy required');
        }
        status.textContent = 'Path copied';
      } catch (_) {
        input.focus(); input.select();
        status.textContent = 'Path selected; copy it manually.';
      }
    });
    panel.appendChild(button); panel.appendChild(status);
    const note = document.createElement('p');
    note.className = 'model-run';
    note.textContent = 'Open this path on the harness computer to review the changes. The harness has not applied this copy to the source folder.';
    panel.appendChild(note); parent.appendChild(panel);
  }
  window.WorkspaceResults = {append: append};
})();

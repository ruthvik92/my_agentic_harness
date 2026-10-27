/* Server paths are copyable text, never file URLs or executable model markup. */
(function () {
  'use strict';
  function append(parent, result) {
    if (result.mode !== 'coding' || typeof result.workspace !== 'string' || !result.workspace) return;
    const panel = document.createElement('div');
    panel.className = 'workspace-result';
    const git = result.git_workspace;
    const heading = document.createElement('strong');
    heading.textContent = git ? 'Agent Git branch' : 'Edited workspace'; panel.appendChild(heading);
    const sourcePath = result.source_workspace || (git && git.repository);
    if (typeof sourcePath === 'string' && sourcePath) {
      const source = document.createElement('p');
      source.textContent = 'Source folder: ' + sourcePath;
      panel.appendChild(source);
    }
    if (git) {
      for (const [label, value] of [
        ['Branch', git.branch], ['Base branch', git.base_branch || 'detached HEAD'],
        ['Starting commit', git.base_commit],
        ['Candidate commit', git.candidate_commit || 'Not published; inspect the worktree'],
        ['Review state', git.state]
      ]) {
        const line = document.createElement('p');
        line.textContent = label + ': ' + value; panel.appendChild(line);
      }
      if (git.source_dirty) {
        const dirty = document.createElement('p');
        dirty.textContent = 'Your source had pending changes. They were left untouched and were not included in this run.';
        panel.appendChild(dirty);
      }
    }
    const label = document.createElement('p');
    label.textContent = 'Edited project on the harness computer:';
    panel.appendChild(label);
    const input = document.createElement('input');
    input.type = 'text'; input.readOnly = true;
    input.value = git && git.worktree ? git.worktree : result.workspace.replace(/\/+$/, '') + '/project';
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
    if (result.job_id && result.diff_ref) {
      const view = document.createElement('button');
      view.type = 'button'; view.textContent = 'View changes';
      const diff = document.createElement('pre');
      diff.hidden = true; diff.style.maxHeight = '24rem'; diff.style.overflow = 'auto';
      view.addEventListener('click', async function () {
        view.disabled = true;
        try {
          const response = await fetch('/api/jobs/' + encodeURIComponent(result.job_id) + '/diff');
          const value = await response.json();
          if (!response.ok) throw new Error(value.error || 'Could not load diff');
          diff.textContent = (value.content || 'No changes captured.') +
            (value.truncated ? '\n[Preview truncated; inspect the full artifact in traces.]' : '');
          diff.hidden = false;
        } catch (error) { status.textContent = error.message; }
        finally { view.disabled = false; }
      });
      panel.appendChild(view); panel.appendChild(diff);
    }
    const note = document.createElement('p');
    note.className = 'model-run';
    note.textContent = git
      ? 'Open this worktree or inspect the branch in your repository. Review the diff and tests before merging; your original checkout has not been switched or updated.'
      : 'Open this path on the harness computer to review the changes. The harness has not applied this copy to the source folder.';
    panel.appendChild(note); parent.appendChild(panel);
  }
  window.WorkspaceResults = {append: append};
})();

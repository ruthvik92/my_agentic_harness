/* Explicit workspace inspection and host merge actions. Model text never creates actions. */
(function () {
  'use strict';
  let actions = null;
  const make = (tag, text) => { const node = document.createElement(tag); if (text) node.textContent = text; return node; };
  function control(node) { node.className = 'workspace-review-control'; return node; }
  function appendRequest(parent, result) {
    const git = result.git_workspace;
    if (!actions || !git?.candidate_commit || !result.job_id || result.kind === 'workspace_review') return;
    const panel = make('fieldset');
    panel.appendChild(make('legend', 'Verify this candidate'));
    panel.appendChild(make('p', 'Candidate commit: ' + git.candidate_commit));
    if (git.workspace_id) panel.appendChild(make('p', 'Workspace: ' + git.workspace_id));
    const directoryLabel = make('label', 'Test working directory (relative to project)');
    const directory = control(make('input')); directory.type = 'text';
    directory.value = result.working_directory || git.working_directory || '.';
    directory.setAttribute('aria-label', 'Review test working directory');
    directoryLabel.appendChild(directory); panel.appendChild(directoryLabel);
    const commandLabel = make('label', 'Tests (auto: reviewer discovers suites; override optional)');
    const command = control(make('input')); command.type = 'text'; command.value = 'auto';
    command.setAttribute('aria-label', 'Review test command');
    commandLabel.appendChild(command); panel.appendChild(commandLabel);
    const button = control(make('button', 'Review workspace and run checks (paid)')); button.type = 'button';
    button.dataset.requiresReviewer = 'true';
    button.addEventListener('click', () => {
      if (!button.disabled) actions.start(result, command.value, directory.value);
    });
    panel.appendChild(button);
    panel.appendChild(make('p', 'Leave tests on auto. The selected paid reviewer inspects the code and test configuration, discovers relevant suites and runs them. Selected tests are repeated in a fresh copy before approval. Missing dependencies and unverified behavior are reported. Merging is a separate action.'));
    parent.appendChild(panel);
  }
  function appendReport(parent, result) {
    const report = result.workspace_review;
    if (!actions || !report) return;
    const panel = make('section'); panel.className = 'workspace-review-report';
    panel.appendChild(make('strong', 'Workspace review: ' + report.status));
    panel.appendChild(make('p', 'Reviewed commit: ' + report.target.candidate_commit));
    for (const finding of report.findings || []) {
      const details=make('details');
      details.appendChild(make('summary',finding.id+' · '+(finding.location || 'Review finding')));
      details.appendChild(make('p','Observed: '+finding.observed));
      details.appendChild(make('p','Expected: '+finding.expected));
      details.appendChild(make('p','Impact: '+finding.impact));
      for(const criterion of finding.acceptance || []) details.appendChild(make('p','Acceptance: '+criterion));
      panel.appendChild(details);
    }
    if (report.project_tests) panel.appendChild(make('p', 'Test plan: ' + report.project_tests.status));
    if (report.project_tests?.error) panel.appendChild(make('p', 'Controller test blocker: ' + report.project_tests.error));
    if (report.reviewer_tests) panel.appendChild(make('p', 'Reviewer-selected tests, independent replay: ' + report.reviewer_tests.status));
    if (report.reviewer_tests?.error) panel.appendChild(make('p', 'Selected-test replay blocker: ' + report.reviewer_tests.error));
    if (report.test_discovery_error) panel.appendChild(make('p', 'Test discovery incomplete: ' + report.test_discovery_error));
    panel.appendChild(make('p', 'Configured check: ' + report.test_command + ' · directory: ' + report.target.working_directory));
    for (const check of report.checks || []) {
      const details = make('details'); details.appendChild(make('summary', 'Check output · exit ' + check.exit_code + ' · ' + check.status));
      details.appendChild(make('p', JSON.stringify(check.argv || []) + ' · directory: ' + (check.cwd || '.') + (check.source === 'reviewer_discovery' ? ' · reviewer-selected, independently repeated' : ' · controller check')));
      const output = make('pre', check.output || '(No output)');
      if (check.truncated) output.textContent += '\n[Preview truncated; full output is retained in the trace.]';
      details.appendChild(output); panel.appendChild(details);
    }
    for (const execution of report.observations || []) {
      if (execution.tool !== 'run_command') continue;
      const details = make('details');
      details.appendChild(make('summary', 'Reviewer command · exit ' + execution.exit_code + ' · ' + execution.status));
      details.appendChild(make('p', JSON.stringify(execution.arguments?.argv || []) + ' · directory: ' + (execution.arguments?.cwd || 'project')));
      details.appendChild(make('pre', (execution.output || '(No output)') + (execution.truncated ? '\n[Preview truncated; full command and output are retained in the trace.]' : '')));
      panel.appendChild(details);
    }
    panel.appendChild(make('p', 'Check copy: ' + (report.checks_copy_unchanged ? 'unchanged' : 'changed or not captured')));
    panel.appendChild(make('p', 'Inspection evidence: ' + (report.inspected_files_and_diff ? 'diff and project file reads recorded' : 'incomplete') + ' · review copy: ' + (report.review_copy_unchanged ? 'unchanged' : 'changed or not captured')));
    const view = control(make('button', 'View saved review report')); view.type = 'button';
    const output = make('pre'); output.hidden = true;
    view.addEventListener('click', async () => {
      if (view.disabled) return;
      try {
        const response = await fetch('/api/jobs/' + encodeURIComponent(result.job_id) + '/workspace-review');
        const value = await response.json();
        if (!response.ok) throw new Error(value.error || 'Could not load review report');
        output.textContent = JSON.stringify(value, null, 2); output.hidden = false;
      } catch (error) { actions.error(error.message); }
    });
    panel.appendChild(view); panel.appendChild(output);
    if (['changes_requested', 'failed'].includes(report.status) &&
        !['merged', 'merging'].includes(report.merge?.status)) {
      const repair = control(make('button', 'Fix with local model')); repair.type = 'button';
      const options = make('fieldset'); options.hidden = true;
      options.appendChild(make('legend', 'Local repair'));
      options.appendChild(make('p', 'Continues this reviewed workspace and agent branch with the saved findings and test output.'));
      const label = make('label', 'Additional repair context (optional, up to 4,000 characters)');
      const context = control(make('textarea')); context.rows = 6; context.maxLength = 4000;
      context.value = '';
      context.setAttribute('aria-label', 'Additional repair context');
      context.placeholder = 'Add priorities, constraints, or details for the local model.';
      label.appendChild(context); options.appendChild(label);
      const start = control(make('button', 'Start local repair')); start.type = 'button';
      start.addEventListener('click', () => {
        if (start.disabled) return;
        if (context.value.length > 4000) {
          actions.error('Additional repair context must be at most 4,000 characters.'); return;
        }
        actions.repair(result, context.value.trim());
      });
      const cancel = control(make('button', 'Cancel')); cancel.type = 'button';
      cancel.addEventListener('click', () => {
        if (!cancel.disabled) { options.hidden = true; repair.hidden = false; }
      });
      options.appendChild(start); options.appendChild(cancel);
      repair.addEventListener('click', () => {
        if (!repair.disabled) {
          options.hidden = false; repair.hidden = true; context.focus?.();
        }
      });
      panel.appendChild(repair); panel.appendChild(options);
    }
    if (report.merge?.status === 'merged') {
      panel.appendChild(make('p', 'Merged into ' + report.merge.branch + ': ' + report.merge.commit));
    } else if (report.status === 'approved') {
      const merge = control(make('button', 'Merge reviewed commit into ' + report.target.source_branch)); merge.type = 'button';
      merge.addEventListener('click', () => {
        if (merge.disabled) return;
        const target = report.target;
        if (window.confirm('Merge reviewed commit ' + target.candidate_commit + '\ninto ' + target.repository + ' (' + target.source_branch + ')?\nThe source checkout must be clean and unchanged.')) actions.merge(result);
      });
      panel.appendChild(merge);
    } else {
      panel.appendChild(make('p', 'Merge unavailable: resolve findings or failed/incomplete checks, then review the new candidate.'));
    }
    if (report.merge?.status === 'rejected') panel.appendChild(make('p', 'Last merge rejected: ' + report.merge.reason));
    parent.appendChild(panel);
  }
  window.WorkspaceReviews = {init: value => { actions = value; }, appendRequest, appendReport};
})();

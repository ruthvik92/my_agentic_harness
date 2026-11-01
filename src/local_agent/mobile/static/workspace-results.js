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
    const task = document.createElement('p');
    task.textContent = 'Task: ' + (result.task_mode || (git && git.task_mode) || 'new') +
      ' · Working subdirectory: ' + (result.working_directory || (git && git.working_directory) || '.');
    panel.appendChild(task);
    const sourcePath = result.source_workspace || (git && git.repository);
    if (typeof sourcePath === 'string' && sourcePath) {
      const source = document.createElement('p');
      source.textContent = 'Source folder: ' + sourcePath;
      panel.appendChild(source);
    }
    if (git) {
      for (const [label, value] of [
        ['Workspace ID', git.workspace_id || git.branch.replace(/^agent\//, '')],
        ['Branch', git.branch], ['Base branch', git.base_branch || 'detached HEAD'],
        ['Starting commit', git.base_commit],
        ['Candidate commit', git.candidate_commit || 'Not published; inspect the worktree'],
        ['Review state', git.state]
      ]) {
        const line = document.createElement('p');
        line.textContent = label + ': ' + value; panel.appendChild(line);
      }
      if (window.ConfigControls && window.ConfigControls.continueTask) {
        const continueButton = document.createElement('button');
        continueButton.type = 'button'; continueButton.textContent = 'Continue this worktree';
        continueButton.addEventListener('click', () => window.ConfigControls.continueTask(result));
        panel.appendChild(continueButton);
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
    panel.appendChild(note);
    parent.appendChild(panel);
  }
  function make(tag, text) {
    const node=document.createElement(tag); node.textContent=text == null ? '' : String(text); return node;
  }
  async function getJSON(path) {
    const response=await fetch(path); const value=await response.json();
    if(!response.ok) throw new Error(value.error || 'Could not load retained evidence');
    return value;
  }
  function timeline(parent, data, options={}) {
    parent.replaceChildren();
    const root=make('section'); root.className='workspace-result';
    root.appendChild(make('strong',data.summary));
    root.appendChild(make('p',(data.model || 'Model not recorded')+' · '+(data.provider || 'provider unknown')+' · '+data.status));
    root.appendChild(make('p','Run: '+data.run_id+' · Workspace: '+data.workspace_id));
    if(data.job_error && data.job_error !== data.summary) root.appendChild(make('pre','Reported error: '+data.job_error));
    const counts=data.counts || {}, usage=data.usage || {};
    if(data.repair_progress) {
      const p=data.repair_progress;
      root.appendChild(make('p','Repair stage: '+p.stage+' · '+p.actions+' observed actions · last milestone at action '+p.last_milestone+' · recoveries: '+p.recoveries+' · '+p.decision+' ('+p.mode+')'));
      if(p.monitor_error) root.appendChild(make('p','Progress measurement blocked: '+p.monitor_error));
    }
    root.appendChild(make('p',(counts.model_requests || 0)+' model requests'+
      (data.limits?.max_model_turns ? ' / '+data.limits.max_model_turns+' allowed' : '')+
      ' · '+(counts.tool_calls || 0)+' tool calls · '+(counts.failed_tools || 0)+' failed or rejected'));
    root.appendChild(make('p','Recorded provider tokens: '+(usage.input_tokens || 0)+' input + '+(usage.output_tokens || 0)+' output'+
      (usage.partial ? ' (partial; some usage unavailable)' : '')+'. Input totals include repeated context across requests.'));
    for(const error of data.provider_errors || []) root.appendChild(make('pre','Provider error: '+(error.type || '')+' '+error.message));
    for(const test of data.tests || []) root.appendChild(make('p','Independent check: '+test.status+(test.error ? ' · '+test.error : '')));
    if(data.actions_omitted) root.appendChild(make('p',data.actions_omitted+' earlier actions omitted here; the raw ledger retains their records.'));
    const list=make('ol');
    for(const action of data.actions || []) {
      const item=make('li'), detail=make('details');
      detail.open=!['succeeded','proposed'].includes(action.status);
      detail.appendChild(make('summary',action.tool+' · '+action.status+(action.path ? ' · '+action.path : '')+
        (action.exit_code == null ? '' : ' · exit '+action.exit_code)));
      if(action.command) detail.appendChild(make('pre','Command argv: '+JSON.stringify(action.command)));
      if(action.actor === 'controller') detail.appendChild(make('p','Independent controller command'));
      if(action.cause) detail.appendChild(make('pre',action.cause));
      const pids=action.resource_usage?.pids;
      if(action.status === 'process_limit' && pids?.after) {
        const sample=pids.after, before=pids.before;
        const delta=Number.isInteger(sample.max_events) && Number.isInteger(before?.max_events) ?
          sample.max_events-before.max_events : null;
        detail.appendChild(make('p','Tasks (processes + threads): '+sample.current+' / '+sample.limit+
          (delta == null ? '' : ' · New rejected task creations: '+delta)));
      }
      if(action.preview_truncated) detail.appendChild(make('p','Preview shortened. Open retained output for the available full text.'));
      if(action.output_available && action.execution_id && data.job_id) {
        const button=make('button','Read full retained output'); button.type='button';
        const output=make('pre'), note=make('p'); output.hidden=true;
        button.addEventListener('click',async()=>{
          button.disabled=true;
          try {
            const value=await getJSON('/api/jobs/'+encodeURIComponent(data.job_id)+'/executions/'+encodeURIComponent(action.execution_id)+'/output');
            output.textContent=value.text || '(No output retained)';output.hidden=false;
            note.textContent=value.retained_bytes+' bytes retained. '+(value.capture_limit_reached ?
              'The capture limit was reached; later output was not retained.' :
              value.capture_size_known ? 'The retained output is shown without preview clipping.' :
              'This older record does not establish whether all original output was captured.');
          } catch(error) {note.textContent=error.message;}
          finally {button.disabled=false;}
        });
        detail.appendChild(button);detail.appendChild(note);detail.appendChild(output);
      }
      item.appendChild(detail);list.appendChild(item);
    }
    root.appendChild(list);
    for(const check of data.checks || []) {
      const detail=make('details');detail.appendChild(make('summary','Independent test run: '+check.status));
      const body=make('div');timeline(body,check,{raw:false});detail.appendChild(body);root.appendChild(detail);
    }
    if(options.raw !== false && data.job_id) {
      const detail=make('details');detail.appendChild(make('summary','Advanced: raw ledger JSON'));
      detail.appendChild(make('p','The actor "phone" is the legacy browser controller. "Activity recorded" is bookkeeping, not test approval. GPT baseline estimates are hypothetical comparisons, separate from measured model usage.'));
      const button=make('button','Load raw ledger');button.type='button';const output=make('pre');
      button.addEventListener('click',async()=>{
        button.disabled=true;
        try {output.textContent=JSON.stringify(await getJSON('/api/jobs/'+encodeURIComponent(data.job_id)+'/events'),null,2);}
        catch(error){output.textContent=error.message;}
        finally{button.disabled=false;}
      });detail.appendChild(button);detail.appendChild(output);root.appendChild(detail);
    }
    parent.appendChild(root);
  }
  function sessions(parent, data, actions) {
    parent.replaceChildren();
    const make = (tag, text) => { const node=document.createElement(tag); node.textContent=text || ''; return node; };
    for (const workspace of data.workspaces || []) {
      const panel=make('details'); panel.className='workspace-result'; panel.open=true;
      const git=workspace.git_workspace;
      panel.appendChild(make('summary','Workspace: '+workspace.workspace_id));
      for (const line of ['Source: '+git.repository, 'Worktree: '+git.worktree,
        'Current attempt: '+git.run_id+' · '+git.state,
        'Ledger: '+workspace.ledger, 'Trace files: '+workspace.trace_directory]) panel.appendChild(make('p',line));
      const container=workspace.container;
      panel.appendChild(make('p',container ? 'Container: '+(container.name || container.id || 'unknown')+' · '+container.state+(container.activity === 'IDLE' ? ' · idle keeper (no agent command running)' : '') : 'Container: none retained'));
      const next=make('button','Continue this workspace'); next.type='button'; next.className='workspace-session-control';
      next.addEventListener('click',()=>{if(!next.disabled) actions.continue(workspace);}); panel.appendChild(next);
      if(actions.startLoop){
        const loop=make('button','Loop until approved…');loop.type='button';loop.className='workspace-session-control';
        loop.addEventListener('click',()=>{if(!loop.disabled)actions.startLoop(workspace);});panel.appendChild(loop);
      }
      if (container?.id && !['removed','unavailable'].includes(container.state)) {
        const stop=make('button','Stop container'); stop.type='button';stop.className='workspace-session-control';
        stop.addEventListener('click',()=>{if(!stop.disabled && window.confirm('Stop this workspace container? Container-only state and background jobs will end; project files remain.')) actions.stop(workspace);});panel.appendChild(stop);
      }
      for (const attempt of workspace.attempts) {
        const details=make('details');
        details.open=attempt === workspace.attempts[0] && ['failed','interrupted'].includes(attempt.status);
        details.appendChild(make('summary',(attempt.kind || 'coding')+' · '+attempt.status+' · '+(attempt.model || '')+' · '+(attempt.run_id || 'run not created')));
        details.appendChild(make('p','Browser job: '+attempt.job_directory));
        if(attempt.diagnostics) details.appendChild(make('p',attempt.diagnostics.summary));
        if(attempt.error) details.appendChild(make('pre',attempt.error));
        for(const failure of attempt.failure_details || []) details.appendChild(make('pre',
          (failure.tool || 'tool')+' '+(failure.path || '')+' · exit '+failure.exit_code+'\n'+failure.cause));
        if(attempt.run_id){
          const trace=make('button','View this attempt timeline');trace.type='button';
          const output=make('div');output.hidden=true;
          trace.addEventListener('click',async()=>{
            try{trace.disabled=true;const value=await getJSON('/api/jobs/'+encodeURIComponent(attempt.job_id)+'/diagnostics');timeline(output,value);output.hidden=false;}
            catch(error){actions.error(error.message);}
            finally{trace.disabled=false;}
          });details.appendChild(trace);details.appendChild(output);
        }
        panel.appendChild(details);
      }
      parent.appendChild(panel);
    }
  }
  window.WorkspaceResults = {append: append, sessions, timeline};
})();

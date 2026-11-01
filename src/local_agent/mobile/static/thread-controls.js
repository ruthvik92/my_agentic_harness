window.ThreadControls = {
  catalogOptions(select, models, selected) {
    const options = [];
    for (const model of models) {
      const option = document.createElement('option');
      option.textContent = model.model + ' · ' + model.provider + ' · ' + (model.capabilities.join(', ') || 'unknown capabilities') + (model.label ? ' · ' + model.label : '') + (model.reason ? ' · ' + model.reason : '');
      option.value = model.id;
      option.disabled = !model.selectable;
      options.push(option);
    }
    select.replaceChildren(...options);
    select.value = models.find(m=>m.id === selected && m.selectable)?.id || models.find(m=>m.selectable)?.id || '';
  },
  breakdown(element, thread) {
    if (!thread) {
      element.textContent = 'No thread selected. Choose models above; actual stage usage appears after each answer.';
      return;
    }
    const messages = thread.messages.filter(m=>m.role === 'assistant');
    const lines = [];
    if (thread.pending_stage) lines.push(thread.pending_stage.status + ': ' + thread.pending_stage.kind + ' · ' + thread.pending_stage.model);
    for (const [label,kind] of [['VLM (image reading)','vision'],['Chat','answer'],['Netlist inference','netlist'],['OpenAI paid review','review']]) {
      const used = [...messages].reverse().find(m=>kind === 'vision'
        ? (m.kind || 'answer') === 'answer' && m.has_image : (kind === 'review' ? ['review','workspace_review'].includes(m.kind) : (m.kind || 'answer') === kind));
      lines.push(label + ': ' + (used ? used.model + ' (' + (used.provider || 'recorded') + ')' : 'not run'));
    }
    lines.push('Memory: latest 3 exchanges / 16,000 characters; ' + Math.floor(thread.messages.length/2) + ' exchanges saved.');
    lines.push('Feedback: ' + (thread.feedback || 'none') + ' · All circuit outputs remain unverified.');
    element.textContent = lines.join('\n');
  },
  renderUsage(element, report, label) {
    const t = report.totals;
    const number = value => value === null || value === undefined ? 'unavailable' : value.toLocaleString();
    const partial = t.unknown_openai_requests || report.unavailable_jobs ? ' (partial; unknown API usage)' : '';
    element.textContent = [label,
      'Measured OpenAI: ' + number(t.measured_openai_input) + ' input + ' + number(t.measured_openai_output) + ' output; total ' + number(t.measured_openai_total) + partial,
      'Reported reasoning: ' + number(t.measured_openai_reasoning) + ' tokens (already included in output)' + (t.unknown_openai_reasoning ? '; breakdown unavailable for ' + t.unknown_openai_reasoning + ' requests' : ''),
      'Measured local: ' + number(t.measured_local_total) + ' native tokens' + (t.unknown_local_usage || report.unavailable_jobs ? ' (partial)' : ''),
      'Estimated all-OpenAI baseline: ' + number(t.estimated_all_openai_baseline),
      'Paid review overhead: ' + number(t.measured_review_tokens),
      'Estimated net tokens saved: ' + number(t.estimated_net_saved_tokens) + (t.estimated_net_saved_percent === null ? '' : ' (' + t.estimated_net_saved_percent.toFixed(1) + '%)'),
      'Baseline model: ' + (report.baseline_models.join(', ') || 'no requests yet'),
      report.assumptions,
      ...(report.unavailable_jobs ? ['Usage unavailable for ' + report.unavailable_jobs + ' saved attempts; measured counts exclude them.'] : [])].join('\n');
  },
  renderMeter(local, verifier, report, scope = '') {
    const t = report?.totals || {};
    const n = value => (value === undefined || value === null) ? (report ? '?' : '0') : value.toLocaleString();
    const prefix = scope ? scope + ' · ' : '';
    local.textContent = prefix + 'Local models' + (t.unknown_local_usage || report?.unavailable_jobs ? ' · partial' : '') + '\n' + n(t.measured_local_input) + ' in + ' + n(t.measured_local_output) + ' out\n' + n(t.measured_local_total) + ' tokens';
    verifier.textContent = prefix + 'OpenAI / verifier' + (t.unknown_openai_requests || report?.unavailable_jobs ? ' · partial' : '') + '\n' + n(t.measured_openai_input) + ' in + ' + n(t.measured_openai_output) + ' out\n' + n(t.measured_openai_total) + ' total · Review: ' + n(t.measured_review_tokens) + ' tokens';
  },
  reviewState(verifier, thread, state) {
    const hasAnswer = thread?.messages?.some(m => m.role === 'assistant');
    const reason = !state.paired ? 'Pair with the server first.'
      : !verifier?.enabled ? (verifier?.reason || 'Reviewer catalog is loading.')
      : state.busy ? 'Wait for the current operation to finish.'
      : !hasAnswer ? 'Ask a question or open a saved chat with an answer first.'
      : !state.selected ? 'Select an available reviewer model.' : '';
    return {enabled: !reason, note: (reason || 'Press Review to send the saved image, recent chat and task metadata to OpenAI. This reviews conversation only. Use Review workspace on a coding result for file inspection and tests.') + ' API billing applies only when you request a review.'};
  },
  historyBusy(list, disabled) {
    list.dataset.busy = String(disabled);
    for (const button of list.querySelectorAll('button')) button.disabled = disabled;
  },
  markThread(list, current) {
    for (const button of list.querySelectorAll('button')) {
      if (button.dataset.threadId === current) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
  },
  renderThreads(list, threads, current, onSelect, disabled = false) {
    const items = [];
    for (const thread of threads) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = thread.title;
      button.dataset.threadId = thread.thread_id;
      button.addEventListener('click', () => {
        if (!button.disabled && list.dataset.busy !== 'true') onSelect(thread.thread_id);
      });
      items.push(button);
    }
    if (!items.length) {
      const empty = document.createElement('p');
      empty.textContent = 'No saved chats yet.';
      items.push(empty);
    }
    list.replaceChildren(...items);
    this.markThread(list, current);
    this.historyBusy(list, disabled);
  }
};

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
        ? (m.kind || 'answer') === 'answer' && m.has_image : (m.kind || 'answer') === kind);
      lines.push(label + ': ' + (used ? used.model + ' (' + (used.provider || 'recorded') + ')' : 'not run'));
    }
    lines.push('Memory: latest 3 exchanges / 16,000 characters; ' + Math.floor(thread.messages.length/2) + ' exchanges saved.');
    lines.push('Feedback: ' + (thread.feedback || 'none') + ' · All circuit outputs remain unverified.');
    element.textContent = lines.join('\n');
  },
  renderUsage(element, report, label) {
    const t = report.totals;
    const number = value => value === null || value === undefined ? 'unavailable' : value.toLocaleString();
    const partial = t.unknown_openai_requests ? ' (partial; unknown API usage)' : '';
    element.textContent = [label,
      'Measured OpenAI: ' + number(t.measured_openai_input) + ' input + ' + number(t.measured_openai_output) + ' output; total ' + number(t.measured_openai_total) + partial,
      'Measured local: ' + number(t.measured_local_total) + ' native tokens' + (t.unknown_local_usage ? ' (partial)' : ''),
      'Estimated all-OpenAI baseline: ' + number(t.estimated_all_openai_baseline),
      'Paid review overhead: ' + number(t.measured_review_tokens),
      'Estimated net tokens saved: ' + number(t.estimated_net_saved_tokens) + (t.estimated_net_saved_percent === null ? '' : ' (' + t.estimated_net_saved_percent.toFixed(1) + '%)'),
      'Baseline model: ' + (report.baseline_models.join(', ') || 'no requests yet'),
      report.assumptions].join('\n');
  },
  renderThreads(select, threads, current) {
    const options = [];
    const fresh = document.createElement('option'); fresh.value = ''; fresh.textContent = 'New chat'; options.push(fresh);
    for (const thread of threads) {
      const option = document.createElement('option');
      option.textContent = thread.title;
      option.value = thread.thread_id;
      options.push(option);
    }
    select.replaceChildren(...options);
    select.value = current;
  }
};

(function () {
  'use strict';
  let api = null, showError = null, onChange = null, bound = false;
  let profiles = [], selected = null, editorName = null;
  let loadedName = null, loadedHash = null, creating = false, requestActive = false, jobDisabled = false;
  const el = (id) => document.getElementById(id);
  const isInt = (v) => Number.isInteger(v);
  const strictInt = (s) => /^\d+$/.test(String(s).trim()) ? parseInt(String(s).trim(), 10) : NaN;

  function setDetail(text) { el('config-detail').textContent = text; }
  function setStatus(text) { el('config-status').textContent = text; }
  function applyDisabled() {
    const d = requestActive || jobDisabled;
    ['config-edit', 'config-cancel', 'config-select', 'config-editor-file', 'config-name', 'config-content', 'config-new',
     'config-clone', 'config-load', 'config-validate', 'config-save', 'config-refresh',
     'workspace-input', 'pdf-input', 'page-input', 'dpi-input', 'context-page-input',
     'region-input', 'model-select', 'run-limit-minutes', 'n-last-chats', 'execution-mode', 'task-mode', 'base-ref',
     'continue-workspace', 'working-directory'].forEach((id) => { const n = el(id); if (n) n.disabled = d; });
  }
  function fillSelect(node, names, current) {
    node.textContent = '';
    names.forEach((n) => node.appendChild(new Option(n, n)));
    if (names.includes(current)) node.value = current;
  }
  function updateVisibility() {
    const mode = selected ? selected.mode : '';
    el('workspace-fields').hidden = mode === 'chat';
    el('circuit-fields').hidden = mode !== 'circuit';
    el('coding-fields').hidden = mode !== 'coding';
    el('task-history-fields').hidden = mode !== 'coding';
    const continuing = el('task-mode').value === 'continue';
    el('new-task-fields').hidden = continuing;
    el('continue-task-fields').hidden = !continuing;
    el('image-fields').hidden = mode === 'circuit';
    const legacyCircuit = mode === 'chat';
    ['legacy-circuit-controls', 'netlist-btn'].forEach(id => {
      el(id).hidden = !legacyCircuit;
    });
    el('execution-fields').hidden = !selected || !Array.isArray(selected.tools) || selected.tools.length === 0;
  }
  function detailText(p) {
    if (!p) return 'No valid agent profile available.';
    return [p.model || 'No model configured', p.mode || '',
      p.error ? 'Error: ' + p.error : ''].filter(Boolean).join(' · ');
  }
  function selectRun(name) {
    selected = profiles.find((x) => x.name === name && x.kind === 'agent' && x.valid) || null;
    el('config-select').value = selected ? selected.name : '';
    setDetail(detailText(selected));
    const runtime=el('run-limit-minutes');
    if(runtime){runtime.value='';runtime.placeholder='Profile default: '+((selected?.limits?.run_timeout_seconds || 1200)/60)+' minutes';}

    updateVisibility();
    const execution = el('execution-mode');
    execution.value = '';
    execution.options[0].textContent = 'Use profile default (' +
      ((selected && selected.execution && selected.execution.execution_mode_default) || 'ephemeral') + ')';
    if (selected && !el('workspace-input').value && window.__allowedRoots && window.__allowedRoots.length)
      el('workspace-input').value = window.__allowedRoots[0];
  }
  function selectEditor(name) { editorName = name; el('config-editor-file').value = name || ''; }
  function resetModelSelect() {
    const node = el('model-select');
    node.textContent = '';
    node.appendChild(new Option('Use config model: ' + (selected ? selected.model || '' : ''), ''));
    node.value = '';
  }
  async function guarded(fn) {
    if (requestActive || jobDisabled) return;
    requestActive = true; applyDisabled();
    try { await fn(); } catch (e) { showError(String((e && e.message) || e)); }
    finally { requestActive = false; applyDisabled(); }
  }
  function safeStem(name) {
    let stem = String(name).replace(/\.[^.]*$/, '').replace(/[^A-Za-z0-9_-]/g, '_');
    if (!/^[A-Za-z0-9]/.test(stem)) stem = 'profile' + stem;
    if (!/^[A-Za-z0-9]/.test(stem)) stem = 'profile';
    return stem.slice(0, 64);
  }
  function uniqueName(base) {
    const dot = base.lastIndexOf('.');
    const stem = dot > 0 ? base.slice(0, dot) : base;
    let suffix = dot > 0 ? base.slice(dot) : '';
    if (!/^\.(yaml|yml|json)$/i.test(suffix)) suffix = '.yaml';
    const taken = new Set(profiles.map((p) => p.name));
    let i = 1;
    for (;;) {
      const counter = i === 1 ? '_copy' : '_copy' + i;
      const maxStem = 64 - counter.length;
      let s = safeStem(stem);
      if (s.length > maxStem) s = s.slice(0, maxStem);
      const candidate = s + counter + suffix;
      if (!taken.has(candidate)) return candidate;
      i += 1;
    }
  }
  function showEditor(visible) {
    el('config-editor-panel').hidden = !visible;
    el('config-edit').setAttribute('aria-expanded', String(visible));
    if (visible) el('config-content').focus();
  }
  function closeEditor() {
    showEditor(false);
    el('config-content').value = '';
    el('config-name').value = '';
    el('config-name-fields').hidden = true;
    loadedName = null; loadedHash = null; creating = false;
    setStatus('');
    el('config-edit').focus();
  }
  function editorTarget() { return creating ? el('config-name').value : loadedName; }
  async function loadEditorFile(name) {
    const res = await api('/configs/' + encodeURIComponent(name));
    el('config-name').value = res.name;
    el('config-content').value = res.content;
    loadedName = res.name; loadedHash = res.hash; creating = false;
    selectEditor(res.name);
    el('config-name-fields').hidden = true;
    el('config-editing-file').textContent = res.name;
    el('config-editor-title').textContent = 'Edit profile';
    showEditor(true);
    const md = res.metadata || {};
    setStatus('Loaded ' + res.name + (md.valid ? '' : ' (invalid)') + (md.error ? ': ' + md.error : ''));
  }
  function bind() {
    if (bound) return; bound = true;
    el('config-edit').addEventListener('click', () => guarded(async () => {
      if (!selected) throw new Error('Select an agent profile first');
      await loadEditorFile(selected.name);
    }));
    el('config-cancel').addEventListener('click', closeEditor);
    el('task-mode').addEventListener('change', updateVisibility);
    el('config-select').addEventListener('change', () => {
      selectRun(el('config-select').value);
      resetModelSelect();
      if (onChange) onChange();
    });
    el('config-editor-file').addEventListener('change', () => selectEditor(el('config-editor-file').value));
    el('config-load').addEventListener('click', () => guarded(async () => {
      if (!editorName) throw new Error('No editor file selected');
      await loadEditorFile(editorName);
    }));
    el('config-new').addEventListener('click', () => {
      creating = true; el('config-name-fields').hidden = false;
      el('config-editing-file').textContent = 'New profile (unsaved)';
      el('config-editor-title').textContent = 'New profile';
      showEditor(true);
      el('config-name').value = ''; el('config-content').value = '';
      loadedName = null; loadedHash = null; setStatus('New profile (unsaved).');
    });
    el('config-clone').addEventListener('click', () => guarded(async () => {
      if (!loadedName && !creating && editorName) await loadEditorFile(editorName);
      el('config-name').value = uniqueName(el('config-name').value || editorName || 'profile.yaml');
      creating = true; el('config-name-fields').hidden = false;
      el('config-editor-title').textContent = 'Save as new profile';
      setStatus('Choose a new filename, then click Save.');
      el('config-name').focus();
    }));
    el('config-validate').addEventListener('click', () => guarded(async () => {
      const res = await api('/configs/validate', { name: editorTarget(), content: el('config-content').value });
      if (res && res.valid) setStatus('Validation OK: ' + (res.message || res.name || ''));
      else setStatus('Validation failed: ' + ((res && (res.error || res.message)) || 'invalid'));
    }));
    el('config-save').addEventListener('click', () => guarded(async () => {
      const name = editorTarget(), content = el('config-content').value;
      if (!name) throw new Error('Enter a profile filename');
      const body = { name, content };
      if (!creating && loadedName && loadedHash && loadedName === name) body.expected_hash = loadedHash;
      const res = await api('/configs/save', body);
      loadedName = name; loadedHash = (res && res.hash) || loadedHash;
      selected = null; editorName = name;
      await refresh(name, window.__allowedRoots || []);
      closeEditor();
      if (res && res.message) setDetail(res.message);
    }));
    el('config-refresh').addEventListener('click', () => guarded(async () => {
      await refresh(el('config-select').value, window.__allowedRoots || []);
    }));
  }
  async function refresh(defaultName, allowedRoots) {
    window.__allowedRoots = allowedRoots || [];
    const data = await api('/configs');
    profiles = (data && data.profiles) || [];
    const runNames = profiles.filter((p) => p.kind === 'agent' && p.valid).map((p) => p.name);
    fillSelect(el('config-select'), runNames, selected ? selected.name : '');
    const editorNames = profiles.map((p) => p.name);
    fillSelect(el('config-editor-file'), editorNames, editorName);
    if (editorName && !editorNames.includes(editorName)) selectEditor(editorNames[0] || '');
    else if (!editorName) selectEditor(editorNames[0] || '');
    const prev = selected ? selected.name : null;
    const target = (prev && runNames.includes(prev)) ? prev
      : (defaultName && runNames.includes(defaultName)) ? defaultName : (runNames[0] || null);
    selectRun(target);
    if (!target) {
      setStatus('No valid agent profile available.');
      resetModelSelect();
      if (onChange) onChange();
      return;
    }
    setDetail(detailText(selected));
    const runtime=el('run-limit-minutes');
    if(runtime){runtime.value='';runtime.placeholder='Profile default: '+((selected?.limits?.run_timeout_seconds || 1200)/60)+' minutes';}

    updateVisibility();
    if (!el('workspace-input').value && allowedRoots && allowedRoots.length)
      el('workspace-input').value = allowedRoots[0];
    resetModelSelect();
    if (onChange) onChange();
  }
  function models(entries) {
    const node = el('model-select');
    const prevValue = node.value;
    node.textContent = '';
    node.appendChild(new Option('Use config model: ' + (selected ? selected.model || '' : ''), ''));
    const prov = selected ? selected.provider : null;
    (entries || []).forEach((e) => {
      if (!e.selectable || prov === null || e.provider !== prov) return;
      node.appendChild(new Option(e.model, e.id));
    });
    node.value = (prevValue && (entries || []).some((e) => e.selectable && e.id === prevValue)) ? prevValue : '';
  }
  function historyLimit() {
    const value = el('n-last-chats').value;
    const count = value === '' ? 8 : strictInt(value);
    if (!Number.isInteger(count) || count < 1 || count > 100)
      throw new Error('Task history must be 1 to 100 whole chats');
    return count;
  }
  function requestFields() {
    if (!selected) throw new Error('No valid profile selected');
    const mode = selected.mode;
    const out = { profile_name: selected.name };
    const runtime=el('run-limit-minutes');
    if(runtime && runtime.value!=='') {
      const minutes=strictInt(runtime.value);
      if(!Number.isInteger(minutes) || minutes<1 || minutes>1440)throw new Error('Agent run limit must be 1 to 1440 whole minutes');
      out.run_limit_minutes=minutes;
    }
    const execution = el('execution-mode').value;
    if (!el('execution-fields').hidden && execution) {
      if (!['ephemeral', 'persistent'].includes(execution)) throw new Error('Invalid execution mode');
      out.execution_mode = execution;
    }
    const ws = el('workspace-input').value.trim();
    if (mode === 'coding' || mode === 'circuit') {
      if (!ws) throw new Error('workspace is required');
      out.workspace = ws;
    }
    if (mode === 'coding') {
      out.n_last_chats = historyLimit();
      if (el('task-mode').value === 'continue') {
        const id = el('continue-workspace').value.trim();
        if (!/^ws_[a-f0-9]{32}$/.test(id)) throw new Error('Enter the previous ws_ workspace ID');
        out.continue_workspace_id = id;
      } else {
        const ref = el('base-ref').value.trim();
        if (ref) out.base_ref = ref;
      }
      const dir = el('working-directory').value.trim();
      if (dir) out.working_directory = dir;
    }
    if (mode === 'circuit') {
      const pdf = el('pdf-input').value.trim();
      if (!pdf) throw new Error('pdf is required');
      out.pdf = pdf;
      const page = strictInt(el('page-input').value);
      if (!isInt(page) || page <= 0) throw new Error('page must be a positive integer');
      out.page = page;
      const dpiRaw = el('dpi-input').value.trim();
      const dpi = dpiRaw === '' ? 300 : strictInt(dpiRaw);
      if (!isInt(dpi) || dpi < 72 || dpi > 1200) throw new Error('dpi must be an integer 72..1200');
      out.dpi = dpi;
      const cpRaw = el('context-page-input').value.trim();
      if (cpRaw !== '') {
        const cp = strictInt(cpRaw);
        if (!isInt(cp) || cp <= 0) throw new Error('context_page must be a positive integer');
        out.context_page = cp;
      }
      const regionRaw = el('region-input').value.trim();
      if (regionRaw !== '') {
        const parts = regionRaw.split(',').map((s) => s.trim());
        if (parts.length !== 4) throw new Error('region must have 4 values');
        if (parts.some((s) => s === '')) throw new Error('region values must be finite numbers');
        const r = parts.map((s) => Number(s));
        if (r.some((v) => !Number.isFinite(v))) throw new Error('region values must be finite numbers');
        const [left, top, right, bottom] = r;
        if (!(0 <= left && left < right && right <= 1)) throw new Error('region left/right invalid');
        if (!(0 <= top && top < bottom && bottom <= 1)) throw new Error('region top/bottom invalid');
        out.region = r;
      }
    }
    return out;
  }
  window.ConfigControls = {
    init(a, se, oc) { api = a; showError = se || (() => {}); onChange = oc || null; bind(); },
    refresh, busy: (d) => { jobDisabled = !!d; applyDisabled(); },
    requestFields, mode: () => (selected ? selected.mode : null), models,
    continueTask(result) {
      if (jobDisabled || requestActive) return;
      const coding = profiles.find(p => p.valid && p.mode === 'coding' && p.name === result.profile_name) ||
        (selected && selected.mode === 'coding' && selected) ||
        profiles.find(p => p.valid && p.kind === 'agent' && p.mode === 'coding');
      if (!coding) { showError('Select or create a coding profile to continue this task.'); return; }
      if (!selected || selected.name !== coding.name) {
        selectRun(coding.name); resetModelSelect(); if (onChange) onChange();
      }
      const git = result.git_workspace;
      el('workspace-input').value = git.repository;
      el('task-mode').value = 'continue';
      el('continue-workspace').value = git.workspace_id || git.branch.replace(/^agent\//, '');
      el('working-directory').value = result.working_directory || git.working_directory || '';
      if (['persistent','ephemeral'].includes(result.execution_mode)) el('execution-mode').value=result.execution_mode;
      updateVisibility();
      el('continue-workspace').focus();
    }
  };
})();

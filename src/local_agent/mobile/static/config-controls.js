(function () {
  'use strict';
  let api = null, showError = null, onChange = null, bound = false;
  let profiles = [], selected = null, editorName = null;
  let loadedName = null, loadedHash = null, requestActive = false, jobDisabled = false;
  const el = (id) => document.getElementById(id);
  const isInt = (v) => Number.isInteger(v);
  const strictInt = (s) => /^\d+$/.test(String(s).trim()) ? parseInt(String(s).trim(), 10) : NaN;

  function setDetail(text) { el('config-detail').textContent = text; }
  function setStatus(text) { el('config-status').textContent = text; }
  function applyDisabled() {
    const d = requestActive || jobDisabled;
    ['config-select', 'config-editor-file', 'config-name', 'config-content', 'config-new',
     'config-clone', 'config-load', 'config-validate', 'config-save', 'config-refresh',
     'workspace-input', 'pdf-input', 'page-input', 'dpi-input', 'context-page-input',
     'region-input', 'model-select'].forEach((id) => { const n = el(id); if (n) n.disabled = d; });
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
    el('image-fields').hidden = mode === 'circuit';
  }
  function detailText(p) {
    if (!p) return 'No valid agent profile available.';
    const parts = ['kind: ' + p.kind, 'valid: ' + (p.valid ? 'yes' : 'no'), 'mode: ' + (p.mode || '-'),
      'provider: ' + (p.provider || '-'), 'model: ' + (p.model || '-'),
      'instructions: ' + (p.instructions_version || '-'), 'tools: ' + (p.tools || '-')];
    if (p.error) parts.push('error: ' + p.error);
    return parts.join(' | ');
  }
  function selectRun(name) {
    selected = profiles.find((x) => x.name === name && x.kind === 'agent' && x.valid) || null;
    el('config-select').value = selected ? selected.name : '';
    setDetail(detailText(selected));
    updateVisibility();
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
  async function loadEditorFile(name) {
    const res = await api('/configs/' + encodeURIComponent(name));
    el('config-name').value = res.name;
    el('config-content').value = res.content;
    loadedName = res.name; loadedHash = res.hash;
    const md = res.metadata || {};
    setStatus('Loaded ' + res.name + (md.valid ? '' : ' (invalid)') + (md.error ? ': ' + md.error : ''));
  }
  function bind() {
    if (bound) return; bound = true;
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
      el('config-name').value = ''; el('config-content').value = '';
      loadedName = null; loadedHash = null; setStatus('New profile (unsaved).');
    });
    el('config-clone').addEventListener('click', () => guarded(async () => {
      if (editorName && loadedName !== editorName) await loadEditorFile(editorName);
      el('config-name').value = uniqueName(el('config-name').value || editorName || 'profile.yaml');
      loadedName = null; loadedHash = null; setStatus('Cloned (unsaved).');
    }));
    el('config-validate').addEventListener('click', () => guarded(async () => {
      const res = await api('/configs/validate', { name: el('config-name').value, content: el('config-content').value });
      if (res && res.valid) setStatus('Validation OK: ' + (res.message || res.name || ''));
      else setStatus('Validation failed: ' + ((res && (res.error || res.message)) || 'invalid'));
    }));
    el('config-save').addEventListener('click', () => guarded(async () => {
      const name = el('config-name').value, content = el('config-content').value;
      const body = { name, content };
      if (loadedName && loadedHash && loadedName === name) body.expected_hash = loadedHash;
      const res = await api('/configs/save', body);
      loadedName = name; loadedHash = (res && res.hash) || loadedHash;
      selected = null; editorName = name;
      await refresh(name, window.__allowedRoots || []);
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
  function requestFields() {
    if (!selected) throw new Error('No valid profile selected');
    const mode = selected.mode;
    const out = { profile_name: selected.name };
    const ws = el('workspace-input').value.trim();
    if (mode === 'coding' || mode === 'circuit') {
      if (!ws) throw new Error('workspace is required');
      out.workspace = ws;
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
    requestFields, mode: () => (selected ? selected.mode : null), models
  };
})();

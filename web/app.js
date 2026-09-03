// app.js — boundless SPA. No frameworks. Fetch-only.
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let currentUpload = null;

async function api(p, opts={}) {
  const r = await fetch(p, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

async function refresh() {
  try {
    const data = await api('/api/status');
    $('#last-updated').textContent = `Last: ${new Date().toLocaleTimeString()}`;
    $('#health').textContent = 'healthy';
  } catch (e) {
    $('#health').textContent = 'unhealthy';
    console.error(e);
  }
  try {
    const ps = await api('/api/processing');
    $('#c-inbox').textContent = ps.inbox.length;
    $('#c-active').textContent = ps.active.length;
    $('#c-done').textContent = ps.done.length;
    $('#c-failed').textContent = ps.failed.length;
    renderLane('inbox', ps.inbox);
    renderLane('active', ps.active);
    renderLane('done', ps.done);
    renderLane('failed', ps.failed);
  } catch (e) {
    console.error(e);
  }
  try {
    const {profiles} = await api('/api/profiles');
    $('#profile-count').textContent = `(${profiles.length})`;
    $('#profiles').innerHTML = profiles.map(profileCard).join('') || '<p class="muted">No profiles yet. Upload or drop in processing/inbox/.</p>';
  } catch (e) { console.error(e); }
}

function renderLane(lane, items) {
  $(`#c-${lane}`).textContent = items.length;
  const ul = $(`#lane-${lane}`);
  if (items.length === 0) {
    ul.innerHTML = `<li class="muted">No items in ${lane}</li>`;
  } else {
    ul.innerHTML = items.map(it => {
      const size = `${(it.size/1024/1024).toFixed(1)}MB`;
      return `<li><code>${esc(it.name)}</code> <span class="muted">${size}</span>` +
        (lane === 'inbox' ? ` <button onclick="processInbox('${esc(it.name)}')">Process</button>` : '') +
        `</li>`;
    }).join('');
  }
}

async function processInbox(name) {
  const s = await api('/api/settings');
  const method = s.default_split_method || 'size';
  const r = await api(`/api/process/${encodeURIComponent(name)}?method=${method}&max_size_mb=${s.default_max_size_mb}`, {method:'POST'});
  alert(`Done: ${r.log.join('\n')}`);
  refresh();
}

function profileCard(p) {
  if (p.error) return `<div class="card"><h3>${esc(p.file)}</h3><div class="meta">${esc(p.error)}</div></div>`;
  const origin = p.origin || {};
  const nr = p.nr_status || '';
  const cls = nr.includes('EXCEEDS') ? 'err' : 'ok';
  return `<div class="card">
    <h3>${esc(p.title||p.file)}</h3>
    <div class="meta">${esc(p.creator||'')} · ${esc(p.publisher||'Unknown')}</div>
    <div><span class="badge ${cls}">${esc(nr||'profile')}</span> <span class="muted">${p.size_mb} MB</span></div>
    <div class="origin"><strong>${esc(origin.publisher||'Unknown')}</strong> · ${esc(origin.pipeline||'pipeline?')}<br/><small>${esc(origin.platform||'')}</small></div>
    <div class="strategy">Strategy: ${esc(p.split_strategy||'-')}</div>
    <button class="ghost" onclick="delProfile('${esc(p.file)}')">Delete</button>
  </div>`;
}

function esc(s) { return String(s||'').replace(/[<>&"']/g, c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c])); }

async function delProfile(file) {
  if (!confirm(`Delete ${file}?`)) return;
  await api(`/api/profiles/${file}`, {method:'DELETE'});
  refresh();
}

$('#drop').addEventListener('dragover', e => { e.preventDefault(); $('#drop').classList.add('hover'); });
$('#drop').addEventListener('dragleave', () => $('#drop').classList.remove('hover'));
$('#drop').addEventListener('drop', async e => {
  e.preventDefault();
  $('#drop').classList.remove('hover');
  await doUpload([...e.dataTransfer.files]);
});
$('#files').addEventListener('change', async e => {
  await doUpload([...e.target.files]);
  e.target.value = '';
});

async function doUpload(files) {
  if (!files.length) return;
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  $('#upload-progress').textContent = `Uploading ${files.length} file(s)…`;
  try {
    const r = await api('/api/upload', {method:'POST', body: fd});
    $('#upload-progress').textContent = `Uploaded ${r.count} file(s); profiles auto-created.`;
    renderUploads(r.uploads);
    refresh();
  } catch (e) {
    $('#upload-progress').textContent = `Error: ${e.message}`;
  }
}

function renderUploads(uploads) {
  const list = $('#upload-list');
  list.innerHTML = uploads.map(u => {
    const p = u.profile || {};
    return `<div class="card">
      <h3>${esc(u.filename)}</h3>
      <div class="meta">${u.size_mb} MB · ${esc(p.origin?.publisher||'')}</div>
      <div><span class="badge ${p.nr_status?.includes('EXCEEDS')?'err':'ok'}">${esc(p.nr_status||'ok')}</span></div>
      <button onclick="selectUpload('${esc(u.upload_id)}')">Select for split</button>
    </div>`;
  }).join('');
  $('#uploaded').hidden = false;
  if (uploads.length) selectUpload(uploads[0].upload_id);
}

function selectUpload(uid) {
  currentUpload = uid;
  $('#split-panel').hidden = false;
  $('#split-result').innerHTML = '';
}

$('#split-toc-btn').addEventListener('click', async () => {
  if (!currentUpload) return alert('Upload first');
  $('#split-toc-btn').disabled = true;
  $('#split-result').innerHTML = '<p class="muted">Splitting by TOC (preserves publisher assets)...</p>';
  try {
    const r = await api(`/api/split-toc/${encodeURIComponent(currentUpload)}`, {method:'POST'});
    const list = r.sections.map(s => `<li><a href="/api/outputs/${encodeURIComponent(r.output_dir.split('/').pop())}/${encodeURIComponent(s)}">${esc(s)}</a></li>`).join('');
    $('#split-result').innerHTML = `<p><strong>${r.count} chunks</strong> from <code>${esc(r.source)}</code> → <code>${esc(r.output_dir)}</code></p><ul class="chunk-list">${list}</ul>`;
    refresh();
  } catch (e) {
    $('#split-result').innerHTML = `<p style="color:var(--err)">Error: ${esc(e.message)}</p>`;
  }
  $('#split-toc-btn').disabled = false;
});

$('#split-btn').addEventListener('click', async () => {
  if (!currentUpload) return alert('Upload first');
  const max = parseInt($('#max-mb').value, 10) || 50;
  $('#split-btn').disabled = true;
  $('#split-result').innerHTML = '<p class="muted">Splitting...</p>';
  try {
    const r = await api(`/api/split/${encodeURIComponent(currentUpload)}?max_size_mb=${max}`, {method:'POST'});
    const chunks = (r.chunks||[]).map(c => `<li>${esc(c.title||c.slug)} — ${(c.size/1024/1024).toFixed(2)} MB</li>`).join('');
    $('#split-result').innerHTML = `
      <p><strong>${r.chunk_count} chunks</strong> from <code>${esc(r.source)}</code> → <code>${esc(r.output_dir)}</code></p>
      <ul class="chunk-list">${chunks}</ul>`;
    refresh();
  } catch (e) {
    $('#split-result').innerHTML = `<p style="color:var(--err)">Error: ${esc(e.message)}</p>`;
  }
  $('#split-btn').disabled = false;
});

$('#refresh').addEventListener('click', refresh);

$('#scan-btn').addEventListener('click', async () => {
  const d = prompt('Directory to scan (no /mnt):', '~/Downloads');
  if (!d) return;
  try {
    const r = await api(`/api/scan?directory=${encodeURIComponent(d)}`, {method:'POST'});
    alert(`Scanned ${r.scanned}, created ${r.profiles_created} profiles`);
    refresh();
  } catch (e) { alert(e.message); }
});

async function loadEdgeCases() {
  try {
    const r = await api('/api/edge-cases');
    $('#ec-epub').textContent = (r.epub||[]).join('\n');
    $('#ec-pdf').textContent = (r.pdf||[]).join('\n');
    $('#ec-docx').textContent = (r.docx||[]).join('\n');
    $('#ec-a11y').textContent = (r.a11y||[]).join('\n');
  } catch (e) { console.error(e); }
}

refresh();
loadEdgeCases();
setInterval(refresh, 5000);

$$('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.tab-btn').forEach(b => {
      b.classList.remove('active');
      b.setAttribute('aria-selected', 'false');
    });
    $$('.tab-pane').forEach(p => p.hidden = true);
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    $('#tab-' + btn.dataset.target).hidden = false;
  });
});

// Theme Toggle
const savedTheme = localStorage.getItem('theme') || 'dark';
document.body.setAttribute('data-theme', savedTheme);
$('#theme-toggle').innerText = savedTheme === 'dark' ? '☀️' : '🌙';

$('#theme-toggle').addEventListener('click', () => {
    const isDark = document.body.getAttribute('data-theme') === 'dark';
    const newTheme = isDark ? 'light' : 'dark';
    document.body.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    $('#theme-toggle').innerText = isDark ? '🌙' : '☀️';
});
$('.tab-btn').click();

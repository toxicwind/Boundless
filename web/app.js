// app.js — Boundless Autonomous Processing Engine UI.
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let currentUpload = null;
let allJobs = [];
let allProfiles = [];

function esc(s) {
  return String(s || '').replace(/[<>&"']/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg, type = 'ok') {
  const c = $('#toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    setTimeout(() => t.remove(), 300);
  }, 3500);
}

async function api(p, opts = {}) {
  const r = await fetch(p, opts);
  if (!r.ok) {
    let errText = '';
    try { errText = await r.text(); } catch (_) {}
    throw new Error(`${r.status}: ${errText || r.statusText}`);
  }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) return r.json();
  return r.text();
}

// ----------------------------------------------------
// Core Status & Pipeline Refresh
// ----------------------------------------------------
async function refresh() {
  try {
    const data = await api('/api/status').catch(() => api('/api/health'));
    $('#last-updated').textContent = `${new Date().toLocaleTimeString()}`;
    
    // Status Pills
    const hp = $('#health-pill');
    if (data.healthy || data.status === 'ok') {
      hp.className = 'status-pill ok';
      $('#health-text').textContent = 'Healthy';
      $('#health').textContent = 'healthy';
      $('#footer-status-pill').textContent = 'System Healthy';
    } else {
      hp.className = 'status-pill err';
      $('#health-text').textContent = 'Degraded';
      $('#health').textContent = 'unhealthy';
      $('#footer-status-pill').textContent = 'Degraded';
    }

    const wp = $('#watcher-pill');
    if (data.watcher?.running) {
      wp.className = 'status-pill ok';
      $('#watcher-text').textContent = data.watcher?.auto_split ? 'Watcher (Auto-Split)' : 'Watcher (Active)';
    } else {
      wp.className = 'status-pill warn';
      $('#watcher-text').textContent = 'Watcher Standby';
    }

    // Top Stats Bar
    $('#s-inbox').textContent = data.inbox ?? 0;
    $('#s-active').textContent = data.active ?? 0;
    $('#s-done').textContent = data.done ?? 0;
    $('#s-profiles').textContent = data.profiles ?? 0;
    $('#footer-port').textContent = data.port || '10200';
    if (data.processing_dir) {
      $('#inbox-path-display').textContent = `${data.processing_dir}/inbox/`;
    }
  } catch (e) {
    $('#health-pill').className = 'status-pill err';
    $('#health-text').textContent = 'Offline';
    $('#health').textContent = 'unhealthy';
    $('#footer-status-pill').textContent = 'Connection Error';
    console.error('Health check failure:', e);
  }

  // Load Pipeline & Inbox
  try {
    const [ps, inboxData] = await Promise.all([
      api('/api/processing'),
      api('/api/inbox').catch(() => ({ items: [] })),
    ]);

    $('#c-inbox').textContent = ps.inbox?.length || 0;
    $('#c-active').textContent = ps.active?.length || 0;
    $('#c-done').textContent = ps.done?.length || 0;
    $('#c-failed').textContent = ps.failed?.length || 0;

    renderInboxLane(ps.inbox || [], inboxData.items || []);
    renderActiveLane(ps.active || []);
    renderDoneLane(ps.done || []);
    renderFailedLane(ps.failed || []);
  } catch (e) {
    console.error('Processing refresh error:', e);
  }

  // Load History Table
  await loadHistory();

  // Load Profiles
  await loadProfiles();
}

// ----------------------------------------------------
// Pipeline Lanes Rendering
// ----------------------------------------------------
function renderInboxLane(files, metadataItems) {
  const metaMap = {};
  metadataItems.forEach(it => { metaMap[it.filename] = it; });

  const container = $('#lane-inbox');
  if (!files.length) {
    container.innerHTML = `
      <div class="muted text-center" style="padding: 2rem 1rem;">
        <p>No files in inbox.</p>
        <small>Drop EPUB/PDF/DOCX into <code>processing/inbox/</code> to auto-process.</small>
      </div>`;
    return;
  }

  container.innerHTML = files.map(f => {
    const m = metaMap[f.name] || {};
    const sizeMb = (f.size / 1024 / 1024).toFixed(1);
    const title = m.title || f.name.replace(/_/g, ' ').replace(/\.[^/.]+$/, '');
    const publisher = m.publisher || 'Unknown Publisher';
    const nr = m.nr_status || (f.size > 50 * 1024 * 1024 ? 'EXCEEDS_50MB' : 'ok');
    const badgeCls = nr.includes('EXCEEDS') ? 'warn' : 'ok';

    return `
      <div class="item-card">
        <h4>${esc(title)}</h4>
        <div class="item-meta">
          <code>${esc(f.name)}</code> · ${sizeMb} MB<br/>
          <span>${esc(publisher)}</span>
        </div>
        <div class="item-tags">
          <span class="badge ${badgeCls}">${esc(nr)}</span>
          <span class="badge info">Pending</span>
        </div>
        <div class="item-actions">
          <button class="primary" onclick="processFile('${esc(f.name)}', 'size')">⚡ Size Split</button>
          <button class="ghost" onclick="processFile('${esc(f.name)}', 'toc')">📑 TOC Split</button>
          <button class="danger ghost" onclick="deleteInboxFile('${esc(f.name)}')">🗑 Delete</button>
        </div>
      </div>`;
  }).join('');
}

function renderActiveLane(files) {
  const container = $('#lane-active');
  if (!files.length) {
    container.innerHTML = `<div class="muted text-center" style="padding: 2rem 1rem;">No active processing jobs</div>`;
    return;
  }
  container.innerHTML = files.map(f => `
    <div class="item-card">
      <h4>⚙️ ${esc(f.name)}</h4>
      <div class="item-meta">Processing in progress...</div>
      <div class="item-tags">
        <span class="badge warn">Active Job</span>
      </div>
    </div>
  `).join('');
}

function renderDoneLane(items) {
  const container = $('#lane-done');
  if (!items.length) {
    container.innerHTML = `<div class="muted text-center" style="padding: 2rem 1rem;">No completed runs yet</div>`;
    return;
  }
  container.innerHTML = items.map(it => {
    const isDir = it.type === 'dir';
    const szMb = ((it.size || 0) / 1024 / 1024).toFixed(1);
    const title = it.name.replace(/_/g, ' ');
    const chunkBadge = it.chunk_count ? `<span class="badge ok">${it.chunk_count} chunks</span>` : '';

    return `
      <div class="item-card">
        <h4>✅ ${esc(title)}</h4>
        <div class="item-meta">Total Output: ${szMb} MB</div>
        <div class="item-tags">
          ${chunkBadge}
          <span class="badge info">Ready</span>
        </div>
        <div class="item-actions">
          ${isDir ? `<button class="primary" onclick="viewChunksModal('${esc(it.name)}')">📦 View Chunks</button>` : ''}
          ${isDir ? `<a href="/api/outputs/${encodeURIComponent(it.name)}/zip"><button class="ghost">⬇ ZIP</button></a>` : ''}
        </div>
      </div>`;
  }).join('');
}

function renderFailedLane(files) {
  const container = $('#lane-failed');
  if (!files.length) {
    container.innerHTML = `<div class="muted text-center" style="padding: 2rem 1rem;">No failed items</div>`;
    return;
  }
  container.innerHTML = files.map(f => `
    <div class="item-card" style="border-color: var(--err);">
      <h4>❌ ${esc(f.name)}</h4>
      <div class="item-meta">Processing encountered an error</div>
      <div class="item-tags"><span class="badge err">Failed</span></div>
    </div>
  `).join('');
}

// ----------------------------------------------------
// History Table
// ----------------------------------------------------
async function loadHistory() {
  try {
    const res = await api('/api/jobs?limit=100');
    allJobs = res.jobs || [];
    $('#history-badge').textContent = allJobs.length;
    renderHistoryTable();
  } catch (e) {
    console.error('History load error:', e);
  }
}

function renderHistoryTable() {
  const tbody = $('#history-tbody');
  const search = ($('#history-search')?.value || '').toLowerCase();
  const filterStatus = $('#history-filter-status')?.value || '';

  const filtered = allJobs.filter(j => {
    if (filterStatus && j.status !== filterStatus) return false;
    if (search) {
      const hay = `${j.book_title || ''} ${j.filename || ''} ${j.publisher || ''} ${j.origin_pipeline || ''}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="muted text-center" style="padding: 2rem;">No matching jobs found in history.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(j => {
    const title = j.book_title || j.filename;
    const sizeMb = ((j.file_size || 0) / 1024 / 1024).toFixed(1);
    const outMb = ((j.total_output_size || 0) / 1024 / 1024).toFixed(1);
    const dateStr = j.created_at ? new Date(j.created_at).toLocaleString() : '-';
    const durStr = j.duration_seconds ? `${j.duration_seconds.toFixed(1)}s` : '-';
    const statusCls = j.status === 'completed' ? 'ok' : j.status === 'failed' ? 'err' : 'warn';
    const dirName = j.output_dir ? j.output_dir.split('/').pop() : '';

    return `
      <tr>
        <td>
          <strong>${esc(title)}</strong><br/>
          <small class="muted"><code>${esc(j.filename)}</code> (${sizeMb} MB)</small>
        </td>
        <td>
          <span>${esc(j.publisher || 'Unknown')}</span><br/>
          <small class="muted">${esc(j.origin_pipeline || '')}</small>
        </td>
        <td>
          <span class="badge info">${esc(j.method.toUpperCase())}</span>
          <small class="muted">(${j.max_size_mb || 50} MB max)</small>
        </td>
        <td><strong>${j.chunk_count || 0}</strong></td>
        <td>${outMb} MB</td>
        <td><small>${esc(dateStr)}</small></td>
        <td><small>${durStr}</small></td>
        <td><span class="badge ${statusCls}">${esc(j.status)}</span></td>
        <td>
          <div style="display:flex; gap: 0.35rem;">
            ${dirName ? `<button class="primary" onclick="viewChunksModal('${esc(dirName)}')">📦 Chunks</button>` : ''}
            ${dirName ? `<a href="/api/outputs/${encodeURIComponent(dirName)}/zip"><button class="ghost">⬇ ZIP</button></a>` : ''}
            <button class="danger ghost" onclick="deleteJobRecord('${esc(j.id)}')">🗑</button>
          </div>
        </td>
      </tr>`;
  }).join('');
}

// ----------------------------------------------------
// Chunks Inspection Modal
// ----------------------------------------------------
async function viewChunksModal(subdir) {
  const modal = $('#chunks-modal');
  $('#modal-title').textContent = `Outputs: ${subdir}`;
  $('#modal-subtitle').textContent = 'Loading chunk details...';
  $('#modal-chunk-list').innerHTML = '<li class="muted">Loading chunks...</li>';
  $('#modal-zip-link').href = `/api/outputs/${encodeURIComponent(subdir)}/zip`;
  modal.hidden = false;

  try {
    const res = await api(`/api/outputs/${encodeURIComponent(subdir)}`);
    const chunks = res.chunks || [];
    $('#modal-subtitle').textContent = `Directory: processing/done/${subdir}/`;
    $('#modal-stats').textContent = `${chunks.length} chunks generated`;

    if (!chunks.length) {
      $('#modal-chunk-list').innerHTML = `<li class="muted">No .epub chunks found in directory.</li>`;
      return;
    }

    $('#modal-chunk-list').innerHTML = chunks.map(c => `
      <li class="chunk-item">
        <div>
          <a href="${esc(c.url)}" download="${esc(c.name)}">📄 ${esc(c.name)}</a><br/>
          <small class="muted">${esc(c.title || '')}</small>
        </div>
        <div style="display:flex; align-items:center; gap:0.75rem;">
          <span class="badge info">${c.size_mb} MB</span>
          <a href="${esc(c.url)}" download="${esc(c.name)}"><button class="ghost">⬇ Download</button></a>
        </div>
      </li>
    `).join('');
  } catch (e) {
    $('#modal-chunk-list').innerHTML = `<li class="muted" style="color:var(--err)">Failed to load chunks: ${esc(e.message)}</li>`;
  }
}

$('#modal-close').addEventListener('click', () => { $('#chunks-modal').hidden = true; });
window.addEventListener('click', e => {
  if (e.target === $('#chunks-modal')) $('#chunks-modal').hidden = true;
});

// ----------------------------------------------------
// Actions (Process, Delete, Batch)
// ----------------------------------------------------
async function processFile(name, method = 'size') {
  toast(`Starting ${method.toUpperCase()} split for ${name}...`, 'info');
  try {
    const s = await api('/api/settings');
    const maxMb = s.default_max_size_mb || 50;
    const r = await api(`/api/process/${encodeURIComponent(name)}?method=${method}&max_size_mb=${maxMb}`, { method: 'POST' });
    toast(`Completed: ${name} split into ${r.chunks?.length || 0} chunks!`, 'ok');
    refresh();
  } catch (e) {
    toast(`Failed to process ${name}: ${e.message}`, 'err');
    console.error(e);
  }
}

async function deleteInboxFile(filename) {
  if (!confirm(`Remove ${filename} from inbox?`)) return;
  try {
    await api(`/api/inbox/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    toast(`Deleted ${filename}`, 'ok');
    refresh();
  } catch (e) {
    toast(`Delete failed: ${e.message}`, 'err');
  }
}

async function deleteJobRecord(jid) {
  if (!confirm(`Delete job record ${jid}?`)) return;
  try {
    await api(`/api/jobs/${encodeURIComponent(jid)}`, { method: 'DELETE' });
    toast('Job record deleted', 'ok');
    refresh();
  } catch (e) {
    toast(`Failed to delete job: ${e.message}`, 'err');
  }
}

$('#process-all-btn').addEventListener('click', async () => {
  toast('Processing all inbox files...', 'info');
  try {
    const res = await api('/api/inbox/process-all', { method: 'POST' });
    toast(`Batch processed ${res.processed} file(s)!`, 'ok');
    refresh();
  } catch (e) {
    toast(`Batch processing error: ${e.message}`, 'err');
  }
});

// ----------------------------------------------------
// Profiles Library
// ----------------------------------------------------
async function loadProfiles() {
  try {
    const res = await api('/api/profiles');
    allProfiles = res.profiles || [];
    $('#profile-count').textContent = `(${allProfiles.length} books)`;
    $('#profile-badge').textContent = allProfiles.length;
    renderProfilesGrid();
  } catch (e) {
    console.error('Profiles load error:', e);
  }
}

function renderProfilesGrid() {
  const container = $('#profiles');
  const search = ($('#profile-search')?.value || '').toLowerCase();
  const filtered = allProfiles.filter(p => {
    if (!search) return true;
    const hay = `${p.title || ''} ${p.file || ''} ${p.creator || ''} ${p.publisher || ''}`.toLowerCase();
    return hay.includes(search);
  });

  if (!filtered.length) {
    container.innerHTML = `<p class="muted">No matching profiles found.</p>`;
    return;
  }

  container.innerHTML = filtered.map(p => {
    if (p.error) return `<div class="card"><h3>${esc(p.file)}</h3><div class="meta">${esc(p.error)}</div></div>`;
    const origin = p.origin || {};
    const nr = p.nr_status || '';
    const cls = nr.includes('EXCEEDS') ? 'warn' : 'ok';
    return `
      <div class="card">
        <div>
          <h3>${esc(p.title || p.file)}</h3>
          <div class="meta">${esc(p.creator || 'Unknown')} · ${esc(p.publisher || 'Unknown Publisher')}</div>
          <div style="margin: 0.5rem 0;">
            <span class="badge ${cls}">${esc(nr || 'Profiled')}</span>
            <span class="badge info">${p.size_mb} MB</span>
            <span class="badge">${esc(origin.confidence || 'Confidence: High')}</span>
          </div>
          <div class="origin">
            <strong>${esc(origin.publisher || 'Standard EPUB')}</strong><br/>
            <small class="muted">${esc(origin.pipeline || 'Standard Content Pipeline')}</small>
          </div>
          <div class="strategy">Strategy: ${esc(p.split_strategy || 'Size / Natural Reader Chunking')}</div>
        </div>
        <div style="margin-top: 1rem; display: flex; justify-content: space-between;">
          <button class="danger ghost" onclick="deleteProfile('${esc(p.file)}')">Delete</button>
        </div>
      </div>`;
  }).join('');
}

async function deleteProfile(file) {
  if (!confirm(`Delete profile for ${file}?`)) return;
  try {
    await api(`/api/profiles/${encodeURIComponent(file)}`, { method: 'DELETE' });
    toast(`Deleted profile for ${file}`, 'ok');
    refresh();
  } catch (e) {
    toast(`Delete profile failed: ${e.message}`, 'err');
  }
}

// ----------------------------------------------------
// Upload & Split Form Handlers
// ----------------------------------------------------
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
  $('#upload-progress').textContent = `Uploading ${files.length} file(s)...`;
  try {
    const r = await api('/api/upload', { method: 'POST', body: fd });
    toast(`Uploaded ${r.count} file(s) into processing/inbox/`, 'ok');
    $('#upload-progress').textContent = `Uploaded ${r.count} file(s); queued to inbox and profiles generated.`;
    renderUploads(r.uploads || []);
    refresh();
  } catch (e) {
    $('#upload-progress').textContent = `Error: ${e.message}`;
    toast(`Upload failed: ${e.message}`, 'err');
  }
}

function renderUploads(uploads) {
  const list = $('#upload-list');
  list.innerHTML = uploads.map(u => {
    const p = u.profile || {};
    return `
      <div class="card">
        <h3>${esc(u.filename)}</h3>
        <div class="meta">${u.size_mb} MB · ${esc(p.origin?.publisher || 'Analyzed')}</div>
        <div><span class="badge ${p.nr_status?.includes('EXCEEDS') ? 'warn' : 'ok'}">${esc(p.nr_status || 'ok')}</span></div>
        <button class="primary" onclick="selectUpload('${esc(u.upload_id)}')">Select for split</button>
      </div>`;
  }).join('');
  $('#uploaded').hidden = false;
  if (uploads.length) selectUpload(uploads[0].upload_id);
}

function selectUpload(uid) {
  currentUpload = uid;
  $('#split-panel').hidden = false;
  $('#split-result').innerHTML = `<p class="muted">Selected: <code>${esc(uid)}</code></p>`;
}

$('#split-toc-btn').addEventListener('click', async () => {
  if (!currentUpload) return alert('Select or upload a book first');
  $('#split-toc-btn').disabled = true;
  $('#split-result').innerHTML = '<p class="muted">Splitting by TOC (preserves publisher assets)...</p>';
  try {
    const r = await api(`/api/split-toc/${encodeURIComponent(currentUpload)}`, { method: 'POST' });
    const list = (r.sections || []).map(s => `<li><a href="/api/outputs/${encodeURIComponent(r.output_dir.split('/').pop())}/${encodeURIComponent(s)}">${esc(s)}</a></li>`).join('');
    $('#split-result').innerHTML = `<p><strong>${r.count} chunks</strong> generated in <code>${esc(r.output_dir)}</code></p><ul class="chunk-item-list">${list}</ul>`;
    toast('TOC split completed!', 'ok');
    refresh();
  } catch (e) {
    $('#split-result').innerHTML = `<p style="color:var(--err)">Error: ${esc(e.message)}</p>`;
    toast(`TOC Split failed: ${e.message}`, 'err');
  }
  $('#split-toc-btn').disabled = false;
});

$('#split-btn').addEventListener('click', async () => {
  if (!currentUpload) return alert('Select or upload a book first');
  const max = parseInt($('#max-mb').value, 10) || 50;
  $('#split-btn').disabled = true;
  $('#split-result').innerHTML = '<p class="muted">Splitting by size constraint (Natural Reader 50MB)...</p>';
  try {
    const r = await api(`/api/split/${encodeURIComponent(currentUpload)}?max_size_mb=${max}`, { method: 'POST' });
    const chunks = (r.chunks || []).map(c => `<li>${esc(c.title || c.slug)} — ${(c.size / 1024 / 1024).toFixed(2)} MB</li>`).join('');
    $('#split-result').innerHTML = `<p><strong>${r.chunk_count} chunks</strong> generated in <code>${esc(r.output_dir)}</code></p><ul>${chunks}</ul>`;
    toast('Size split completed!', 'ok');
    refresh();
  } catch (e) {
    $('#split-result').innerHTML = `<p style="color:var(--err)">Error: ${esc(e.message)}</p>`;
    toast(`Size split failed: ${e.message}`, 'err');
  }
  $('#split-btn').disabled = false;
});

// ----------------------------------------------------
// Directory Scan
// ----------------------------------------------------
$('#scan-btn').addEventListener('click', async () => {
  const d = prompt('Directory to scan for books (no /mnt):', '~/Downloads');
  if (!d) return;
  try {
    toast(`Scanning ${d}...`, 'info');
    const r = await api(`/api/scan?directory=${encodeURIComponent(d)}`, { method: 'POST' });
    toast(`Scanned ${r.scanned} files, created ${r.profiles_created} profiles`, 'ok');
    refresh();
  } catch (e) {
    toast(`Scan error: ${e.message}`, 'err');
  }
});

// ----------------------------------------------------
// Edge Cases
// ----------------------------------------------------
async function loadEdgeCases() {
  try {
    const r = await api('/api/edge-cases');
    $('#ec-epub').textContent = (r.epub || []).join('\n');
    $('#ec-pdf').textContent = (r.pdf || []).join('\n');
    $('#ec-docx').textContent = (r.docx || []).join('\n');
    $('#ec-a11y').textContent = (r.a11y || []).join('\n');
  } catch (e) { console.error('Edge cases load error:', e); }
}

// ----------------------------------------------------
// Tabs & Theme
// ----------------------------------------------------
$$('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.tab-btn').forEach(b => {
      b.classList.remove('active');
      b.setAttribute('aria-selected', 'false');
    });
    $$('.tab-pane').forEach(p => p.hidden = true);
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    const target = $('#tab-' + btn.dataset.target);
    if (target) target.hidden = false;
  });
});

$('#theme-toggle').addEventListener('click', () => {
  const isDark = document.body.getAttribute('data-theme') === 'dark';
  const newTheme = isDark ? 'light' : 'dark';
  document.body.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
  $('#theme-toggle').innerText = isDark ? '🌙' : '☀️';
});

const savedTheme = localStorage.getItem('theme') || 'dark';
document.body.setAttribute('data-theme', savedTheme);
$('#theme-toggle').innerText = savedTheme === 'dark' ? '☀️' : '🌙';

$('#refresh').addEventListener('click', refresh);
$('#history-search')?.addEventListener('input', renderHistoryTable);
$('#history-filter-status')?.addEventListener('change', renderHistoryTable);
$('#history-reload-btn')?.addEventListener('click', loadHistory);
$('#profile-search')?.addEventListener('input', renderProfilesGrid);

// Initial Load and Auto-Refresh Interval
refresh();
loadEdgeCases();
setInterval(refresh, 3500);

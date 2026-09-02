// settings.js
async function api(p, opts={}) {
  const r = await fetch(p, {headers:{'Content-Type':'application/json'}, ...opts});
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

async function load() {
  const s = await api('/api/settings');
  document.getElementById('auto_watch_inbox').checked = s.auto_watch_inbox;
  document.getElementById('auto_profile_on_upload').checked = s.auto_profile_on_upload;
  document.getElementById('auto_split_on_upload').checked = s.auto_split_on_upload;
  document.getElementById('scan_recursive').checked = s.scan_recursive;
  document.getElementById('default_max_size_mb').value = s.default_max_size_mb;
  document.getElementById('default_split_method').value = s.default_split_method;
  document.getElementById('scan_extensions').value = s.scan_extensions.join(',');
  document.getElementById('theme').value = s.theme;
  document.getElementById('tray_enabled').checked = s.tray_enabled;
  document.getElementById('auto_open_browser_on_launch').checked = s.auto_open_browser_on_launch;
  document.getElementById('host').value = s.host;
  document.getElementById('port').value = s.port;
}

async function save() {
  const s = {
    auto_watch_inbox: document.getElementById('auto_watch_inbox').checked,
    auto_profile_on_upload: document.getElementById('auto_profile_on_upload').checked,
    auto_split_on_upload: document.getElementById('auto_split_on_upload').checked,
    scan_recursive: document.getElementById('scan_recursive').checked,
    default_max_size_mb: parseInt(document.getElementById('default_max_size_mb').value, 10),
    default_split_method: document.getElementById('default_split_method').value,
    scan_extensions: document.getElementById('scan_extensions').value.split(',').map(x=>x.trim()).filter(Boolean),
    theme: document.getElementById('theme').value,
    tray_enabled: document.getElementById('tray_enabled').checked,
    auto_open_browser_on_launch: document.getElementById('auto_open_browser_on_launch').checked,
    host: document.getElementById('host').value,
    port: parseInt(document.getElementById('port').value, 10),
  };
  await api('/api/settings', {method:'PUT', body: JSON.stringify(s)});
  document.getElementById('status').textContent = 'Saved.';
  setTimeout(() => document.getElementById('status').textContent = '', 2000);
}

document.getElementById('save').onclick = save;
document.getElementById('reload').onclick = load;
load();

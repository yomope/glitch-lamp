const listEl = document.getElementById('playlist-list');
const urlInput = document.getElementById('playlist-url');
const fileSelect = document.getElementById('playlist-local-file');
const titleInput = document.getElementById('playlist-title');
const addBtn = document.getElementById('add-playlist-item');
const clearBtn = document.getElementById('clear-playlist');
const statusEl = document.getElementById('add-status');
const toast = document.getElementById('toast');

function showToast(msg, error = false) {
  if (!toast) return;
  toast.textContent = msg;
  toast.style.borderColor = error ? '#d04545' : '#1d2738';
  toast.style.color = error ? '#f38b8b' : '#e9f1fb';
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
}

async function loadUploads() {
  try {
    const res = await fetch('/uploads-list');
    const files = await res.json();
    fileSelect.innerHTML = '<option value="">-- Aucun --</option>';
    files.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f.filename;
      opt.textContent = `${f.filename} (${Math.round(f.size / 1024)} Ko)`;
      fileSelect.appendChild(opt);
    });
  } catch (e) {
    console.error('Uploads fetch error', e);
  }
}

async function loadPlaylist() {
  try {
    const res = await fetch('/playlist');
    const items = await res.json();
    listEl.innerHTML = '';
    if (!items.length) {
      const li = document.createElement('li');
      li.textContent = 'Playlist vide';
      listEl.appendChild(li);
      return;
    }
    items.forEach(item => {
      const li = document.createElement('li');
      const left = document.createElement('div');
      const right = document.createElement('div');
      const label = item.title || item.url || item.local_file || '(sans titre)';
      left.innerHTML = `<strong>${label}</strong><div class="small">${item.local_file ? 'Local' : 'URL'}${item.url ? ' • ' + item.url : ''}${item.local_file ? ' • ' + item.local_file : ''}</div>`;
      const del = document.createElement('button');
      del.className = 'btn secondary';
      del.textContent = 'Supprimer';
      del.onclick = async () => {
        try {
          await fetch(`/playlist/${item.id}`, { method: 'DELETE' });
          showToast('Supprimé');
          loadPlaylist();
        } catch (e) {
          console.error(e);
          showToast('Erreur suppression', true);
        }
      };
      right.appendChild(del);
      li.appendChild(left);
      li.appendChild(right);
      listEl.appendChild(li);
    });
  } catch (e) {
    console.error('Playlist fetch error', e);
  }
}

addBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();
  const local_file = fileSelect.value.trim();
  const title = titleInput.value.trim();
  if (!url && !local_file) {
    statusEl.textContent = 'Fournissez une URL ou un fichier uploadé.';
    statusEl.style.color = '#f38b8b';
    return;
  }
  statusEl.textContent = 'Ajout...';
  statusEl.style.color = '#19e1a3';
  try {
    await fetch('/playlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, local_file, title })
    });
    statusEl.textContent = 'Ajouté';
    statusEl.style.color = '#19e1a3';
    urlInput.value = '';
    titleInput.value = '';
    loadPlaylist();
  } catch (e) {
    console.error(e);
    statusEl.textContent = 'Erreur ajout';
    statusEl.style.color = '#f38b8b';
  }
});

clearBtn.addEventListener('click', async () => {
  if (!confirm('Vider la playlist ?')) return;
  try {
    await fetch('/playlist/clear', { method: 'POST' });
    showToast('Playlist vidée');
    loadPlaylist();
  } catch (e) {
    console.error(e);
    showToast('Erreur clear', true);
  }
});

loadUploads();
loadPlaylist();

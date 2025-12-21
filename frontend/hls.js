const listEl = document.getElementById('segments');
const refreshBtn = document.getElementById('refresh');
const resetBtn = document.getElementById('reset');
const statusEl = document.getElementById('status');
const toast = document.getElementById('toast');
let previewEl = null;
let previewVideo = null;
let previewHls = null;
let refreshTimer = null;

function showToast(msg, error = false) {
  if (!toast) return;
  toast.textContent = msg;
  toast.style.borderColor = error ? '#d04545' : '#1d2738';
  toast.style.color = error ? '#f38b8b' : '#e9f1fb';
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
}

function destroyPreview() {
  if (previewHls) {
    previewHls.destroy();
    previewHls = null;
  }
  if (previewVideo) {
    previewVideo.pause();
    previewVideo.src = '';
  }
  if (previewEl && previewEl.parentNode) {
    previewEl.parentNode.removeChild(previewEl);
  }
  previewEl = null;
  previewVideo = null;
}

function positionPreview(x, y) {
  if (!previewEl) return;
  const padding = 12;
  const width = 220;
  const height = 150;
  let left = x + 16;
  let top = y + 16;
  if (left + width + padding > window.innerWidth) {
    left = x - width - 16;
  }
  if (top + height + padding > window.innerHeight) {
    top = y - height - 16;
  }
  previewEl.style.left = `${left}px`;
  previewEl.style.top = `${top}px`;
}

function createPreview(seg, x, y) {
  destroyPreview();
  previewEl = document.createElement('div');
  previewEl.className = 'preview-card';
  previewVideo = document.createElement('video');
  previewVideo.muted = true;
  previewVideo.loop = true;
  previewVideo.playsInline = true;
  previewVideo.autoplay = true;
  // Charger la playlist HLS (les .ts seuls ne sont pas lisibles directement dans la plupart des navigateurs)
  const playlistUrl = '/stream/stream.m3u8';
  if (window.Hls && Hls.isSupported()) {
    previewHls = new Hls({ liveDurationInfinity: true });
    previewHls.loadSource(playlistUrl);
    previewHls.attachMedia(previewVideo);
  } else {
    previewVideo.src = playlistUrl;
  }
  previewEl.appendChild(previewVideo);
  document.body.appendChild(previewEl);
  positionPreview(x, y);
  previewVideo.play().catch(() => {});
}

async function loadSegments() {
  destroyPreview();
  statusEl.textContent = 'Chargement...';
  try {
    const res = await fetch('/api/stream/segments');
    const segments = await res.json();
    statusEl.textContent = `${segments.length} segments`;
    listEl.innerHTML = '';
    if (!segments.length) {
      const li = document.createElement('li');
      li.textContent = 'Aucun segment (attendre la génération)';
      listEl.appendChild(li);
      return;
    }
    segments.forEach(seg => {
      const li = document.createElement('li');
      const left = document.createElement('div');
      const right = document.createElement('div');
      left.innerHTML = `<strong>#${seg.seq}</strong> — ${seg.filename} <div class="small">${seg.duration.toFixed(2)}s${seg.exists ? '' : ' • manquant'}</div>`;
      const del = document.createElement('button');
      del.className = 'btn secondary';
      del.textContent = 'Supprimer';
      del.onclick = async () => {
        try {
          await fetch(`/api/stream/segment/${seg.seq}`, { method: 'DELETE' });
          showToast(`Segment #${seg.seq} supprimé`);
          loadSegments();
        } catch (e) {
          console.error(e);
          showToast('Erreur suppression', true);
        }
      };
      right.appendChild(del);
      li.appendChild(left);
      li.appendChild(right);
      li.addEventListener('mouseenter', (e) => createPreview(seg, e.clientX, e.clientY));
      li.addEventListener('mousemove', (e) => positionPreview(e.clientX, e.clientY));
      li.addEventListener('mouseleave', destroyPreview);
      listEl.appendChild(li);
    });
  } catch (e) {
    statusEl.textContent = 'Erreur de chargement';
    console.error(e);
  }
}

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(loadSegments, 5000);
}

refreshBtn.addEventListener('click', loadSegments);
resetBtn.addEventListener('click', async () => {
  if (!confirm('Reset HLS (efface tous les segments) ?')) return;
  try {
    await fetch('/api/stream/reset', { method: 'POST' });
    showToast('HLS réinitialisé');
    loadSegments();
  } catch (e) {
    console.error(e);
    showToast('Erreur reset', true);
  }
});

window.addEventListener('scroll', destroyPreview);
window.addEventListener('resize', destroyPreview);
window.addEventListener('beforeunload', () => {
  if (refreshTimer) clearInterval(refreshTimer);
  destroyPreview();
});

loadSegments();
startAutoRefresh();

async function confirmDialog(message) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.style.position = 'fixed';
    overlay.style.inset = '0';
    overlay.style.background = 'rgba(0,0,0,0.5)';
    overlay.style.backdropFilter = 'blur(2px)';
    overlay.style.display = 'grid';
    overlay.style.placeItems = 'center';
    overlay.style.zIndex = '4000';

    const box = document.createElement('div');
    box.style.background = '#0d1320';
    box.style.border = '1px solid #1d2738';
    box.style.borderRadius = '12px';
    box.style.padding = '16px';
    box.style.minWidth = '260px';
    box.style.maxWidth = '90vw';
    box.style.boxShadow = '0 20px 50px rgba(0,0,0,0.35)';
    box.innerHTML = `
      <div style="color:#e9f1fb; margin-bottom:12px; font-weight:600;">${message}</div>
      <div style="display:flex; gap:10px; justify-content:flex-end; flex-wrap:wrap;">
        <button class="btn secondary" id="c-cancel">Annuler</button>
        <button class="btn" id="c-ok">OK</button>
      </div>
    `;
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    const done = (res) => { overlay.remove(); resolve(res); };
    box.querySelector('#c-cancel').onclick = () => done(false);
    box.querySelector('#c-ok').onclick = () => done(true);
  });
}
const listEl = document.getElementById('segments');
const refreshBtn = document.getElementById('refresh');
const resetBtn = document.getElementById('reset');
const statusEl = document.getElementById('status');
const batchTimerEl = document.getElementById('batch-timer');
const toast = document.getElementById('toast');
let previewEl = null;
let previewVideo = null;
let previewHls = null;
let refreshTimer = null;
let playlistHls = null;
const playerEl = document.getElementById('playlist-player');
const playPauseBtn = document.getElementById('play-pause');
const muteBtn = document.getElementById('mute-btn');
const volumeSlider = document.getElementById('volume-slider');
const progressBar = document.getElementById('progress-bar');
const progressFill = document.getElementById('progress-fill');
const timeDisplay = document.getElementById('time-display');
const fullscreenBtn = document.getElementById('fullscreen-btn');
const resetStatsBtn = document.getElementById('reset-stats');

function showToast(msg, error = false) {
  if (!toast) return;
  toast.textContent = msg;
  toast.style.borderColor = error ? '#d04545' : '#1d2738';
  toast.style.color = error ? '#f38b8b' : '#e9f1fb';
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
}

function destroyPreview() {
  // Détruire HLS.js d'abord pour éviter les erreurs de chargement
  if (previewHls) {
    try {
      previewHls.destroy();
    } catch (e) {
      // Ignorer les erreurs lors de la destruction
    }
    previewHls = null;
  }
  if (previewVideo) {
    try {
      previewVideo.pause();
      previewVideo.src = '';
      previewVideo.load(); // Réinitialiser le player
    } catch (e) {
      // Ignorer les erreurs lors du nettoyage
    }
  }
  if (previewEl && previewEl.parentNode) {
    previewEl.parentNode.removeChild(previewEl);
  }
  previewEl = null;
  previewVideo = null;
}

function formatTime(seconds) {
  if (isNaN(seconds) || !isFinite(seconds)) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function positionPreview(x, y) {
  if (!previewEl) return;
  const rect = previewEl.getBoundingClientRect();
  const winW = window.innerWidth;
  const winH = window.innerHeight;
  let posX = x + 15;
  let posY = y + 15;
  if (posX + rect.width > winW) posX = x - rect.width - 15;
  if (posY + rect.height > winH) posY = y - rect.height - 15;
  previewEl.style.left = `${posX}px`;
  previewEl.style.top = `${posY}px`;
  previewEl.style.right = 'auto';
  previewEl.style.bottom = 'auto';
}

function createPreview(seg, x, y) {
  destroyPreview();
  
  // Vérifier que le segment existe
  if (!seg || !seg.filename || !seg.exists) {
    return; // Pas de preview si le segment n'existe pas
  }
  
  previewEl = document.createElement('div');
  previewEl.className = 'preview-card';
  // Position initiale hors champ pour mesure
  previewEl.style.left = '-9999px';
  previewEl.style.top = '-9999px';

  previewVideo = document.createElement('video');
  previewVideo.muted = true;
  previewVideo.loop = true;
  previewVideo.playsInline = true;
  previewVideo.autoplay = true;
  
  // Utiliser une mini-playlist HLS pour ce segment spécifique
  const previewPlaylistUrl = `/api/stream/segment/${seg.seq}/preview.m3u8`;
  
  // Utiliser HLS.js si disponible pour une meilleure compatibilité
  if (window.Hls && Hls.isSupported()) {
    previewHls = new Hls({ 
      liveDurationInfinity: false,
      maxBufferLength: 10,
      maxMaxBufferLength: 20
    });
    previewHls.loadSource(previewPlaylistUrl);
    previewHls.attachMedia(previewVideo);
    previewHls.on(Hls.Events.ERROR, (event, data) => {
      // Ignorer les erreurs si le preview a été détruit
      if (!previewEl || !previewVideo) {
        return;
      }
      
      if (data.fatal) {
        // En cas d'erreur fatale, essayer de charger directement le segment TS
        try {
          if (previewHls) {
            previewHls.destroy();
            previewHls = null;
          }
          previewVideo.src = `/stream/${seg.filename}`;
          previewVideo.play().catch(() => {});
        } catch (e) {
          // Ignorer les erreurs si le preview est détruit pendant le traitement
          if (previewEl && previewVideo) {
            console.debug('Preview error handling failed:', e);
          }
        }
      }
    });
  } else {
    // Fallback pour les navigateurs qui supportent HLS nativement
    previewVideo.src = previewPlaylistUrl;
  }
  
  previewEl.appendChild(previewVideo);
  document.body.appendChild(previewEl);
  
  // Positionner après ajout au DOM
  if (x !== undefined && y !== undefined) {
      positionPreview(x, y);
  } else {
     // Fallback fixed position if coords missing
     previewEl.style.right = '12px';
     previewEl.style.bottom = '12px';
     previewEl.style.left = 'auto';
     previewEl.style.top = 'auto';
  }
  
  previewVideo.play().catch((e) => {
    // Ignorer les erreurs si le preview a été détruit
    if (previewEl && previewVideo) {
      console.debug('Preview playback failed:', e);
    }
  });
}

function showVideoPreview(url, x, y) {
  destroyPreview();
  previewEl = document.createElement('div');
  previewEl.className = 'preview-card';
  previewEl.style.left = '-9999px';
  previewEl.style.top = '-9999px';

  previewVideo = document.createElement('video');
  previewVideo.muted = true;
  previewVideo.loop = true;
  previewVideo.playsInline = true;
  previewVideo.autoplay = true;
  previewVideo.src = url;
  
  previewEl.appendChild(previewVideo);
  document.body.appendChild(previewEl);
  
  if (x !== undefined && y !== undefined) {
      positionPreview(x, y);
  }
  
  previewVideo.play().catch(() => {});
}

let lastSegmentCount = 0;
let lastMaxSeq = 0;

async function loadSegments() {
  destroyPreview();
  statusEl.textContent = 'Chargement...';
  try {
    // Charger les segments groupés par vidéo
    const res = await fetch('/api/stream/segments/grouped');
    const videoGroups = await res.json();
    
    // Calculer le total de segments pour les stats
    const totalSegments = videoGroups.reduce((sum, group) => sum + group.segments.length, 0);
    statusEl.textContent = `${videoGroups.length} vidéos (${totalSegments} segments)`;
    
    // Détecter si de nouveaux segments ont été ajoutés
    const allSegments = videoGroups.flatMap(g => g.segments);
    const currentMaxSeq = allSegments.length > 0 ? Math.max(...allSegments.map(s => s.seq)) : 0;
    const hasNewSegments = totalSegments > lastSegmentCount || currentMaxSeq > lastMaxSeq;
    
    if (hasNewSegments && playlistHls && playerEl && !playerEl.paused) {
      // Recharger la playlist HLS pour inclure les nouveaux segments
      try {
        playlistHls.startLoad();
      } catch (e) {
        console.debug('Erreur lors du rechargement de la playlist après nouveaux segments:', e);
      }
    }
    
    lastSegmentCount = totalSegments;
    lastMaxSeq = currentMaxSeq;
    
    listEl.innerHTML = '';
    if (!videoGroups.length) {
      const li = document.createElement('li');
      li.textContent = 'Aucun segment (attendre la génération)';
      listEl.appendChild(li);
      return;
    }
    
    // Afficher chaque vidéo avec ses segments
    videoGroups.forEach(videoGroup => {
      // Conteneur pour la vidéo
      const videoContainer = document.createElement('li');
      videoContainer.style.display = 'flex';
      videoContainer.style.flexDirection = 'column';
      videoContainer.style.gap = '8px';
      videoContainer.style.padding = '12px';
      
      // En-tête de la vidéo
      const videoHeader = document.createElement('div');
      videoHeader.style.display = 'flex';
      videoHeader.style.justifyContent = 'space-between';
      videoHeader.style.alignItems = 'center';
      videoHeader.style.marginBottom = '8px';
      
      const videoInfo = document.createElement('div');
      videoInfo.style.display = 'flex';
      videoInfo.style.flexDirection = 'column';
      videoInfo.style.gap = '4px';
      videoInfo.innerHTML = `<strong>Vidéo #${videoGroup.video_id}</strong> — ${videoGroup.segments.length} segments <div class="small">Durée totale: ${videoGroup.total_duration.toFixed(2)}s</div>`;
      
      const videoActions = document.createElement('div');
      videoActions.style.display = 'flex';
      videoActions.style.gap = '8px';
      videoActions.style.alignItems = 'center';
      
      // Bouton pour afficher/masquer les segments
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'btn secondary';
      toggleBtn.style.padding = '4px 8px';
      toggleBtn.style.fontSize = '12px';
      toggleBtn.textContent = 'Afficher segments';
      
      const deleteVideoBtn = document.createElement('button');
      deleteVideoBtn.className = 'btn secondary';
      deleteVideoBtn.style.borderColor = '#d04545';
      deleteVideoBtn.style.color = '#f38b8b';
      deleteVideoBtn.textContent = 'Supprimer vidéo';
      deleteVideoBtn.onclick = async () => {
        const ok = await confirmDialog(`Supprimer toute la vidéo #${videoGroup.video_id} (${videoGroup.segments.length} segments) ?`);
        if (!ok) return;
        try {
          await fetch(`/api/stream/video/${videoGroup.video_id}`, { method: 'DELETE' });
          showToast(`Vidéo #${videoGroup.video_id} supprimée`);
          loadSegments();
        } catch (e) {
          console.error(e);
          showToast('Erreur suppression', true);
        }
      };
      
      // Liste des segments de cette vidéo (repliable)
      const segmentsList = document.createElement('div');
      segmentsList.style.display = 'none';
      segmentsList.style.marginLeft = '20px';
      segmentsList.style.marginTop = '8px';
      segmentsList.style.paddingLeft = '12px';
      segmentsList.style.borderLeft = '2px solid #1d2738';
      
      toggleBtn.onclick = () => {
        const isVisible = segmentsList.style.display !== 'none';
        segmentsList.style.display = isVisible ? 'none' : 'block';
        toggleBtn.textContent = isVisible ? 'Afficher segments' : 'Masquer segments';
      };
      
      videoGroup.segments.forEach(seg => {
        const segLi = document.createElement('div');
        segLi.style.display = 'flex';
        segLi.style.justifyContent = 'space-between';
        segLi.style.alignItems = 'center';
        segLi.style.padding = '8px';
        segLi.style.marginBottom = '6px';
        segLi.style.background = '#0b111d';
        segLi.style.borderRadius = '6px';
        segLi.style.border = '1px solid #1d2738';
        
        const segLeft = document.createElement('div');
        segLeft.innerHTML = `<span class="small">#${seg.seq}</span> — ${seg.filename} <div class="small">${seg.duration.toFixed(2)}s${seg.exists ? '' : ' • manquant'}</div>`;
        
        const segRight = document.createElement('div');
        const delSegBtn = document.createElement('button');
        delSegBtn.className = 'btn secondary';
        delSegBtn.style.padding = '4px 8px';
        delSegBtn.style.fontSize = '12px';
        delSegBtn.textContent = 'Supprimer';
        delSegBtn.onclick = async () => {
          try {
            await fetch(`/api/stream/segment/${seg.seq}`, { method: 'DELETE' });
            showToast(`Segment #${seg.seq} supprimé`);
            loadSegments();
          } catch (e) {
            console.error(e);
            showToast('Erreur suppression', true);
          }
        };
        segRight.appendChild(delSegBtn);
        
        segLi.appendChild(segLeft);
        segLi.appendChild(segRight);
        segLi.addEventListener('mouseenter', (e) => createPreview(seg, e.pageX, e.pageY));
        segLi.addEventListener('mousemove', (e) => positionPreview(e.pageX, e.pageY));
        segLi.addEventListener('mouseleave', destroyPreview);
        segmentsList.appendChild(segLi);
      });
      
      videoActions.appendChild(toggleBtn);
      videoActions.appendChild(deleteVideoBtn);
      videoHeader.appendChild(videoInfo);
      videoHeader.appendChild(videoActions);
      videoContainer.appendChild(videoHeader);
      videoContainer.appendChild(segmentsList);
      listEl.appendChild(videoContainer);
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
  const ok = await confirmDialog('Reset HLS (efface tous les segments) ?');
  if (!ok) return;
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
  stopPlaylistReload();
  if (playlistHls) {
    try {
      playlistHls.destroy();
    } catch (e) {
      // Ignorer les erreurs
    }
  }
  destroyPreview();
});

loadSegments();
startAutoRefresh();

// ===== Lecteur playlist =====
let playlistReloadTimer = null;
let playlistReloadInterval = 5000; // Recharger la playlist toutes les 5 secondes
let loopCheckInterval = null;

function attachPlaylist() {
  if (!playerEl) return;
  if (playlistHls) {
    playlistHls.destroy();
    playlistHls = null;
  }
  const src = '/stream/stream.m3u8';
  if (window.Hls && Hls.isSupported()) {
    playlistHls = new Hls({ 
      liveDurationInfinity: true,
      // Options pour permettre la mise à jour de la playlist
      manifestLoadingTimeOut: 10000,
      manifestLoadingMaxRetry: 3,
      manifestLoadingRetryDelay: 1000,
      // Options pour la boucle
      enableWorker: true,
      lowLatencyMode: false
    });
    playlistHls.loadSource(src);
    playlistHls.attachMedia(playerEl);
    
    // Écouter les événements pour recharger la playlist
    playlistHls.on(Hls.Events.MANIFEST_PARSED, () => {
      console.debug('Playlist HLS chargée');
      // Démarrer la lecture automatiquement
      if (playerEl.paused) {
        playerEl.play().catch(() => {});
      }
    });
    
    // Recharger la playlist périodiquement pour détecter les nouveaux segments
    playlistHls.on(Hls.Events.LEVEL_LOADED, () => {
      // La playlist a été rechargée avec succès
    });
    
    // Gérer les erreurs
    playlistHls.on(Hls.Events.ERROR, (event, data) => {
      if (data.fatal) {
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            console.warn('Erreur réseau HLS, tentative de rechargement...');
            try {
              playlistHls.startLoad();
            } catch (e) {
              console.error('Erreur lors du rechargement:', e);
            }
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            console.warn('Erreur média HLS, tentative de récupération...');
            try {
              playlistHls.recoverMediaError();
            } catch (e) {
              console.error('Erreur lors de la récupération:', e);
            }
            break;
          default:
            console.error('Erreur HLS fatale:', data);
            // Recharger complètement la playlist
            setTimeout(() => {
              attachPlaylist();
            }, 2000);
            break;
        }
      }
    });
  } else {
    playerEl.src = src;
    // Pour les navigateurs natifs, ajouter la boucle
    playerEl.loop = true;
  }
  
  // Gérer la fin de la vidéo pour boucler
  let endedHandler = () => {
    console.debug('Vidéo terminée, redémarrage en boucle...');
    // Recharger la playlist et redémarrer depuis le début
    if (playlistHls) {
      try {
        // Recharger la playlist pour avoir les derniers segments
        playlistHls.startLoad();
        // Attendre un peu pour que la playlist se recharge
        setTimeout(() => {
          playerEl.currentTime = 0;
          playerEl.play().catch(() => {});
        }, 100);
      } catch (e) {
        console.debug('Erreur lors du redémarrage, rechargement complet:', e);
        // Si erreur, recharger complètement
        setTimeout(() => {
          attachPlaylist();
        }, 500);
      }
    } else {
      // Pour les navigateurs natifs
      playerEl.currentTime = 0;
      playerEl.play().catch(() => {});
    }
  };
  
  // Supprimer l'ancien gestionnaire s'il existe
  playerEl.removeEventListener('ended', endedHandler);
  playerEl.addEventListener('ended', endedHandler);
  
  // Pour les flux live sans #EXT-X-ENDLIST, détecter quand on arrive à la fin
  // et redémarrer manuellement
  let loopCheckInterval = null;
  let lastDuration = 0;
  
  function startLoopCheck() {
    if (loopCheckInterval) clearInterval(loopCheckInterval);
    loopCheckInterval = setInterval(() => {
      if (!playerEl || playerEl.paused) return;
      
      const currentTime = playerEl.currentTime || 0;
      const duration = playerEl.duration;
      
      // Si la durée a changé, c'est que la playlist a été mise à jour
      if (duration && duration !== lastDuration) {
        lastDuration = duration;
      }
      
      // Si on est très proche de la fin (moins de 0.5 seconde), redémarrer
      if (duration && isFinite(duration) && duration > 0) {
        const remaining = duration - currentTime;
        if (remaining < 0.5 && remaining > 0) {
          console.debug('Fin de playlist détectée, redémarrage en boucle...');
          // Recharger la playlist et redémarrer
          if (playlistHls) {
            try {
              playlistHls.startLoad();
              setTimeout(() => {
                playerEl.currentTime = 0;
                playerEl.play().catch(() => {});
              }, 100);
            } catch (e) {
              console.debug('Erreur lors du redémarrage:', e);
              attachPlaylist();
            }
          } else {
            playerEl.currentTime = 0;
            playerEl.play().catch(() => {});
          }
        }
      }
    }, 500); // Vérifier toutes les 500ms
  }
  
  startLoopCheck();
  
  // Démarrer le timer de rechargement périodique de la playlist
  startPlaylistReload();
}

function startPlaylistReload() {
  if (playlistReloadTimer) clearInterval(playlistReloadTimer);
  playlistReloadTimer = setInterval(() => {
    if (playlistHls && playerEl && !playerEl.paused) {
      try {
        // Recharger la playlist pour détecter les nouveaux segments
        playlistHls.startLoad();
      } catch (e) {
        console.debug('Erreur lors du rechargement de la playlist:', e);
      }
    }
  }, playlistReloadInterval);
}

function stopPlaylistReload() {
  if (playlistReloadTimer) {
    clearInterval(playlistReloadTimer);
    playlistReloadTimer = null;
  }
  if (loopCheckInterval) {
    clearInterval(loopCheckInterval);
    loopCheckInterval = null;
  }
}

function updatePlayUI() {
  if (!playPauseBtn || !playerEl) return;
  playPauseBtn.textContent = playerEl.paused ? '▶ Play' : '⏸ Pause';
}

function updateMuteUI() {
  if (muteBtn) muteBtn.textContent = playerEl.muted ? '🔇' : '🔊';
  if (volumeSlider) volumeSlider.value = playerEl.muted ? 0 : playerEl.volume * 100;
}

function updateProgressUI() {
  if (!playerEl || !progressFill || !timeDisplay) return;
  const dur = playerEl.duration;
  const cur = playerEl.currentTime || 0;
  if (dur && isFinite(dur) && dur > 0) {
    const pct = (cur / dur) * 100;
    progressFill.style.width = `${pct}%`;
    timeDisplay.textContent = `${formatTime(cur)} / ${formatTime(dur)}`;
  } else {
    progressFill.style.width = '0%';
    timeDisplay.textContent = `${formatTime(cur)} / --`;
  }
}

if (playerEl) {
  attachPlaylist();
  playerEl.addEventListener('loadedmetadata', updateProgressUI);
  playerEl.addEventListener('timeupdate', updateProgressUI);
  playerEl.addEventListener('play', updatePlayUI);
  playerEl.addEventListener('pause', updatePlayUI);
  playerEl.addEventListener('volumechange', updateMuteUI);
  playerEl.volume = 1;
}

if (playPauseBtn && playerEl) {
  playPauseBtn.addEventListener('click', () => {
    if (playerEl.paused) {
      playerEl.play().catch(() => {});
    } else {
      playerEl.pause();
    }
    updatePlayUI();
  });
}

if (muteBtn && playerEl) {
  muteBtn.addEventListener('click', () => {
    playerEl.muted = !playerEl.muted;
    updateMuteUI();
  });
}

if (volumeSlider && playerEl) {
  volumeSlider.addEventListener('input', (e) => {
    const v = Number(e.target.value) / 100;
    playerEl.volume = v;
    playerEl.muted = v === 0;
    updateMuteUI();
  });
}

if (progressBar && playerEl) {
  progressBar.addEventListener('click', (e) => {
    const rect = progressBar.getBoundingClientRect();
    const percent = (e.clientX - rect.left) / rect.width;
    if (playerEl.duration && isFinite(playerEl.duration)) {
      playerEl.currentTime = percent * playerEl.duration;
    }
  });
}

if (fullscreenBtn && playerEl) {
  fullscreenBtn.addEventListener('click', () => {
    const doc = playerEl.ownerDocument;
    if (!doc.fullscreenElement) {
      playerEl.requestFullscreen().catch(() => {});
    } else {
      doc.exitFullscreen().catch(() => {});
    }
  });
}

// ===== Historique / Exports =====
async function loadHistory() {
  const historyList = document.getElementById('history-list');
  if (!historyList) return;
  try {
    const res = await fetch('/history');
    if (res.ok) {
      const history = await res.json();
      if (!history.length) {
        historyList.innerHTML = '<div class="small" style="text-align:center;">Aucun clip</div>';
        return;
      }
      
      // Filtrer les clips dont les fichiers existent (vérification rapide avec HEAD)
      const checkPromises = history.reverse().map(async (clip) => {
        try {
          // Utiliser AbortController pour timeout si AbortSignal.timeout n'est pas supporté
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 1000);
          const headRes = await fetch(clip.url, { method: 'HEAD', signal: controller.signal });
          clearTimeout(timeoutId);
          return headRes.ok ? clip : null;
        } catch (e) {
          return null; // Fichier n'existe pas ou erreur
        }
      });
      
      const results = await Promise.all(checkPromises);
      const filtered = results.filter(clip => clip !== null);
      
      if (!filtered.length) {
        historyList.innerHTML = '<div class="small" style="text-align:center;">Aucun clip disponible</div>';
        return;
      }
      
      historyList.innerHTML = filtered.map((clip, index) => {
        const date = new Date(clip.timestamp);
        // On ajoute un attribut data-url pour le survol
        return `
          <div class="history-item" data-url="${clip.url}" style="display:flex; justify-content:space-between; align-items:center; gap:8px; padding:8px; border-bottom:1px solid #1d2738; cursor:pointer;">
            <div style="display:flex; gap:10px; align-items:center;">
              <video muted loop playsinline preload="metadata" src="${clip.url}" style="width:120px; height:68px; border-radius:8px; border:1px solid #1d2738; object-fit:cover; background:#000;"></video>
              <div class="small">${date.toLocaleString()}</div>
              <div style="font-size:11px; color:#e9f1fb; word-break:break-all;">${clip.url}</div>
            </div>
            <button class="btn secondary" style="padding:6px 10px; font-size:12px;" data-export="${clip.url}">📥</button>
          </div>
        `;
      }).join('');
      
      // Attach hover events for preview
      historyList.querySelectorAll('.history-item').forEach(item => {
          item.addEventListener('mouseenter', (e) => {
             const url = item.dataset.url;
             showVideoPreview(url, e.pageX, e.pageY);
          });
          item.addEventListener('mousemove', (e) => positionPreview(e.pageX, e.pageY));
          item.addEventListener('mouseleave', destroyPreview);
      });

      historyList.querySelectorAll('[data-export]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation(); // Prevent preview from messing up
            exportClip(btn.dataset.export);
        });
      });
    }
  } catch (e) {
    historyList.innerHTML = '<div class="small" style="color:#f38b8b;">Erreur lors du chargement</div>';
    console.error('History error:', e);
  }
}

async function exportClip(url) {
  try {
    const res = await fetch('/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    if (res.ok) {
      showToast('Clip exporté');
      loadExports();
    } else {
      throw new Error('Export failed');
    }
  } catch (e) {
    showToast('Erreur export', true);
    console.error('Export error:', e);
  }
}

async function loadExports() {
  const exportsList = document.getElementById('exports-list');
  if (!exportsList) return;
  try {
    const res = await fetch('/exports');
    if (res.ok) {
      const data = await res.json();
      if (!data.length) {
        exportsList.innerHTML = '<div class="small" style="text-align:center;">Aucun export</div>';
        return;
      }
      exportsList.innerHTML = data.map(exp => {
        const date = new Date(exp.created);
        const sizeMB = (exp.size / 1024 / 1024).toFixed(2);
        return `
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; padding:8px; border-bottom:1px solid #1d2738;">
            <div>
              <div class="small">${date.toLocaleString()}</div>
              <div style="font-size:11px; color:#e9f1fb;">${exp.filename} (${sizeMB} MB)</div>
            </div>
            <a class="btn secondary" style="padding:6px 10px; font-size:12px;" href="${exp.url}" download>📥</a>
          </div>
        `;
      }).join('');
    }
  } catch (e) {
    exportsList.innerHTML = '<div class="small" style="color:#f38b8b;">Erreur lors du chargement</div>';
    console.error('Exports error:', e);
  }
}

// ===== Batch Status =====
async function loadBatchStatus() {
  if (!batchTimerEl) return;
  try {
    const res = await fetch('/api/batch/status');
    if (res.ok) {
      const status = await res.json();
      if (status.active) {
        const remainingSeconds = status.remaining_seconds || 0;
        const timeStr = formatTime(remainingSeconds);
        batchTimerEl.textContent = `Prochain batch: ${timeStr} (Next: ${status.next_size || 0}/${status.target_size || 0})`;
        batchTimerEl.style.color = '#19e1a3';
      } else {
        batchTimerEl.textContent = 'Batch inactif';
        batchTimerEl.style.color = '#8da0b3';
      }
    }
  } catch (e) {
    console.error('Batch status error:', e);
    if (batchTimerEl) {
      batchTimerEl.textContent = 'Erreur chargement';
      batchTimerEl.style.color = '#f38b8b';
    }
  }
}

// ===== Statistiques =====
async function loadStats() {
  const clipsEl = document.getElementById('stat-clips');
  const timeEl = document.getElementById('stat-time');
  const todayEl = document.getElementById('stat-today');
  const sessionEl = document.getElementById('stat-session');
  if (!clipsEl) return;
  try {
    const res = await fetch('/stats');
    if (res.ok) {
      const stats = await res.json();
      clipsEl.textContent = stats.total_clips_played || 0;
      timeEl.textContent = stats.total_playback_time_formatted || '0s';
      todayEl.textContent = `${stats.clips_today || 0} clips`;
      sessionEl.textContent = stats.session_duration_formatted || '0s';
    }
  } catch (e) {
    console.error('Stats error:', e);
  }
}

if (resetStatsBtn) {
  resetStatsBtn.addEventListener('click', async () => {
    const ok = await confirmDialog('Réinitialiser les statistiques ?');
    if (!ok) return;
    try {
      await fetch('/stats/reset', { method: 'POST' });
      loadStats();
    } catch (e) {
      showToast('Erreur reset stats', true);
    }
  });
}

loadHistory();
loadExports();
loadStats();
loadBatchStatus();
setInterval(loadHistory, 10000);
setInterval(loadExports, 10000);
setInterval(loadStats, 5000);
setInterval(loadBatchStatus, 1000);

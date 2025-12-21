const mainPlayer = document.getElementById('main-player');

// Streaming centralisé
let ws = null;
let isConnected = false;
let playbackSpeed = 1.0;
let syncPosition = 0;
let syncDuration = 0;
let lastSyncTime = 0;
let isSyncing = false;
let hls = null;
let lastStallRecover = 0;
let initialLiveSyncDone = false;
let stallTimestamps = [];
let stallRestarting = false;

// Statistiques - enregistrement seulement (pas d'affichage)
let currentClipDuration = 0;

function resetVideoLayout() {
    mainPlayer.style.width = '100%';
    mainPlayer.style.height = '100%';
    mainPlayer.style.left = '0';
    mainPlayer.style.top = '0';
    mainPlayer.style.transform = 'none';
    mainPlayer.style.objectFit = 'cover';
}

function registerStall() {
    const now = Date.now();
    stallTimestamps.push(now);
    // Garder une fenêtre glissante de 10s
    stallTimestamps = stallTimestamps.filter((t) => now - t < 10000);
    return stallTimestamps.length;
}

function liveEdgePosition() {
    if (hls && typeof hls.liveSyncPosition === 'number') {
        return hls.liveSyncPosition;
    }
    try {
        const seekable = mainPlayer.seekable;
        if (seekable && seekable.length) {
            return seekable.end(seekable.length - 1);
        }
    } catch (_) {}
    return null;
}

function restartHls(delay = 300) {
    if (stallRestarting) return;
    stallRestarting = true;
    try {
        if (hls) {
            hls.destroy();
        }
    } catch (_) {}
    hls = null;
    setTimeout(() => {
        stallRestarting = false;
        startHlsStream();
    }, delay);
}

function startHlsStream() {
    const src = '/stream/stream.m3u8';
    resetVideoLayout();
    initialLiveSyncDone = false;
    lastStallRecover = 0;
    stallTimestamps = [];
    if (window.Hls && Hls.isSupported()) {
        hls = new Hls({
            liveDurationInfinity: true,
            lowLatencyMode: false,
            maxBufferLength: 8,
            maxMaxBufferLength: 16,
            liveSyncDurationCount: 2,
            liveMaxLatencyDurationCount: 5,
            nudgeOffset: 0.1,
            nudgeMaxRetry: 5,
            fragLoadingTimeOut: 15000,
            fragLoadingMaxRetry: 3,
            fragLoadingRetryDelay: 1000,
            startPosition: -1,
            autoStartLoad: true
        });
        hls.loadSource(src);
        hls.attachMedia(mainPlayer);
        hls.on(Hls.Events.MEDIA_ATTACHED, () => {
            try { hls.startLoad(-1); } catch (_) {}
        });
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
            mainPlayer.play().catch(() => {});
        });
        hls.on(Hls.Events.LEVEL_LOADED, (event, data) => {
            if ((data.details && (data.details.live || data.details.type === 'EVENT')) && !initialLiveSyncDone) {
                const edge = hls.liveSyncPosition ?? data.details.edge ?? data.details.totalduration ?? 0;
                if (Number.isFinite(edge)) {
                    mainPlayer.currentTime = Math.max(0, edge - 0.5);
                }
                initialLiveSyncDone = true;
                mainPlayer.play().catch(() => {});
            }
        });
        hls.on(Hls.Events.ERROR, (event, data) => {
            console.warn('HLS error', data);
            // Tentatives de récupération non fatales (buffer stall, petites erreurs réseau)
            if (data.details === Hls.ErrorDetails.BUFFER_STALLED_ERROR) {
                const now = Date.now();
                if (now - lastStallRecover > 3000) {
                    lastStallRecover = now;
                    const edge = liveEdgePosition();
                    try {
                        const b = mainPlayer.buffered;
                        if (b && b.length) {
                            const end = b.end(b.length - 1);
                            mainPlayer.currentTime = Math.max(0, end - 0.5);
                        } else if (edge !== null) {
                            mainPlayer.currentTime = Math.max(0, edge - 0.5);
                        }
                    } catch (_) {}
                    try { hls.startLoad(-1); } catch (_) {}
                    mainPlayer.play().catch(() => {});
                }
                const stalls = registerStall();
                if (stalls >= 3) {
                    restartHls(200);
                    return;
                }
            }
            if (data.fatal) {
                switch (data.type) {
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        try { hls.startLoad(-1); } catch (_) {}
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        try { hls.recoverMediaError(); } catch (_) {}
                        break;
                    default:
                        restartHls(300);
                        break;
                }
            }
        });
    } else if (mainPlayer.canPlayType('application/vnd.apple.mpegurl')) {
        mainPlayer.src = src;
    } else {
        mainPlayer.src = src;
    }
    mainPlayer.muted = true;
    mainPlayer.play().catch(() => {});
}
// Enregistrer les statistiques quand un clip se termine
async function recordClipPlayed(duration) {
    try {
        await fetch('/stats/record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration: duration })
        });
    } catch (e) {
        console.log('Could not record stats', e);
    }
}

async function loadPlayerSettings() {
    try {
        const res = await fetch('/settings');
        if (res.ok) {
            const s = await res.json();
            const newSpeed = s.playback_speed || 1.0;
            
            // Update speed via WebSocket si connecté
            if (isConnected && Math.abs(playbackSpeed - newSpeed) > 0.01) {
                playbackSpeed = newSpeed;
                if (ws) {
                    ws.send(JSON.stringify({ type: "speed", speed: newSpeed }));
                }
            }
        }
    } catch (e) {
        console.log('Could not load settings, using defaults', e);
    }
}

// Poll settings every 2 seconds to allow real-time updates
setInterval(loadPlayerSettings, 2000);

// ===== WEBSOCKET STREAMING =====

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log('WebSocket connecté');
        isConnected = true;
        // Demander l'état actuel
        ws.send(JSON.stringify({ type: "get_state" }));
    };
    
    ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleStreamingMessage(message);
        } catch (e) {
            console.error('Erreur parsing message WebSocket:', e);
        }
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
    
    ws.onclose = () => {
        console.log('WebSocket déconnecté, reconnexion...');
        isConnected = false;
        // Reconnexion après 3 secondes
        setTimeout(connectWebSocket, 3000);
    };
}

function handleStreamingMessage(message) {
    const type = message.type;
    
    switch (type) {
        case 'state':
            // On ne change pas la source HLS ; on peut juste aligner la vitesse si besoin
            playbackSpeed = message.playback_speed || 1.0;
            mainPlayer.playbackRate = playbackSpeed;
            // Corriger un éventuel drift si on a la position
            if (typeof message.position === 'number' && !Number.isNaN(message.position)) {
                const drift = Math.abs((mainPlayer.currentTime || 0) - message.position);
                if (drift > 1.5) {
                    mainPlayer.currentTime = message.position;
                }
            }
            break;
            
        case 'video_change':
            // La diffusion HLS est continue : ignorer les changements directs de fichier
            break;
            
        case 'play':
            if (mainPlayer.paused) {
                mainPlayer.play().catch(e => console.log('Play failed:', e));
            }
            syncPosition = message.position || mainPlayer.currentTime;
            lastSyncTime = message.timestamp || Date.now() / 1000;
            break;
            
        case 'pause':
            if (!mainPlayer.paused) {
                mainPlayer.pause();
            }
            syncPosition = message.position || mainPlayer.currentTime;
            lastSyncTime = message.timestamp || Date.now() / 1000;
            break;
            
        case 'seek':
            syncPosition = message.position || 0;
            mainPlayer.currentTime = syncPosition;
            lastSyncTime = message.timestamp || Date.now() / 1000;
            break;
            
        case 'speed':
            playbackSpeed = message.speed || 1.0;
            mainPlayer.playbackRate = playbackSpeed;
            break;
    }
}

function loadVideo(url, duration) {
    const currentSrc = mainPlayer.src || '';
    if (!currentSrc || currentSrc !== url) {
        mainPlayer.src = url;
    }
    syncDuration = duration || 0;
    currentClipDuration = duration || 0;
    syncPosition = 0;
    mainPlayer.playbackRate = playbackSpeed;
    resetVideoLayout();
    
    mainPlayer.addEventListener('loadedmetadata', () => {
        if (syncDuration === 0) {
            syncDuration = mainPlayer.duration || 0;
            currentClipDuration = syncDuration;
        }
        syncVideoPosition();
    }, { once: true });
}

function syncVideoPosition() {
    if (!isConnected || !ws) return;
    
    isSyncing = true;
    
    // Demander l'état actuel périodiquement
    const syncInterval = setInterval(() => {
        if (!isConnected || !ws) {
            clearInterval(syncInterval);
            isSyncing = false;
            return;
        }
        
        ws.send(JSON.stringify({ type: "get_state" }));
    }, 1000); // Synchronisation toutes les secondes
    
    // Nettoyer après 5 secondes
    setTimeout(() => {
        clearInterval(syncInterval);
        isSyncing = false;
    }, 5000);
}

// Écouter les événements du lecteur et les envoyer au serveur
mainPlayer.addEventListener('play', () => {
    if (isConnected && ws) {
        ws.send(JSON.stringify({ type: "play" }));
    }
});

mainPlayer.addEventListener('pause', () => {
    if (isConnected && ws) {
        ws.send(JSON.stringify({ type: "pause" }));
    }
});

mainPlayer.addEventListener('seeked', () => {
    // Ne pas renvoyer au serveur pour éviter des boucles de seek
});

mainPlayer.addEventListener('error', () => {
    console.log("Video error, le serveur va générer une nouvelle vidéo");
    // Le serveur détectera l'erreur et générera une nouvelle vidéo
});

// La génération de clips est maintenant gérée par le serveur via WebSocket
// Le serveur génère automatiquement le prochain clip quand nécessaire

// Initial Load
async function initialLoad() {
    await loadPlayerSettings();
    startHlsStream();
    
    // Se connecter au WebSocket pour le streaming synchronisé
    connectWebSocket();
    
    // Le serveur génère automatiquement le premier clip au démarrage
    // et le diffuse via WebSocket
}

initialLoad();

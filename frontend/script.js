const mainPlayer = document.getElementById('main-player');

// Streaming centralisé
let ws = null;
let isConnected = false;
let minReplays = 1;
let playbackSpeed = 1.0;
let playCountForCurrent = 0;
let syncPosition = 0;
let syncDuration = 0;
let lastSyncTime = 0;
let isSyncing = false;
let isLooping = false; // Flag pour éviter les boucles multiples

// Statistiques - enregistrement seulement (pas d'affichage)
let currentClipDuration = 0;
let screenOrientation = "auto";

// Appliquer l'orientation de l'écran avec rotation
function applyScreenOrientation(orientation) {
    screenOrientation = orientation;
    document.body.className = document.body.className.replace(/orientation-\w+/g, '');
    
    if (orientation === "auto") {
        // Détection automatique basée sur les dimensions de la vidéo
        if (mainPlayer.videoWidth && mainPlayer.videoHeight) {
            const aspectRatio = mainPlayer.videoWidth / mainPlayer.videoHeight;
            // Si la vidéo est en portrait (hauteur > largeur), la faire tourner
            if (aspectRatio < 1) {
                // Vidéo portrait : rotation de 90°
                mainPlayer.style.width = '100vh';
                mainPlayer.style.height = '100vw';
                mainPlayer.style.left = '50%';
                mainPlayer.style.top = '50%';
                mainPlayer.style.transform = 'translate(-50%, -50%) rotate(90deg)';
                mainPlayer.style.objectFit = 'cover';
            } else {
                // Vidéo paysage : pas de rotation
                mainPlayer.style.width = '100%';
                mainPlayer.style.height = '100%';
                mainPlayer.style.left = '0';
                mainPlayer.style.top = '0';
                mainPlayer.style.transform = 'rotate(0deg)';
                mainPlayer.style.objectFit = 'cover';
            }
        } else {
            // Par défaut, pas de rotation
            mainPlayer.style.width = '100%';
            mainPlayer.style.height = '100%';
            mainPlayer.style.left = '0';
            mainPlayer.style.top = '0';
            mainPlayer.style.transform = 'rotate(0deg)';
        }
    } else {
        // Appliquer la classe d'orientation (le CSS gère la rotation)
        document.body.classList.add(`orientation-${orientation}`);
        
        // Appliquer les styles directement pour plus de contrôle
        if (orientation === "portrait" || orientation === "portrait-right") {
            mainPlayer.style.width = '100vh';
            mainPlayer.style.height = '100vw';
            mainPlayer.style.left = '50%';
            mainPlayer.style.top = '50%';
            mainPlayer.style.transform = 'translate(-50%, -50%) rotate(90deg)';
            mainPlayer.style.objectFit = 'cover';
        } else if (orientation === "portrait-left") {
            mainPlayer.style.width = '100vh';
            mainPlayer.style.height = '100vw';
            mainPlayer.style.left = '50%';
            mainPlayer.style.top = '50%';
            mainPlayer.style.transform = 'translate(-50%, -50%) rotate(-90deg)';
            mainPlayer.style.objectFit = 'cover';
        } else if (orientation === "upside-down") {
            mainPlayer.style.width = '100%';
            mainPlayer.style.height = '100%';
            mainPlayer.style.left = '0';
            mainPlayer.style.top = '0';
            mainPlayer.style.transform = 'rotate(180deg)';
            mainPlayer.style.objectFit = 'cover';
        } else {
            // Landscape (par défaut)
            mainPlayer.style.width = '100%';
            mainPlayer.style.height = '100%';
            mainPlayer.style.left = '0';
            mainPlayer.style.top = '0';
            mainPlayer.style.transform = 'rotate(0deg)';
            mainPlayer.style.objectFit = 'cover';
        }
    }
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
            minReplays = s.min_replays_before_next || 1;
            const newSpeed = s.playback_speed || 1.0;
            
            // Update speed via WebSocket si connecté
            if (isConnected && Math.abs(playbackSpeed - newSpeed) > 0.01) {
                playbackSpeed = newSpeed;
                if (ws) {
                    ws.send(JSON.stringify({ type: "speed", speed: newSpeed }));
                }
            }
            
            // Appliquer l'orientation
            const newOrientation = s.screen_orientation || "auto";
            if (newOrientation !== screenOrientation) {
                applyScreenOrientation(newOrientation);
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
            // État initial ou mise à jour
            // Toujours essayer de charger la vidéo (loadVideo décidera si elle doit être ignorée)
            if (message.current_video) {
                loadVideo(message.current_video, message.duration);
            }
            syncPosition = message.position || 0;
            syncDuration = message.duration || 0;
            lastSyncTime = message.timestamp || Date.now() / 1000;
            
            // Synchroniser la lecture (mais pas si on est en train de boucler)
            if (!isLooping) {
                if (message.is_playing && mainPlayer.paused) {
                    mainPlayer.play().catch(e => console.log('Play failed:', e));
                } else if (!message.is_playing && !mainPlayer.paused) {
                    mainPlayer.pause();
                }
            }
            
            // Synchroniser la position (mais pas si on est en train de boucler)
            if (!isSyncing && !isLooping) {
                syncVideoPosition();
            }
            
            playbackSpeed = message.playback_speed || 1.0;
            mainPlayer.playbackRate = playbackSpeed;
            break;
            
        case 'video_change':
            // Toujours essayer de charger la nouvelle vidéo (loadVideo décidera si elle doit être ignorée)
            loadVideo(message.url, message.duration);
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
    // Vérifier si c'est vraiment la même vidéo qu'on est en train de boucler
    const currentSrc = mainPlayer.src || '';
    
    // Extraire le nom de fichier de chaque URL pour comparaison
    const getVideoName = (src) => {
        if (!src) return '';
        try {
            const urlObj = new URL(src, window.location.origin);
            return urlObj.pathname.split('/').pop();
        } catch {
            return src.split('/').pop();
        }
    };
    
    const currentVideoName = getVideoName(currentSrc);
    const newVideoName = getVideoName(url);
    const isSameVideo = currentSrc && (currentSrc === url || currentVideoName === newVideoName || 
                                        currentSrc.includes(newVideoName) || url.includes(currentVideoName));
    
    // Si c'est la même vidéo et qu'on est en train de boucler (playCount < minReplays), ne pas recharger
    if (isSameVideo && playCountForCurrent < minReplays) {
        console.log('Ignoring video change: looping current video', playCountForCurrent, '/', minReplays);
        return;
    }
    
    // C'est une nouvelle vidéo ou on a fini de boucler, charger la vidéo
    console.log('Loading video:', url, 'playCount:', playCountForCurrent, 'minReplays:', minReplays);
    
    // Réinitialiser le compteur de répétitions et le flag de boucle quand une nouvelle vidéo est chargée
    playCountForCurrent = 0;
    isLooping = false;
    
    mainPlayer.src = url;
    syncDuration = duration || 0;
    currentClipDuration = duration || 0;
    syncPosition = 0;
    mainPlayer.playbackRate = playbackSpeed;
    applyScreenOrientation(screenOrientation);
    
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
    if (isConnected && ws && !isSyncing) {
        ws.send(JSON.stringify({ 
            type: "seek", 
            position: mainPlayer.currentTime 
        }));
    }
});

mainPlayer.addEventListener('timeupdate', () => {
    // Gérer la boucle manuellement si nécessaire
    if (syncDuration > 0 && mainPlayer.currentTime >= syncDuration - 0.1 && !isLooping) {
        // La vidéo a atteint la fin
        if (playCountForCurrent < minReplays) {
            // Relancer la vidéo pour la boucle
            isLooping = true;
            playCountForCurrent += 1;
            mainPlayer.currentTime = 0;
            mainPlayer.play().catch(() => {
                isLooping = false;
            });
            // Réinitialiser le flag après un court délai
            setTimeout(() => {
                isLooping = false;
            }, 100);
            return;
        } else {
            // On a fini de boucler (playCountForCurrent >= minReplays)
            // Enregistrer les statistiques et permettre au serveur de changer de vidéo
            isLooping = true;
            if (currentClipDuration > 0) {
                recordClipPlayed(currentClipDuration * minReplays);
            }
            
            // Ajouter à l'historique
            if (mainPlayer.src) {
                fetch('/history/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: mainPlayer.src,
                        duration: currentClipDuration * minReplays
                    })
                }).catch(e => console.log('Could not add to history:', e));
            }
            
            // Réinitialiser le compteur et permettre au serveur de changer de vidéo
            playCountForCurrent = 0;
            setTimeout(() => {
                isLooping = false;
            }, 100);
        }
    }
    
    // Réinitialiser le flag si on n'est plus à la fin
    if (syncDuration > 0 && mainPlayer.currentTime < syncDuration - 0.5) {
        isLooping = false;
    }
    
    // Vérifier si on approche de la fin et demander la prochaine vidéo
    if (syncDuration > 0 && mainPlayer.currentTime >= syncDuration - 2) {
        // Le serveur gère automatiquement la transition via la boucle de streaming
    }
});

mainPlayer.addEventListener('ended', () => {
    // L'événement 'ended' peut être déclenché même si on gère la boucle dans timeupdate
    // On le gère ici aussi pour être sûr
    if (playCountForCurrent < minReplays) {
        playCountForCurrent += 1;
        mainPlayer.currentTime = 0;
        mainPlayer.play().catch(() => {});
        return;
    }
    
    // Si on arrive ici, c'est que la boucle est terminée (géré dans timeupdate normalement)
    playCountForCurrent = 0;
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
    // Appliquer l'orientation initiale
    applyScreenOrientation(screenOrientation);
    
    // Se connecter au WebSocket pour le streaming synchronisé
    connectWebSocket();
    
    // Le serveur génère automatiquement le premier clip au démarrage
    // et le diffuse via WebSocket
}

initialLoad();

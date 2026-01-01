const effectChainContainer = document.getElementById('effect-chain');
const contextMenu = document.getElementById('context-menu');
const nodeCanvas = document.getElementById('node-canvas');
const nodeStage = document.getElementById('node-stage');
const nodeViewport = document.getElementById('node-viewport');
const connectionsSvg = document.getElementById('node-links');
const resetViewportBtn = document.getElementById('reset-viewport');
const quickEffectSelect = document.getElementById('quick-effect-select');
const addEffectBtn = document.getElementById('add-effect-btn');
const chainListView = document.getElementById('chain-list-view');
const viewToggle = document.getElementById('view-toggle');
const viewListBtn = document.getElementById('view-list-btn');
const viewCanvasBtn = document.getElementById('view-canvas-btn');
const canvasHint = document.getElementById('canvas-hint');

// Détection iOS
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || 
              (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isMobile = window.innerWidth <= 900 || isIOS;

// Helper pour attacher les événements compatibles iOS
function attachIOSCompatibleEvent(element, eventType, handler) {
    if (!element) return;
    
    // Sur iOS, utiliser touchend en plus de click pour une meilleure réactivité
    if (isIOS) {
        let touchStartTime = 0;
        let touchMoved = false;
        
        element.addEventListener('touchstart', (e) => {
            touchStartTime = Date.now();
            touchMoved = false;
        }, { passive: true });
        
        element.addEventListener('touchmove', () => {
            touchMoved = true;
        }, { passive: true });
        
        element.addEventListener('touchend', (e) => {
            const touchDuration = Date.now() - touchStartTime;
            // Si le touch est rapide (< 300ms) et n'a pas bougé, considérer comme un clic
            if (touchDuration < 300 && !touchMoved) {
                e.preventDefault();
                e.stopPropagation();
                handler(e);
            }
        }, { passive: false });
    }
    
    // Toujours attacher click aussi pour desktop et fallback
    // Sur iOS, on peut avoir un double déclenchement, donc on utilise un flag
    let clickHandled = false;
    element.addEventListener(eventType, (e) => {
        if (isIOS && clickHandled) {
            clickHandled = false;
            return;
        }
        if (isIOS) {
            // Sur iOS, le click peut se déclencher après touchend, on l'ignore si c'est trop rapide
            setTimeout(() => { clickHandled = false; }, 100);
            clickHandled = true;
        }
        handler(e);
    });
}
const cleanupStorageBtn = document.getElementById('cleanup-storage');
const cleanupUploadsBtn = document.getElementById('cleanup-uploads');
const killGenerationBtn = document.getElementById('kill-generation');
const pauseGenerationBtn = document.getElementById('pause-generation');
const generateNowResetTimerBtn = document.getElementById('generate-now-reset-timer');
const generatePreviewBtn = document.getElementById('generate-preview');
let generationPaused = false;

let previewOverlay = null;
let previewVideo = null;
let previewHls = null;

let availableEffects = [];
let effectChain = [];
let toastTimer = null;
let pendingNodePosition = null;

const VIEWPORT_WIDTH = 3200;
const VIEWPORT_HEIGHT = 1800;
const viewportState = { x: 40, y: 40, scale: 0.9 };
let isPanning = false;
let panStart = null;
let selectedOutput = null;
const INPUT_PORTS = {
    'mix': ['A', 'B'],
    'transfer-motion': ['A', 'B'],
    'time-shift': ['In'],
    'chopper': ['A', 'B', 'C', 'D'],
};
let nodeIdCounter = 0;
let logPanel = null;
let logContent = null;
let logStatus = null;
let progressDl = null;
let progressProc = null;
let progressStatus = null;
let progressTimer = null;
let previewProgressTimer = null;
let logsTimer = null;
let processedNodes = new Set(); // Set des nœuds qui ont été traités
let currentProcessingNode = null; // Nœud actuellement en traitement
let previousWorkers = new Set(); // Pour suivre les workers précédents
let confirmOverlay = null;

function confirmDialog(message) {
    return new Promise((resolve) => {
        if (confirmOverlay) confirmOverlay.remove();
        confirmOverlay = document.createElement('div');
        confirmOverlay.style.position = 'fixed';
        confirmOverlay.style.inset = '0';
        confirmOverlay.style.background = 'rgba(0,0,0,0.5)';
        confirmOverlay.style.backdropFilter = 'blur(2px)';
        confirmOverlay.style.display = 'grid';
        confirmOverlay.style.placeItems = 'center';
        confirmOverlay.style.zIndex = '6000';

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
                <button class="btn secondary sm" id="confirm-cancel">Annuler</button>
                <button class="btn sm" id="confirm-ok">OK</button>
            </div>
        `;
        confirmOverlay.appendChild(box);
        document.body.appendChild(confirmOverlay);

        const done = (result) => {
            confirmOverlay.remove();
            confirmOverlay = null;
            resolve(result);
        };
        box.querySelector('#confirm-cancel').onclick = () => done(false);
        box.querySelector('#confirm-ok').onclick = () => done(true);
    });
}

function makeNodeId() {
    nodeIdCounter += 1;
    return `node_${Date.now()}_${nodeIdCounter}`;
}

const SOURCE_YOUTUBE = {
    name: 'source',
    description: 'Source YouTube / playlist',
    type: 'source-youtube',
    options: [
        { name: 'keywords', label: 'Keywords (comma separated)', type: 'text' },
        { name: 'playlist_url', label: 'Playlist URL (optional)', type: 'text' },
        { name: 'video_quality', label: 'Video Quality', type: 'select', options: ['best', '1080p', '720p', '480p'], default: 'best' },
        { name: 'include_reels', label: 'Include Shorts/Reels', type: 'bool', default: true },
        { name: 'duration', label: 'Duration (seconds)', type: 'int', min: 1, max: 60, default: 5 },
        { name: 'duration_variation', label: 'Duration Variation (+/-)', type: 'int', min: 0, max: 30, default: 0 },
        { name: 'playback_speed', label: 'Playback Speed', type: 'float', min: 0.1, max: 4.0, step: 0.1, default: 1.0 },
    ]
};

const SOURCE_LOCAL = {
    name: 'source-local',
    description: 'Source fichier local',
    type: 'source-local',
    options: []
};

function clampScale(value) {
    return Math.min(1.9, Math.max(0.45, value));
}

// Convertir scale (0.45-1.9) en pourcentage (45-190)
function scaleToPercent(scale) {
    return Math.round(scale * 100);
}

// Convertir pourcentage (45-190) en scale (0.45-1.9)
function percentToScale(percent) {
    return percent / 100;
}

function applyViewportTransform() {
    if (!nodeViewport) return;
    
    // Utiliser transform3d pour l'accélération matérielle sur iOS
    const transform = `translate3d(${viewportState.x}px, ${viewportState.y}px, 0) scale(${viewportState.scale})`;
    nodeViewport.style.transform = transform;
    nodeViewport.style.webkitTransform = transform;
    
    // Faire suivre la grille infinie avec background-position
    if (nodeStage) {
        // Calculer la position de la grille en fonction du panning et du zoom
        // La grille doit suivre le panning pour donner l'impression d'être infinie
        const gridSize = 48;
        // Calculer le modulo pour créer l'effet de répétition infinie
        const bgX = viewportState.x % gridSize;
        const bgY = viewportState.y % gridSize;
        // Ajuster pour le zoom (la grille doit rester à la même taille visuelle)
        const scaledX = bgX / viewportState.scale;
        const scaledY = bgY / viewportState.scale;
        nodeStage.style.backgroundPosition = `${scaledX}px ${scaledY}px`;
        nodeStage.style.backgroundSize = `${gridSize / viewportState.scale}px ${gridSize / viewportState.scale}px`;
    }
    
    // Mettre à jour le slider de zoom si présent (sans déclencher l'event)
    const zoomSlider = document.getElementById('zoom-slider');
    const zoomValue = document.getElementById('zoom-value');
    if (zoomSlider && zoomValue && !zoomSlider.matches(':active')) {
        const percent = scaleToPercent(viewportState.scale);
        if (parseInt(zoomSlider.value, 10) !== percent) {
            zoomSlider.value = percent;
            zoomValue.textContent = `${percent}%`;
        }
    }
    
    // Forcer la mise à jour des connexions après le zoom
    updateConnections();
}

function resetViewport() {
    viewportState.x = 40;
    viewportState.y = 40;
    viewportState.scale = 0.9;
    applyViewportTransform();
    
    // Mettre à jour le slider de zoom si présent
    const zoomSlider = document.getElementById('zoom-slider');
    const zoomValue = document.getElementById('zoom-value');
    if (zoomSlider && zoomValue) {
        const percent = scaleToPercent(viewportState.scale);
        zoomSlider.value = percent;
        zoomValue.textContent = `${percent}%`;
    }
}

function clientToWorld(clientX, clientY) {
    if (!nodeStage) return { x: clientX, y: clientY };
    const rect = nodeStage.getBoundingClientRect();
    const localX = (clientX - rect.left - viewportState.x) / viewportState.scale;
    const localY = (clientY - rect.top - viewportState.y) / viewportState.scale;
    return { x: localX, y: localY };
}

function getDefaultPosition(idx = 0) {
    const colSpacing = 360;
    const rowSpacing = 160;
    const col = idx % 4;
    const row = Math.floor(idx / 4);
    return { x: 120 + col * colSpacing, y: 120 + row * rowSpacing };
}

function ensurePositions() {
    effectChain.forEach((entry, idx) => {
        if (!entry.position) {
            entry.position = getDefaultPosition(idx);
        }
        if (!entry.id) entry.id = makeNodeId();
        if (!entry.inputs) entry.inputs = [];
    });
}

function normalizeChainData(chain) {
    if (!Array.isArray(chain)) return [];
    return chain.map((entry, idx) => {
        const normalized = {
            id: entry.id || makeNodeId(),
            name: entry.name,
            options: entry.options || {},
            inputs: Array.isArray(entry.inputs) ? entry.inputs.slice() : [],
            position: entry.position || getDefaultPosition(idx),
        };
        return normalized;
    });
}

function initViewport() {
    if (nodeViewport) {
        nodeViewport.style.width = `${VIEWPORT_WIDTH}px`;
        nodeViewport.style.height = `${VIEWPORT_HEIGHT}px`;
    }
    resetViewport();
    setupPanning();
    setupZoom();
}

function getViewportCenterPosition() {
    if (!nodeStage) return getDefaultPosition(effectChain.length);
    const rect = nodeStage.getBoundingClientRect();
    return clientToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
}

function getMaxInputs(effectName) {
    if (effectName === 'mix') return 2;
    if (effectName === 'transfer-motion') return 2;
    if (effectName === 'chopper') return 4;
    if (effectName === 'source' || effectName === 'source-local' || effectName === 'noise') return 0;
    return 1;
}

function getEffectDefinition(name) {
    return availableEffects.find(e => e.name === name);
}

function createOptionInput(effectName, optDef, value) {
    const wrapper = document.createElement('div');
    wrapper.className = 'option-item';

    const label = document.createElement('label');
    label.textContent = optDef.label || optDef.name;
    if (optDef.tooltip) label.title = optDef.tooltip;

    if (optDef.type === 'bool') {
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.effect = effectName;
        input.dataset.option = optDef.name;
        input.dataset.type = optDef.type;
        input.checked = Boolean(value);
        if (optDef.tooltip) input.title = optDef.tooltip;
        wrapper.appendChild(label);
        wrapper.appendChild(input);
        return wrapper;
    }

    if (optDef.type === 'int' || optDef.type === 'float') {
        let min = optDef.min !== undefined ? optDef.min : (optDef.type === 'int' ? 0 : 0);
        let max = optDef.max !== undefined ? optDef.max : (optDef.type === 'int' ? 100 : 1);
        const step = optDef.step !== undefined ? optDef.step : (optDef.type === 'int' ? 1 : 0.01);
        const startVal = value !== undefined ? value : (optDef.default !== undefined ? optDef.default : min);

        const sliderWrap = document.createElement('div');
        sliderWrap.className = 'slider-wrap';

        const input = document.createElement('input');
        input.type = 'range';
        input.className = 'range-input';
        input.min = min;
        input.max = max;
        input.step = step;
        input.value = startVal;
        input.dataset.effect = effectName;
        input.dataset.option = optDef.name;
        input.dataset.type = optDef.type;
        if (optDef.tooltip) input.title = optDef.tooltip;

        const chip = document.createElement('span');
        chip.className = 'value-chip';
        chip.textContent = startVal;

        input.addEventListener('input', () => {
            chip.textContent = input.value;
        });

        const startInlineEdit = (target) => {
            const editor = document.createElement('input');
            editor.type = 'number';
            editor.className = 'manual-edit';
            editor.value = input.value;
            editor.step = step;
            editor.style.width = '80px';

            const finish = (commit) => {
                if (commit) {
                    const parsed = parseFloat(editor.value);
                    if (!Number.isNaN(parsed)) {
                        let val = optDef.type === 'int' ? Math.round(parsed) : parsed;
                        if (val < min) { min = val; input.min = val; }
                        if (val > max) { max = val; input.max = val; }
                        input.value = val;
                        chip.textContent = val;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }
                target.style.display = '';
                editor.remove();
            };

            editor.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    finish(true);
                }
                if (e.key === 'Escape') {
                    e.preventDefault();
                    finish(false);
                }
            });
            editor.addEventListener('blur', () => finish(true));

            target.style.display = 'none';
            target.parentNode.insertBefore(editor, target);
            editor.focus();
            editor.select();
        };

        label.addEventListener('click', () => startInlineEdit(chip));
        chip.addEventListener('click', () => startInlineEdit(chip));

        // Prevent node dragging when interacting with slider
        input.addEventListener('pointerdown', (e) => {
            e.stopPropagation();
            const card = input.closest('.effect-item');
            if (card) card.draggable = false;
        });
        input.addEventListener('pointerup', (e) => {
            e.stopPropagation();
            const card = input.closest('.effect-item');
            if (card) card.draggable = true;
        });
        input.addEventListener('pointerleave', () => {
            const card = input.closest('.effect-item');
            if (card) card.draggable = true;
        });

        sliderWrap.appendChild(input);
        sliderWrap.appendChild(chip);

        wrapper.appendChild(label);
        wrapper.appendChild(sliderWrap);
        return wrapper;
    }

    if (optDef.type === 'select') {
        const select = document.createElement('select');
        select.dataset.effect = effectName;
        select.dataset.option = optDef.name;
        select.dataset.type = optDef.type;
        if (optDef.tooltip) select.title = optDef.tooltip;

        const opts = optDef.options || [];
        opts.forEach(optVal => {
            const option = document.createElement('option');
            option.value = optVal;
            option.textContent = optVal;
            if (optVal === value) option.selected = true;
            select.appendChild(option);
        });

        wrapper.appendChild(label);
        wrapper.appendChild(select);
        return wrapper;
    }

    const input = document.createElement('input');
    input.type = 'text';
    input.dataset.effect = effectName;
    input.dataset.option = optDef.name;
    input.dataset.type = optDef.type;
    input.value = value ?? '';

    wrapper.appendChild(label);
    wrapper.appendChild(input);
    return wrapper;
}

function buildOptions(effectName, options) {
    const def = getEffectDefinition(effectName);
    const container = document.createElement('div');
    container.className = 'effect-options';
    if (!def || !def.options) return container;

    def.options.forEach(opt => {
        const val = options && options[opt.name] !== undefined ? options[opt.name] : opt.default;
        container.appendChild(createOptionInput(effectName, opt, val));
    });
    return container;
}

function getCardById(nodeId) {
    if (!effectChainContainer) return null;
    return effectChainContainer.querySelector(`[data-node-id="${nodeId}"]`);
}

function getEntryById(nodeId) {
    return effectChain.find(e => e.id === nodeId);
}

function getPortPositionById(nodeId, selector, portIndex = 0) {
    const card = getCardById(nodeId);
    if (!card) return null;
    const ports = card.querySelectorAll(selector);
    const port = ports[portIndex] || ports[0];
    const entry = getEntryById(nodeId);
    if (!port || !entry || !entry.position) return null;
    
    // Calcul simple : position du nœud + offset du port
    // Les positions sont déjà en coordonnées monde (viewport)
    return {
        x: entry.position.x + port.offsetLeft + (port.offsetWidth / 2),
        y: entry.position.y + port.offsetTop + (port.offsetHeight / 2),
    };
}

function updateConnections() {
    if (!connectionsSvg) return;
    connectionsSvg.setAttribute('viewBox', `0 0 ${VIEWPORT_WIDTH} ${VIEWPORT_HEIGHT}`);
    connectionsSvg.innerHTML = '';
    const frag = document.createDocumentFragment();

    effectChain.forEach(entry => {
        (entry.inputs || []).forEach((inputId, idx) => {
            const start = getPortPositionById(inputId, '.port-out', 0);
            const end = getPortPositionById(entry.id, '.port-in', idx);
            if (!start || !end) return;

            const dx = Math.max(90, Math.abs(end.x - start.x) * 0.4);
            const d = `M ${start.x} ${start.y} C ${start.x + dx} ${start.y} ${end.x - dx} ${end.y} ${end.x} ${end.y}`;

            const shadow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            shadow.setAttribute('d', d);
            shadow.setAttribute('class', 'node-link-shadow');
            frag.appendChild(shadow);

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', d);
            path.setAttribute('class', 'node-link-path');
            frag.appendChild(path);
        });
    });

    connectionsSvg.appendChild(frag);
    
    // Sur iOS, forcer le reflow pour s'assurer que le rendu est mis à jour
    if (isIOS && nodeViewport) {
        // Force reflow
        void nodeViewport.offsetHeight;
    }
}

function connectNodes(fromId, toId, portIndex = 0) {
    if (!fromId || !toId || fromId === toId) return;
    const target = getEntryById(toId);
    if (!target) return;
    const maxInputs = getMaxInputs(target.name);
    if (maxInputs === 0) return;
    const inputs = Array.isArray(target.inputs) ? target.inputs.slice() : [];
    while (inputs.length < maxInputs) inputs.push(null);
    inputs[portIndex] = fromId;
    // dédupliquer en gardant la position
    for (let i = 0; i < inputs.length; i++) {
        if (inputs[i] === fromId && i !== portIndex) {
            inputs[i] = null;
        }
    }
    target.inputs = inputs.slice(0, maxInputs);
    renderChain();
}

function clearSelectedOutput() {
    selectedOutput = null;
    document.querySelectorAll('.port.port-selected').forEach(p => p.classList.remove('port-selected'));
}

function startNodeDrag(e, card, nodeId) {
    if (e.button !== 0) return;
    const entry = getEntryById(nodeId);
    if (!entry) return;
    ensurePositions();
    const start = { x: entry.position.x, y: entry.position.y };
    const pointerStart = { x: e.clientX, y: e.clientY };
    card.classList.add('dragging');
    if (nodeStage) nodeStage.classList.add('dragging-node');

    const onMove = (ev) => {
        const dx = (ev.clientX - pointerStart.x) / viewportState.scale;
        const dy = (ev.clientY - pointerStart.y) / viewportState.scale;
        entry.position = { x: start.x + dx, y: start.y + dy };
        const transform = `translate3d(${entry.position.x}px, ${entry.position.y}px, 0)`;
        card.style.transform = transform;
        card.style.webkitTransform = transform;
        updateConnections();
    };

    const onUp = () => {
        card.classList.remove('dragging');
        if (nodeStage) nodeStage.classList.remove('dragging-node');
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
    };

    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
}

function enableNodeDragging(card, idx) {
    const header = card.querySelector('.effect-header');
    const handle = card.querySelector('.drag-handle');
    if (!header) return;

    // Sur mobile, désactiver le drag & drop, utiliser les boutons de réorganisation
    if (isMobile) {
        return;
    }

    header.addEventListener('pointerdown', (e) => {
        if (e.target.closest('select') || e.target.closest('input') || e.target.closest('button')) return;
        const nodeId = card.dataset.nodeId;
        startNodeDrag(e, card, nodeId);
    });
}

function setupPanning() {
    if (!nodeStage || !nodeViewport) return;
    
    // Sur iOS/mobile, désactiver le pan sur le canvas, utiliser scroll natif
    if (isMobile) {
        nodeStage.style.overflow = 'auto';
        nodeStage.style.cursor = 'default';
        return;
    }

    nodeStage.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        if (e.target.closest('.effect-item')) return;
        isPanning = true;
        nodeStage.classList.add('panning');
        panStart = { x: e.clientX, y: e.clientY, vx: viewportState.x, vy: viewportState.y };
    });

    document.addEventListener('pointermove', (e) => {
        if (!isPanning || !panStart) return;
        const dx = e.clientX - panStart.x;
        const dy = e.clientY - panStart.y;
        viewportState.x = panStart.vx + dx;
        viewportState.y = panStart.vy + dy;
        applyViewportTransform();
    });

    document.addEventListener('pointerup', () => {
        isPanning = false;
        if (nodeStage) nodeStage.classList.remove('panning');
    });
}

function setupZoom() {
    if (!nodeStage) return;
    
    // Sur mobile, désactiver le zoom à la molette
    if (isMobile) return;
    
    nodeStage.addEventListener('wheel', (e) => {
        if (!nodeViewport) return;
        // Désactiver le zoom si le menu contextuel est visible
        if (contextMenu && contextMenu.classList.contains('visible')) {
            return;
        }
        e.preventDefault();
        const { clientX, clientY } = e;
        const rect = nodeStage.getBoundingClientRect();
        const before = clientToWorld(clientX, clientY);
        const delta = e.deltaY * -0.001;
        const newScale = clampScale(viewportState.scale * (1 + delta));
        viewportState.scale = newScale;
        viewportState.x = (clientX - rect.left) - before.x * viewportState.scale;
        viewportState.y = (clientY - rect.top) - before.y * viewportState.scale;

        applyViewportTransform();
    }, { passive: false });
}
function renderChainList() {
    debugLog(`renderChainList appelé, effectChain.length = ${effectChain.length}`, 'info');
    if (!chainListView) {
        debugLog('ERREUR: chainListView est null!', 'error');
        return;
    }
    chainListView.innerHTML = '';
    ensurePositions();
    debugLog(`Rendu de ${effectChain.length} nœuds dans la liste`, 'info');

    effectChain.forEach((entry, idx) => {
        const item = document.createElement('div');
        item.className = 'chain-list-item';
        item.dataset.nodeId = entry.id;

        const header = document.createElement('div');
        header.className = 'chain-list-item-header';

        const orderControls = document.createElement('div');
        orderControls.className = 'chain-order-controls';

        const moveUpBtn = document.createElement('button');
        moveUpBtn.className = 'btn ghost sm chain-order-btn';
        moveUpBtn.textContent = '↑';
        moveUpBtn.disabled = idx === 0;
        attachIOSCompatibleEvent(moveUpBtn, 'click', () => {
            if (idx > 0) {
                [effectChain[idx - 1], effectChain[idx]] = [effectChain[idx], effectChain[idx - 1]];
                renderChain();
                renderChainList();
            }
        });

        const moveDownBtn = document.createElement('button');
        moveDownBtn.className = 'btn ghost sm chain-order-btn';
        moveDownBtn.textContent = '↓';
        moveDownBtn.disabled = idx === effectChain.length - 1;
        attachIOSCompatibleEvent(moveDownBtn, 'click', () => {
            if (idx < effectChain.length - 1) {
                [effectChain[idx], effectChain[idx + 1]] = [effectChain[idx + 1], effectChain[idx]];
                renderChain();
                renderChainList();
            }
        });

        orderControls.appendChild(moveUpBtn);
        orderControls.appendChild(moveDownBtn);

        const title = document.createElement('div');
        title.className = 'effect-title';
        title.textContent = entry.name;
        title.style.flex = '1';
        title.style.cursor = 'pointer';
        attachIOSCompatibleEvent(title, 'click', () => {
            item.classList.toggle('expanded');
        });

        const select = document.createElement('select');
        select.style.flex = '1';
        availableEffects.forEach(effect => {
            const opt = document.createElement('option');
            opt.value = effect.name;
            opt.textContent = `${effect.name} - ${effect.description}`;
            if (effect.name === entry.name) opt.selected = true;
            select.appendChild(opt);
        });

        const isSource = entry.name === 'source';
        const isLocalSource = entry.name === 'source-local';
        if (isSource || isLocalSource) {
            select.disabled = true;
        }

        select.addEventListener('change', (e) => {
            const newName = e.target.value;
            entry.name = newName;
            entry.options = {};
            entry.inputs = entry.inputs || [];
            const maxInputs = getMaxInputs(newName);
            if (entry.inputs.length > maxInputs) entry.inputs = entry.inputs.slice(0, maxInputs);
            title.textContent = newName;
            const optsContainer = item.querySelector('.chain-list-item-options');
            if (optsContainer) optsContainer.replaceWith(buildOptions(newName, {}));
            wireOptionInputs(item, entry.id);
            renderChain();
            renderChainList();
        });

        const removeBtn = document.createElement('button');
        removeBtn.className = 'close-btn';
        removeBtn.textContent = '×';
        attachIOSCompatibleEvent(removeBtn, 'click', () => {
            removeEffectById(entry.id);
        });

        header.appendChild(orderControls);
        header.appendChild(title);
        header.appendChild(select);
        header.appendChild(removeBtn);

        const optionsContainer = document.createElement('div');
        optionsContainer.className = 'chain-list-item-options';

        if (isSource) {
            const options = buildOptions(entry.name, entry.options || {});
            optionsContainer.appendChild(options);
        } else if (isLocalSource) {
            const localBody = document.createElement('div');
            localBody.className = 'effect-options';
            const localFileInputId = `local-file-input-${entry.id}`;
            const uploadFileBtnId = `upload-file-btn-${entry.id}`;
            const uploadStatusId = `upload-status-${entry.id}`;
            const localFileSelectId = `local-file-select-${entry.id}`;
            localBody.innerHTML = `
                <div class="source-grid">
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label>Fichier local (upload)</label>
                        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                            <input type="file" id="${localFileInputId}" accept="video/*" style="flex: 1; min-width: 180px;">
                            <button class="btn secondary" id="${uploadFileBtnId}">Upload</button>
                        </div>
                        <div id="${uploadStatusId}" style="margin-top: 5px; font-size: 12px; color: var(--muted);"></div>
                        <select id="${localFileSelectId}" style="margin-top: 8px; width: 100%;">
                            <option value="">-- Sélectionner un fichier --</option>
                        </select>
                    </div>
                </div>
            `;
            optionsContainer.appendChild(localBody);
            wireLocalSourceNode(item, entry.id, entry.options || {});
        } else {
            const options = buildOptions(entry.name, entry.options || {});
            optionsContainer.appendChild(options);
        }

        if (!isLocalSource) {
            wireOptionInputs(item, entry.id);
        }

        item.appendChild(header);
        item.appendChild(optionsContainer);
        chainListView.appendChild(item);
        debugLog(`Nœud "${entry.name}" ajouté à la liste (index ${idx})`, 'info');
    });
    
    debugLog(`Total: ${chainListView.children.length} éléments dans la liste`, 'success');
}

function renderChain() {
    if (!effectChainContainer) return;
    effectChainContainer.innerHTML = '';
    ensurePositions();

    effectChain.forEach((entry) => {
        const card = document.createElement('div');
        card.className = 'effect-item';
        card.dataset.nodeId = entry.id;
        card.dataset.nodeName = entry.name; // Ajouter le nom du nœud pour faciliter la correspondance
        // Utiliser transform3d pour l'accélération matérielle sur iOS
        const transform = `translate3d(${entry.position.x}px, ${entry.position.y}px, 0)`;
        card.style.transform = transform;
        card.style.webkitTransform = transform;
        card.style.willChange = 'transform';

        const isSource = entry.name === 'source';
        const isLocalSource = entry.name === 'source-local';

        const header = document.createElement('div');
        header.className = 'effect-header';

        const portsCol = document.createElement('div');
        portsCol.style.display = 'flex';
        portsCol.style.flexDirection = 'column';
        portsCol.style.gap = '6px';

        const portLabels = INPUT_PORTS[entry.name] || (isSource || isLocalSource ? [] : ['In']);
        portLabels.forEach((label, idx) => {
            const wrap = document.createElement('div');
            wrap.style.display = 'flex';
            wrap.style.alignItems = 'center';
            wrap.style.gap = '6px';
            const portIn = document.createElement('div');
            portIn.className = 'port port-in';
            portIn.dataset.portIndex = idx;
            wrap.appendChild(portIn);
            const lbl = document.createElement('span');
            lbl.className = 'small';
            lbl.style.color = 'var(--muted)';
            lbl.textContent = label;
            wrap.appendChild(lbl);
            portsCol.appendChild(wrap);
        });
        if (portLabels.length === 0) {
            portsCol.style.visibility = 'hidden';
        }

        const handle = document.createElement('div');
        handle.className = 'drag-handle';
        handle.textContent = '⋮⋮';

        const title = document.createElement('div');
        title.className = 'effect-title';

        const select = document.createElement('select');
        availableEffects.forEach(effect => {
            const opt = document.createElement('option');
            opt.value = effect.name;
            opt.textContent = `${effect.name} - ${effect.description}`;
            if (effect.name === entry.name) opt.selected = true;
            select.appendChild(opt);
        });

        title.textContent = entry.name;

        if (isSource || isLocalSource) {
            select.disabled = true;
        }

        select.addEventListener('change', (e) => {
            const newName = e.target.value;
            entry.name = newName;
            entry.options = {};
            entry.inputs = entry.inputs || [];
            const maxInputs = getMaxInputs(newName);
            if (entry.inputs.length > maxInputs) entry.inputs = entry.inputs.slice(0, maxInputs);
            title.textContent = newName;
            const optsContainer = card.querySelector('.effect-options');
            if (optsContainer) optsContainer.replaceWith(buildOptions(newName, {}));
            wireOptionInputs(card, entry.id);
            renderChain();
        });

        const controls = document.createElement('div');
        controls.className = 'effect-controls';

        const removeBtn = document.createElement('button');
        removeBtn.className = 'close-btn';
        removeBtn.textContent = '×';
        removeBtn.title = 'Remove effect';
        removeBtn.onclick = () => {
            removeEffectById(entry.id);
        };

        controls.appendChild(removeBtn);

        const portOut = document.createElement('div');
        portOut.className = 'port port-out';
        portOut.title = 'Sortie (cliquer pour connecter)';
        portOut.addEventListener('click', (e) => {
            e.stopPropagation();
            clearSelectedOutput();
            selectedOutput = entry.id;
            portOut.classList.add('port-selected');
            showToast('Sortie sélectionnée : cliquez sur une entrée', false);
        });

        header.appendChild(portsCol);
        header.appendChild(handle);
        header.appendChild(title);
        header.appendChild(select);
        header.appendChild(controls);
        header.appendChild(portOut);
        card.appendChild(header);

        if (isSource) {
            const options = buildOptions(entry.name, entry.options || {});
            card.appendChild(options);
        } else if (isLocalSource) {
            const localBody = document.createElement('div');
            localBody.className = 'effect-options';
            const localFileInputId = `local-file-input-${entry.id}`;
            const uploadFileBtnId = `upload-file-btn-${entry.id}`;
            const uploadStatusId = `upload-status-${entry.id}`;
            const localFileSelectId = `local-file-select-${entry.id}`;
            localBody.innerHTML = `
                <div class="source-grid">
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label>Fichier local (upload)</label>
                        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                            <input type="file" id="${localFileInputId}" accept="video/*" style="flex: 1; min-width: 180px;">
                            <button class="btn secondary" id="${uploadFileBtnId}">Upload</button>
                        </div>
                        <div id="${uploadStatusId}" style="margin-top: 5px; font-size: 12px; color: var(--muted);"></div>
                        <select id="${localFileSelectId}" style="margin-top: 8px; width: 100%;">
                            <option value="">-- Sélectionner un fichier --</option>
                        </select>
                    </div>
                </div>
            `;
            card.appendChild(localBody);
            // Charger la liste des fichiers uploadés et configurer les contrôles
            wireLocalSourceNode(card, entry.id, entry.options || {});
        } else {
            const options = buildOptions(entry.name, entry.options || {});
            card.appendChild(options);
        }

        if (!isLocalSource) {
            wireOptionInputs(card, entry.id);
        }

        enableNodeDragging(card, entry.id);
        card.querySelectorAll('.port-in').forEach(port => {
            port.title = 'Entrée (cliquer après avoir sélectionné une sortie)';
            port.addEventListener('click', (e) => {
                e.stopPropagation();
                if (!selectedOutput) {
                    showToast('Sélectionnez d\'abord une sortie', true);
                    return;
                }
                const idx = Number(port.dataset.portIndex || 0);
                connectNodes(selectedOutput, entry.id, idx);
                clearSelectedOutput();
            });
        });
        effectChainContainer.appendChild(card);
    });
    updateConnections();
    wirePlaybackSpeedControls();
    // Mettre à jour les états visuels des nœuds après le rendu
    updateNodeVisualStates();
    if (chainListView && chainListView.classList.contains('active')) {
        renderChainList();
    }
}

function wireOptionInputs(card, nodeId) {
    const entry = getEntryById(nodeId);
    if (!entry) return;
    // Support à la fois pour les cartes canvas et les items liste
    const inputs = card.querySelectorAll('.effect-options input, .effect-options select, .chain-list-item-options input, .chain-list-item-options select');
    inputs.forEach(input => {
        const type = input.dataset.type;
        const optName = input.dataset.option;
        const handler = () => {
            let val;
            if (type === 'bool') {
                val = input.checked;
            } else if (type === 'int') {
                const parsed = parseInt(input.value, 10);
                val = Number.isNaN(parsed) ? 0 : parsed;
            } else if (type === 'float') {
                const parsed = parseFloat(input.value);
                val = Number.isNaN(parsed) ? 0 : parsed;
            } else {
                val = input.value;
            }
            if (!entry.options) entry.options = {};
            entry.options[optName] = val;
        };

        const eventName = (type === 'bool' || type === 'select') ? 'change' : 'input';
        input.addEventListener(eventName, handler);
    });
}

function removeEffectById(nodeId) {
    const idx = effectChain.findIndex(e => e.id === nodeId);
    if (idx === -1) return;
    effectChain.splice(idx, 1);
    // Purger les connexions vers ce nœud
    effectChain.forEach(e => {
        e.inputs = (e.inputs || []).filter(i => i !== nodeId);
    });
    renderChain();
    if (chainListView && chainListView.classList.contains('active')) {
        renderChainList();
    }
}

function addEffect(name, positionOverride = null) {
    if (name === 'source-local' && effectChain.some(e => e.name === 'source-local')) {
        showToast('Le nœud source local existe déjà.', true);
        return;
    }
    const def = getEffectDefinition(name) || availableEffects[0];
    if (!def) return;
    const position = positionOverride || getViewportCenterPosition() || getDefaultPosition(effectChain.length);
    effectChain.push({ id: makeNodeId(), name: def.name, options: {}, position, inputs: [] });
    renderChain();
    if (chainListView && chainListView.classList.contains('active')) {
        renderChainList();
    }
}

function populateQuickEffectPicker() {
    if (!quickEffectSelect) return;
    quickEffectSelect.innerHTML = '<option value=\"\">Sélectionnez un effet...</option>';
    availableEffects.forEach(effect => {
        const opt = document.createElement('option');
        opt.value = effect.name;
        opt.textContent = `${effect.name} — ${effect.description}`;
        quickEffectSelect.appendChild(opt);
    });
}

async function loadPresets() {
    try {
        const res = await fetch('/presets');
        const presets = await res.json();
        const select = document.getElementById('preset-select');
        const selectToolbar = document.getElementById('preset-select-toolbar');
        
        const updateSelect = (sel) => {
            if (sel) {
                sel.innerHTML = '<option value="">Select a preset...</option>';
                presets.forEach(name => {
                    const opt = document.createElement('option');
                    opt.value = name;
                    opt.textContent = name;
                    sel.appendChild(opt);
                });
            }
        };
        
        updateSelect(select);
        updateSelect(selectToolbar);
    } catch (e) {
        console.error('Failed to load presets', e);
    }
}

// Fonctions réutilisables pour les presets
async function loadPresetByName(name) {
    if (!name) return;
    try {
        const res = await fetch(`/presets/${name}`);
        if (!res.ok) throw new Error('Failed to load');
        const chain = await res.json();
        effectChain = normalizeChainData(chain);
        renderChain();
        if (chainListView && chainListView.classList.contains('active')) {
            renderChainList();
        }
        // Synchroniser les selects
        const select = document.getElementById('preset-select');
        const selectToolbar = document.getElementById('preset-select-toolbar');
        if (select) select.value = name;
        if (selectToolbar) selectToolbar.value = name;
        showToast(`Preset "${name}" loaded`);
    } catch (e) {
        showToast('Error loading preset', true);
    }
}

async function savePresetByName(name) {
    if (!name || !name.trim()) {
        showToast('Enter a preset name', true);
        return;
    }
    
    // Collect current chain (positions + liens)
    const entryById = {};
    effectChain.forEach(e => { entryById[e.id] = e; });

    const cards = Array.from(effectChainContainer.querySelectorAll('.effect-item'));
    const chainToSave = cards.map((card, idx) => {
        const nodeId = card.dataset.nodeId;
        const select = card.querySelector('select');
        const effectName = select ? select.value : (entryById[nodeId]?.name || '');
        const opts = {};
        
        // Pour les nœuds source-local, récupérer le fichier sélectionné
        if (effectName === 'source-local') {
            const localFileSelect = card.querySelector(`#local-file-select-${nodeId}`);
            if (localFileSelect && localFileSelect.value) {
                opts.local_file = localFileSelect.value;
            }
        } else {
            // Pour les autres nœuds, collecter les options normalement
            card.querySelectorAll('.effect-options input, .effect-options select').forEach(input => {
                const type = input.dataset.type;
                let val;
                if (type === 'bool') {
                    val = input.checked;
                } else if (type === 'int') {
                    val = parseInt(input.value);
                } else if (type === 'float') {
                    val = parseFloat(input.value);
                } else {
                    val = input.value;
                }
                if (input.dataset.option) {
                    opts[input.dataset.option] = val;
                }
            });
        }
        
        const prev = entryById[nodeId] || {};
        return {
            id: nodeId || makeNodeId(),
            name: effectName,
            options: opts,
            inputs: Array.isArray(prev.inputs) ? prev.inputs.slice() : [],
            position: prev.position || getDefaultPosition(idx),
        };
    });

    try {
        await fetch(`/presets/${name}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(chainToSave)
        });
        showToast(`Preset "${name}" saved`);
        loadPresets(); // Refresh list
        return true;
    } catch (e) {
        showToast('Error saving preset', true);
        return false;
    }
}

async function deletePresetByName(name) {
    if (!name) return;
    const ok = await confirmDialog(`Supprimer le preset "${name}" ?`);
    if (!ok) return;
    
    try {
        await fetch(`/presets/${name}`, { method: 'DELETE' });
        showToast(`Preset "${name}" deleted`);
        loadPresets();
    } catch (e) {
        showToast('Error deleting preset', true);
    }
}

// Event listeners pour les presets - à attacher après chargement du DOM
function attachPresetListeners() {
    // Anciens boutons dans la card Presets
    const loadPresetBtn = document.getElementById('load-preset');
    if (loadPresetBtn) {
        attachIOSCompatibleEvent(loadPresetBtn, 'click', async () => {
            const name = document.getElementById('preset-select').value;
            await loadPresetByName(name);
        });
    }

    const savePresetBtn = document.getElementById('save-preset');
    if (savePresetBtn) {
        attachIOSCompatibleEvent(savePresetBtn, 'click', async () => {
            const name = document.getElementById('new-preset-name').value.trim();
            if (await savePresetByName(name)) {
                document.getElementById('new-preset-name').value = '';
            }
        });
    }

    const deletePresetBtn = document.getElementById('delete-preset');
    if (deletePresetBtn) {
        attachIOSCompatibleEvent(deletePresetBtn, 'click', async () => {
            const name = document.getElementById('preset-select').value;
            await deletePresetByName(name);
        });
    }
    
    // Nouveaux boutons dans la toolbar
    const loadPresetToolbarBtn = document.getElementById('load-preset-toolbar');
    if (loadPresetToolbarBtn) {
        attachIOSCompatibleEvent(loadPresetToolbarBtn, 'click', async () => {
            const name = document.getElementById('preset-select-toolbar').value;
            await loadPresetByName(name);
        });
    }

    const savePresetToolbarBtn = document.getElementById('save-preset-toolbar');
    if (savePresetToolbarBtn) {
        attachIOSCompatibleEvent(savePresetToolbarBtn, 'click', async () => {
            const name = prompt('Enter preset name:');
            if (name) {
                await savePresetByName(name.trim());
            }
        });
    }

    const deletePresetToolbarBtn = document.getElementById('delete-preset-toolbar');
    if (deletePresetToolbarBtn) {
        attachIOSCompatibleEvent(deletePresetToolbarBtn, 'click', async () => {
            const name = document.getElementById('preset-select-toolbar').value;
            await deletePresetByName(name);
        });
    }

    const newPresetToolbarBtn = document.getElementById('new-preset-toolbar');
    if (newPresetToolbarBtn) {
        attachIOSCompatibleEvent(newPresetToolbarBtn, 'click', async () => {
            // Vérifier si la chaîne actuelle a des éléments
            const hasChanges = effectChain.length > 0 && effectChain.some(e => e.name !== 'source');
            
            if (hasChanges) {
                const shouldSave = await confirmDialog('Voulez-vous sauvegarder le preset actuel avant de créer un nouveau ?');
                if (shouldSave) {
                    const name = prompt('Enter preset name:');
                    if (name && name.trim()) {
                        await savePresetByName(name.trim());
                    } else {
                        // Si l'utilisateur annule la sauvegarde, demander confirmation
                        const proceed = await confirmDialog('Créer un nouveau preset sans sauvegarder ? Les modifications actuelles seront perdues.');
                        if (!proceed) return;
                    }
                }
            }
            
            // Réinitialiser avec seulement une source YouTube
            effectChain = [{ 
                id: makeNodeId(), 
                name: 'source', 
                options: {}, 
                inputs: [], 
                position: getDefaultPosition(0) 
            }];
            
            renderChain();
            if (chainListView && chainListView.classList.contains('active')) {
                renderChainList();
            }
            
            // Réinitialiser les selects
            const select = document.getElementById('preset-select');
            const selectToolbar = document.getElementById('preset-select-toolbar');
            if (select) select.value = '';
            if (selectToolbar) selectToolbar.value = '';
            
            showToast('Nouveau preset créé');
        });
    }
}

function randomizeChain() {
    if (!availableEffects.length) return;
    
    effectChain = [{ id: makeNodeId(), name: 'source', options: {}, inputs: [], position: getDefaultPosition(0) }]; // Toujours démarrer avec YouTube

    const usableEffects = availableEffects.filter(e => e.name !== 'source' && e.name !== 'source-local');
    const length = Math.floor(Math.random() * 5); // 0 à 4 effets supplémentaires

    for (let i = 0; i < length; i++) {
        const effect = usableEffects[Math.floor(Math.random() * usableEffects.length)];
        if (!effect) continue;
        const options = {};
        
        // Randomize options
        if (effect.options) {
            effect.options.forEach(opt => {
                if (opt.type === 'int') {
                    const min = opt.min !== undefined ? opt.min : 0;
                    const max = opt.max !== undefined ? opt.max : 100;
                    options[opt.name] = Math.floor(Math.random() * (max - min + 1)) + min;
                } else if (opt.type === 'float') {
                    const min = opt.min !== undefined ? opt.min : 0;
                    const max = opt.max !== undefined ? opt.max : 1;
                    options[opt.name] = Math.random() * (max - min) + min;
                } else if (opt.type === 'bool') {
                    options[opt.name] = Math.random() > 0.5;
                } else if (opt.type === 'select' && opt.options && opt.options.length) {
                    options[opt.name] = opt.options[Math.floor(Math.random() * opt.options.length)];
                } else if (opt.type === 'text' && opt.name.toLowerCase().includes('color')) {
                     options[opt.name] = '#' + Math.floor(Math.random()*16777215).toString(16).padStart(6, '0');
                }
            });
        }
        
        effectChain.push({ id: makeNodeId(), name: effect.name, options, inputs: [], position: getDefaultPosition(effectChain.length) });
    }
    renderChain();
    if (chainListView && chainListView.classList.contains('active')) {
        renderChainList();
    }
    showToast('Random chain generated');
}

// Tous les listeners sont maintenant attachés dans attachButtonListeners() appelé dans DOMContentLoaded

initViewport();

function wirePlaybackSpeedControls() {
    const playbackSpeedInput = document.getElementById('playback-speed');
    const playbackSpeedVal = document.getElementById('playback-speed-val');
    if (!playbackSpeedInput || !playbackSpeedVal) return;

    playbackSpeedInput.oninput = (e) => {
        playbackSpeedVal.textContent = e.target.value;
    };
    // Auto-save speed on change for real-time update
    playbackSpeedInput.onchange = () => {
        const saveBtn = document.getElementById('save-settings');
        if (saveBtn) saveBtn.click();
    };
}

function wireModeToggles() {
    const autosaveToggle = async () => {
        try {
            await saveSettings();
            showToast('Modes sauvegardés');
        } catch (e) {
            console.error('Mode toggle save failed', e);
            showToast('Échec sauvegarde modes', true);
        }
    };
    const randomPresetModeEl = document.getElementById('random-preset-mode');
    if (randomPresetModeEl) {
        randomPresetModeEl.addEventListener('change', autosaveToggle);
    }
    const freestyleModeEl = document.getElementById('freestyle-mode');
    if (freestyleModeEl) {
        freestyleModeEl.addEventListener('change', autosaveToggle);
        freestyleModeEl.addEventListener('change', () => {
            const row = document.getElementById('freestyle-keywords-row');
            if (row) {
                row.style.display = freestyleModeEl.checked ? '' : 'none';
            }
        });
        // init display
        const row = document.getElementById('freestyle-keywords-row');
        if (row) row.style.display = freestyleModeEl.checked ? '' : 'none';
    }
}

async function loadSettings() {
    try {
        debugLog('Début du chargement des settings...', 'info');
        console.log('Loading settings from backend...');
        const [settingsRes, effectsRes] = await Promise.all([
            fetch('/settings', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Cache-Control': 'no-cache'
                }
            }).catch(err => {
                console.error('Error fetching settings:', err);
                throw err;
            }),
            fetch('/effects', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Cache-Control': 'no-cache'
                }
            }).catch(err => {
                console.error('Error fetching effects:', err);
                throw err;
            })
        ]);

        if (!settingsRes.ok) {
            throw new Error(`Settings fetch failed: ${settingsRes.status} ${settingsRes.statusText}`);
        }
        if (!effectsRes.ok) {
            throw new Error(`Effects fetch failed: ${effectsRes.status} ${effectsRes.statusText}`);
        }

        const settings = await settingsRes.json();
        availableEffects = await effectsRes.json();
        console.log('Settings loaded:', settings);
        console.log('Effects loaded:', availableEffects.length);
        debugLog(`Settings chargés: ${JSON.stringify(settings).substring(0, 100)}...`, 'success');
        debugLog(`Effects chargés: ${availableEffects.length} effets`, 'success');
        
        // appendLog peut ne pas être défini au moment du chargement initial
        try {
            if (typeof appendLog === 'function') {
                appendLog('Settings: chargés');
            }
        } catch (e) {
            console.log('appendLog not available yet');
        }
        if (!availableEffects.find(e => e.name === SOURCE_YOUTUBE.name)) {
            availableEffects.unshift(SOURCE_YOUTUBE);
        }
        if (!availableEffects.find(e => e.name === SOURCE_LOCAL.name)) {
            availableEffects.splice(1, 0, SOURCE_LOCAL);
        }
        populateQuickEffectPicker();

        // Build effect chain (prefer new field, fallback to legacy) before hydrating inputs
        if (settings.effect_chain && settings.effect_chain.length) {
            effectChain = normalizeChainData(settings.effect_chain);
            debugLog(`Chaîne chargée depuis effect_chain: ${effectChain.length} nœuds`, 'info');
        } else {
            effectChain = (settings.active_effects || []).map(name => ({
                id: makeNodeId(),
                name,
                options: (settings.effect_options && settings.effect_options[name]) ? settings.effect_options[name] : {},
                inputs: []
            }));
            debugLog(`Chaîne créée depuis active_effects: ${effectChain.length} nœuds`, 'info');
        }
        
        debugLog(`EffectChain après normalisation: ${effectChain.length} nœuds`, 'info');
        debugLog(`Nœuds: ${effectChain.map(e => e.name).join(', ')}`, 'info');
        // Ne pas forcer l'ajout d'un nœud source si:
        // - un nœud source-local existe déjà
        // - un nœud source (YouTube) existe déjà
        // - la chaîne commence par un nœud autonome comme "noise" qui génère sa propre source
        const hasSource = effectChain.find(e => e.name === 'source' || e.name === 'source-local');
        const hasAutonomousSource = effectChain.length > 0 && effectChain[0].name === 'noise';
        if (!hasSource && !hasAutonomousSource) {
            effectChain.unshift({ name: 'source', options: {} });
        }
        // Si local_file existe dans les settings mais pas dans la chaîne, l'ajouter au nœud source-local
        if (settings.local_file) {
            const localSourceNode = effectChain.find(e => e.name === 'source-local');
            if (localSourceNode) {
                if (!localSourceNode.options) localSourceNode.options = {};
                localSourceNode.options.local_file = settings.local_file;
            } else {
                effectChain.push({ name: 'source-local', options: { local_file: settings.local_file } });
            }
        }

        // Initialiser la vue avant de rendre la chaîne
        if (typeof setupViewToggle === 'function') {
            setupViewToggle();
        }
        
        debugLog(`Rendu de la chaîne: ${effectChain.length} nœuds`, 'info');
        renderChain();
        
        // S'assurer que la vue liste est rendue si active
        if (chainListView && chainListView.classList.contains('active')) {
            debugLog('Rendu de la vue liste', 'info');
            renderChainList();
        } else {
            debugLog('Vue liste non active, canvas devrait être affiché', 'warn');
        }
        
        // Populate general inputs now that the source card exists
        const keywordsEl = document.getElementById('keywords');
        if (keywordsEl) keywordsEl.value = settings.keywords || '';

        const playlistEl = document.getElementById('playlist-url');
        if (playlistEl) playlistEl.value = settings.playlist_url || '';

        const durationEl = document.getElementById('duration');
        if (durationEl) durationEl.value = settings.duration;

        const durationVarEl = document.getElementById('duration-variation');
        if (durationVarEl) durationVarEl.value = settings.duration_variation;

        const videoQualityEl = document.getElementById('video-quality');
        if (videoQualityEl) videoQualityEl.value = settings.video_quality || 'best';

        const includeReelsEl = document.getElementById('include-reels');
        if (includeReelsEl) includeReelsEl.checked = settings.include_reels !== false;

        const speed = settings.playback_speed || 1.0;
        const playbackSpeedInput = document.getElementById('playback-speed');
        const playbackSpeedVal = document.getElementById('playback-speed-val');
        if (playbackSpeedInput) playbackSpeedInput.value = speed;
        if (playbackSpeedVal) playbackSpeedVal.textContent = speed;

        const randomPresetModeEl = document.getElementById('random-preset-mode');
        if (randomPresetModeEl) randomPresetModeEl.checked = settings.random_preset_mode || false;

        const freestyleModeEl = document.getElementById('freestyle-mode');
        if (freestyleModeEl) freestyleModeEl.checked = settings.freestyle_mode || false;

        // Batch Settings
        const batchModeEl = document.getElementById('batch-mode');
        if (batchModeEl) batchModeEl.checked = settings.batch_mode || false;
        const batchSizeEl = document.getElementById('batch-size');
        if (batchSizeEl) batchSizeEl.value = settings.batch_size || 3;
        const batchIntervalEl = document.getElementById('batch-interval');
        if (batchIntervalEl) batchIntervalEl.value = settings.batch_interval || 5;

        const fsRow = document.getElementById('freestyle-keywords-row');
        if (fsRow) fsRow.style.display = (settings.freestyle_mode ? '' : 'none');
        const fsKw = document.getElementById('freestyle-keywords');
        if (fsKw) fsKw.value = settings.keywords || '';

        wirePlaybackSpeedControls();
        wireModeToggles();
        loadPresets(); // Load presets on startup
    } catch (e) {
        console.error('Error loading settings:', e);
        console.error('Error details:', e.message, e.stack);
        debugLog(`ERREUR chargement settings: ${e.message || e}`, 'error');
        debugLog(`Stack: ${e.stack || 'N/A'}`, 'error');
        
        // appendLog peut ne pas être défini au moment du chargement initial
        try {
            if (typeof appendLog === 'function') {
                appendLog(`Settings load error: ${e && e.message ? e.message : e}`);
            }
        } catch (logErr) {
            console.log('appendLog not available for error logging');
        }
        
        // Afficher une erreur visible à l'utilisateur
        try {
            if (typeof showToast === 'function') {
                showToast('Erreur lors du chargement des paramètres. Nouvelle tentative...', true);
            } else {
                // Fallback si showToast n'est pas encore disponible
                alert('Erreur lors du chargement des paramètres. Vérifiez le panneau de debug.');
            }
        } catch (toastErr) {
            console.log('showToast not available');
        }
        
        // Réessayer après 2 secondes (max 3 tentatives)
        if (!loadSettings.retryCount) {
            loadSettings.retryCount = 0;
        }
        if (loadSettings.retryCount < 3) {
            loadSettings.retryCount++;
            debugLog(`Nouvelle tentative ${loadSettings.retryCount}/3 dans 2s...`, 'warn');
            setTimeout(() => {
                console.log(`Retrying to load settings... (attempt ${loadSettings.retryCount})`);
                loadSettings();
            }, 2000);
        } else {
            console.error('Max retries reached for loadSettings');
            debugLog('Nombre maximum de tentatives atteint!', 'error');
        }
    }
}

function collectSettings() {
    const getEl = (id) => document.getElementById(id);
    const val = (id, def = '') => {
        const el = getEl(id);
        return el ? el.value : def;
    };
    const boolVal = (id, def = false) => {
        const el = getEl(id);
        return el ? !!el.checked : def;
    };
    const intVal = (id, def = 0) => {
        const el = getEl(id);
        if (!el) return def;
        const n = parseInt(el.value, 10);
        return Number.isNaN(n) ? def : n;
    };
    const floatVal = (id, def = 0) => {
        const el = getEl(id);
        if (!el) return def;
        const n = parseFloat(el.value);
        return Number.isNaN(n) ? def : n;
    };

    const cards = Array.from(effectChainContainer.querySelectorAll('.effect-item'));
    const chainToSave = cards.map(card => {
        const select = card.querySelector('select');
        const name = select ? select.value : 'source';
        const opts = {};
        
        // Pour les nœuds source-local, récupérer le fichier sélectionné
        if (name === 'source-local') {
            const nodeId = card.dataset.nodeId;
            const localFileSelect = card.querySelector(`#local-file-select-${nodeId}`);
            if (localFileSelect && localFileSelect.value) {
                opts.local_file = localFileSelect.value;
            }
        } else {
            // Pour les autres nœuds, collecter les options normalement
            card.querySelectorAll('.effect-options input, .effect-options select').forEach(input => {
                const type = input.dataset.type;
                let valOpt;
                if (type === 'bool') {
                    valOpt = input.checked;
                } else if (type === 'int') {
                    valOpt = parseInt(input.value, 10);
                } else if (type === 'float') {
                    valOpt = parseFloat(input.value);
                } else {
                    valOpt = input.value;
                }
                if (input.dataset.option) {
                    opts[input.dataset.option] = valOpt;
                }
            });
        }
        
        const nodeId = card.dataset.nodeId;
        const entryRef = getEntryById(nodeId);
        const pos = entryRef && entryRef.position ? entryRef.position : null;
        const inputs = entryRef && entryRef.inputs ? entryRef.inputs : [];
        const entry = { id: nodeId, name, options: opts, inputs };
        if (pos) entry.position = pos;
        return entry;
    });

    const freestyleKeywords = val('freestyle-keywords', '');
    // Récupérer local_file depuis le nœud source-local dans la chaîne
    let localFileFromChain = null;
    const localSourceNode = chainToSave.find(e => e.name === 'source-local');
    if (localSourceNode && localSourceNode.options && localSourceNode.options.local_file) {
        localFileFromChain = localSourceNode.options.local_file;
    }
    const settings = {
        keywords: boolVal('freestyle-mode', false) ? freestyleKeywords : '',
        playlist_url: val('playlist-url', '') || null,
        local_file: localFileFromChain,
        duration: intVal('duration', 5),
        duration_variation: intVal('duration-variation', 0),
        video_quality: val('video-quality', 'best') || 'best',
        include_reels: boolVal('include-reels', true),
        playback_speed: floatVal('playback-speed', 1.0),
        random_preset_mode: boolVal('random-preset-mode', false),
        freestyle_mode: boolVal('freestyle-mode', false),
        batch_mode: boolVal('batch-mode', false),
        batch_size: intVal('batch-size', 3),
        batch_interval: intVal('batch-interval', 5),
        active_effects: chainToSave.filter(e => e.name !== 'source' && e.name !== 'source-local').map(e => e.name),
        effect_options: {},
        effect_chain: chainToSave
    };
    return settings;
}

// Fonction debugLog pour la console uniquement (pas de panneau visible)
function debugLog(message, type = 'info') {
    // Log uniquement dans la console
    console.log(`[DEBUG ${type.toUpperCase()}]`, message);
}

function appendLog(line) {
    if (!logContent) return;
    const now = new Date();
    const stamp = now.toISOString().split('T')[1].slice(0, 12);
    logContent.textContent += `[${stamp}] ${line}\n`;
    logContent.scrollTop = logContent.scrollHeight;
    
    // Aussi dans le debug panel
    debugLog(line, 'info');
}

function toggleLogPanel(force) {
    if (!logPanel) return;
    const isVisible = logPanel.style.display === 'block' || logPanel.style.display === 'flex';
    const next = force !== undefined ? force : !isVisible;
    logPanel.style.display = next ? 'flex' : 'none';
    if (logStatus) logStatus.textContent = next ? 'ON' : 'OFF';
    if (next) {
        startProgressPoll();
        startLogsPoll();
    } else {
        stopProgressPoll();
        stopLogsPoll();
    }
}

function updatePauseButton() {
    if (!pauseGenerationBtn) return;
    if (generationPaused) {
        pauseGenerationBtn.textContent = '▶️ Reprendre génération';
        pauseGenerationBtn.classList.remove('danger');
        pauseGenerationBtn.classList.add('sm');
    } else {
        pauseGenerationBtn.textContent = '⏸️ Pause génération';
        pauseGenerationBtn.classList.remove('danger');
        pauseGenerationBtn.classList.add('sm');
    }
}

async function checkGenerationStatus() {
    try {
        const res = await fetch('/generation/status');
        if (res.ok) {
            const data = await res.json();
            generationPaused = data.paused || false;
            updatePauseButton();
        }
    } catch (_) {
        // ignore
    }
}

function resetNodeGlows() {
    // Réinitialiser tous les états visuels des nœuds
    processedNodes.clear();
    currentProcessingNode = null;
    updateNodeVisualStates();
}

function updateNodeVisualStates() {
    // Retirer toutes les classes de processing/processed
    const allNodes = document.querySelectorAll('.effect-item');
    allNodes.forEach(node => {
        node.classList.remove('processing', 'processed');
    });
    
    // Appliquer l'état "processed" aux nœuds traités
    processedNodes.forEach(nodeName => {
        const nodes = Array.from(allNodes).filter(node => {
            const nodeId = node.dataset.nodeId;
            if (!nodeId) return false;
            // Trouver l'entrée correspondante dans effectChain
            const entry = effectChain.find(e => e.id === nodeId);
            return entry && entry.name === nodeName;
        });
        nodes.forEach(node => {
            node.classList.add('processed');
        });
    });
    
    // Appliquer l'état "processing" au nœud actuellement en traitement
    if (currentProcessingNode) {
        const nodes = Array.from(allNodes).filter(node => {
            const nodeId = node.dataset.nodeId;
            if (!nodeId) return false;
            const entry = effectChain.find(e => e.id === nodeId);
            return entry && entry.name === currentProcessingNode;
        });
        nodes.forEach(node => {
            node.classList.add('processing');
            // Retirer "processed" si le nœud est en cours de traitement
            node.classList.remove('processed');
        });
    }
}

function renderProgress(state) {
    if (!state) return;
    const stage = state.stage || 'idle';
    const pct = Number(state.percent || 0);
    const msg = state.message || '';
    if (progressStatus) {
        progressStatus.textContent = `${stage} ${msg ? '· ' + msg : ''}`;
    }
    
    // Mettre à jour le nœud en cours de traitement
    const previousProcessingNode = currentProcessingNode;
    if (state.current_node && stage === 'processing') {
        currentProcessingNode = state.current_node;
        // Si on change de nœud, marquer l'ancien comme traité
        if (previousProcessingNode && previousProcessingNode !== currentProcessingNode) {
            processedNodes.add(previousProcessingNode);
        }
    } else if (stage === 'ready' || stage === 'error') {
        // Quand le traitement est terminé, marquer le nœud actuel comme traité
        if (currentProcessingNode) {
            processedNodes.add(currentProcessingNode);
            currentProcessingNode = null;
        }
        // Si on passe à ready, c'est qu'un nouveau clip a été généré - réinitialiser les glow
        if (stage === 'ready') {
            resetNodeGlows();
        }
    } else if (stage === 'idle' || stage === 'preparing') {
        // Réinitialiser quand on démarre une nouvelle génération
        if (stage === 'preparing') {
            resetNodeGlows();
        }
    }
    
    // Mettre à jour les états visuels des nœuds
    updateNodeVisualStates();
    
    if (progressDl && progressProc) {
        let dl = 0, proc = 0;
        if (stage === 'downloading') {
            dl = pct;
            proc = 0;
        } else if (stage === 'processing') {
            dl = 100;
            proc = pct;
        } else if (stage === 'ready') {
            dl = 100; proc = 100;
        } else if (stage === 'error') {
            dl = 0; proc = 0;
        }
        progressDl.style.width = `${Math.max(0, Math.min(100, dl))}%`;
        progressProc.style.width = `${Math.max(0, Math.min(100, proc))}%`;
    }
    const detailsEl = document.getElementById('progress-details');
    if (detailsEl) {
        const lines = [];
        if (state.current_preset) lines.push(`Preset : ${state.current_preset}`);
        if (state.current_file) lines.push(`Fichier : ${state.current_file}`);
        if (state.current_node) lines.push(`Noeud : ${state.current_node}`);
        if (state.steps && Array.isArray(state.steps)) {
            lines.push('Étapes :');
            state.steps.forEach(step => {
                const spct = step.percent !== undefined ? `${Math.round(step.percent)}%` : '';
                lines.push(`- ${step.name}${spct ? ' · '+spct : ''}`);
            });
        }
        detailsEl.textContent = lines.join('\n');
    }
}

async function pollProgressOnce() {
    try {
        const res = await fetch('/progress');
        if (!res.ok) return;
        const state = await res.json();
        renderProgress(state);
    } catch (_) {
        // ignore
    }
}

function startProgressPoll() {
    stopProgressPoll();
    pollProgressOnce();
    progressTimer = setInterval(pollProgressOnce, 1000);
}

function stopProgressPoll() {
    if (progressTimer) {
        clearInterval(progressTimer);
        progressTimer = null;
    }
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
}

let lastWorkerCount = 0;

async function pollWorkersOnce() {
    try {
        const res = await fetch('/workers');
        if (!res.ok) return;
        const data = await res.json();
        const workersList = document.getElementById('workers-list');
        if (!workersList) return;
        
        const workers = Object.entries(data || {});
        const currentWorkerIds = new Set(Object.keys(data || {}));
        const currentWorkerCount = workers.length;
        
        // Si un nouveau worker apparaît (nouveau clip en génération), réinitialiser les glow
        if (currentWorkerCount > lastWorkerCount && lastWorkerCount === 0) {
            // Nouveau clip commence à être généré
            resetNodeGlows();
        }
        lastWorkerCount = currentWorkerCount;
        
        // Si un worker a disparu, réinitialiser les états visuels des nœuds
        const removedWorkers = new Set([...previousWorkers].filter(id => !currentWorkerIds.has(id)));
        if (removedWorkers.size > 0) {
            // Quand un worker est terminé, réinitialiser les états visuels
            processedNodes.clear();
            currentProcessingNode = null;
            updateNodeVisualStates();
        }
        previousWorkers = currentWorkerIds;
        
        if (workers.length === 0) {
            workersList.innerHTML = '<div style="color: var(--muted); font-size: 10px; padding: 8px;">Aucun worker actif</div>';
            return;
        }
        
        workersList.innerHTML = workers.map(([id, worker]) => {
            const typeLabel = worker.type === 'generation' ? 'Génération' : worker.type === 'preview' ? 'Prévisualisation' : worker.type;
            const clipName = worker.clip_name || '(en attente...)';
            const preset = worker.preset || 'chaine editeur';
            const duration = formatDuration(worker.duration || 0);
            return `
                <div class="worker-item">
                    <div>
                        <span class="worker-type">${typeLabel}</span>
                    </div>
                    <div class="worker-info">
                        <span><span class="worker-label">Clip:</span> ${clipName}</span>
                        <span><span class="worker-label">Preset:</span> ${preset}</span>
                        <span><span class="worker-label">Durée:</span> ${duration}</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (_) {
        // ignore
    }
}

async function pollLogsOnce() {
    try {
        const res = await fetch('/logs');
        if (!res.ok) return;
        const data = await res.json();
        if (data && Array.isArray(data.lines) && logContent) {
            logContent.textContent = data.lines.join('\n') + '\n';
            logContent.scrollTop = logContent.scrollHeight;
        }
    } catch (_) {
        // ignore
    }
}

function startLogsPoll() {
    stopLogsPoll();
    pollLogsOnce();
    pollWorkersOnce();
    checkGenerationStatus();
    logsTimer = setInterval(() => {
        pollLogsOnce();
        pollWorkersOnce();
        // Vérifier l'état de la génération toutes les 5 secondes
        if (Math.floor(Date.now() / 1000) % 5 === 0) {
            checkGenerationStatus();
        }
    }, 1000);
}

function stopLogsPoll() {
    if (logsTimer) {
        clearInterval(logsTimer);
        logsTimer = null;
    }
}

async function saveSettings() {
    const settings = collectSettings();
    await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    });
}

// Fonction pour attacher tous les listeners de boutons
function attachButtonListeners() {
    // Bouton save-settings
    const saveSettingsBtn = document.getElementById('save-settings');
    if (saveSettingsBtn) {
        debugLog('Attachement du listener save-settings', 'info');
        attachIOSCompatibleEvent(saveSettingsBtn, 'click', async () => {
            try {
                debugLog('Clic sur Save & Apply détecté', 'info');
                const settings = collectSettings();
                debugLog(`Settings collectés: ${JSON.stringify(settings).substring(0, 200)}...`, 'info');
                appendLog('Settings: envoi /settings');
                debugLog('Envoi POST /settings...', 'info');
                
                const response = await fetch('/settings', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify(settings)
                });
                
                debugLog(`Réponse reçue: ${response.status} ${response.statusText}`, response.ok ? 'success' : 'error');
                
                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }
                
                const result = await response.json();
                debugLog('Sauvegarde réussie!', 'success');
                showToast('Settings saved');
                appendLog('Settings: sauvegarde OK');
            } catch (e) {
                console.error('Failed to save settings', e);
                debugLog(`ERREUR sauvegarde: ${e.message || e}`, 'error');
                showToast('Save failed', true);
                appendLog(`Settings: échec ${e && e.message ? e.message : e}`);
            }
        });
    } else {
        debugLog('ERREUR: save-settings button introuvable!', 'error');
    }

    // Bouton randomize-chain
    const randomizeChainBtn = document.getElementById('randomize-chain');
    if (randomizeChainBtn) {
        attachIOSCompatibleEvent(randomizeChainBtn, 'click', () => {
            randomizeChain();
            if (chainListView && chainListView.classList.contains('active')) {
                renderChainList();
            }
        });
    }

    // Bouton add-effect
    if (addEffectBtn) {
        attachIOSCompatibleEvent(addEffectBtn, 'click', () => {
            if (!availableEffects.length) {
                showToast('Aucun effet disponible', true);
                return;
            }
            const selected = (quickEffectSelect && quickEffectSelect.value) ? quickEffectSelect.value : availableEffects[0].name;
            addEffect(selected);
            showToast(`Effet "${selected}" ajouté`);
        });
    }

    // Bouton cleanup-storage
    if (cleanupStorageBtn) {
        attachIOSCompatibleEvent(cleanupStorageBtn, 'click', async () => {
            const ok = await confirmDialog('Supprimer tous les fichiers temp_videos et hls ?');
            if (!ok) return;
            try {
                const res = await fetch('/cleanup-storage', { method: 'POST' });
                if (!res.ok) throw new Error('Request failed');
                const data = await res.json();
                const r = data.removed || {};
                showToast(`Nettoyé: temp ${r.temp_videos || 0}, hls ${r.hls || 0}`);
            } catch (e) {
                console.error('Cleanup error:', e);
                showToast('Échec du nettoyage', true);
            }
        });
    }

    // Bouton cleanup-uploads
    if (cleanupUploadsBtn) {
        attachIOSCompatibleEvent(cleanupUploadsBtn, 'click', async () => {
            const ok = await confirmDialog('Supprimer tous les fichiers du dossier uploads ?');
            if (!ok) return;
            try {
                const res = await fetch('/cleanup-uploads', { method: 'POST' });
                if (!res.ok) throw new Error('Request failed');
                const data = await res.json();
                showToast(`Nettoyé: ${data.removed || 0} fichiers uploads`);
            } catch (e) {
                console.error('Cleanup uploads error:', e);
                showToast('Échec du nettoyage uploads', true);
            }
        });
    }

    // Bouton kill-generation
    if (killGenerationBtn) {
        attachIOSCompatibleEvent(killGenerationBtn, 'click', async () => {
            const ok = await confirmDialog('Tuer tous les processus de génération en cours ?');
            if (!ok) return;
            try {
                const res = await fetch('/kill-generation', { method: 'POST' });
                if (!res.ok) throw new Error('Request failed');
                showToast('Génération interrompue');
                // Forcer la mise à jour de la liste des workers
                await pollWorkersOnce();
                // Réinitialiser les états visuels des nœuds
                resetNodeGlows();
            } catch (e) {
                console.error('Kill generation error:', e);
                showToast('Échec de l\'interruption', true);
            }
        });
    }
    
    // Bouton pause-generation
    if (pauseGenerationBtn) {
        updatePauseButton();
        attachIOSCompatibleEvent(pauseGenerationBtn, 'click', async () => {
            try {
                const endpoint = generationPaused ? '/generation/resume' : '/generation/pause';
                const res = await fetch(endpoint, { method: 'POST' });
                if (!res.ok) throw new Error('Request failed');
                const data = await res.json();
                generationPaused = data.paused;
                updatePauseButton();
                showToast(generationPaused ? 'Génération en pause' : 'Génération reprise');
            } catch (e) {
                console.error('Pause/resume generation error:', e);
                showToast('Échec de la commande', true);
            }
        });
    }
    
    // Vérifier l'état de la génération au chargement
    checkGenerationStatus();

    // Bouton generate-now-reset-timer
    if (generateNowResetTimerBtn) {
        attachIOSCompatibleEvent(generateNowResetTimerBtn, 'click', async () => {
            const ok = await confirmDialog('Générer un clip maintenant et remettre le timer à 0 ?');
            if (!ok) return;
            try {
                const res = await fetch('/generate-now-reset-timer', { method: 'POST' });
                if (!res.ok) throw new Error('Request failed');
                showToast('Génération lancée, timer remis à 0');
            } catch (e) {
                console.error('Generate now error:', e);
                showToast('Échec de la génération', true);
            }
        });
    }

    // Bouton generate-preview
    const generatePreviewBtnLocal = document.getElementById('generate-preview');
    if (generatePreviewBtnLocal) {
        debugLog('Attachement du listener generate-preview', 'info');
        attachIOSCompatibleEvent(generatePreviewBtnLocal, 'click', async () => {
            debugLog('Clic sur generate-preview détecté', 'info');
            const ok = await confirmDialog('Générer un clip et ouvrir la prévisualisation ?');
            debugLog(`confirmDialog retourné: ${ok}`, 'info');
            if (!ok) {
                debugLog('Utilisateur a annulé', 'info');
                return;
            }
            const originalText = generatePreviewBtnLocal.textContent;
            generatePreviewBtnLocal.disabled = true;
            generatePreviewBtnLocal.textContent = 'Génération...';
            try {
                // Collecter les settings actuels SANS les sauvegarder
                const settings = collectSettings();
                
                // Ouvrir le modal de prévisualisation avec les barres de progression
                showPreviewModal();
                
                // Démarrer le polling de progression
                startPreviewProgressPoll();
                
                // Demander la génération du clip de prévisualisation avec les settings actuels
                appendLog('Preview: requête /preview/generate avec settings actuels');
                const res = await fetch('/preview/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });
                if (!res.ok) throw new Error('Preview generation request failed');
                const data = await res.json();
                appendLog('Preview: génération lancée');
                showToast('Génération de prévisualisation lancée...');

                // Attendre que la génération soit terminée
                let attempts = 0;
                const maxAttempts = 300; // 5 minutes max
                while (attempts < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, 1000));
                    const progressRes = await fetch('/preview/progress');
                    if (progressRes.ok) {
                        const progress = await progressRes.json();
                        if (progress.stage === 'ready' || progress.stage === 'error') {
                            stopPreviewProgressPoll();
                            if (progress.stage === 'ready' && data.url) {
                                // Charger la vidéo dans le modal
                                await loadPreviewVideo(data.url, data.url);
                                showToast('Prévisualisation prête !');
                            } else {
                                showToast('Erreur lors de la génération', true);
                            }
                            break;
                        }
                    }
                    attempts++;
                }
                
                if (attempts >= maxAttempts) {
                    stopPreviewProgressPoll();
                    showToast('Timeout lors de la génération', true);
                }
            } catch (e) {
                console.error('Preview generation error:', e);
                showToast('Échec de la génération ou de la prévisualisation', true);
                appendLog(`Preview error: ${e && e.message ? e.message : e}`);
                stopPreviewProgressPoll();
            } finally {
                generatePreviewBtnLocal.disabled = false;
                generatePreviewBtnLocal.textContent = originalText;
            }
        });
    } else {
        debugLog('ERREUR: generate-preview button introuvable!', 'error');
    }

    // Bouton reset-viewport
    if (resetViewportBtn) {
        attachIOSCompatibleEvent(resetViewportBtn, 'click', () => {
            resetViewport();
            updateConnections();
        });
    }
    
    // Attacher les listeners pour les presets (load, save, delete)
    attachPresetListeners();
    loadPresets();
}

// Gestion du toggle de vue
function setupViewToggle() {
    if (!viewToggle || !viewListBtn || !viewCanvasBtn) return;

    // Afficher le toggle sur mobile/iOS
    if (isMobile) {
        viewToggle.style.display = 'flex';
        if (canvasHint) canvasHint.style.display = 'none';
        
        // Afficher les contrôles de zoom sur mobile/iOS
        const zoomControls = document.getElementById('zoom-controls');
        if (zoomControls) {
            zoomControls.style.display = 'flex';
        }
        
        // Par défaut, afficher la vue liste sur mobile
        switchToView('list');
    } else {
        viewToggle.style.display = 'none';
        switchToView('canvas');
    }

    attachIOSCompatibleEvent(viewListBtn, 'click', () => switchToView('list'));
    attachIOSCompatibleEvent(viewCanvasBtn, 'click', () => switchToView('canvas'));
    
    // Configurer le slider de zoom
    setupZoomSlider();
}

function setupZoomSlider() {
    const zoomSlider = document.getElementById('zoom-slider');
    const zoomValue = document.getElementById('zoom-value');
    
    if (!zoomSlider || !zoomValue) return;
    
    // Initialiser avec la valeur actuelle
    const currentPercent = scaleToPercent(viewportState.scale);
    zoomSlider.value = currentPercent;
    zoomValue.textContent = `${currentPercent}%`;
    
    // Mettre à jour le zoom quand le slider change
    const updateZoom = (e) => {
        const percent = parseInt(e.target.value, 10);
        const newScale = percentToScale(percent);
        const oldScale = viewportState.scale;
        viewportState.scale = clampScale(newScale);
        
        // Ajuster la position pour garder le centre visible
        if (nodeStage) {
            const rect = nodeStage.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            const before = clientToWorld(centerX, centerY);
            viewportState.x = centerX - before.x * viewportState.scale;
            viewportState.y = centerY - before.y * viewportState.scale;
        }
        
        applyViewportTransform();
        zoomValue.textContent = `${percent}%`;
        
        // Forcer le re-rendu des connexions immédiatement
        updateConnections();
        
        // Sur iOS, forcer un double reflow pour s'assurer que tout est redessiné
        if (isIOS) {
            requestAnimationFrame(() => {
                if (nodeViewport) {
                    // Force reflow multiple pour iOS
                    void nodeViewport.offsetHeight;
                    void nodeViewport.offsetWidth;
                }
                // Re-mettre à jour les connexions après le reflow
                updateConnections();
            });
        }
    };
    
    zoomSlider.addEventListener('input', updateZoom);
    
    // Sur iOS, aussi écouter change pour s'assurer que la mise à jour se fait
    if (isIOS) {
        zoomSlider.addEventListener('change', (e) => {
            updateZoom(e);
            // Double mise à jour sur change pour iOS
            setTimeout(() => {
                updateConnections();
            }, 50);
        });
    }
    
    // Utiliser attachIOSCompatibleEvent pour le slider aussi
    if (isIOS) {
        attachIOSCompatibleEvent(zoomSlider, 'input', (e) => {
            // Déjà géré par l'event listener ci-dessus
        });
    }
}

function switchToView(view) {
    debugLog(`switchToView appelé avec: ${view}`, 'info');
    const zoomControls = document.getElementById('zoom-controls');
    
    if (view === 'list') {
        if (chainListView) {
            chainListView.classList.add('active');
            debugLog('Vue liste activée', 'info');
        } else {
            debugLog('ERREUR: chainListView est null!', 'error');
        }
        if (nodeCanvas) nodeCanvas.classList.remove('active');
        if (viewListBtn) viewListBtn.classList.add('active');
        if (viewCanvasBtn) viewCanvasBtn.classList.remove('active');
        
        // Masquer les contrôles de zoom en vue liste
        if (zoomControls) zoomControls.style.display = 'none';
        
        debugLog(`Rendu de la liste avec ${effectChain.length} nœuds`, 'info');
        renderChainList();
    } else {
        if (chainListView) chainListView.classList.remove('active');
        if (nodeCanvas) {
            nodeCanvas.classList.add('active');
            debugLog('Vue canvas activée', 'info');
        }
        if (viewListBtn) viewListBtn.classList.remove('active');
        if (viewCanvasBtn) viewCanvasBtn.classList.add('active');
        
        // Afficher les contrôles de zoom en vue canvas sur mobile/iOS
        if (zoomControls && isMobile) {
            zoomControls.style.display = 'flex';
        }
        
        debugLog(`Rendu du canvas avec ${effectChain.length} nœuds`, 'info');
        renderChain();
    }
}

// Attendre que le DOM soit chargé avant de charger les settings
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        loadSettings();
    });
} else {
    // DOM déjà chargé
    loadSettings();
}

document.addEventListener('DOMContentLoaded', () => {
    debugLog('DOMContentLoaded déclenché', 'info');
    
    // Attacher tous les listeners de boutons
    attachButtonListeners();
    debugLog('Listeners de boutons attachés', 'info');
    
    setupViewToggle();
    debugLog('View toggle configuré', 'info');
    
    logPanel = document.getElementById('log-panel');
    logContent = document.getElementById('log-content');
    logStatus = document.getElementById('log-status');
    progressDl = document.getElementById('prog-dl');
    progressProc = document.getElementById('prog-proc');
    progressStatus = document.getElementById('progress-status');
    
    // Ouvrir les logs automatiquement sur mobile/iOS
    if (isMobile && logPanel) {
        toggleLogPanel(true);
        debugLog('Logs ouverts automatiquement sur mobile', 'info');
    }
    
    const toggleBtn = document.getElementById('toggle-log-btn');
    if (toggleBtn) {
        attachIOSCompatibleEvent(toggleBtn, 'click', () => toggleLogPanel());
    }
    // Auto-open logs if requested via hash
    if (window.location.hash === '#logs') {
        toggleLogPanel(true);
    }
    
    debugLog('Initialisation DOMContentLoaded terminée', 'success');
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'l' || e.key === 'L') {
        toggleLogPanel();
    }
});

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.style.borderColor = isError ? '#d04545' : 'var(--border)';
    toast.style.color = isError ? '#f38b8b' : 'var(--text)';
    toast.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.remove('show');
    }, 2000);
}

// Context menu for adding nodes on right-click
function hideContextMenu() {
    contextMenu.classList.remove('visible');
}

function showContextMenu(x, y) {
    contextMenu.classList.add('visible'); // show early to measure if needed
    contextMenu.innerHTML = '';
    pendingNodePosition = clientToWorld(x, y);
    availableEffects.forEach(effect => {
        const item = document.createElement('div');
        item.className = 'context-item';
        item.textContent = `${effect.name} — ${effect.description}`;
        item.onclick = () => {
            addEffect(effect.name, pendingNodePosition);
            pendingNodePosition = null;
            hideContextMenu();
        };
        contextMenu.appendChild(item);
    });
    // Positionner sans déborder l'écran, sinon activer le scroll interne
    const menuWidth = 240;
    const maxX = window.innerWidth - menuWidth - 12;
    const maxY = window.innerHeight - 12;
    const posX = Math.max(8, Math.min(x, maxX));
    const posY = Math.max(8, Math.min(y, maxY));
    contextMenu.style.left = `${posX}px`;
    contextMenu.style.top = `${posY}px`;
    contextMenu.style.maxHeight = `${window.innerHeight - posY - 12}px`;
    contextMenu.style.overflowY = 'auto';
    // Retarder l'auto-hide pour éviter disparition immédiate
    setTimeout(() => contextMenu.classList.add('visible'), 0);
}

if (nodeCanvas) {
    nodeCanvas.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        showContextMenu(e.clientX, e.clientY);
    });
    
    // Sur mobile, utiliser long press pour le menu contextuel
    if (isMobile) {
        let longPressTimer = null;
        nodeCanvas.addEventListener('touchstart', (e) => {
            if (e.target.closest('.effect-item')) return;
            longPressTimer = setTimeout(() => {
                const touch = e.touches[0] || e.changedTouches[0];
                if (touch) {
                    showContextMenu(touch.clientX, touch.clientY);
                }
            }, 500);
        });
        nodeCanvas.addEventListener('touchend', () => {
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        });
        nodeCanvas.addEventListener('touchmove', () => {
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        });
    }
}

document.addEventListener('mousedown', (e) => {
    if (!contextMenu.contains(e.target)) hideContextMenu();
});

document.addEventListener('scroll', (e) => {
    // Ne pas fermer le menu si le scroll se produit dans le menu contextuel
    if (contextMenu && contextMenu.contains(e.target)) {
        return;
    }
    hideContextMenu();
}, true);

// Empêcher le zoom/pan de la scène quand on scrolle dans le menu contextuel
if (contextMenu) {
    contextMenu.addEventListener('wheel', (e) => {
        e.stopPropagation();
        // Empêcher la fermeture du menu lors du scroll
        e.stopImmediatePropagation();
    }, { passive: true });
    contextMenu.addEventListener('scroll', (e) => {
        e.stopPropagation();
        // Empêcher la fermeture du menu lors du scroll interne
        e.stopImmediatePropagation();
    }, { passive: true });
    contextMenu.addEventListener('touchstart', (e) => {
        e.stopPropagation();
    }, { passive: true });
}

// ===== CONTRÔLES VIDÉO ET STATISTIQUES =====
// Ces contrôles fonctionnent en contrôlant le lecteur sur index.html via window.opener ou en créant une référence

// Référence au lecteur vidéo (peut être sur index.html ou dans une iframe)
let mainPlayer = null;
let playerWindow = null;

// Essayer de trouver le lecteur vidéo
function findPlayer() {
    // Si option.html est ouverte depuis index.html
    if (window.opener && window.opener.document) {
        const player = window.opener.document.getElementById('main-player');
        if (player) {
            mainPlayer = player;
            playerWindow = window.opener;
            return true;
        }
    }
    // Si on peut accéder au parent (iframe)
    try {
        if (window.parent && window.parent !== window) {
            const player = window.parent.document.getElementById('main-player');
            if (player) {
                mainPlayer = player;
                playerWindow = window.parent;
                return true;
            }
        }
    } catch (e) {
        // Cross-origin, on ne peut pas accéder
    }
    return false;
}

// Éléments de contrôle
const playPauseBtn = document.getElementById('play-pause-btn');
const muteBtn = document.getElementById('mute-btn');
const volumeSlider = document.getElementById('volume-slider');
const progressBar = document.getElementById('progress-bar');
const progressFilled = document.getElementById('progress-filled');
const timeDisplay = document.getElementById('time-display');
const fullscreenBtn = document.getElementById('fullscreen-btn');
const resetStatsBtn = document.getElementById('reset-stats-btn');

// Format time helper
function formatTime(seconds) {
    if (isNaN(seconds) || !isFinite(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Update progress bar
function updateProgress() {
    if (!mainPlayer || !findPlayer()) return;
    if (mainPlayer.duration) {
        const percent = (mainPlayer.currentTime / mainPlayer.duration) * 100;
        if (progressFilled) progressFilled.style.width = percent + '%';
        if (timeDisplay) timeDisplay.textContent = `${formatTime(mainPlayer.currentTime)} / ${formatTime(mainPlayer.duration)}`;
    }
}

// Update play/pause button
function updatePlayPauseButton() {
    if (!mainPlayer || !findPlayer()) return;
    if (playPauseBtn) {
        playPauseBtn.textContent = mainPlayer.paused ? '▶ Play' : '⏸ Pause';
    }
}

// Update mute button
function updateMuteButton() {
    if (!mainPlayer || !findPlayer()) return;
    if (muteBtn) {
        muteBtn.textContent = mainPlayer.muted ? '🔇' : '🔊';
    }
    if (volumeSlider) {
        volumeSlider.value = mainPlayer.muted ? 0 : mainPlayer.volume * 100;
    }
}

// Contrôles de lecture
if (playPauseBtn) {
    playPauseBtn.addEventListener('click', () => {
        if (!findPlayer()) {
            showToast('Ouvrez index.html pour contrôler la lecture', true);
            return;
        }
        if (mainPlayer.paused) {
            mainPlayer.play().catch(e => console.log('Play failed:', e));
        } else {
            mainPlayer.pause();
        }
        updatePlayPauseButton();
    });
}

if (muteBtn) {
    muteBtn.addEventListener('click', () => {
        if (!findPlayer()) {
            showToast('Ouvrez index.html pour contrôler la lecture', true);
            return;
        }
        mainPlayer.muted = !mainPlayer.muted;
        updateMuteButton();
    });
}

if (volumeSlider) {
    volumeSlider.addEventListener('input', (e) => {
        if (!findPlayer()) return;
        mainPlayer.volume = e.target.value / 100;
        mainPlayer.muted = e.target.value == 0;
        updateMuteButton();
    });
}

// Barre de progression
if (progressBar) {
    progressBar.addEventListener('click', (e) => {
        if (!findPlayer()) return;
        const rect = progressBar.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        if (mainPlayer.duration) {
            mainPlayer.currentTime = percent * mainPlayer.duration;
        }
    });
}

// Mode plein écran
if (fullscreenBtn) {
    fullscreenBtn.addEventListener('click', () => {
        if (!findPlayer()) {
            showToast('Ouvrez index.html pour utiliser le mode plein écran', true);
            return;
        }
        const elem = playerWindow.document.documentElement;
        if (!playerWindow.document.fullscreenElement) {
            elem.requestFullscreen().catch(err => {
                console.log('Error attempting to enable fullscreen:', err);
            });
        } else {
            playerWindow.document.exitFullscreen();
        }
    });
}

// Mettre à jour les contrôles périodiquement
if (findPlayer()) {
    setInterval(() => {
        if (findPlayer()) {
            updateProgress();
            updatePlayPauseButton();
            updateMuteButton();
        }
    }, 500);
}

// Écouter les événements du lecteur si accessible
if (findPlayer() && mainPlayer) {
    mainPlayer.addEventListener('play', updatePlayPauseButton);
    mainPlayer.addEventListener('pause', updatePlayPauseButton);
    mainPlayer.addEventListener('timeupdate', updateProgress);
    mainPlayer.addEventListener('loadedmetadata', () => {
        updateProgress();
        updateMuteButton();
    });
    mainPlayer.addEventListener('volumechange', updateMuteButton);
}

// ===== UPLOAD =====

async function loadUploadedFiles() {
    try {
        const res = await fetch('/uploads-list');
        if (!res.ok) return [];
        const files = await res.json();
        return files;
    } catch (e) {
        console.error('Error loading uploads:', e);
        return [];
    }
}

async function wireLocalSourceNode(card, nodeId, options) {
    const entry = getEntryById(nodeId);
    if (!entry) return;
    
    const localFileInputId = `local-file-input-${nodeId}`;
    const uploadFileBtnId = `upload-file-btn-${nodeId}`;
    const uploadStatusId = `upload-status-${nodeId}`;
    const localFileSelectId = `local-file-select-${nodeId}`;
    
    const uploadFileBtn = card.querySelector(`#${uploadFileBtnId}`);
    const localFileInput = card.querySelector(`#${localFileInputId}`);
    const uploadStatus = card.querySelector(`#${uploadStatusId}`);
    const localFileSelect = card.querySelector(`#${localFileSelectId}`);

    if (!uploadFileBtn || !localFileInput || !uploadStatus || !localFileSelect) return;

    // Charger la liste des fichiers uploadés
    const files = await loadUploadedFiles();
    localFileSelect.innerHTML = '<option value="">-- Sélectionner un fichier --</option>';
    files.forEach(f => {
        const option = document.createElement('option');
        option.value = f.filename;
        option.textContent = `${f.filename} (${Math.round(f.size / 1024)} Ko)`;
        localFileSelect.appendChild(option);
    });
    
    // Restaurer la sélection si elle existe dans les options
    if (options.local_file) {
        localFileSelect.value = options.local_file;
    }

    // Gérer l'upload
    uploadFileBtn.onclick = async () => {
        const file = localFileInput.files[0];
        if (!file) {
            uploadStatus.textContent = 'Sélectionnez un fichier';
            uploadStatus.style.color = '#f38b8b';
            return;
        }

        uploadStatus.textContent = 'Upload en cours...';
        uploadStatus.style.color = 'var(--accent)';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/upload', {
                method: 'POST',
                body: formData
            });

            if (res.ok) {
                const data = await res.json();
                uploadStatus.textContent = `✓ Upload réussi: ${data.filename}`;
                uploadStatus.style.color = 'var(--accent)';
                
                // Ajouter au select et sélectionner
                const option = document.createElement('option');
                option.value = data.filename;
                option.textContent = `${data.filename} (nouveau)`;
                localFileSelect.appendChild(option);
                localFileSelect.value = data.filename;
                
                // Enregistrer dans les options du nœud
                if (!entry.options) entry.options = {};
                entry.options.local_file = data.filename;
                
                // Sauvegarder les settings
                await saveSettings();
            } else {
                throw new Error('Upload failed');
            }
        } catch (e) {
            uploadStatus.textContent = 'Erreur lors de l\'upload';
            uploadStatus.style.color = '#f38b8b';
            console.error('Upload error:', e);
        }
    };

    // Gérer la sélection d'un fichier existant
    localFileSelect.addEventListener('change', () => {
        const selectedFile = localFileSelect.value;
        if (!entry.options) entry.options = {};
        entry.options.local_file = selectedFile || null;
        // Sauvegarder automatiquement
        saveSettings();
    });
}

function wireLocalUploadControls() {
    // Cette fonction est maintenant obsolète car chaque nœud source-local
    // est géré individuellement par wireLocalSourceNode
    // On la garde pour compatibilité mais elle ne fait plus rien
}

// ===== PREVIEW HLS =====

async function ensureHlsLib() {
    if (window.Hls) return;
    await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}


function showPreviewModal() {
    destroyPreviewModal();
    previewOverlay = document.createElement('div');
    previewOverlay.className = 'preview-overlay';
    previewOverlay.innerHTML = `
        <div class="preview-box">
            <div class="preview-header">
                <strong>Prévisualisation de la chaîne</strong>
                <button class="preview-close">Fermer</button>
            </div>
            <div class="preview-progress-block" style="margin-bottom: 12px;">
                <div class="preview-progress-row">
                    <span>Téléchargement</span>
                    <div class="preview-progress-bar"><div class="preview-progress-fill" id="preview-prog-dl"></div></div>
                </div>
                <div class="preview-progress-row">
                    <span>Traitement</span>
                    <div class="preview-progress-bar"><div class="preview-progress-fill" id="preview-prog-proc"></div></div>
                </div>
                <div id="preview-progress-status" style="margin-top: 8px; font-size: 13px; color: var(--muted);"></div>
            </div>
            <video class="preview-video" id="preview-video" controls autoplay muted playsinline style="display: none;"></video>
            <div style="display: flex; gap: 10px; align-items: center; margin-top: 12px;">
                <p id="preview-message" style="margin:0;color:var(--muted);font-size:13px;flex:1;">
                    Génération en cours...
                </p>
                <button class="btn secondary sm" id="preview-download-btn" style="display: none;">📥 Télécharger</button>
            </div>
        </div>
    `;
    document.body.appendChild(previewOverlay);

    const closeBtn = previewOverlay.querySelector('.preview-close');
    closeBtn.addEventListener('click', destroyPreviewModal);
    previewOverlay.addEventListener('click', (e) => {
        if (e.target === previewOverlay) destroyPreviewModal();
    });

    previewVideo = previewOverlay.querySelector('#preview-video');
}

function renderPreviewProgress(state) {
    if (!state || !previewOverlay) return;
    const stage = state.stage || 'idle';
    const pct = Number(state.percent || 0);
    const msg = state.message || '';
    const statusEl = previewOverlay.querySelector('#preview-progress-status');
    const progDl = previewOverlay.querySelector('#preview-prog-dl');
    const progProc = previewOverlay.querySelector('#preview-prog-proc');
    
    if (statusEl) {
        statusEl.textContent = `${stage} ${msg ? '· ' + msg : ''}`;
    }
    
    if (progDl && progProc) {
        let dl = 0, proc = 0;
        if (stage === 'downloading') {
            dl = pct;
            proc = 0;
        } else if (stage === 'processing' || stage === 'preparing') {
            dl = 100;
            proc = pct;
        } else if (stage === 'ready') {
            dl = 100;
            proc = 100;
        } else if (stage === 'error') {
            dl = 0;
            proc = 0;
        }
        progDl.style.width = `${Math.max(0, Math.min(100, dl))}%`;
        progProc.style.width = `${Math.max(0, Math.min(100, proc))}%`;
    }
}

async function pollPreviewProgressOnce() {
    try {
        const res = await fetch('/preview/progress');
        if (!res.ok) return;
        const state = await res.json();
        renderPreviewProgress(state);
    } catch (_) {
        // ignore
    }
}

function startPreviewProgressPoll() {
    stopPreviewProgressPoll();
    pollPreviewProgressOnce();
    previewProgressTimer = setInterval(pollPreviewProgressOnce, 500);
}

function stopPreviewProgressPoll() {
    if (previewProgressTimer) {
        clearInterval(previewProgressTimer);
        previewProgressTimer = null;
    }
}

async function loadPreviewVideo(url, downloadUrl) {
    if (!previewVideo || !previewOverlay) return;
    const messageEl = previewOverlay.querySelector('#preview-message');
    if (messageEl) {
        messageEl.textContent = 'Chargement de la vidéo...';
    }
    previewVideo.style.display = 'block';
    previewVideo.src = url;
    previewVideo.load();
    
    // Ajouter le bouton de téléchargement
    const downloadBtn = previewOverlay.querySelector('#preview-download-btn');
    if (downloadBtn) {
        downloadBtn.style.display = 'inline-block';
        downloadBtn.onclick = () => {
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = downloadUrl.split('/').pop() || 'preview.mp4';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        };
    }
    
    if (messageEl) {
        messageEl.textContent = 'Prévisualisation prête !';
    }
}

function destroyPreviewModal() {
    stopPreviewProgressPoll();
    if (previewHls) {
        previewHls.destroy();
        previewHls = null;
    }
    if (previewOverlay && previewOverlay.parentNode) {
        previewOverlay.remove();
    }
    previewOverlay = null;
    previewVideo = null;
}

// Export de preset
const exportPresetBtn = document.getElementById('export-preset-btn');
if (exportPresetBtn) {
    exportPresetBtn.addEventListener('click', async () => {
        const presetSelect = document.getElementById('preset-select');
        const presetName = presetSelect.value;
        if (!presetName) {
            showToast('Sélectionnez un preset à exporter', true);
            return;
        }

        try {
            const res = await fetch(`/presets/export/${presetName}`);
            if (res.ok) {
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${presetName}.json`;
                a.click();
                window.URL.revokeObjectURL(url);
                showToast('Preset exporté');
            }
        } catch (e) {
            showToast('Erreur lors de l\'export', true);
            console.error('Export error:', e);
        }
    });
}

// Import de preset
const importPresetBtn = document.getElementById('import-preset-btn');
const importPresetInput = document.getElementById('import-preset-input');
if (importPresetBtn && importPresetInput) {
    importPresetBtn.addEventListener('click', () => {
        importPresetInput.click();
    });

    importPresetInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/presets/import', {
                method: 'POST',
                body: formData
            });

            if (res.ok) {
                const data = await res.json();
                showToast(`Preset importé: ${data.name}`);
                loadPresets();
            } else {
                throw new Error('Import failed');
            }
        } catch (err) {
            showToast('Erreur lors de l\'import', true);
            console.error('Import error:', err);
        }

        importPresetInput.value = '';
    });
}

// Historique/exports déplacés vers hls.html

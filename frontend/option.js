const effectChainContainer = document.getElementById('effect-chain');
const contextMenu = document.getElementById('context-menu');
const nodeCanvas = document.querySelector('.node-canvas');

let availableEffects = [];
let effectChain = [];
let dragIndex = null;
let toastTimer = null;
let minReplays = 1;

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

function renderChain() {
    effectChainContainer.innerHTML = '';
    effectChain.forEach((entry, idx) => {
        const currentIdx = idx; // capture for listeners
        const card = document.createElement('div');
        card.className = 'effect-item';
        card.dataset.index = idx;
        card.draggable = true;

        card.addEventListener('dragstart', (e) => {
            dragIndex = idx;
            card.classList.add('dragging');
            if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
        });

        card.addEventListener('dragend', () => {
            dragIndex = null;
            card.classList.remove('dragging');
            document.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
        });

        card.addEventListener('dragover', (e) => {
            e.preventDefault();
            card.classList.add('drop-target');
            if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        });

        card.addEventListener('dragleave', () => {
            card.classList.remove('drop-target');
        });

        card.addEventListener('drop', (e) => {
            e.preventDefault();
            card.classList.remove('drop-target');
            if (dragIndex === null) return;
            const targetIdx = Number(card.dataset.index);
            if (Number.isNaN(targetIdx) || targetIdx === dragIndex) return;
            const [item] = effectChain.splice(dragIndex, 1);
            effectChain.splice(targetIdx, 0, item);
            renderChain();
        });

        const header = document.createElement('div');
        header.className = 'effect-header';

        const portIn = document.createElement('div');
        portIn.className = 'port';

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

        select.addEventListener('change', (e) => {
            const newName = e.target.value;
            const def = getEffectDefinition(newName);
            effectChain[idx].name = newName;
            effectChain[idx].options = {};
            title.textContent = newName;
            const optsContainer = card.querySelector('.effect-options');
            optsContainer.replaceWith(buildOptions(newName, {}));
            wireOptionInputs(card, currentIdx);
        });

        const controls = document.createElement('div');
        controls.className = 'effect-controls';

        const removeBtn = document.createElement('button');
        removeBtn.className = 'close-btn';
        removeBtn.textContent = '×';
        removeBtn.title = 'Remove effect';
        removeBtn.onclick = () => removeEffect(idx);

        controls.appendChild(removeBtn);

        const portOut = document.createElement('div');
        portOut.className = 'port';

        header.appendChild(portIn);
        header.appendChild(handle);
        header.appendChild(title);
        header.appendChild(select);
        header.appendChild(controls);
        header.appendChild(portOut);
        card.appendChild(header);

        const options = buildOptions(entry.name, entry.options || {});
        card.appendChild(options);

        // Persist option changes back into effectChain so re-renders keep user edits
        wireOptionInputs(card, currentIdx);

        effectChainContainer.appendChild(card);
    });
}

function wireOptionInputs(card, idx) {
    const inputs = card.querySelectorAll('.effect-options input, .effect-options select');
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
            if (!effectChain[idx].options) effectChain[idx].options = {};
            effectChain[idx].options[optName] = val;
        };

        const eventName = (type === 'bool' || type === 'select') ? 'change' : 'input';
        input.addEventListener(eventName, handler);
    });
}

function moveEffect(index, delta) {
    const newIndex = index + delta;
    if (newIndex < 0 || newIndex >= effectChain.length) return;
    const [item] = effectChain.splice(index, 1);
    effectChain.splice(newIndex, 0, item);
    renderChain();
}

function removeEffect(index) {
    effectChain.splice(index, 1);
    renderChain();
}

function addEffect(name) {
    const def = getEffectDefinition(name) || availableEffects[0];
    if (!def) return;
    effectChain.push({ name: def.name, options: {} });
    renderChain();
}

async function loadPresets() {
    try {
        const res = await fetch('/presets');
        const presets = await res.json();
        const select = document.getElementById('preset-select');
        select.innerHTML = '<option value="">Select a preset...</option>';
        presets.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load presets', e);
    }
}

document.getElementById('load-preset').addEventListener('click', async () => {
    const name = document.getElementById('preset-select').value;
    if (!name) return;
    try {
        const res = await fetch(`/presets/${name}`);
        if (!res.ok) throw new Error('Failed to load');
        const chain = await res.json();
        effectChain = chain;
        renderChain();
        showToast(`Preset "${name}" loaded`);
    } catch (e) {
        showToast('Error loading preset', true);
    }
});

document.getElementById('save-preset').addEventListener('click', async () => {
    const name = document.getElementById('new-preset-name').value.trim();
    if (!name) {
        showToast('Enter a preset name', true);
        return;
    }
    
    // Collect current chain
    const cards = Array.from(effectChainContainer.querySelectorAll('.effect-item'));
    const chainToSave = cards.map(card => {
        const select = card.querySelector('select');
        const effectName = select.value;
        const opts = {};
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
            opts[input.dataset.option] = val;
        });
        return { name: effectName, options: opts };
    });

    try {
        await fetch(`/presets/${name}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(chainToSave)
        });
        showToast(`Preset "${name}" saved`);
        document.getElementById('new-preset-name').value = '';
        loadPresets(); // Refresh list
    } catch (e) {
        showToast('Error saving preset', true);
    }
});

document.getElementById('delete-preset').addEventListener('click', async () => {
    const name = document.getElementById('preset-select').value;
    if (!name) return;
    if (!confirm(`Delete preset "${name}"?`)) return;
    
    try {
        await fetch(`/presets/${name}`, { method: 'DELETE' });
        showToast(`Preset "${name}" deleted`);
        loadPresets();
    } catch (e) {
        showToast('Error deleting preset', true);
    }
});

function randomizeChain() {
    if (!availableEffects.length) return;
    
    const length = Math.floor(Math.random() * 5) + 1; // 1 to 5 effects
    effectChain = [];
    
    for (let i = 0; i < length; i++) {
        const effect = availableEffects[Math.floor(Math.random() * availableEffects.length)];
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
        
        effectChain.push({ name: effect.name, options });
    }
    renderChain();
    showToast('Random chain generated');
}

document.getElementById('randomize-chain').addEventListener('click', randomizeChain);

async function loadSettings() {
    try {
        const [settingsRes, effectsRes] = await Promise.all([
            fetch('/settings'),
            fetch('/effects')
        ]);

        const settings = await settingsRes.json();
        availableEffects = await effectsRes.json();

        minReplays = settings.min_replays_before_next || 1;

        // Populate general inputs
        document.getElementById('keywords').value = settings.keywords;
        document.getElementById('playlist-url').value = settings.playlist_url || '';
        if (settings.local_file && localFileSelect) {
            localFileSelect.value = settings.local_file;
            localFileSelect.style.display = 'block';
        }
        document.getElementById('duration').value = settings.duration;
        document.getElementById('duration-variation').value = settings.duration_variation;
        document.getElementById('video-quality').value = settings.video_quality || 'best';
        document.getElementById('include-reels').checked = settings.include_reels !== false;
        document.getElementById('min-replays').value = settings.min_replays_before_next || 1;
        
        const speed = settings.playback_speed || 1.0;
        document.getElementById('playback-speed').value = speed;
        document.getElementById('playback-speed-val').textContent = speed;

        document.getElementById('random-preset-mode').checked = settings.random_preset_mode || false;
        document.getElementById('freestyle-mode').checked = settings.freestyle_mode || false;

        // Build effect chain (prefer new field, fallback to legacy)
        if (settings.effect_chain && settings.effect_chain.length) {
            effectChain = settings.effect_chain.map(e => ({ name: e.name, options: e.options || {} }));
        } else {
            effectChain = (settings.active_effects || []).map(name => ({
                name,
                options: (settings.effect_options && settings.effect_options[name]) ? settings.effect_options[name] : {}
            }));
        }

        renderChain();
        loadPresets(); // Load presets on startup
    } catch (e) {
        console.error('Error loading settings:', e);
    }
}

function collectSettings() {
    const cards = Array.from(effectChainContainer.querySelectorAll('.effect-item'));
    const chainToSave = cards.map(card => {
        const select = card.querySelector('select');
        const name = select.value;
        const opts = {};
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
            opts[input.dataset.option] = val;
        });
        return { name, options: opts };
    });

    const localFileSelect = document.getElementById('local-file-select');
    return {
        keywords: document.getElementById('keywords').value,
        playlist_url: document.getElementById('playlist-url').value || null,
        local_file: localFileSelect && localFileSelect.value ? localFileSelect.value : null,
        duration: parseInt(document.getElementById('duration').value) || 5,
        duration_variation: parseInt(document.getElementById('duration-variation').value) || 0,
        video_quality: document.getElementById('video-quality').value || 'best',
        include_reels: document.getElementById('include-reels').checked,
        min_replays_before_next: parseInt(document.getElementById('min-replays').value) || 1,
        playback_speed: parseFloat(document.getElementById('playback-speed').value) || 1.0,
        random_preset_mode: document.getElementById('random-preset-mode').checked,
        freestyle_mode: document.getElementById('freestyle-mode').checked,
        active_effects: chainToSave.map(e => e.name),
        effect_options: {},
        effect_chain: chainToSave
    };
}

async function saveSettings() {
    const settings = collectSettings();
    await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    });
}

document.getElementById('playback-speed').addEventListener('input', (e) => {
    document.getElementById('playback-speed-val').textContent = e.target.value;
});

// Auto-save speed on change for real-time update
document.getElementById('playback-speed').addEventListener('change', async (e) => {
    // Trigger save
    document.getElementById('save-settings').click();
});

document.getElementById('save-settings').addEventListener('click', async () => {
    try {
        const settings = collectSettings();
        await fetch('/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        showToast('Settings saved');
    } catch (e) {
        console.error('Failed to save settings', e);
        showToast('Save failed', true);
    }
});

loadSettings();

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
    contextMenu.innerHTML = '';
    availableEffects.forEach(effect => {
        const item = document.createElement('div');
        item.className = 'context-item';
        item.textContent = `${effect.name} — ${effect.description}`;
        item.onclick = () => {
            addEffect(effect.name);
            hideContextMenu();
        };
        contextMenu.appendChild(item);
    });
    contextMenu.style.left = `${x}px`;
    contextMenu.style.top = `${y}px`;
    contextMenu.classList.add('visible');
}

nodeCanvas.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    showContextMenu(e.clientX, e.clientY);
});

document.addEventListener('click', (e) => {
    if (!contextMenu.contains(e.target)) hideContextMenu();
});

document.addEventListener('scroll', hideContextMenu, true);

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
            alert('Ouvrez index.html pour contrôler la lecture');
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
            alert('Ouvrez index.html pour contrôler la lecture');
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
            alert('Ouvrez index.html pour utiliser le mode plein écran');
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

// Statistiques
async function loadStats() {
    try {
        const res = await fetch('/stats');
        if (res.ok) {
            const stats = await res.json();
            const clipsEl = document.getElementById('stat-clips');
            const timeEl = document.getElementById('stat-time');
            const todayEl = document.getElementById('stat-today');
            const sessionEl = document.getElementById('stat-session');
            
            if (clipsEl) clipsEl.textContent = stats.total_clips_played || 0;
            if (timeEl) timeEl.textContent = stats.total_playback_time_formatted || '0s';
            if (todayEl) todayEl.textContent = `${stats.clips_today || 0} clips`;
            if (sessionEl) sessionEl.textContent = stats.session_duration_formatted || '0s';
        }
    } catch (e) {
        console.log('Could not load stats', e);
    }
}

if (resetStatsBtn) {
    resetStatsBtn.addEventListener('click', async () => {
        if (confirm('Voulez-vous réinitialiser les statistiques ?')) {
            try {
                await fetch('/stats/reset', { method: 'POST' });
                loadStats();
            } catch (e) {
                console.log('Could not reset stats', e);
            }
        }
    });
}

// Charger les stats au démarrage et périodiquement
loadStats();
setInterval(loadStats, 5000); // Rafraîchir toutes les 5 secondes

// ===== UPLOAD ET EXPORT =====

// Upload de fichier
const uploadFileBtn = document.getElementById('upload-file-btn');
const localFileInput = document.getElementById('local-file-input');
const uploadStatus = document.getElementById('upload-status');
const localFileSelect = document.getElementById('local-file-select');

if (uploadFileBtn && localFileInput) {
    uploadFileBtn.addEventListener('click', async () => {
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
                
                // Ajouter au select
                const option = document.createElement('option');
                option.value = data.filename;
                option.textContent = data.filename;
                localFileSelect.appendChild(option);
                localFileSelect.value = data.filename;
                localFileSelect.style.display = 'block';
                
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
    });
}

// Charger les fichiers uploadés
async function loadUploadedFiles() {
    try {
        // Pour l'instant, on liste depuis le select existant
        // On pourrait ajouter un endpoint pour lister les uploads
    } catch (e) {
        console.error('Error loading uploaded files:', e);
    }
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

// Historique
async function loadHistory() {
    const historyList = document.getElementById('history-list');
    if (!historyList) return;

    try {
        const res = await fetch('/history');
        if (res.ok) {
            const history = await res.json();
            if (history.length === 0) {
                historyList.innerHTML = '<div style="color: var(--muted); font-size: 12px; text-align: center;">Aucun clip dans l\'historique</div>';
                return;
            }

            historyList.innerHTML = history.reverse().map(clip => {
                const date = new Date(clip.timestamp);
                return `
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; border-bottom: 1px solid var(--border);">
                        <div>
                            <div style="font-size: 12px; color: var(--muted);">${date.toLocaleString()}</div>
                            <div style="font-size: 11px; color: var(--text); word-break: break-all;">${clip.url}</div>
                        </div>
                        <button class="btn sm" onclick="exportClip('${clip.url}')">📥 Export</button>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        historyList.innerHTML = '<div style="color: #f38b8b; font-size: 12px;">Erreur lors du chargement</div>';
        console.error('History error:', e);
    }
}

// Export de clip
window.exportClip = async function(url) {
    try {
        const res = await fetch('/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        if (res.ok) {
            const data = await res.json();
            showToast('Clip exporté');
            loadExports();
        } else {
            throw new Error('Export failed');
        }
    } catch (e) {
        showToast('Erreur lors de l\'export', true);
        console.error('Export error:', e);
    }
};

// Liste des exports
async function loadExports() {
    const exportsList = document.getElementById('exports-list');
    if (!exportsList) return;

    try {
        const res = await fetch('/exports');
        if (res.ok) {
            const exports = await res.json();
            if (exports.length === 0) {
                exportsList.innerHTML = '<div style="color: var(--muted); font-size: 12px; text-align: center;">Aucun export</div>';
                return;
            }

            exportsList.innerHTML = exports.map(exp => {
                const date = new Date(exp.created);
                const sizeMB = (exp.size / 1024 / 1024).toFixed(2);
                return `
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; border-bottom: 1px solid var(--border);">
                        <div>
                            <div style="font-size: 12px; color: var(--muted);">${date.toLocaleString()}</div>
                            <div style="font-size: 11px; color: var(--text);">${exp.filename} (${sizeMB} MB)</div>
                        </div>
                        <a href="${exp.url}" download class="btn sm">📥 Télécharger</a>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        exportsList.innerHTML = '<div style="color: #f38b8b; font-size: 12px;">Erreur lors du chargement</div>';
        console.error('Exports error:', e);
    }
}


// Charger l'historique et les exports au démarrage
loadHistory();
loadExports();
setInterval(() => {
    loadHistory();
    loadExports();
}, 10000); // Rafraîchir toutes les 10 secondes

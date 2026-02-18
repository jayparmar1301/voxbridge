/**
 * Voxxwire — Frontend Application Logic
 * Communicates with the Python backend via pywebview's JS bridge.
 */

// ═══════════════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════════════
let isRunning = false;
let selectedModel = 'small';
let pollInterval = null;

// ═══════════════════════════════════════════════════════════════════════════
//  DOM REFERENCES
// ═══════════════════════════════════════════════════════════════════════════
const $ = (id) => document.getElementById(id);

const statusDot       = $('statusDot');
const statusText      = $('statusText');
const startBtn        = $('startBtn');
const outputMessages  = $('outputMessages');
const outputWelcome   = $('outputWelcome');
const logText         = $('logText');
const logArea         = $('logArea');
const logToggle       = $('logToggle');
const progressBar     = $('progressBar');
const progressContainer = $('progressContainer');
const clearBtn        = $('clearBtn');
const outputScroll    = $('outputScroll');

// ═══════════════════════════════════════════════════════════════════════════
//  INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════
window.addEventListener('pywebviewready', async () => {
    console.log('pywebview bridge ready');
    await initApp();
});

async function initApp() {
    try {
        // Load devices
        const devices = await pywebview.api.get_devices();
        populateDevices(devices);

        // Load languages
        const languages = await pywebview.api.get_languages();
        populateLanguages(languages);

        // Load current settings
        const settings = await pywebview.api.get_settings();
        applySettings(settings);

    } catch (e) {
        console.error('Init error:', e);
        appendLog('⚠ Failed to initialize: ' + e.message);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  POPULATE UI
// ═══════════════════════════════════════════════════════════════════════════
function populateDevices(devices) {
    const micSelect = $('micDevice');
    const lbSelect = $('loopbackDevice');

    micSelect.innerHTML = '';
    lbSelect.innerHTML = '';

    devices.inputs.forEach(d => {
        const opt = new Option(d.name, d.index);
        micSelect.add(opt);
    });

    devices.inputs.forEach(d => {
        const opt = new Option(d.name, d.index);
        lbSelect.add(opt);
    });
}

function populateLanguages(languages) {
    const selects = ['micSrcLang', 'micTgtLang', 'lbSrcLang', 'lbTgtLang'];
    selects.forEach(id => {
        const sel = $(id);
        sel.innerHTML = '';
        languages.forEach(lang => {
            sel.add(new Option(lang.name, lang.code));
        });
    });
}

function applySettings(s) {
    // Devices
    $('micDevice').value = s.mic_device ?? '';
    $('loopbackDevice').value = s.loopback_device ?? '';

    // Languages
    $('micSrcLang').value = s.mic_src_lang;
    $('micTgtLang').value = s.mic_tgt_lang;
    $('lbSrcLang').value = s.lb_src_lang;
    $('lbTgtLang').value = s.lb_tgt_lang;

    // Model
    selectedModel = s.whisper_model;
    document.querySelectorAll('.model-card').forEach(card => {
        card.classList.toggle('active', card.dataset.value === selectedModel);
    });

    // Toggles
    $('toggleSubtitles').checked = s.subtitles;
    $('toggleMic').checked = s.mic_channel;
    $('toggleLoopback').checked = s.loopback_channel;
}

// ═══════════════════════════════════════════════════════════════════════════
//  EVENTS
// ═══════════════════════════════════════════════════════════════════════════

// Start / Stop button
startBtn.addEventListener('click', async () => {
    if (!isRunning) {
        await startEngine();
    } else {
        await stopEngine();
    }
});

// Model card selection
document.querySelectorAll('.model-card').forEach(card => {
    card.addEventListener('click', () => {
        document.querySelectorAll('.model-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        selectedModel = card.dataset.value;
    });
});

// Log toggle
logToggle.addEventListener('click', () => {
    logArea.classList.toggle('expanded');
});

// Clear output
clearBtn.addEventListener('click', () => {
    outputMessages.innerHTML = '';
    outputWelcome.classList.remove('hidden');
});

// ═══════════════════════════════════════════════════════════════════════════
//  ENGINE CONTROL
// ═══════════════════════════════════════════════════════════════════════════
async function startEngine() {
    // Gather current settings
    const settings = {
        mic_device: parseInt($('micDevice').value) || 0,
        loopback_device: parseInt($('loopbackDevice').value) || 0,
        mic_src_lang: $('micSrcLang').value,
        mic_tgt_lang: $('micTgtLang').value,
        lb_src_lang: $('lbSrcLang').value,
        lb_tgt_lang: $('lbTgtLang').value,
        whisper_model: selectedModel,
        subtitles: $('toggleSubtitles').checked,
        mic_channel: $('toggleMic').checked,
        loopback_channel: $('toggleLoopback').checked,
    };

    setStatus('starting', 'Starting…');
    setRunning(true);
    showProgress(true, 0);
    logArea.classList.add('expanded');
    appendLog('Starting translator engine…');

    try {
        await pywebview.api.start_engine(settings);
        startPolling();
    } catch (e) {
        appendLog('❌ Failed to start: ' + e.message);
        setStatus('error', 'Error');
        setRunning(false);
        showProgress(false);
    }
}

async function stopEngine() {
    appendLog('Stopping translator…');
    try {
        await pywebview.api.stop_engine();
    } catch (e) {
        console.error('Stop error:', e);
    }
    stopPolling();
    setStatus('idle', 'Ready');
    setRunning(false);
    showProgress(false);
}

// ═══════════════════════════════════════════════════════════════════════════
//  POLLING (fetch messages from Python queue)
// ═══════════════════════════════════════════════════════════════════════════
function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(pollMessages, 200);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function pollMessages() {
    try {
        const messages = await pywebview.api.poll_messages();
        if (!messages || messages.length === 0) return;

        messages.forEach(msg => {
            switch (msg.type) {
                case 'log':
                    appendLog(msg.text);
                    break;
                case 'subtitle':
                    addTranslation(msg);
                    break;
                case 'progress':
                    showProgress(true, msg.value);
                    break;
                case 'status':
                    setStatus(msg.state, msg.text);
                    break;
                case 'stopped':
                    setStatus('idle', 'Ready');
                    setRunning(false);
                    showProgress(false);
                    stopPolling();
                    break;
            }
        });
    } catch (e) {
        // Ignore polling errors
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  UI HELPERS
// ═══════════════════════════════════════════════════════════════════════════
function setStatus(state, text) {
    statusDot.className = 'status-dot ' + state;
    statusText.textContent = text;
}

function setRunning(running) {
    isRunning = running;
    if (running) {
        startBtn.classList.add('running');
        startBtn.querySelector('.btn-start-icon').textContent = '■';
        startBtn.querySelector('.btn-start-text').textContent = 'Stop Translator';
    } else {
        startBtn.classList.remove('running');
        startBtn.querySelector('.btn-start-icon').textContent = '▶';
        startBtn.querySelector('.btn-start-text').textContent = 'Start Translator';
    }
}

function showProgress(visible, value) {
    progressContainer.classList.toggle('visible', visible);
    if (value !== undefined) {
        progressBar.style.width = (value * 100) + '%';
    }
}

function appendLog(text) {
    logText.textContent += text;
    // Auto-scroll log
    const logContent = $('logContent');
    logContent.scrollTop = logContent.scrollHeight;
}

function addTranslation(msg) {
    outputWelcome.classList.add('hidden');

    const item = document.createElement('div');
    item.className = 'msg-item' + (msg.channel === 'loopback' ? ' loopback' : '');

    const channelLabel = msg.channel === 'mic' ? '🎙️ Your Speech' : '🔊 Remote Speech';

    item.innerHTML = `
        <div class="msg-channel">${channelLabel} · ${msg.src_lang} → ${msg.tgt_lang}</div>
        <div class="msg-original">${escapeHtml(msg.original)}</div>
        <div class="msg-translated">${escapeHtml(msg.translated)}</div>
    `;

    outputMessages.appendChild(item);

    // Keep max 50 messages
    while (outputMessages.children.length > 50) {
        outputMessages.removeChild(outputMessages.firstChild);
    }

    // Auto-scroll
    outputScroll.scrollTop = outputScroll.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

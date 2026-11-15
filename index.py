from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import threading
import time
import urllib.request
import wave
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyttsx3
import soundcard as sc
import sounddevice as sd
from flask import Flask, Response, jsonify, render_template, request
from shazamio import Shazam

CAPTURE_RATE = 48_000
BLOCK_SIZE = 1024
QUEUE_BLOCKS = 16
SAMPLE_RATES = (48_000, 44_100, 32_000, 22_050, 16_000, 96_000)
PLUGINS_FILE = "plugins.json"

# ==========================================
# AUTO-GENERATE HTML TEMPLATES ON STARTUP
# ==========================================
os.makedirs("templates", exist_ok=True)

NAV_HTML = """
<div class="nav">
    <a href="/">🏠 Audio Hub</a>
    <a href="/plugins">🧩 Plugins Marketplace</a>
    <a href="/docs">📚 Documentation</a>
</div>
"""

BASE_STYLES = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; line-height: 1.5; }
.container { max-width: 800px; margin: 0 auto; background: #1e293b; padding: 25px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.35); }
h1 { margin-top: 0; color: #38bdf8; font-size: 22px; display: flex; justify-content: space-between; align-items: center; }
h3 { margin: 0 0 8px 0; font-size: 16px; color: #f1f5f9; }
p { color: #94a3b8; font-size: 14px; margin: 6px 0; }
.badge { font-size: 11px; background: #059669; color: white; padding: 4px 10px; border-radius: 12px; }
.nav { display: flex; gap: 10px; margin-bottom: 20px; }
.nav a { flex: 1; text-align: center; padding: 10px; background: #334155; color: #38bdf8; text-decoration: none; border-radius: 6px; font-weight: bold; transition: background 0.2s; }
.nav a:hover { background: #475569; }
.section { background: #0f172a; padding: 16px; border-radius: 8px; margin: 16px 0; border: 1px solid #334155; }
.btn-group { display: flex; gap: 10px; margin-top: 14px; }
button { flex: 1; padding: 11px; font-size: 14px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; transition: opacity 0.2s; }
button:hover { opacity: 0.9; }
.btn-start { background: #22c55e; color: white; }
.btn-stop { background: #ef4444; color: white; }
.btn-blue { background: #0284c7; color: white; }
.db-badge { background: #090d16; border: 1px solid #334155; padding: 4px 10px; border-radius: 4px; font-family: monospace; font-size: 13px; color: #38bdf8; }
"""

with open("templates/index.html", "w", encoding="utf-8") as f:
    f.write(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Universal Audio Gateway Hub</title>
    <style>
        {BASE_STYLES}
        .song-banner {{ background: #334155; padding: 10px 15px; border-radius: 6px; margin-bottom: 10px; font-size: 14px; color: #38bdf8; font-weight: bold; }}
        .info-panel {{ background: #090d16; padding: 10px 15px; border-radius: 6px; margin-bottom: 14px; font-size: 13px; color: #34d399; border: 1px solid #334155; }}
        .toggle-box {{ background: #090d16; padding: 10px 15px; border-radius: 6px; margin-bottom: 14px; border: 1px solid #334155; display: flex; align-items: center; justify-content: space-between; font-size: 14px; }}
        .history-box {{ max-height: 90px; overflow-y: auto; background: #0f172a; padding: 8px 12px; border-radius: 6px; font-size: 12px; color: #cbd5e1; border: 1px solid #334155; }}
        .device-list {{ max-height: 150px; overflow-y: auto; margin-top: 8px; padding-right: 5px; }}
        .device-list label {{ display: block; margin-bottom: 6px; cursor: pointer; font-size: 14px; }}
        .slider-group {{ margin-top: 10px; font-size: 13px; color: #94a3b8; display: flex; align-items: center; gap: 10px; }}
        .slider-group input {{ flex: 1; accent-color: #38bdf8; }}
        .meter-row {{ display: flex; justify-content: space-between; margin-top: 10px; font-size: 12px; color: #38bdf8; }}
        canvas {{ width: 100%; height: 60px; background: #090d16; border-radius: 6px; margin-top: 6px; }}
        .status {{ margin-top: 10px; font-weight: bold; font-size: 13px; color: #94a3b8; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Universal Audio Gateway Hub <span class="badge">v2.0 Release</span></h1>
        <p>Live desktop streaming, multi-speaker mirroring, microphone routing, and real-time dB telemetry.</p>
        {NAV_HTML}

        <div id="nowPlaying" class="song-banner">🎵 24/7 Identified Track: Listening...</div>
        <div id="weatherInfo" class="info-panel">🌤️ Weather Telemetry: Loading...</div>

        <div class="toggle-box">
            <span>Enable 24/7 Shazam Track Recognition</span>
            <input type="checkbox" id="recognitionToggle" checked onchange="toggleRecognition(this.checked)">
        </div>

        <div style="font-size: 12px; color: #94a3b8; margin-bottom: 5px;">📜 Recent Tracks Log:</div>
        <div id="songHistory" class="history-box">No tracks identified yet.</div>

        <button class="btn-blue" onclick="fetchDevices()" style="margin-top: 14px; padding: 8px 14px; font-size: 13px;">🔄 Refresh Audio Devices</button>

        <div class="section">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>1. Browser / Phone Desktop Audio Player</h3>
                <span id="desktopDbBadge" class="db-badge">Stream: -100.0 dB</span>
            </div>
            <p>Stream live PC system audio directly into your phone or browser speakers.</p>
            <div class="slider-group">
                <label for="volumeSlider">Volume:</label>
                <input type="range" id="volumeSlider" min="0" max="1" step="0.05" value="1" oninput="setVolume(this.value)">
            </div>
            <div class="meter-row">
                <span>Frequency Spectrum</span>
                <span id="clientDbText">Browser Output: -60.0 dB</span>
            </div>
            <canvas id="visualizer"></canvas>
            <div class="btn-group">
                <button class="btn-start" onclick="startDesktopStream()">Start Listening</button>
                <button class="btn-stop" onclick="stopDesktopStream()">Stop Listening</button>
            </div>
            <div id="desktopStatus" class="status">Status: Idle</div>
        </div>

        <div class="section">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>2. Hardware Speaker Mirroring (PC → Other Speakers)</h3>
                <span id="mirrorDbBadge" class="db-badge">Mirror: -100.0 dB</span>
            </div>
            <p>Select physical output devices to mirror desktop audio simultaneously:</p>
            <div class="device-list" id="mirrorDeviceList">Loading devices...</div>
            <div class="btn-group">
                <button class="btn-start" onclick="startMirror()">Start Mirror</button>
                <button class="btn-stop" onclick="stopMirror()">Stop Mirror</button>
            </div>
            <div id="mirrorStatus" class="status">Status: Idle</div>
        </div>

        <div class="section">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>3. Browser / Phone Microphone → System Speakers</h3>
                <span id="micDbBadge" class="db-badge">Mic: -100.0 dB</span>
            </div>
            <p>Broadcast your phone or browser microphone live to selected PC speakers:</p>
            <div class="device-list" id="micDeviceList">Loading devices...</div>
            <div class="slider-group">
                <label for="gainSlider">Mic Gain:</label>
                <input type="range" id="gainSlider" min="0" max="2.5" step="0.1" value="1" oninput="setGain(this.value)">
            </div>
            <div class="btn-group">
                <button class="btn-start" onclick="startMicStream()">Start Mic</button>
                <button class="btn-stop" onclick="stopMicStream()">Stop Mic</button>
            </div>
            <div id="micStatus" class="status">Status: Idle</div>
        </div>
    </div>

    <script>
        let audioCtx = null, desktopReader = null, isListening = false;
        let masterGainNode = null, analyserNode = null, gainNode = null;
        let micMediaStream = null, micProcessorNode = null, micSourceNode = null;

        function initAudioContext() {{
            if (!audioCtx) {{
                audioCtx = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate: 48000 }});
                masterGainNode = audioCtx.createGain();
                analyserNode = audioCtx.createAnalyser();
                analyserNode.fftSize = 256;
                masterGainNode.connect(analyserNode);
                analyserNode.connect(audioCtx.destination);
                drawVisualizer();
            }}
            if (audioCtx.state === 'suspended') audioCtx.resume();
        }}

        function setVolume(val) {{ if (masterGainNode) masterGainNode.gain.value = parseFloat(val); }}
        function setGain(val) {{ if (gainNode) gainNode.gain.value = parseFloat(val); }}

        async function toggleRecognition(enabled) {{
            await fetch('/api/toggle_recognition', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ enabled }})
            }});
        }}

        function drawVisualizer() {{
            const canvas = document.getElementById('visualizer');
            const ctx = canvas.getContext('2d');
            const freqData = new Uint8Array(analyserNode.frequencyBinCount);
            const timeData = new Float32Array(analyserNode.fftSize);

            function render() {{
                requestAnimationFrame(render);
                if (!analyserNode) return;
                analyserNode.getByteFrequencyData(freqData);
                analyserNode.getFloatTimeDomainData(timeData);

                let sum = 0;
                for (let i = 0; i < timeData.length; i++) sum += timeData[i] * timeData[i];
                let rms = Math.sqrt(sum / timeData.length);
                let db = 20 * Math.log10(rms);
                if (db < -60 || isNaN(db)) db = -60;
                document.getElementById('clientDbText').innerText = `Browser Output: ${{db.toFixed(1)}} dB`;

                ctx.fillStyle = '#090d16';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                const barWidth = (canvas.width / freqData.length) * 2.5;
                let x = 0;
                for (let i = 0; i < freqData.length; i++) {{
                    const h = (freqData[i] / 255) * canvas.height;
                    ctx.fillStyle = '#38bdf8';
                    ctx.fillRect(x, canvas.height - h, barWidth, h);
                    x += barWidth + 1;
                }}
            }}
            render();
        }}

        async function fetchDevices() {{
            try {{
                const res = await fetch('/api/devices');
                const devices = await res.json();
                const mirrorList = document.getElementById('mirrorDeviceList');
                const micList = document.getElementById('micDeviceList');
                const checkedMirror = new Set(Array.from(mirrorList.querySelectorAll('input:checked')).map(c => c.value));
                const checkedMic = new Set(Array.from(micList.querySelectorAll('input:checked')).map(c => c.value));

                mirrorList.innerHTML = '';
                micList.innerHTML = '';
                devices.forEach(dev => {{
                    mirrorList.innerHTML += `<label><input type="checkbox" value="${{dev.index}}" ${{dev.isDefault ? 'disabled' : ''}} ${{checkedMirror.has(String(dev.index)) ? 'checked' : ''}}> <strong>${{dev.name}}</strong> (${{dev.sampleRate}} Hz) ${{dev.isDefault ? '<em>(Default)</em>' : ''}}</label>`;
                    micList.innerHTML += `<label><input type="checkbox" value="${{dev.index}}" ${{checkedMic.has(String(dev.index)) ? 'checked' : ''}}> <strong>${{dev.name}}</strong> (${{dev.sampleRate}} Hz)</label>`;
                }});
            }} catch (e) {{}}
        }}

        async function startDesktopStream() {{
            initAudioContext();
            const statusEl = document.getElementById('desktopStatus');
            try {{
                isListening = true;
                const res = await fetch('/api/stream_desktop');
                desktopReader = res.body.getReader();
                statusEl.innerText = "Status: Listening Live 🟢";
                statusEl.style.color = "#4ade80";

                let nextTime = audioCtx.currentTime + 0.15;
                while (isListening) {{
                    const {{ value, done }} = await desktopReader.read();
                    if (done) break;
                    const float32 = new Float32Array(value.buffer);
                    if (float32.length === 0) continue;
                    const buf = audioCtx.createBuffer(2, float32.length / 2, 48000);
                    buf.getChannelData(0).set(float32.filter((_, i) => i % 2 === 0));
                    buf.getChannelData(1).set(float32.filter((_, i) => i % 2 !== 0));
                    const src = audioCtx.createBufferSource();
                    src.buffer = buf;
                    src.connect(masterGainNode);
                    if (nextTime < audioCtx.currentTime) nextTime = audioCtx.currentTime + 0.05;
                    src.start(nextTime);
                    nextTime += buf.duration;
                }}
            }} catch (err) {{
                if (isListening) {{
                    statusEl.innerText = "Status: Reconnecting...";
                    statusEl.style.color = "#f87171";
                    setTimeout(startDesktopStream, 2000);
                }}
            }}
        }}

        function stopDesktopStream() {{
            isListening = false;
            if (desktopReader) {{ desktopReader.cancel().catch(() => {{}}); desktopReader = null; }}
            document.getElementById('desktopStatus').innerText = "Status: Stopped 🔴";
            document.getElementById('desktopStatus').style.color = "#f87171";
        }}

        async function startMirror() {{
            const indices = Array.from(document.querySelectorAll('#mirrorDeviceList input:checked')).map(cb => parseInt(cb.value));
            if (indices.length === 0) return alert('Select at least one output speaker!');
            const res = await fetch('/api/start_mirror', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ devices: indices }})
            }});
            const data = await res.json();
            const statusEl = document.getElementById('mirrorStatus');
            if (data.success) {{ statusEl.innerText = "Status: Mirroring Active 🟢"; statusEl.style.color = "#4ade80"; }}
            else alert('Error: ' + data.error);
        }}

        async function stopMirror() {{
            await fetch('/api/stop_mirror', {{ method: 'POST' }});
            document.getElementById('mirrorStatus').innerText = "Status: Stopped 🔴";
            document.getElementById('mirrorStatus').style.color = "#f87171";
        }}

        async function startMicStream() {{
            initAudioContext();
            const indices = Array.from(document.querySelectorAll('#micDeviceList input:checked')).map(cb => parseInt(cb.value));
            if (indices.length === 0) return alert('Select at least one target speaker!');
            try {{
                micMediaStream = await navigator.mediaDevices.getUserMedia({{ audio: true, video: false }});
                micSourceNode = audioCtx.createMediaStreamSource(micMediaStream);
                gainNode = audioCtx.createGain();
                micProcessorNode = audioCtx.createScriptProcessor(1024, 1, 1);
                micProcessorNode.onaudioprocess = (e) => {{
                    fetch('/api/push_mic', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ audio: Array.from(e.inputBuffer.getChannelData(0)) }})
                    }}).catch(() => {{}});
                }};
                micSourceNode.connect(gainNode);
                gainNode.connect(micProcessorNode);
                micProcessorNode.connect(audioCtx.destination);
                await fetch('/api/start_mic', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ devices: indices }})
                }});
                const statusEl = document.getElementById('micStatus');
                statusEl.innerText = "Status: Mic Live 🟢";
                statusEl.style.color = "#4ade80";
            }} catch (err) {{ alert('Mic Error: ' + err.message); }}
        }}

        async function stopMicStream() {{
            if (micMediaStream) micMediaStream.getTracks().forEach(t => t.stop());
            if (micProcessorNode) {{ micProcessorNode.disconnect(); micProcessorNode = null; }}
            await fetch('/api/stop_mic', {{ method: 'POST' }});
            document.getElementById('micStatus').innerText = "Status: Stopped 🔴";
            document.getElementById('micStatus').style.color = "#f87171";
        }}

        setInterval(async () => {{
            try {{
                const res = await fetch('/api/info');
                const data = await res.json();
                if (data.song) document.getElementById('nowPlaying').innerText = "🎵 24/7 Identified Track: " + data.song;
                if (data.weather) document.getElementById('weatherInfo').innerText = "🌤️ Weather Telemetry: " + data.weather;
                if (data.history && data.history.length > 0) {{
                    document.getElementById('songHistory').innerHTML = data.history.map(s => `<div>• ${{s}}</div>`).join('');
                }}
                if (data.telemetry) {{
                    document.getElementById('desktopDbBadge').innerText = `Stream: ${{data.telemetry.desktop_stream_db.toFixed(1)}} dB`;
                    document.getElementById('mirrorDbBadge').innerText = `Mirror: ${{data.telemetry.mirror_stream_db.toFixed(1)}} dB`;
                    document.getElementById('micDbBadge').innerText = `Mic: ${{data.telemetry.mic_stream_db.toFixed(1)}} dB`;
                }}
            }} catch (e) {{}}
        }}, 1000);

        fetchDevices();
    </script>
</body>
</html>""")

with open("templates/plugins.html", "w", encoding="utf-8") as f:
    f.write(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Plugins Marketplace - Universal Audio Hub</title>
    <style>
        {BASE_STYLES}
        .plugin-card {{ background: #0f172a; border: 1px solid #334155; padding: 15px; border-radius: 8px; margin-bottom: 15px; }}
        .plugin-header {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; }}
        input[type="text"] {{ background: #090d16; color: #fff; border: 1px solid #334155; padding: 8px; border-radius: 4px; flex: 1; font-size: 14px; }}
        textarea {{ width: 100%; height: 150px; background: #090d16; color: #38bdf8; font-family: monospace; font-size: 13px; border: 1px solid #334155; border-radius: 6px; padding: 10px; box-sizing: border-box; margin-top: 10px; resize: vertical; }}
        .console {{ background: #090d16; color: #34d399; font-family: monospace; padding: 12px; height: 170px; overflow-y: auto; font-size: 12px; border-radius: 6px; border: 1px solid #334155; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Plugins Marketplace <span class="badge" style="background:#8b5cf6;">Persistent Multi-Plugin IDE</span></h1>
        <p>Create, enable, and run multiple custom Python audio plugins simultaneously. Saved automatically to disk.</p>
        {NAV_HTML}

        <button class="btn-blue" onclick="addPlugin()" style="width: 100%; margin-bottom: 16px;">➕ Create New Plugin</button>
        <div id="pluginList">Loading plugins...</div>

        <div class="section">
            <h3>Live Plugin Console Output</h3>
            <div id="logs" class="console">Waiting for plugin logs...</div>
        </div>
    </div>

    <script>
        async function loadPlugins() {{
            const res = await fetch('/api/plugins');
            const data = await res.json();
            const container = document.getElementById('pluginList');
            container.innerHTML = '';
            data.plugins.forEach(p => {{
                const card = document.createElement('div');
                card.className = 'plugin-card';
                card.innerHTML = `
                    <div class="plugin-header">
                        <input type="text" id="name_${{p.id}}" value="${{p.name.replace(/"/g, '&quot;')}}">
                        <label style="font-size:14px; cursor:pointer;"><input type="checkbox" id="en_${{p.id}}" ${{p.enabled ? 'checked' : ''}}> Active</label>
                        <button class="btn-stop" onclick="delPlugin('${{p.id}}')" style="flex:0; padding:6px 12px;">Delete</button>
                    </div>
                    <textarea id="code_${{p.id}}">${{p.code}}</textarea>
                    <div style="margin-top: 10px; display: flex; align-items: center; gap: 12px;">
                        <button class="btn-start" onclick="savePlugin('${{p.id}}')" style="flex:0; padding: 8px 18px;">Save & Compile</button>
                        <span id="msg_${{p.id}}" style="font-size:13px; color:#38bdf8; font-weight:bold;"></span>
                    </div>
                `;
                container.appendChild(card);
            }});
        }}

        async function addPlugin() {{
            await fetch('/api/plugins/add', {{ method: 'POST' }});
            loadPlugins();
        }}

        async function delPlugin(id) {{
            if (!confirm('Delete this plugin?')) return;
            await fetch('/api/plugins/delete', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ id }})
            }});
            loadPlugins();
        }}

        async function savePlugin(id) {{
            const msgEl = document.getElementById(`msg_${{id}}`);
            const res = await fetch('/api/plugins/save', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    id,
                    name: document.getElementById(`name_${{id}}`).value,
                    enabled: document.getElementById(`en_${{id}}`).checked,
                    code: document.getElementById(`code_${{id}}`).value
                }})
            }});
            const data = await res.json();
            msgEl.innerText = data.success ? "✅ Saved to disk!" : "❌ Error saving";
            setTimeout(() => msgEl.innerText = "", 2500);
        }}

        setInterval(async () => {{
            try {{
                const res = await fetch('/api/plugin/logs');
                const data = await res.json();
                if (data.logs) {{
                    const el = document.getElementById('logs');
                    el.innerHTML = data.logs.join('<br>');
                    el.scrollTop = el.scrollHeight;
                }}
            }} catch (e) {{}}
        }}, 1500);

        loadPlugins();
    </script>
</body>
</html>""")

with open("templates/docs.html", "w", encoding="utf-8") as f:
    f.write(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Documentation - Universal Audio Hub</title>
    <style>
        {BASE_STYLES}
        h2 {{ color: #34d399; font-size: 17px; border-bottom: 1px solid #334155; padding-bottom: 6px; margin-top: 22px; }}
        code {{ background: #090d16; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-family: monospace; }}
        pre {{ background: #090d16; color: #38bdf8; padding: 14px; border-radius: 6px; border: 1px solid #334155; overflow-x: auto; font-family: monospace; font-size: 13px; }}
        li {{ color: #cbd5e1; font-size: 14px; margin-bottom: 6px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Developer Documentation <span class="badge" style="background:#0284c7;">API & Plugins</span></h1>
        <p>Reference guide for building custom audio processing plugins and using the REST API.</p>
        {NAV_HTML}

        <h2>1. Plugin Sandbox Variables</h2>
        <ul>
            <li><code>audio_snippet</code>: 1D NumPy <code>float32</code> array of 16,000 Hz mono desktop audio (5-second window).</li>
            <li><code>sample_rate</code>: Sampling rate in Hz (<code>16000</code>).</li>
            <li><code>np</code>: Pre-imported NumPy module for fast DSP math.</li>
            <li><code>state</code>: Persistent dictionary unique to each plugin—use it to store counters, timers, or history between runs.</li>
            <li><code>speak_status(text)</code>: Speaks text aloud via the host PC's text-to-speech engine.</li>
            <li><code>print(*args)</code>: Logs directly to the live Plugins Marketplace console.</li>
        </ul>

        <h2>2. Example: Peak Volume Alert Plugin</h2>
        <pre><code>rms = np.sqrt(np.mean(audio_snippet**2))
db = float(20 * np.log10(rms)) if rms > 0 else -100.0
if db > -15.0:
    print(f"Loud spike detected: {{db:.1f}} dB")
    speak_status(f"Alert, volume reached {{db:.0f}} decibels")</code></pre>

        <h2>3. REST Endpoints</h2>
        <ul>
            <li><code>GET /api/info</code> — Returns current song, history, weather, and live dB telemetry across all streams.</li>
            <li><code>GET /api/devices</code> — Lists all compatible Windows WASAPI output speakers.</li>
            <li><code>GET /api/plugins</code> — Lists all configured plugins.</li>
        </ul>
    </div>
</body>
</html>""")


# ==========================================
# FLASK APPLICATION BACKEND
# ==========================================
app = Flask(__name__)

# Global threads & state
active_mirror_thread: threading.Thread | None = None
active_stop_event: threading.Event | None = None
active_errors: list[tuple[str, Exception]] = []

mic_input_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=QUEUE_BLOCKS)
mic_stop_event: threading.Event | None = None
mic_thread: threading.Thread | None = None

tts_lock = threading.Lock()
known_device_names: set[str] = set()
current_identified_song: str = "Listening for music 24/7..."
song_history: list[str] = []
last_announced_song: str = ""
current_weather_info: str = "Weather info updating..."
music_recognition_enabled: bool = True

global_telemetry: dict[str, float] = {
    "desktop_stream_db": -100.0,
    "mirror_stream_db": -100.0,
    "mic_stream_db": -100.0,
}

DEFAULT_PLUGINS = [
    {
        "id": "plugin_1",
        "name": "10-Second Volume Speaker",
        "enabled": True,
        "code": """import time

state.setdefault("last_time", 0.0)
state.setdefault("readings", [])

rms = np.sqrt(np.mean(audio_snippet**2))
current_db = float(20 * np.log10(rms)) if rms > 0 else -100.0
state["readings"].append(current_db)

now = time.time()
if now - state["last_time"] >= 10.0:
    avg_db = sum(state["readings"]) / len(state["readings"])
    msg = f"Current audio loudness is {avg_db:.1f} decibels"
    print(f"📢 {msg}")
    speak_status(msg)
    state["last_time"] = now
    state["readings"] = []
else:
    print(f"📊 Sampling... Current block: {current_db:.1f} dB")
""",
    }
]


def load_plugins() -> list[dict[str, Any]]:
    if os.path.exists(PLUGINS_FILE):
        try:
            with open(PLUGINS_FILE, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    save_plugins(DEFAULT_PLUGINS)
    return DEFAULT_PLUGINS


def save_plugins(plugins: list[dict[str, Any]]) -> None:
    try:
        with open(PLUGINS_FILE, "w", encoding="utf-8") as fp:
            json.dump(plugins, fp, indent=2)
    except Exception:
        pass


plugins_registry: list[dict[str, Any]] = load_plugins()
plugin_states: dict[str, dict[str, Any]] = {}
plugin_console_logs: list[str] = ["Plugin engine initialized successfully."]


def speak_status(text: str) -> None:
    def _speak():
        with tts_lock:
            try:
                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()
            except Exception:
                pass

    threading.Thread(target=_speak, daemon=True).start()


def log_plugin_output(message: str) -> None:
    global plugin_console_logs
    timestamp = time.strftime("[%H:%M:%S]")
    plugin_console_logs.append(f"{timestamp} {message}")
    if len(plugin_console_logs) > 60:
        plugin_console_logs.pop(0)


def execute_all_plugins(audio_snippet: np.ndarray, sample_rate: int) -> None:
    for plugin in list(plugins_registry):
        if not plugin.get("enabled", True):
            continue
        p_id = plugin["id"]
        p_state = plugin_states.setdefault(p_id, {})
        try:
            local_scope = {
                "audio_snippet": audio_snippet,
                "sample_rate": sample_rate,
                "np": np,
                "state": p_state,
                "speak_status": speak_status,
                "print": lambda *args, p_name=plugin["name"]: log_plugin_output(
                    f"[{p_name}] " + " ".join(map(str, args))
                ),
            }
            exec(plugin["code"], {"__builtins__": __builtins__}, local_scope)
        except Exception as e:
            log_plugin_output(f"[{plugin['name']}] Error: {e}")


@dataclass
class Speaker:
    device: dict[str, Any]
    channels: int
    sample_rate: int
    blocks: queue.Queue[np.ndarray] = field(
        default_factory=lambda: queue.Queue(maxsize=QUEUE_BLOCKS)
    )
    dropped_blocks: int = 0

    def push(self, audio: np.ndarray) -> None:
        try:
            self.blocks.put_nowait(audio)
        except queue.Full:
            try:
                self.blocks.get_nowait()
            except queue.Empty:
                pass
            try:
                self.blocks.put_nowait(audio)
                self.dropped_blocks += 1
            except queue.Full:
                self.dropped_blocks += 1


def compatible_speakers() -> list[dict[str, Any]]:
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()
    wasapi_apis = {
        i for i, h in enumerate(host_apis) if "WASAPI" in h["name"].upper()
    }
    if not wasapi_apis:
        raise RuntimeError("Windows WASAPI audio outputs were not found.")

    default_index = sd.default.device[1]
    default_name = (
        str(devices[default_index]["name"]).strip().casefold()
        if default_index is not None and default_index >= 0
        else ""
    )

    speakers: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, device in enumerate(devices):
        name = str(device["name"]).strip()
        normalized_name = name.casefold()
        if int(device["hostapi"]) not in wasapi_apis:
            continue
        if any(
            f in normalized_name
            for f in (
                "loopback",
                "steam streaming mic",
                "microphone",
                "mapper",
                "primary sound",
                "communications",
            )
        ):
            continue
        if normalized_name in seen_names or int(device["max_output_channels"]) < 1:
            continue

        channels = min(2, int(device["max_output_channels"]))
        supported_rate = None
        for rate in dict.fromkeys((*SAMPLE_RATES, int(device["default_samplerate"]))):
            try:
                sd.check_output_settings(
                    device=index, channels=channels, dtype="float32", samplerate=rate
                )
                supported_rate = rate
                break
            except sd.PortAudioError:
                continue
        if supported_rate is None:
            continue

        seen_names.add(normalized_name)
        speakers.append(
            {
                "index": index,
                "name": name,
                "channels": channels,
                "sampleRate": supported_rate,
                "isDefault": index == default_index or normalized_name == default_name,
            }
        )
    return speakers


def device_monitor_worker() -> None:
    global known_device_names
    try:
        known_device_names = {d["name"] for d in compatible_speakers()}
    except Exception:
        pass

    while True:
        time.sleep(3)
        try:
            current_names = {d["name"] for d in compatible_speakers()}
            for dev in current_names - known_device_names:
                speak_status(f"New speaker connected: {dev}")
            for dev in known_device_names - current_names:
                speak_status(f"Speaker disconnected: {dev}")
            known_device_names = current_names
        except Exception:
            pass


threading.Thread(target=device_monitor_worker, daemon=True).start()


def find_default_loopback() -> Any:
    default_speaker = sc.default_speaker()
    loopback = next(
        (
            m
            for m in sc.all_microphones(include_loopback=True)
            if m.isloopback and m.id == default_speaker.id
        ),
        None,
    )
    if loopback is None:
        loopback = next(
            (m for m in sc.all_microphones(include_loopback=True) if m.isloopback),
            None,
        )
    if loopback is None:
        raise RuntimeError("Could not find loopback capture for speakers.")
    return loopback


def weather_info_worker() -> None:
    global current_weather_info
    while True:
        try:
            req = urllib.request.urlopen(
                "https://api.open-meteo.com/v1/forecast?latitude=42.33&longitude=-83.04&current_weather=true",
                timeout=5,
            )
            data = json.loads(req.read().decode())
            w = data.get("current_weather", {})
            current_weather_info = (
                f"Temp: {w.get('temperature', 'N/A')}°C | Wind: {w.get('windspeed', 'N/A')} km/h"
            )
        except Exception:
            current_weather_info = "Weather telemetry active (Offline Mode)"
        time.sleep(600)


threading.Thread(target=weather_info_worker, daemon=True).start()


def continuous_music_recognition_worker() -> None:
    global current_identified_song, last_announced_song, song_history, music_recognition_enabled, global_telemetry

    async def worker_loop() -> None:
        global current_identified_song, last_announced_song, song_history, music_recognition_enabled, global_telemetry
        shazam = Shazam()
        try:
            while True:
                try:
                    loopback = find_default_loopback()
                    with loopback.recorder(samplerate=16_000, channels=1) as recorder:
                        audio_snippet = recorder.record(numframes=16_000 * 5)

                    if audio_snippet.size == 0:
                        global_telemetry["desktop_stream_db"] = -100.0
                        await asyncio.sleep(1)
                        continue

                    rms = float(np.sqrt(np.mean(audio_snippet**2)))
                    db = float(20 * np.log10(rms)) if rms > 0 else -100.0
                    global_telemetry["desktop_stream_db"] = max(-100.0, db)

                    execute_all_plugins(audio_snippet, 16_000)

                    if not music_recognition_enabled:
                        current_identified_song = "Audio Recognition Paused ⏸️"
                        await asyncio.sleep(2)
                        continue

                    if np.max(np.abs(audio_snippet)) < 0.02:
                        await asyncio.sleep(1)
                        continue

                    wav_io = io.BytesIO()
                    with wave.open(wav_io, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16_000)
                        wf.writeframes((audio_snippet * 32767).astype(np.int16).tobytes())

                    out = await shazam.recognize(wav_io.getvalue())
                    track = out.get("track")
                    if track and track.get("title"):
                        artist = track.get("subtitle")
                        song_str = (
                            f"{track['title']} by {artist}" if artist else track["title"]
                        )
                        if song_str != current_identified_song:
                            current_identified_song = song_str
                            if song_str not in song_history:
                                song_history.insert(0, song_str)
                                if len(song_history) > 10:
                                    song_history.pop()
                            if song_str != last_announced_song:
                                last_announced_song = song_str
                                speak_status(f"Now playing: {song_str}")

                    await asyncio.sleep(1)
                except Exception:
                    global_telemetry["desktop_stream_db"] = -100.0
                    await asyncio.sleep(2)
        finally:
            # Cleanly close underlying aiohttp client if exposed
            client = getattr(shazam, "http_client", None) or getattr(shazam, "_client", None)
            if client and hasattr(client, "close"):
                await client.close()

    asyncio.run(worker_loop())


threading.Thread(target=continuous_music_recognition_worker, daemon=True).start()


def resample(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == CAPTURE_RATE or audio.shape[0] == 0:
        return audio
    output_frames = max(1, round(audio.shape[0] * sample_rate / CAPTURE_RATE))
    positions = np.arange(output_frames, dtype=np.float64) * (
        CAPTURE_RATE / sample_rate
    )
    positions = np.minimum(positions, audio.shape[0] - 1)
    left = positions.astype(np.intp)
    right = np.minimum(left + 1, audio.shape[0] - 1)
    fraction = (positions - left)[:, np.newaxis]
    return (audio[left] * (1.0 - fraction) + audio[right] * fraction).astype(np.float32)


def prepare_audio(audio: np.ndarray, speaker: Speaker) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples[:, np.newaxis]
    if speaker.channels == 1 and samples.shape[1] > 1:
        samples = samples.mean(axis=1, keepdims=True)
    elif speaker.channels == 2 and samples.shape[1] == 1:
        samples = np.repeat(samples, 2, axis=1)
    return np.ascontiguousarray(
        np.clip(resample(samples, speaker.sample_rate), -1.0, 1.0), dtype=np.float32
    )


def output_worker(
    speaker: Speaker,
    stop_event: threading.Event,
    ready_event: threading.Event,
    errors: list[tuple[str, Exception]],
) -> None:
    device_name = speaker.device["name"]
    try:
        with sd.OutputStream(
            device=speaker.device["index"],
            channels=speaker.channels,
            samplerate=speaker.sample_rate,
            dtype="float32",
            blocksize=0,
        ) as stream:
            ready_event.set()
            speak_status(f"Speaker online: {device_name}")
            while not stop_event.is_set() or not speaker.blocks.empty():
                try:
                    audio = speaker.blocks.get(timeout=0.1)
                except queue.Empty:
                    continue
                rms = float(np.sqrt(np.mean(audio**2)))
                global_telemetry["mirror_stream_db"] = max(
                    -100.0, float(20 * np.log10(rms)) if rms > 0 else -100.0
                )
                stream.write(audio)
    except Exception as exc:
        errors.append((device_name, exc))
        speak_status(f"Speaker disconnected: {device_name}")
        ready_event.set()


# ==========================================
# FLASK ROUTES & API ENDPOINTS
# ==========================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/plugins")
def plugins_page():
    return render_template("plugins.html")


@app.route("/docs")
def docs_page():
    return render_template("docs.html")


@app.route("/api/devices")
def api_devices():
    try:
        return jsonify(compatible_speakers())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ping")
def api_ping():
    return jsonify({"status": "alive"})


@app.route("/api/info")
def api_info():
    return jsonify(
        {
            "song": current_identified_song,
            "history": song_history,
            "weather": current_weather_info,
            "recognition_enabled": music_recognition_enabled,
            "telemetry": global_telemetry,
        }
    )


@app.route("/api/toggle_recognition", methods=["POST"])
def api_toggle_recognition():
    global music_recognition_enabled
    music_recognition_enabled = bool((request.json or {}).get("enabled", True))
    return jsonify({"success": True})


@app.route("/api/plugins")
def api_plugins_list():
    return jsonify({"plugins": plugins_registry})


@app.route("/api/plugins/add", methods=["POST"])
def api_plugins_add():
    global plugins_registry
    new_id = f"plugin_{int(time.time() * 1000)}"
    plugins_registry.append(
        {
            "id": new_id,
            "name": "New Custom Plugin",
            "enabled": True,
            "code": "rms = np.sqrt(np.mean(audio_snippet**2))\nprint(f'RMS Level: {rms:.4f}')",
        }
    )
    save_plugins(plugins_registry)
    return jsonify({"success": True, "id": new_id})


@app.route("/api/plugins/save", methods=["POST"])
def api_plugins_save():
    global plugins_registry
    data = request.json or {}
    p_id = data.get("id")
    for p in plugins_registry:
        if p["id"] == p_id:
            p["name"] = data.get("name", p["name"])
            p["enabled"] = bool(data.get("enabled", True))
            p["code"] = data.get("code", p["code"])
            plugin_states[p_id] = {}  # Reset state on code update
            save_plugins(plugins_registry)
            log_plugin_output(f"Saved & compiled '{p['name']}'.")
            return jsonify({"success": True})
    return jsonify({"success": False}), 404


@app.route("/api/plugins/delete", methods=["POST"])
def api_plugins_delete():
    global plugins_registry
    p_id = (request.json or {}).get("id")
    plugins_registry = [p for p in plugins_registry if p["id"] != p_id]
    plugin_states.pop(p_id, None)
    save_plugins(plugins_registry)
    return jsonify({"success": True})


@app.route("/api/plugin/logs")
def api_plugin_logs():
    return jsonify({"logs": plugin_console_logs})


@app.route("/api/stream_desktop")
def api_stream_desktop():
    def generate():
        try:
            loopback = find_default_loopback()
            with loopback.recorder(samplerate=CAPTURE_RATE, channels=2) as recorder:
                while True:
                    audio = recorder.record(numframes=BLOCK_SIZE)
                    if audio.size == 0:
                        continue
                    rms = float(np.sqrt(np.mean(audio**2)))
                    global_telemetry["desktop_stream_db"] = max(
                        -100.0, float(20 * np.log10(rms)) if rms > 0 else -100.0
                    )
                    yield audio.astype(np.float32).tobytes()
        except Exception:
            pass

    return Response(generate(), mimetype="application/octet-stream")


@app.route("/api/start_mirror", methods=["POST"])
def api_start_mirror():
    global active_mirror_thread, active_stop_event, active_errors
    if active_mirror_thread and active_mirror_thread.is_alive():
        return jsonify({"success": False, "error": "Hardware mirror is already running."})

    data = request.json or {}
    try:
        devices = compatible_speakers()
        selected = [d for d in devices if d["index"] in data.get("devices", [])]
        if not selected:
            return jsonify({"success": False, "error": "No valid devices selected."})

        active_stop_event = threading.Event()
        active_errors = []

        def mirror_task():
            try:
                speakers = [
                    Speaker(
                        device=dev,
                        channels=dev["channels"],
                        sample_rate=dev["sampleRate"],
                    )
                    for dev in selected
                ]
                loopback = find_default_loopback()
                started = []
                for s in speakers:
                    ready = threading.Event()
                    threading.Thread(
                        target=output_worker,
                        args=(s, active_stop_event, ready, active_errors),
                        daemon=True,
                    ).start()
                    if ready.wait(timeout=5):
                        started.append(s)
                if not started:
                    return
                with loopback.recorder(samplerate=CAPTURE_RATE, channels=2) as rec:
                    while not active_stop_event.is_set():
                        audio = rec.record(numframes=BLOCK_SIZE)
                        if audio.size == 0:
                            continue
                        for s in started:
                            s.push(prepare_audio(audio, s))
                        if active_errors:
                            break
            finally:
                active_stop_event.set()

        active_mirror_thread = threading.Thread(target=mirror_task, daemon=True)
        active_mirror_thread.start()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stop_mirror", methods=["POST"])
def api_stop_mirror():
    global active_stop_event, active_mirror_thread
    if active_stop_event:
        active_stop_event.set()
    if active_mirror_thread:
        active_mirror_thread.join(timeout=2)
    global_telemetry["mirror_stream_db"] = -100.0
    return jsonify({"success": True})


@app.route("/api/start_mic", methods=["POST"])
def api_start_mic():
    global mic_thread, mic_stop_event, mic_input_queue
    data = request.json or {}
    try:
        devices = compatible_speakers()
        selected = [d for d in devices if d["index"] in data.get("devices", [])]
        if not selected:
            return jsonify({"success": False, "error": "No valid devices selected."})

        mic_stop_event = threading.Event()
        mic_input_queue = queue.Queue(maxsize=QUEUE_BLOCKS)

        def mic_worker():
            try:
                speakers = [
                    Speaker(
                        device=dev,
                        channels=dev["channels"],
                        sample_rate=dev["sampleRate"],
                    )
                    for dev in selected
                ]
                errors: list[tuple[str, Exception]] = []
                for s in speakers:
                    ready = threading.Event()
                    threading.Thread(
                        target=output_worker,
                        args=(s, mic_stop_event, ready, errors),
                        daemon=True,
                    ).start()
                    ready.wait(timeout=5)
                while not mic_stop_event.is_set():
                    try:
                        chunk = mic_input_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    for s in speakers:
                        s.push(prepare_audio(chunk[:, np.newaxis], s))
            finally:
                mic_stop_event.set()

        mic_thread = threading.Thread(target=mic_worker, daemon=True)
        mic_thread.start()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/push_mic", methods=["POST"])
def api_push_mic():
    data = request.json or {}
    audio_data = data.get("audio", [])
    if audio_data and mic_input_queue:
        arr = np.array(audio_data, dtype=np.float32)
        rms = float(np.sqrt(np.mean(arr**2)))
        global_telemetry["mic_stream_db"] = max(
            -100.0, float(20 * np.log10(rms)) if rms > 0 else -100.0
        )
        try:
            mic_input_queue.put_nowait(arr)
        except queue.Full:
            pass
    return jsonify({"success": True})


@app.route("/api/stop_mic", methods=["POST"])
def api_stop_mic():
    global mic_stop_event, mic_thread
    if mic_stop_event:
        mic_stop_event.set()
    if mic_thread:
        mic_thread.join(timeout=2)
    global_telemetry["mic_stream_db"] = -100.0
    return jsonify({"success": True})


if __name__ == "__main__":
    print("Starting Universal Audio Gateway Hub on https://0.0.0.0:5000 ...")
    app.run(host="0.0.0.0", port=5000, ssl_context="adhoc", debug=False)

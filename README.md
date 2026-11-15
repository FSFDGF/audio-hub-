# audio-hub

This code makes it self pls check the wiki thank you 


Welcome to the audio-hub- wiki!

Here is the complete Audio Hub Wiki & Usage Guide for your GitHub repository! You can save this directly as your README.md and create a wiki/ folder with these pages.

📚 Universal Audio Gateway Hub - Wiki & Guide
Welcome to the official documentation for the Universal Audio Gateway Hub. This tool turns your PC into a central audio server capable of:

Live Browser/Phone Streaming: Stream PC audio directly to any browser or phone over HTTPS.

Hardware Speaker Mirroring: Mirror PC desktop audio to multiple physical output devices simultaneously.

Microphone Broadcasting: Broadcast your phone or browser microphone live into your PC speakers.

24/7 Shazam Music Recognition: Automatically identifies playing songs and reads them aloud.

Multi-Plugin IDE & Marketplace: Write, save, and run custom Python DSP plugins in real-time.

🚀 1. Installation & Setup Guide
Step 1: Prerequisites
Make sure you have Python installed (preferably your Pinokio Python environment or standard Python 3.10+).

Step 2: Install Dependencies
Open your terminal inside your project folder and run:

Bash
pip install flask numpy sounddevice soundcard shazamio pyttsx3
Step 3: Run the Server
Launch your single-file application:

Bash
python app.py
The server will automatically generate its HTML templates and start running securely on HTTPS ([https://127.0.0.1:5000](https://127.0.0.1:5000) and your local network IP).

🎛️ 2. User Guide: How to Use Each Feature
🏠 Tab 1: The Audio Hub (Main Dashboard)
Desktop Stream: Click "Start Listening" to stream your PC's audio straight to your phone or browser. Use the Volume slider to adjust playback and watch the live frequency visualizer.

Hardware Speaker Mirroring: Select one or more physical speakers from the checklist under section 2 and click "Start Mirror". Your PC desktop audio will duplicate and play across all selected speakers simultaneously.

Microphone Broadcasting: Select target speakers under section 3, click "Start Mic", and anything you speak into your phone or laptop microphone will instantly broadcast through your PC speakers.

24/7 Shazam Recognition: The background worker listens to your audio stream every few seconds, identifies any playing song, logs it to the history box, and announces it via Text-to-Speech. You can toggle this on/off anytime.

🧩 Tab 2: Plugins Marketplace (Multi-Plugin IDE)
Click "➕ Create New Plugin" to spin up a new sandboxed Python script.

Give it a custom name, write your DSP logic in the code editor, check "Active", and click "Save & Compile".

Your plugins persist automatically to disk (plugins.json) and run sequentially on every audio block!

📚 Tab 3: Documentation
Quick syntax reference for writing plugins and accessing the REST API.

🧩 3. Plugin Development Tutorial
Each plugin executes in real-time against incoming audio blocks (16,000 Hz mono float32 numpy arrays).

Available Sandbox Variables & Functions:
audio_snippet: A 1D NumPy array of audio samples ranging from -1.0 to 1.0.

sample_rate: Integer value (16000).

np: The standard NumPy library.

state: A persistent dictionary unique to your plugin (use this to save counters, timestamps, or buffers between runs).

speak_status(text): Triggers the host PC's text-to-speech voice engine to read text aloud.

print(message): Automatically captures your logs and streams them to the live web console in the Plugins Marketplace.

Example Plugin: Loud Volume Warning Alert
Paste this code into a new custom plugin to have your PC speak an alert whenever audio exceeds -15 dB:
Python
import time
# Initialize persistent state variables safely
state.setdefault("last_alert", 0.0)


# Calculate decibels
rms = np.sqrt(np.mean(audio_snippet**2))
db = float(20 * np.log10(rms)) if rms > 0 else -100.0


# Trigger alert if volume spikes and 15 seconds have passed
if db > -15.0 and time.time() - state["last_alert"] > 15.0:
msg = f"Warning! High volume detected at {db:.1f} decibels"
print(f"🚨 {msg}")
speak_status(msg)
state["last_alert"] = time.time()
else:
print(f"Monitoring volume... Current: {db:.1f} dB")

🔌 4. REST API Reference
Endpoint	Method	Description
/api/info	GET	Returns current identified track, history log, weather, and live dB telemetry.
/api/devices	GET	Returns a list of all compatible Windows WASAPI physical audio outputs.
/api/plugins	GET	Returns the JSON list of all registered plugins.
/api/plugins/add	POST	Creates a new blank plugin script.
/api/plugins/save	POST	Updates name, active status, and code for a specific plugin ID.
/api/plugins/delete	POST	Deletes a plugin from the registry and disk.
/api/plugin/logs	GET	Returns the live console output stream.

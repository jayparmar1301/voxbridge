"""
Voxxwire — Offline Real-Time Speech Translator (GUI)

Premium desktop interface using pywebview for a modern HTML/CSS/JS frontend
with the full Python ML backend.

Usage:
    python gui_app.py
"""

import sys
import os
import threading
import logging
import time
import asyncio
import queue as thread_queue
import traceback

# ---------------------------------------------------------------------------
# PATH SETUP — works for both normal Python and PyInstaller frozen exe
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = sys._MEIPASS
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    _APP_DIR = _BUNDLE_DIR

if _BUNDLE_DIR not in sys.path:
    sys.path.insert(0, _BUNDLE_DIR)

os.chdir(_APP_DIR)

# ---------------------------------------------------------------------------
# LIGHT IMPORTS (no ML deps at top level)
# ---------------------------------------------------------------------------
import config

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception:
    _SD_AVAILABLE = False

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)-20s] %(levelname)-7s %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler('translator.log', mode='w', encoding='utf-8'),
    ]
)
logger = logging.getLogger('Voxxwire.gui')

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
LANGUAGES = {
    "Arabic": "ar", "Azerbaijani": "az", "Bengali": "bn", "Bulgarian": "bg",
    "Catalan": "ca", "Chinese (Simplified)": "zh", "Chinese (Traditional)": "zt",
    "Czech": "cs", "Danish": "da", "Dutch": "nl", "English": "en",
    "Esperanto": "eo", "Estonian": "et", "Basque": "eu", "Finnish": "fi",
    "French": "fr", "Galician": "gl", "German": "de", "Greek": "el",
    "Hebrew": "he", "Hindi": "hi", "Hungarian": "hu", "Indonesian": "id",
    "Irish": "ga", "Italian": "it", "Japanese": "ja", "Korean": "ko",
    "Kyrgyz": "ky", "Lithuanian": "lt", "Latvian": "lv", "Malay": "ms",
    "Norwegian (Bokmål)": "nb", "Persian": "fa", "Polish": "pl",
    "Portuguese": "pt", "Portuguese (Brazil)": "pb", "Romanian": "ro",
    "Russian": "ru", "Slovak": "sk", "Slovenian": "sl", "Albanian": "sq",
    "Spanish": "es", "Swedish": "sv", "Tagalog": "tl", "Thai": "th",
    "Turkish": "tr", "Ukrainian": "uk", "Urdu": "ur", "Vietnamese": "vi",
}
LANG_CODES = {v: k for k, v in LANGUAGES.items()}
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

# ---------------------------------------------------------------------------
# HELPER: AUDIO DEVICES
# ---------------------------------------------------------------------------
def get_audio_devices():
    if not _SD_AVAILABLE:
        return [], []
    try:
        devices = sd.query_devices()
        inputs, outputs = [], []
        for idx, d in enumerate(devices):
            name = d["name"]
            if d["max_input_channels"] > 0:
                inputs.append({"index": idx, "name": f"[{idx}] {name}"})
            if d["max_output_channels"] > 0:
                outputs.append({"index": idx, "name": f"[{idx}] {name}"})
        return inputs, outputs
    except Exception:
        return [], []


# ---------------------------------------------------------------------------
# HELPER: LANGUAGE PACK MANAGEMENT
# ---------------------------------------------------------------------------
def get_installed_pairs():
    try:
        import argostranslate.package
        installed = argostranslate.package.get_installed_packages()
        return {(p.from_code, p.to_code) for p in installed}
    except Exception:
        return set()


def _get_available_packages():
    import argostranslate.package
    argostranslate.package.update_package_index()
    return argostranslate.package.get_available_packages()


def resolve_needed_packages(from_code, to_code, available, installed):
    if from_code == to_code:
        return []
    has_direct = any(p.from_code == from_code and p.to_code == to_code for p in available)
    if has_direct:
        if (from_code, to_code) not in installed:
            return [(from_code, to_code)]
        return []
    needed = []
    if from_code != "en" and (from_code, "en") not in installed:
        if any(p.from_code == from_code and p.to_code == "en" for p in available):
            needed.append((from_code, "en"))
    if to_code != "en" and ("en", to_code) not in installed:
        if any(p.from_code == "en" and p.to_code == to_code for p in available):
            needed.append(("en", to_code))
    return needed


def download_single_package(from_code, to_code, available, msg_queue):
    pair_label = f"{LANG_CODES.get(from_code, from_code)} → {LANG_CODES.get(to_code, to_code)} ({from_code}→{to_code})"
    msg_queue.put({"type": "log", "text": f"  📥  Downloading {pair_label}…\n"})
    try:
        import argostranslate.package
        matching = [p for p in available if p.from_code == from_code and p.to_code == to_code]
        if not matching:
            msg_queue.put({"type": "log", "text": f"  ⚠  No package for {pair_label}\n"})
            return False
        path = matching[0].download()
        argostranslate.package.install_from_path(path)
        msg_queue.put({"type": "log", "text": f"  ✅  Installed {pair_label}\n"})
        return True
    except Exception as e:
        msg_queue.put({"type": "log", "text": f"  ❌  Failed: {pair_label}: {e}\n"})
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  SUBTITLE BRIDGE  →  sends translations to the JS frontend
# ═══════════════════════════════════════════════════════════════════════════
class GUISubtitleDisplay:
    """Drop-in for subtitles.SubtitleDisplay — pushes to the message queue."""
    def __init__(self, msg_queue):
        self._q = msg_queue

    def show(self, channel, original, translated, source_lang, target_lang):
        self._q.put({
            "type": "subtitle",
            "channel": channel,
            "original": original,
            "translated": translated,
            "src_lang": f"{LANG_CODES.get(source_lang, source_lang)}",
            "tgt_lang": f"{LANG_CODES.get(target_lang, target_lang)}",
        })

    def stop(self):
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  PYWEBVIEW API  (exposed to JavaScript)
# ═══════════════════════════════════════════════════════════════════════════
class Api:
    def __init__(self):
        self._msg_queue = thread_queue.Queue()
        self._stop_event = threading.Event()
        self._engine_thread = None
        self._running = False

    # ── Device / Language data ────────────────────────────────────────────
    def get_devices(self):
        inputs, outputs = get_audio_devices()
        return {"inputs": inputs, "outputs": outputs}

    def get_languages(self):
        return [{"name": name, "code": code} for name, code in sorted(LANGUAGES.items())]

    def get_settings(self):
        return {
            "mic_device": config.MIC_DEVICE_INDEX,
            "loopback_device": config.LOOPBACK_DEVICE_INDEX,
            "mic_src_lang": config.MIC_SOURCE_LANG,
            "mic_tgt_lang": config.MIC_TARGET_LANG,
            "lb_src_lang": config.LOOPBACK_SOURCE_LANG,
            "lb_tgt_lang": config.LOOPBACK_TARGET_LANG,
            "whisper_model": config.WHISPER_MODEL_SIZE,
            "subtitles": config.ENABLE_SUBTITLES,
            "mic_channel": config.ENABLE_MIC_CHANNEL,
            "loopback_channel": config.ENABLE_LOOPBACK_CHANNEL,
        }

    # ── Engine control ───────────────────────────────────────────────────
    def start_engine(self, settings):
        """Called from JS when user clicks Start."""
        # Apply settings to config
        config.MIC_DEVICE_INDEX = settings.get('mic_device')
        config.LOOPBACK_DEVICE_INDEX = settings.get('loopback_device')
        config.MIC_SOURCE_LANG = settings.get('mic_src_lang', 'en')
        config.MIC_TARGET_LANG = settings.get('mic_tgt_lang', 'ja')
        config.LOOPBACK_SOURCE_LANG = settings.get('lb_src_lang', 'ja')
        config.LOOPBACK_TARGET_LANG = settings.get('lb_tgt_lang', 'en')
        config.WHISPER_MODEL_SIZE = settings.get('whisper_model', 'small')
        config.ENABLE_SUBTITLES = settings.get('subtitles', True)
        config.ENABLE_MIC_CHANNEL = settings.get('mic_channel', True)
        config.ENABLE_LOOPBACK_CHANNEL = settings.get('loopback_channel', True)
        config.ENABLE_TTS_OUTPUT = False

        self._stop_event.clear()
        self._running = True
        self._engine_thread = threading.Thread(target=self._engine_worker, daemon=True)
        self._engine_thread.start()
        return True

    def stop_engine(self):
        """Called from JS when user clicks Stop."""
        self._stop_event.set()
        self._running = False
        return True

    def poll_messages(self):
        """Called from JS every 200ms to get new messages."""
        messages = []
        while not self._msg_queue.empty():
            try:
                messages.append(self._msg_queue.get_nowait())
            except Exception:
                break
        return messages

    # ── Engine worker (background thread) ────────────────────────────────
    def _engine_worker(self):
        q = self._msg_queue
        try:
            q.put({"type": "log", "text": "Loading modules…\n"})

            from whisper_asr import WhisperASR
            from vad_engine import SileroVAD
            from mic_capture import MicCapture
            from loopback_capture import LoopbackCapture
            from channel import ChannelPipeline

            # [1/4] ASR
            q.put({"type": "log", "text": "[1/4] Loading ASR model (faster-whisper)…\n"})
            q.put({"type": "progress", "value": 0.15})
            q.put({"type": "status", "state": "starting", "text": "Loading ASR…"})
            asr = WhisperASR()
            asr.load()
            if self._stop_event.is_set(): return

            # [2/4] VAD
            q.put({"type": "log", "text": "[2/4] Loading VAD model (Silero)…\n"})
            q.put({"type": "progress", "value": 0.35})
            q.put({"type": "status", "state": "starting", "text": "Loading VAD…"})
            test_vad = SileroVAD()
            test_vad.load()
            del test_vad
            if self._stop_event.is_set(): return

            # [3/4] Translation packs
            q.put({"type": "log", "text": "[3/4] Checking translation models…\n"})
            q.put({"type": "progress", "value": 0.50})

            user_pairs = set()
            if config.ENABLE_MIC_CHANNEL:
                user_pairs.add((config.MIC_SOURCE_LANG, config.MIC_TARGET_LANG))
            if config.ENABLE_LOOPBACK_CHANNEL:
                user_pairs.add((config.LOOPBACK_SOURCE_LANG, config.LOOPBACK_TARGET_LANG))
            user_pairs = {(s, t) for s, t in user_pairs if s != t}

            q.put({"type": "log", "text": "  Checking available packages…\n"})
            available = _get_available_packages()
            installed = get_installed_pairs()

            to_download = []
            for src, tgt in user_pairs:
                to_download.extend(resolve_needed_packages(src, tgt, available, installed))
            to_download = list(dict.fromkeys(to_download))

            if to_download:
                labels = [f"{fc}→{tc}" for fc, tc in to_download]
                q.put({"type": "log", "text": f"  {len(to_download)} package(s): {', '.join(labels)}\n"})
                q.put({"type": "status", "state": "downloading", "text": "Downloading…"})
                for i, (fc, tc) in enumerate(to_download):
                    if self._stop_event.is_set(): return
                    ok = download_single_package(fc, tc, available, q)
                    if not ok:
                        q.put({"type": "log", "text": "❌ Could not install required language packs.\n"})
                        q.put({"type": "stopped"})
                        return
                    q.put({"type": "progress", "value": 0.50 + 0.15 * ((i + 1) / len(to_download))})
                q.put({"type": "log", "text": "  All language packs ready!\n"})
            else:
                q.put({"type": "log", "text": "  All packs already installed ✓\n"})

            if self._stop_event.is_set(): return

            # [4/4] Audio devices
            q.put({"type": "log", "text": "[4/4] Setting up audio devices…\n"})
            q.put({"type": "progress", "value": 0.75})
            q.put({"type": "status", "state": "starting", "text": "Setting up audio…"})

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            mic_queue = asyncio.Queue(maxsize=config.QUEUE_MAX_SIZE)
            loopback_queue = asyncio.Queue(maxsize=config.QUEUE_MAX_SIZE)

            mic_capture = None
            loopback_capture = None

            if config.ENABLE_MIC_CHANNEL:
                mic_capture = MicCapture(mic_queue, loop)
            if config.ENABLE_LOOPBACK_CHANNEL:
                loopback_capture = LoopbackCapture(loopback_queue, loop)

            gui_subs = GUISubtitleDisplay(q)
            pipelines = []

            if config.ENABLE_MIC_CHANNEL:
                pipelines.append(ChannelPipeline(
                    name="mic", audio_queue=mic_queue,
                    source_lang=config.MIC_SOURCE_LANG,
                    target_lang=config.MIC_TARGET_LANG,
                    vad=SileroVAD(), asr=asr, tts=None,
                    subtitles=gui_subs, audio_player=None,
                ))

            if config.ENABLE_LOOPBACK_CHANNEL:
                pipelines.append(ChannelPipeline(
                    name="loopback", audio_queue=loopback_queue,
                    source_lang=config.LOOPBACK_SOURCE_LANG,
                    target_lang=config.LOOPBACK_TARGET_LANG,
                    vad=SileroVAD(), asr=asr, tts=None,
                    subtitles=gui_subs, audio_player=None,
                ))

            q.put({"type": "progress", "value": 0.90})

            # Start captures
            if mic_capture:
                try:
                    mic_capture.start()
                except Exception as e:
                    q.put({"type": "log", "text": f"⚠ Mic capture failed: {e}\n"})

            if loopback_capture:
                try:
                    loopback_capture.start()
                except Exception as e:
                    q.put({"type": "log", "text": f"⚠ Loopback capture failed: {e}\n"})

            # Start pipeline tasks
            tasks = [loop.create_task(p.run()) for p in pipelines]

            q.put({"type": "progress", "value": 1.0})
            q.put({"type": "status", "state": "running", "text": "Translating…"})
            q.put({"type": "log", "text": "✅ Engine running! Speak to translate.\n"})

            # Run until stop
            while not self._stop_event.is_set():
                loop.run_until_complete(asyncio.sleep(0.5))

            # Cleanup
            for p in pipelines:
                p.stop()
            for t in tasks:
                t.cancel()

            if mic_capture:
                mic_capture.stop()
            if loopback_capture:
                loopback_capture.stop()
            gui_subs.stop()
            loop.close()

            q.put({"type": "log", "text": "Engine stopped.\n"})
            q.put({"type": "stopped"})

        except Exception as e:
            logger.error(f"Engine error: {e}", exc_info=True)
            q.put({"type": "log", "text": f"❌ Engine error: {e}\n"})
            q.put({"type": "stopped"})
        finally:
            self._running = False


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        import webview

        api = Api()

        # Determine UI path
        ui_dir = os.path.join(_BUNDLE_DIR, 'ui')
        if not os.path.isdir(ui_dir):
            ui_dir = os.path.join(_APP_DIR, 'ui')

        index_path = os.path.join(ui_dir, 'index.html')

        window = webview.create_window(
            'Voxxwire — Offline Translator',
            url=index_path,
            js_api=api,
            width=1100,
            height=750,
            min_size=(800, 550),
            background_color='#0a0a14',
            frameless=False,
            easy_drag=False,
        )

        webview.start(debug=False)

    except Exception as e:
        error_msg = f"Voxxwire failed to start:\n\n{traceback.format_exc()}"
        try:
            crash_path = os.path.join(_APP_DIR, "Voxxwire_crash.log")
            with open(crash_path, "w", encoding="utf-8") as f:
                f.write(error_msg)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox as mb
            root = tk.Tk()
            root.withdraw()
            mb.showerror("Voxxwire — Startup Error", error_msg)
            root.destroy()
        except Exception:
            print(error_msg)
            input("Press Enter to exit...")

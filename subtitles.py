"""
Terminal-based subtitle display with speaker labels and colored output.
"""

import os
import sys
import time
import threading
from collections import deque

import config

# Force UTF-8 output on Windows so Japanese/Hindi characters display correctly
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")  # Set console to UTF-8
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

COLORS = {
    "mic": "\033[96m",      # Cyan — your speech
    "loopback": "\033[93m", # Yellow — remote speech
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "green": "\033[92m",
    "red": "\033[91m",
}


class SubtitleDisplay:
    def __init__(self):
        self._lines: deque[str] = deque(maxlen=config.SUBTITLE_MAX_LINES)
        self._lock = threading.Lock()
        self._started = False

    def start(self):
        self._started = True
        os.system("cls" if os.name == "nt" else "clear")
        print(f"{COLORS['bold']}{'=' * 70}")
        print(f"  REAL-TIME SPEECH TRANSLATOR (Offline)")
        print(f"  Mic: {config.LANG_NAMES.get(config.MIC_SOURCE_LANG, config.MIC_SOURCE_LANG)} "
              f"-> {config.LANG_NAMES.get(config.MIC_TARGET_LANG, config.MIC_TARGET_LANG)}")
        print(f"  System Audio: {config.LANG_NAMES.get(config.LOOPBACK_SOURCE_LANG, config.LOOPBACK_SOURCE_LANG)} "
              f"-> {config.LANG_NAMES.get(config.LOOPBACK_TARGET_LANG, config.LOOPBACK_TARGET_LANG)}")
        print(f"{'=' * 70}{COLORS['reset']}")
        print(f"{COLORS['dim']}  Press Ctrl+C to stop{COLORS['reset']}\n")

    def show(self, channel: str, original: str, translated: str, source_lang: str, target_lang: str):
        if not config.ENABLE_SUBTITLES or not self._started:
            return

        color = COLORS.get(channel, COLORS["reset"])
        timestamp = time.strftime("%H:%M:%S")

        label = "YOU" if channel == "mic" else "REMOTE"

        src_name = config.LANG_NAMES.get(source_lang, source_lang).upper()[:3]
        tgt_name = config.LANG_NAMES.get(target_lang, target_lang).upper()[:3]

        line1 = f"{COLORS['dim']}[{timestamp}]{COLORS['reset']} {color}{COLORS['bold']}[{label}]{COLORS['reset']} {COLORS['dim']}[{src_name}]{COLORS['reset']} {original}"
        line2 = f"         {color}[{tgt_name}]{COLORS['reset']} {COLORS['bold']}{translated}{COLORS['reset']}"

        with self._lock:
            self._lines.append(line1)
            self._lines.append(line2)
            self._lines.append("")

            sys.stdout.write(line1 + "\n")
            sys.stdout.write(line2 + "\n")
            sys.stdout.write("\n")
            sys.stdout.flush()

    def show_status(self, message: str):
        if not self._started:
            return
        sys.stdout.write(f"\r{COLORS['dim']}  {message}{COLORS['reset']}  ")
        sys.stdout.flush()

    def stop(self):
        if self._started:
            print(f"\n{COLORS['bold']}{COLORS['red']}Translator stopped.{COLORS['reset']}")
            self._started = False
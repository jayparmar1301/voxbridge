"""
Audio player for TTS output with feedback loop prevention.

Plays translated speech through speakers while gating the
loopback capture to prevent infinite re-translation.
"""

import numpy as np
import sounddevice as sd
import threading
import queue
import logging
import time

import config

logger = logging.getLogger(__name__)


class AudioPlayer:
    def __init__(self, loopback_capture=None):
        self._loopback = loopback_capture
        self._play_queue: queue.Queue = queue.Queue(maxsize=20)
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._player_loop,
            daemon=True,
            name="audio-player",
        )
        self._thread.start()
        logger.info("Audio player started")

    def _player_loop(self):
        while self._running:
            try:
                audio = self._play_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if audio is None:
                continue

            duration = len(audio) / config.SAMPLE_RATE

            if self._loopback is not None:
                self._loopback.set_gate(duration)
                time.sleep(0.05)

            try:
                sd.play(audio, samplerate=config.SAMPLE_RATE, blocking=True)
                logger.debug(f"Played {duration:.2f}s of TTS audio")
            except Exception as e:
                logger.error(f"Audio playback error: {e}")

    def play(self, audio: np.ndarray):
        if not config.ENABLE_TTS_OUTPUT:
            return

        if audio is None or len(audio) == 0:
            return

        try:
            self._play_queue.put_nowait(audio)
        except queue.Full:
            logger.warning("Audio play queue full — dropping TTS audio")

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            sd.stop()
        except Exception:
            pass
        logger.info("Audio player stopped")

"""
Offline Text-to-Speech using Piper.

Converts translated text to spoken audio.
Voice models must be pre-downloaded using setup_tts_voices.py.
"""

import os
import io
import wave
import numpy as np
import logging

import config

logger = logging.getLogger(__name__)


class PiperTTS:
    def __init__(self):
        self._voices: dict[str, object] = {}
        self._piper_available = False
        self._voices_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            config.PIPER_VOICES_DIR,
        )

    def load(self):
        logger.info("Loading Piper TTS voices...")

        try:
            from piper import PiperVoice
            self._piper_available = True
        except ImportError:
            logger.warning(
                "piper-tts not installed. TTS will be disabled. "
                "Install with: pip install piper-tts"
            )
            self._piper_available = False
            return

        needed_langs = set()
        if config.ENABLE_MIC_CHANNEL:
            needed_langs.add(config.MIC_TARGET_LANG)
        if config.ENABLE_LOOPBACK_CHANNEL:
            needed_langs.add(config.LOOPBACK_TARGET_LANG)

        for lang in needed_langs:
            voice_name = config.PIPER_VOICE_MODELS.get(lang)
            if voice_name is None:
                logger.warning(f"No Piper voice configured for language: {lang}")
                continue

            model_path = os.path.join(self._voices_dir, f"{voice_name}.onnx")
            config_path = os.path.join(self._voices_dir, f"{voice_name}.onnx.json")

            if not os.path.exists(model_path):
                logger.warning(
                    f"Piper voice model not found: {model_path}. "
                    f"Run setup_tts_voices.py to download it."
                )
                continue

            try:
                voice = PiperVoice.load(model_path, config_path=config_path)
                self._voices[lang] = voice
                logger.info(f"  Loaded TTS voice for [{lang}]: {voice_name}")
            except Exception as e:
                logger.warning(f"  Failed to load TTS voice for [{lang}]: {e}")

    def synthesize(self, text: str, language: str) -> np.ndarray | None:
        if not text or not text.strip():
            return None

        if not self._piper_available:
            return None

        voice = self._voices.get(language)
        if voice is None:
            logger.debug(f"No TTS voice loaded for language: {language}")
            return None

        try:
            audio_buffer = io.BytesIO()

            with wave.open(audio_buffer, "wb") as wav_file:
                voice.synthesize(text, wav_file)

            audio_buffer.seek(0)
            with wave.open(audio_buffer, "rb") as wav_file:
                n_frames = wav_file.getnframes()
                sample_width = wav_file.getsampwidth()
                framerate = wav_file.getframerate()
                raw_data = wav_file.readframes(n_frames)

            if sample_width == 2:
                audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                audio = np.frombuffer(raw_data, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

            if framerate != config.SAMPLE_RATE:
                ratio = config.SAMPLE_RATE / framerate
                new_len = int(len(audio) * ratio)
                indices = np.linspace(0, len(audio) - 1, new_len)
                audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

            duration = len(audio) / config.SAMPLE_RATE
            logger.debug(f"TTS [{language}]: synthesized {duration:.2f}s audio")

            return audio

        except Exception as e:
            logger.error(f"TTS synthesis error [{language}]: {e}")
            return None

    @property
    def available_languages(self) -> list[str]:
        return list(self._voices.keys())

"""
Offline ASR using faster-whisper (CTranslate2-optimized Whisper).

Transcribes audio segments detected by VAD into text.
Supports English, Japanese, and Hindi.
"""

import numpy as np
import logging
from faster_whisper import WhisperModel

import config

logger = logging.getLogger(__name__)

LANG_MAP = {
    "en": "en",
    "ja": "ja",
    "hi": "hi",
}


class WhisperASR:
    """Offline speech-to-text using faster-whisper."""

    def __init__(self):
        self.model: WhisperModel | None = None

    def load(self):
        model_size = config.WHISPER_MODEL_SIZE

        device = config.WHISPER_DEVICE
        compute_type = config.WHISPER_COMPUTE_TYPE

        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        logger.info(
            f"Loading Whisper model: size={model_size}, "
            f"device={device}, compute_type={compute_type}"
        )

        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            if device == "cuda":
                logger.info("Retrying with CPU...")
                self.model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type="int8",
                )
                logger.info("Whisper model loaded on CPU")

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        if self.model is None:
            raise RuntimeError("Whisper model not loaded. Call load() first.")

        whisper_lang = LANG_MAP.get(language, language)

        try:
            segments, info = self.model.transcribe(
                audio,
                language=whisper_lang,
                beam_size=5,
                best_of=3,
                vad_filter=False,
                without_timestamps=True,
                condition_on_previous_text=False,
            )

            texts = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    texts.append(text)

            full_text = " ".join(texts)

            if full_text:
                logger.debug(
                    f"ASR [{whisper_lang}]: \"{full_text}\" "
                    f"(prob={info.language_probability:.2f})"
                )

            return full_text

        except Exception as e:
            logger.error(f"ASR transcription error: {e}")
            return ""

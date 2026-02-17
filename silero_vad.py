"""
Silero Voice Activity Detection (VAD).

Processes audio chunks and determines whether speech is present.
Accumulates speech segments and signals when a complete utterance
is ready for ASR processing.
"""

import numpy as np
import torch
import logging
import time

import config

logger = logging.getLogger(__name__)


class SileroVAD:
    """
    Streaming VAD using Silero.

    Buffers audio during speech and emits complete utterances when
    silence is detected after speech.
    """

    def __init__(self):
        self.model = None
        self._speech_buffer: list[np.ndarray] = []
        self._is_speaking = False
        self._silence_start: float | None = None
        self._speech_start: float | None = None

        self._silero_chunk_size = 512  # samples at 16kHz
        self._leftover = np.array([], dtype=np.float32)

    def load(self):
        """Load the Silero VAD model."""
        logger.info("Loading Silero VAD model...")
        try:
            self.model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
                trust_repo=True,
            )
            self.model.eval()
            logger.info("Silero VAD loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Silero VAD: {e}")
            logger.info("Falling back to simple energy-based VAD")
            self.model = None

    def reset(self):
        """Reset VAD state for a new utterance."""
        self._speech_buffer.clear()
        self._is_speaking = False
        self._silence_start = None
        self._speech_start = None
        self._leftover = np.array([], dtype=np.float32)
        if self.model is not None:
            self.model.reset_states()

    def _get_speech_prob(self, chunk: np.ndarray) -> float:
        if self.model is not None:
            tensor = torch.from_numpy(chunk).float()
            with torch.no_grad():
                prob = self.model(tensor, config.SAMPLE_RATE).item()
            return prob
        else:
            energy = np.sqrt(np.mean(chunk ** 2))
            return min(energy * 20.0, 1.0)

    def process_chunk(self, audio_chunk: np.ndarray) -> np.ndarray | None:
        """
        Process an audio chunk through VAD.

        Returns:
            Complete utterance as float32 array when speech ends,
            or None if still collecting.
        """
        if len(self._leftover) > 0:
            audio_chunk = np.concatenate([self._leftover, audio_chunk])
            self._leftover = np.array([], dtype=np.float32)

        now = time.monotonic()
        result = None

        pos = 0
        while pos + self._silero_chunk_size <= len(audio_chunk):
            chunk = audio_chunk[pos:pos + self._silero_chunk_size]
            prob = self._get_speech_prob(chunk)
            pos += self._silero_chunk_size

            if prob >= config.VAD_THRESHOLD:
                self._silence_start = None

                if not self._is_speaking:
                    self._is_speaking = True
                    self._speech_start = now
                    logger.debug("VAD: Speech started")

                self._speech_buffer.append(chunk)

            else:
                if self._is_speaking:
                    self._speech_buffer.append(chunk)

                    if self._silence_start is None:
                        self._silence_start = now
                    elif (now - self._silence_start) * 1000 >= config.VAD_MIN_SILENCE_MS:
                        if len(self._speech_buffer) > 0:
                            utterance = np.concatenate(self._speech_buffer)
                            duration = len(utterance) / config.SAMPLE_RATE

                            if duration >= config.MIN_SPEECH_DURATION_S:
                                logger.debug(
                                    f"VAD: Speech ended, duration={duration:.2f}s"
                                )
                                result = utterance
                            else:
                                logger.debug(
                                    f"VAD: Speech too short ({duration:.2f}s), discarding"
                                )

                        self.reset()

            # Safety: force emit if buffer too long
            if self._is_speaking and self._speech_start is not None:
                elapsed = now - self._speech_start
                if elapsed >= config.MAX_SPEECH_DURATION_S:
                    if len(self._speech_buffer) > 0:
                        utterance = np.concatenate(self._speech_buffer)
                        logger.debug(f"VAD: Force emit after {elapsed:.1f}s")
                        result = utterance
                    self.reset()

        if pos < len(audio_chunk):
            self._leftover = audio_chunk[pos:]

        return result

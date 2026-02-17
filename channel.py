"""
Audio processing channel pipeline.

Each channel (mic, loopback) has its own pipeline:
  Audio Queue -> VAD -> ASR -> Translation -> Subtitles + TTS

Runs as an async task, consuming audio chunks from the capture queue.
"""

import asyncio
import numpy as np
import logging
import time
import concurrent.futures

from vad_engine import SileroVAD
from whisper_asr import WhisperASR
from argos_translate import translate_text
from piper_tts import PiperTTS
from subtitles import SubtitleDisplay
from audio_player import AudioPlayer

import config

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound work (ASR, Translation, TTS)
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="pipeline"
)


class ChannelPipeline:
    """
    Processing pipeline for one audio channel.

    Consumes audio chunks from a queue, runs VAD, ASR, translation,
    and outputs subtitles + TTS audio.
    """

    def __init__(
        self,
        name: str,
        audio_queue: asyncio.Queue,
        source_lang: str,
        target_lang: str,
        vad: SileroVAD,
        asr: WhisperASR,
        tts: PiperTTS,
        subtitles: SubtitleDisplay,
        audio_player: AudioPlayer,
    ):
        self.name = name
        self.audio_queue = audio_queue
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.vad = vad
        self.asr = asr
        self.tts = tts
        self.subtitles = subtitles
        self.audio_player = audio_player
        self._running = False

    async def run(self):
        """
        Main pipeline loop. Runs until stopped.

        Flow: audio chunks -> VAD -> ASR -> translate -> output
        """
        self._running = True
        logger.info(
            f"Pipeline [{self.name}] started: "
            f"{self.source_lang} -> {self.target_lang}"
        )

        # Each channel gets its own VAD instance (they track state independently)
        channel_vad = SileroVAD()
        channel_vad.load()

        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # Get audio chunk from capture (with timeout to allow shutdown)
                try:
                    audio_chunk = await asyncio.wait_for(
                        self.audio_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Run VAD (fast, runs inline)
                utterance = channel_vad.process_chunk(audio_chunk)

                if utterance is None:
                    continue

                # We have a complete utterance — process it
                logger.debug(
                    f"[{self.name}] Processing utterance: "
                    f"{len(utterance)/config.SAMPLE_RATE:.2f}s"
                )

                # Run ASR in thread pool (CPU-intensive)
                transcript = await loop.run_in_executor(
                    _executor,
                    self.asr.transcribe,
                    utterance,
                    self.source_lang,
                )

                if not transcript or not transcript.strip():
                    continue

                # Translate in thread pool
                translated = await loop.run_in_executor(
                    _executor,
                    translate_text,
                    transcript,
                    self.source_lang,
                    self.target_lang,
                )

                if not translated:
                    continue

                # Output: subtitles
                self.subtitles.show(
                    channel=self.name,
                    original=transcript,
                    translated=translated,
                    source_lang=self.source_lang,
                    target_lang=self.target_lang,
                )

                # Output: TTS (synthesize in thread pool, then queue for playback)
                if config.ENABLE_TTS_OUTPUT:
                    tts_audio = await loop.run_in_executor(
                        _executor,
                        self.tts.synthesize,
                        translated,
                        self.target_lang,
                    )
                    if tts_audio is not None:
                        self.audio_player.play(tts_audio)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Pipeline [{self.name}] error: {e}", exc_info=True)
                await asyncio.sleep(0.1)

        logger.info(f"Pipeline [{self.name}] stopped")

    def stop(self):
        """Signal the pipeline to stop."""
        self._running = False

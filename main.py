"""
Real-Time Offline Speech Translator — Main Entry Point

Usage:
  python main.py

Press Ctrl+C to stop.
"""

import asyncio
import signal
import sys
import os
import logging
import time

# =============================================================================
# PATH SETUP
# =============================================================================
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

# =============================================================================
# LOCAL IMPORTS (flat file structure — no sub-packages)
# =============================================================================
import config
from whisper_asr import WhisperASR
from vad_engine import SileroVAD
from argos_translate import verify_pairs, translate_text
from piper_tts import PiperTTS
from mic_capture import MicCapture
from loopback_capture import LoopbackCapture
from subtitles import SubtitleDisplay
from audio_player import AudioPlayer
from channel import ChannelPipeline

# =============================================================================
# LOGGING SETUP
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-20s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler("translator.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# Suppress noisy Argos internal logging that causes Unicode errors on Windows
logging.getLogger("argostranslate").setLevel(logging.WARNING)

stderr_handler = logging.StreamHandler(
    open(sys.stderr.fileno(), mode='w', encoding='utf-8', closefd=False)
)
stderr_handler.setLevel(logging.ERROR)
stderr_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logging.getLogger().addHandler(stderr_handler)


def print_banner():
    print("\n" + "=" * 70)
    print("  REAL-TIME OFFLINE SPEECH TRANSLATOR")
    print("=" * 70)
    print(f"  Mic channel:      {config.LANG_NAMES.get(config.MIC_SOURCE_LANG)} "
          f"-> {config.LANG_NAMES.get(config.MIC_TARGET_LANG)}")
    print(f"  Loopback channel: {config.LANG_NAMES.get(config.LOOPBACK_SOURCE_LANG)} "
          f"-> {config.LANG_NAMES.get(config.LOOPBACK_TARGET_LANG)}")
    print(f"  Whisper model:    {config.WHISPER_MODEL_SIZE}")
    print(f"  Subtitles:        {'ON' if config.ENABLE_SUBTITLES else 'OFF'}")
    print(f"  TTS output:       {'ON' if config.ENABLE_TTS_OUTPUT else 'OFF'}")
    print("=" * 70 + "\n")


async def main():
    print_banner()

    # =========================================================================
    # Step 1: Load models
    # =========================================================================
    print("[1/5] Loading ASR model (faster-whisper)...")
    asr = WhisperASR()
    asr.load()

    print("[2/5] Loading VAD model (Silero)...")
    test_vad = SileroVAD()
    test_vad.load()
    del test_vad

    print("[3/5] Verifying translation models (Argos)...")
    if not verify_pairs():
        print("\nERROR: Some translation pairs are missing!")
        print("Run: python setup_languages.py")
        sys.exit(1)

    print("[4/5] Loading TTS voices (Piper)...")
    tts = PiperTTS()
    tts.load()
    if not tts.available_languages:
        print("  WARNING: No TTS voices loaded. Subtitles will still work.")
        print("  Run: python setup_tts_voices.py")

    print("[5/5] Setting up audio devices...")

    loop = asyncio.get_event_loop()

    # =========================================================================
    # Step 2: Create audio queues and capture instances
    # =========================================================================
    mic_queue = asyncio.Queue(maxsize=config.QUEUE_MAX_SIZE)
    loopback_queue = asyncio.Queue(maxsize=config.QUEUE_MAX_SIZE)

    mic_capture = None
    loopback_capture = None

    if config.ENABLE_MIC_CHANNEL:
        mic_capture = MicCapture(mic_queue, loop)

    if config.ENABLE_LOOPBACK_CHANNEL:
        loopback_capture = LoopbackCapture(loopback_queue, loop)

    # =========================================================================
    # Step 3: Create output handlers
    # =========================================================================
    subtitles_display = SubtitleDisplay()
    audio_player = AudioPlayer(loopback_capture=loopback_capture)

    # =========================================================================
    # Step 4: Create processing pipelines
    # =========================================================================
    pipelines = []
    tasks = []

    if config.ENABLE_MIC_CHANNEL:
        mic_pipeline = ChannelPipeline(
            name="mic",
            audio_queue=mic_queue,
            source_lang=config.MIC_SOURCE_LANG,
            target_lang=config.MIC_TARGET_LANG,
            vad=SileroVAD(),
            asr=asr,
            tts=tts,
            subtitles=subtitles_display,
            audio_player=audio_player,
        )
        pipelines.append(mic_pipeline)

    if config.ENABLE_LOOPBACK_CHANNEL:
        loopback_pipeline = ChannelPipeline(
            name="loopback",
            audio_queue=loopback_queue,
            source_lang=config.LOOPBACK_SOURCE_LANG,
            target_lang=config.LOOPBACK_TARGET_LANG,
            vad=SileroVAD(),
            asr=asr,
            tts=tts,
            subtitles=subtitles_display,
            audio_player=audio_player,
        )
        pipelines.append(loopback_pipeline)

    # =========================================================================
    # Step 5: Start everything
    # =========================================================================
    print("\nStarting audio capture and processing pipelines...")

    audio_player.start()

    try:
        if mic_capture:
            mic_capture.start()
            print("  Microphone capture: STARTED")
    except Exception as e:
        print(f"  Microphone capture: FAILED ({e})")
        logger.error(f"Mic capture failed: {e}")
        if not config.ENABLE_LOOPBACK_CHANNEL:
            sys.exit(1)

    try:
        if loopback_capture:
            loopback_capture.start()
            print("  Loopback capture: STARTED")
    except Exception as e:
        print(f"  Loopback capture: FAILED ({e})")
        logger.error(f"Loopback capture failed: {e}")
        print("\n  TIP: You may need to:")
        print("    - Enable 'Stereo Mix' in Windows Sound settings")
        print("    - Or install VB-Audio Virtual Cable")
        print("    - Or set LOOPBACK_DEVICE_INDEX in config.py")
        if not config.ENABLE_MIC_CHANNEL:
            sys.exit(1)

    subtitles_display.start()

    for pipeline in pipelines:
        task = asyncio.create_task(pipeline.run())
        tasks.append(task)

    print("\n  Translator is running! Speak into your mic or play audio.\n")

    # =========================================================================
    # Step 6: Run until Ctrl+C
    # =========================================================================
    shutdown_event = asyncio.Event()

    def handle_shutdown(*args):
        logger.info("Shutdown signal received")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        await shutdown_event.wait()
    except KeyboardInterrupt:
        pass

    # =========================================================================
    # Step 7: Clean shutdown
    # =========================================================================
    print("\n\nShutting down...")

    for pipeline in pipelines:
        pipeline.stop()

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    if mic_capture:
        mic_capture.stop()
    if loopback_capture:
        loopback_capture.stop()

    audio_player.stop()
    subtitles_display.stop()

    print("Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        print(f"\nFatal error: {e}")
        print("Check translator.log for details.")
        sys.exit(1)
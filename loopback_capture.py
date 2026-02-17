"""
System audio capture for Windows.

Supports two modes (controlled by config.LOOPBACK_IS_INPUT_DEVICE):
  1. Stereo Mix / input device mode (recommended, most reliable)
  2. WASAPI loopback mode (fallback)
"""

import asyncio
import numpy as np
import sounddevice as sd
import logging
import time

import config

logger = logging.getLogger(__name__)


class LoopbackCapture:
    """
    Captures system audio via Stereo Mix or WASAPI loopback.

    Includes a feedback gate: when TTS is playing translated audio,
    capture is suppressed to prevent infinite translation loops.
    """

    def __init__(self, audio_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.audio_queue = audio_queue
        self.loop = loop
        self.stream: sd.InputStream | None = None
        self._running = False

        self.device_index = config.LOOPBACK_DEVICE_INDEX
        self.is_input_device = getattr(config, "LOOPBACK_IS_INPUT_DEVICE", True)

        # Feedback gate: timestamp until which loopback is muted
        self._gate_until: float = 0.0

    def set_gate(self, duration_s: float):
        """
        Mute loopback capture for the given duration.
        Called by the TTS audio player when it starts playing.
        """
        gate_end = time.monotonic() + duration_s + config.FEEDBACK_GATE_BUFFER_S
        self._gate_until = max(self._gate_until, gate_end)
        logger.debug(f"Loopback gate set for {duration_s:.2f}s + buffer")

    @property
    def is_gated(self) -> bool:
        return time.monotonic() < self._gate_until

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status: sd.CallbackFlags):
        if status:
            logger.warning(f"Loopback capture status: {status}")

        if not self._running or self.is_gated:
            return

        if indata.ndim > 1 and indata.shape[1] > 1:
            audio_chunk = indata.mean(axis=1).astype(np.float32)
        else:
            audio_chunk = indata[:, 0].copy().astype(np.float32)

        def _safe_put(chunk=audio_chunk):
            if not self.audio_queue.full():
                try:
                    self.audio_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

        try:
            self.loop.call_soon_threadsafe(_safe_put)
        except RuntimeError:
            pass

    def _make_resampling_callback(self, native_sr: int):
        target_sr = config.SAMPLE_RATE

        if native_sr == target_sr:
            return self._audio_callback

        ratio = target_sr / native_sr

        def resampling_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Loopback status: {status}")
            if not self._running or self.is_gated:
                return

            if indata.ndim > 1 and indata.shape[1] > 1:
                mono = indata.mean(axis=1).astype(np.float32)
            else:
                mono = indata[:, 0].copy().astype(np.float32)

            if len(mono) > 1:
                new_len = int(len(mono) * ratio)
                indices = np.linspace(0, len(mono) - 1, new_len)
                resampled = np.interp(indices, np.arange(len(mono)), mono).astype(np.float32)
            else:
                resampled = mono

            def _safe_put(chunk=resampled):
                if not self.audio_queue.full():
                    try:
                        self.audio_queue.put_nowait(chunk)
                    except asyncio.QueueFull:
                        pass

            try:
                self.loop.call_soon_threadsafe(_safe_put)
            except RuntimeError:
                pass

        return resampling_callback

    def _start_as_input_device(self, device_idx: int):
        device_info = sd.query_devices(device_idx)
        native_sr = int(device_info["default_samplerate"])
        in_channels = max(device_info["max_input_channels"], 1)

        logger.info(
            f"Starting loopback capture (input device mode): "
            f"device=[{device_idx}] {device_info['name']}, "
            f"sr={native_sr}, ch={in_channels}"
        )

        self.stream = sd.InputStream(
            device=device_idx,
            samplerate=native_sr,
            channels=min(in_channels, 2),
            dtype="float32",
            blocksize=int(native_sr * config.CHUNK_DURATION_MS / 1000),
            callback=self._make_resampling_callback(native_sr),
        )
        self.stream.start()
        logger.info(f"Loopback capture started via input device (sr: {native_sr})")

    def _start_as_wasapi_loopback(self, device_idx: int):
        device_info = sd.query_devices(device_idx)
        native_sr = int(device_info["default_samplerate"])
        out_channels = max(device_info["max_output_channels"], 1)

        logger.info(
            f"Starting loopback capture (WASAPI loopback mode): "
            f"device=[{device_idx}] {device_info['name']}, "
            f"sr={native_sr}, ch={out_channels}"
        )

        extra_settings = sd.WasapiSettings(exclusive=False)

        self.stream = sd.InputStream(
            device=device_idx,
            samplerate=native_sr,
            channels=out_channels,
            dtype="float32",
            blocksize=int(native_sr * config.CHUNK_DURATION_MS / 1000),
            callback=self._make_resampling_callback(native_sr),
            extra_settings=extra_settings,
        )
        self.stream.start()
        logger.info(f"Loopback capture started via WASAPI loopback (sr: {native_sr})")

    def start(self):
        if self.device_index is None:
            raise RuntimeError(
                "LOOPBACK_DEVICE_INDEX is not set in config.py. "
                "Run `python list_devices.py` to find your device index."
            )

        self._running = True

        try:
            if self.is_input_device:
                self._start_as_input_device(self.device_index)
            else:
                self._start_as_wasapi_loopback(self.device_index)
        except Exception as e:
            self._running = False
            raise RuntimeError(
                f"Cannot capture system audio from device [{self.device_index}]: {e}\n"
                "Run `python list_devices.py` to check available devices."
            )

    def stop(self):
        self._running = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.warning(f"Error stopping loopback stream: {e}")
            self.stream = None
        logger.info("Loopback capture stopped")
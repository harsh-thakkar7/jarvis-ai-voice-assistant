#!/usr/bin/env python3
"""Local speech-to-text for JARVIS using the Canary 180M Flash model.

Replaces the ``speech_recognition`` stack (Google Web Speech API via
``sr.Recognizer`` + ``sr.Microphone``) with fully on-device transcription:
capture uses PyAudio at the model's native 16 kHz mono rate, and inference
runs through transcribe.cpp's Canary 180M Flash GGUF on the Apple Metal
backend.

The voice-activity detector mirrors ``sr.Recognizer.listen`` semantics
(timeout, phrase_time_limit, pause_threshold, ambient calibration) so the
rest of JARVIS keeps working unchanged.
"""

import array
import math
import os
import threading
import time

import pyaudio

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # int16
CHANNELS = 1
CHUNK = SAMPLE_RATE // 10  # 100 ms blocks: good VAD granularity at 16 kHz

_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "models", "canary-180m-flash.gguf",
)
MODEL_PATH = os.environ.get("JARVIS_CANARY_MODEL", _MODEL_PATH)


class WaitTimeoutError(Exception):
    """No phrase started within the timeout window (normal silence)."""


class MicError(Exception):
    """Microphone unavailable or permission denied."""


class ModelUnavailable(Exception):
    """Canary model file or transcribe-cpp runtime missing/failed to load."""


class AudioChunk:
    """Minimal stand-in for ``sr.AudioData``: holds int16 PCM bytes."""

    def __init__(self, raw_data, sample_rate, sample_width):
        self.raw_data = raw_data or b""
        self.sample_rate = sample_rate
        self.sample_width = sample_width

    def get_raw_data(self, convert_rate=None, convert_width=None):
        return self.raw_data

    @property
    def duration(self):
        if self.sample_width <= 0 or self.sample_rate <= 0:
            return 0.0
        return len(self.raw_data) / (self.sample_width * self.sample_rate)


def _rms16(data):
    n = len(data) // 2
    if n <= 0:
        return 0.0
    vals = array.array("h", data[: n * 2])
    s = 0.0
    for v in vals:
        s += v * v
    return math.sqrt(s / n)


# Serialize all microphone use (and all model runs) so background listeners,
# hold-to-talk and interrupt-watch never race the single Metal backend.
_STREAM_LOCK = threading.Lock()


class MicCapture:
    """A PyAudio input session opened on demand, in the style of sr.Microphone."""

    SAMPLE_RATE = SAMPLE_RATE
    SAMPLE_WIDTH = SAMPLE_WIDTH
    CHANNELS = CHANNELS
    CHUNK = CHUNK

    def __init__(self, device_index=None):
        self.device_index = device_index
        self._pa = None
        self._stream = None

    # -- stream lifecycle ---------------------------------------------------
    def _open(self):
        if self._stream is not None:
            return
        if self._pa is None:
            self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=1024,
            )
        except Exception as exc:
            self.close()
            raise MicError(str(exc)) from exc

    def read(self, num_frames=None):
        self._open()
        return self._stream.read(num_frames or CHUNK)

    def close(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        pa, self._pa = self._pa, None
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *exc):
        self.close()

    # -- recognition helpers ------------------------------------------------
    def calibrate(self, duration=1.0):
        """Sample ambient noise and return a usable energy threshold."""
        rms_values = []
        blocks = max(1, int(SAMPLE_RATE * duration) // CHUNK)
        with _STREAM_LOCK:
            with self:
                for _ in range(blocks):
                    rms_values.append(_rms16(self.read(CHUNK)))
        if not rms_values:
            return 150
        return max(150, sum(rms_values) / len(rms_values) * 4.0)

    def listen(self, timeout=6, phrase_time_limit=10, pause_threshold=0.7,
               energy_threshold=None):
        """Block until a phrase starts, then return its AudioChunk.

        Raises WaitTimeoutError if nothing starts within ``timeout`` seconds.
        """
        threshold = float(energy_threshold) if energy_threshold else 150.0
        frames = []
        with _STREAM_LOCK:
            self._open()
            try:
                deadline = None if timeout is None else time.monotonic() + timeout
                while True:
                    if deadline is not None and time.monotonic() > deadline:
                        raise WaitTimeoutError
                    block = self.read(CHUNK)
                    level = _rms16(block)
                    if level <= threshold:
                        continue  # wait for speech
                    # phrase started
                    frames = [block]
                    silence = 0.0
                    elapsed = CHUNK / float(SAMPLE_RATE)
                    if phrase_time_limit and elapsed >= phrase_time_limit:
                        break
                    while True:
                        block = self.read(CHUNK)
                        level = _rms16(block)
                        elapsed += CHUNK / float(SAMPLE_RATE)
                        if level <= threshold:
                            silence += CHUNK / float(SAMPLE_RATE)
                            if silence >= pause_threshold:
                                break
                        else:
                            silence = 0.0
                        frames.append(block)
                        if phrase_time_limit and elapsed >= phrase_time_limit:
                            break
                    break  # phrase ended
            finally:
                self.close()
        return AudioChunk(b"".join(frames), SAMPLE_RATE, SAMPLE_WIDTH)

    def record_until(self, stop_event, max_bytes=None):
        """Capture frames until ``stop_event`` fires (hold-to-talk)."""
        frames = []
        total = 0
        limit = max_bytes or (SAMPLE_RATE * SAMPLE_WIDTH * 15)
        with _STREAM_LOCK:
            self._open()
            try:
                while not stop_event.is_set() and total < limit:
                    block = self.read(CHUNK)
                    frames.append(block)
                    total += len(block)
            finally:
                if self._stream is not None:
                    try:
                        self._stream.stop_stream()
                        self.close()
                    except Exception:
                        pass
        if frames:
            return AudioChunk(b"".join(frames), SAMPLE_RATE, SAMPLE_WIDTH)
        return None


# -- Canary model -----------------------------------------------------------

_LOAD_LOCK = threading.Lock()
_TRANSCRIBE_LOCK = threading.Lock()
_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    with _LOAD_LOCK:
        if _model is not None:
            return _model
        if not os.path.exists(MODEL_PATH):
            raise ModelUnavailable(
                "Canary model not found at %s. Run JARVIS setup to install it."
                % MODEL_PATH)
        try:
            import transcribe_cpp
        except Exception as exc:
            raise ModelUnavailable(
                "transcribe-cpp runtime not installed. Run 'pip install transcribe-cpp'."
            ) from exc
        try:
            _model = transcribe_cpp.Model(MODEL_PATH, backend="metal")
        except Exception:
            _model = transcribe_cpp.Model(MODEL_PATH)  # auto backend fallback
        return _model


def transcribe(pcm16):
    """Transcribe int16 mono little-endian PCM bytes (16 kHz) to text."""
    if not pcm16:
        return ""
    m = _load_model()
    import transcribe_cpp

    values = array.array("f", (v / 32768.0 for v in array.array("h", pcm16)))
    with _TRANSCRIBE_LOCK:
        result = transcribe_cpp.transcribe(m, values)
    return (result.text or "").strip()
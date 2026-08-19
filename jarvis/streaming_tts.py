"""Sentence-streaming TTS with instant barge-in.

Drop-in engine class for JARVIS-style UIs. Never imports main; never
hard-requires pyttsx3 (the driver is an injectable duck-typed seam).

Driver protocol (duck-typed):
    say(chunk: str) -> None      required
    stop() -> None               required (guarded internally)
    iterate() -> None            optional; driven after each chunk

Usage:
    spk = StreamingSpeaker()          # uses pyttsx3 if importable, else NullDriver
    stop = threading.Event()
    spk.speak("First sentence here. Second one follows.", stop)
    spk.interrupt()                   # barge-in from any thread
    print(spk.stats())
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional

__all__ = ["StreamingSpeaker", "NullDriver", "chunk_sentences"]

# Sentence boundary: [.!?] followed by whitespace/newline, or a newline itself.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MIN_CHUNK = 12


def chunk_sentences(text: str) -> list[str]:
    """Split *text* into sentence chunks. Pure function, no data loss.

    Tiny fragments (< _MIN_CHUNK chars) are merged into the previous chunk;
    a leading tiny fragment is merged forward so "".join(chunks) preserves
    all content modulo whitespace normalization.
    """
    if not text or not text.strip():
        return []
    raw = [p.strip() for p in _SENTENCE_RE.split(text) if p and p.strip()]
    if not raw:
        return []
    chunks: list[str] = []
    for piece in raw:
        if chunks and len(chunks[-1]) < _MIN_CHUNK:
            chunks[-1] = chunks[-1] + " " + piece
        elif len(piece) < _MIN_CHUNK:
            # Too short to lead; hold it to merge with the next piece.
            chunks.append(piece)
        else:
            chunks.append(piece)
    # A trailing tiny fragment stands alone rather than losing data.
    return chunks


class NullDriver:
    """Records spoken chunks when no real TTS backend is available."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def say(self, chunk: str) -> None:
        self.spoken.append(chunk)

    def stop(self) -> None:
        pass


def _default_driver():
    try:
        import pyttsx3  # noqa: PLC0415 - optional dependency by design
    except Exception:
        return NullDriver()
    try:
        engine = pyttsx3.init()
    except Exception:
        return NullDriver()

    class _Pyttsx3Driver:
        def say(self, chunk: str) -> None:
            engine.say(chunk)

        def stop(self) -> None:
            try:
                engine.stop()
            except Exception:
                pass

        def iterate(self) -> None:
            try:
                engine.iterate()
            except Exception:
                pass

    return _Pyttsx3Driver()


class StreamingSpeaker:
    """Sentence-streaming speaker with instant barge-in.

    speak() starts the first chunk as soon as it is known — before the rest
    of the text is processed — so first-audio latency beats total speak time.
    """

    def __init__(
        self,
        driver=None,
        on_chunk_start: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.driver = driver if driver is not None else _default_driver()
        self.on_chunk_start = on_chunk_start
        self._speak_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stop = threading.Event()
        self.chunks_spoken = 0
        self.chars_spoken = 0
        self.interrupts = 0

    # ------------------------------------------------------------------ #
    def speak(self, text: str, stop_event: threading.Event) -> bool:
        """Speak *text* sentence-by-sentence until done or stopped.

        Returns False immediately if another speak() is already running.
        """
        if not self._speak_lock.acquire(blocking=False):
            return False
        try:
            self._stop.clear()
            for chunk in chunk_sentences(text):
                if stop_event.is_set() or self._stop.is_set():
                    break
                cb = self.on_chunk_start
                if cb is not None:
                    try:
                        cb(chunk)
                    except Exception:
                        pass
                self.driver.say(chunk)
                iterate = getattr(self.driver, "iterate", None)
                if callable(iterate):
                    iterate()
                with self._stats_lock:
                    self.chunks_spoken += 1
                    self.chars_spoken += len(chunk)
            return True
        finally:
            self._speak_lock.release()

    # ------------------------------------------------------------------ #
    def interrupt(self) -> None:
        """Barge-in: set internal stop and ask the driver to halt."""
        self._stop.set()
        with self._stats_lock:
            self.interrupts += 1
        stop = getattr(self.driver, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    def stats(self) -> dict[str, int]:
        with self._stats_lock:
            return {
                "chunks_spoken": self.chunks_spoken,
                "chars_spoken": self.chars_spoken,
                "interrupts": self.interrupts,
            }

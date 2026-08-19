"""Tests for streaming_tts: sentence streaming, latency, barge-in, stats."""

import threading
import time

import pytest

import streaming_tts as streaming_tts_mod
from streaming_tts import NullDriver, StreamingSpeaker, chunk_sentences


class FakeDriver:
    """Records chunks with timestamps; simulate slow iterate() via delay."""

    def __init__(self, iterate_delay=0.0):
        self.chunks = []  # (chunk, t)
        self.t0 = time.perf_counter()
        self.stopped = False
        self.iterate_calls = 0
        self.iterate_delay = iterate_delay
        self._lock = threading.Lock()

    def say(self, chunk):
        with self._lock:
            self.chunks.append((chunk, time.perf_counter() - self.t0))

    def stop(self):
        self.stopped = True

    def iterate(self):
        self.iterate_calls += 1
        if self.iterate_delay:
            time.sleep(self.iterate_delay)


LONG_TEXT = (
    "Good morning, sir. The system check is complete and all cores are nominal. "
    "Shall I proceed with the scheduled backup?\nYes or no will do fine."
)


def _squash(s):
    return "".join(s.split())


def test_chunker_stable_and_no_data_loss():
    chunks = chunk_sentences(LONG_TEXT)
    assert len(chunks) >= 2
    assert all(c.strip() for c in chunks)
    # No data loss modulo whitespace diffs.
    assert _squash("".join(chunks)) == _squash(LONG_TEXT)


def test_chunker_newline_and_multiple_punct():
    text = "One! Two? Three.\nFour... Five."
    chunks = chunk_sentences(text)
    assert any("Three" in c for c in chunks)
    assert any("Five." in c for c in chunks)
    assert _squash("".join(chunks)) == _squash(text)


def test_chunker_merges_tiny_fragments():
    chunks = chunk_sentences("Hi. Ok then. This sentence is long enough to stand.")
    assert not any(len(c) < 12 and len(chunks) > 1 for c in chunks[:-1])
    assert "This sentence is long enough to stand." in chunks


def test_chunker_empty_and_whitespace_only():
    assert chunk_sentences("") == []
    assert chunk_sentences("   \n\t ") == []


def test_first_chunk_latency_below_total_speak_time():
    driver = FakeDriver(iterate_delay=0.05)  # slow engine loop
    spk = StreamingSpeaker(driver=driver)
    stop = threading.Event()
    spk.speak("Short opener here. Second sentence arrives later. Third wraps up.", stop)
    total_speak_time = driver.chunks[-1][1]
    first_chunk_latency = driver.chunks[0][1]
    assert first_chunk_latency < total_speak_time
    assert first_chunk_latency < 0.06  # starts before later chunks processed
    assert len(driver.chunks) == 3


def test_stop_event_midway_breaks_immediately():
    driver = FakeDriver()
    spk = StreamingSpeaker(driver=driver)
    stop_event = threading.Event()
    seen = []

    def cb(chunk):
        seen.append(chunk)
        if len(seen) >= 2:
            stop_event.set()

    spk.on_chunk_start = cb
    result = spk.speak(
        "First spoken sentence. Second spoken sentence. Third never heard. Fourth also skipped.",
        stop_event,
    )
    assert result is True
    spoken = [c for c, _ in driver.chunks]
    assert 0 < len(spoken) < 4
    assert "Third never heard." not in spoken
    assert spk.stats()["chunks_spoken"] == len(spoken)


def test_interrupt_barge_in_from_another_thread():
    driver = FakeDriver(iterate_delay=0.15)
    spk = StreamingSpeaker(driver=driver)
    stop_event = threading.Event()
    t = threading.Thread(target=lambda: time.sleep(0.18), daemon=True)
    timer = threading.Timer(0.18, spk.interrupt)
    timer.start()
    start = time.perf_counter()
    try:
        spk.speak(
            "Alpha sentence goes here. Beta sentence goes here. Gamma goes here. Delta goes here. Epsilon last.",
            stop_event,
        )
    finally:
        timer.join()
    elapsed = time.perf_counter() - start
    spoken = [c for c, _ in driver.chunks]
    assert 0 < len(spoken) < 5          # stopped midway, some already spoken
    assert driver.stopped is True       # driver.stop() was called
    assert elapsed < 0.9                # didn't finish all 5 x 0.15s
    stats = spk.stats()
    assert stats["interrupts"] == 1
    assert stats["chunks_spoken"] == len(spoken)


def test_concurrent_second_speak_returns_false():
    release = threading.Event()
    first_said = threading.Event()

    class BlockingDriver(FakeDriver):
        def say(self, chunk):
            super().say(chunk)
            first_said.set()
            release.wait(timeout=3)

    spk = StreamingSpeaker(driver=BlockingDriver())
    done = threading.Event()
    results = {}

    def worker():
        results["first"] = spk.speak("Hold this line please.", threading.Event())
        done.set()

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    assert first_said.wait(timeout=3)  # first speak is mid-flight, holding lock
    second = spk.speak("Second caller blocked.", threading.Event())
    assert second is False
    release.set()
    assert done.wait(timeout=3)
    assert results["first"] is True
    assert spk.stats()["chunks_spoken"] == 1


def test_stats_correct_after_full_speak():
    driver = FakeDriver()
    spk = StreamingSpeaker(driver=driver)
    text = "The quick brown fox. Jumps over the lazy dog."
    assert spk.speak(text, threading.Event()) is True
    st = spk.stats()
    assert st["chunks_spoken"] == 2
    expected_chars = sum(len(c) for c in chunk_sentences(text))
    assert st["chars_spoken"] == expected_chars
    assert st["interrupts"] == 0


def test_null_driver_path_without_pyttsx3(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def deny(name, *a, **k):
        if name == "pyttsx3":
            raise ImportError("blocked by test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", deny)
    monkeypatch.setattr(streaming_tts_mod, "_default_driver", lambda: NullDriver())
    spk = StreamingSpeaker()  # falls back to NullDriver
    assert isinstance(spk.driver, NullDriver)
    assert spk.speak("Fallback works fine. Even without a backend.", threading.Event())
    assert spk.driver.spoken == ["Fallback works fine.", "Even without a backend."]
    assert spk.stats()["chunks_spoken"] == 2


def test_on_chunk_start_callback_fires_in_order():
    seen = []
    spk = StreamingSpeaker(driver=FakeDriver(), on_chunk_start=seen.append)
    spk.speak("First up today. Second one next.", threading.Event())
    assert [c for c in seen] == ["First up today.", "Second one next."]

"""Tests for hotkey_ptt: edge-triggered global push-to-talk engine."""

import threading
import time

import pytest

import hotkey_ptt as hk


class FakeListener:
    """Scriptable stand-in for pynput.keyboard.Listener.

    Events are dicts: {"type": "press" | "release", "key": "<token>"}.
    """

    instances = []

    def __init__(self, on_press=None, on_release=None):
        self.on_press_cb = on_press
        self.on_release_cb = on_release
        self.stopped = False
        self.ran = False
        FakeListener.instances.append(self)

    def run(self):
        self.ran = True
        while not self.stopped:
            time.sleep(0.005)

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        deadline = time.monotonic() + (timeout or 0)
        while not self.stopped and time.monotonic() < deadline:
            time.sleep(0.005)

    def feed(self, event):
        if self.stopped:
            return  # post-stop events are dropped, like a dead OS listener
        cb = self.on_press_cb if event.get("type") == "press" else self.on_release_cb
        if cb is not None:
            cb(event.get("key"))


@pytest.fixture
def ptt_factory(monkeypatch):
    FakeListener.instances = []
    # Inject availability alongside the fake so the suite is green with or
    # without real pynput installed.
    monkeypatch.setattr(hk, "HAVE_PYNPUT", True)
    monkeypatch.setattr(hk.GlobalPTT, "LISTENER_FACTORY", FakeListener)
    engines = []

    def make(**kw):
        defaults = {"on_start": lambda: None, "on_stop": lambda: None}
        defaults.update(kw)
        eng = hk.GlobalPTT(**defaults)
        assert eng.start() is True
        engines.append(eng)
        return eng

    yield make
    for eng in engines:
        eng.stop()
    hk.release()


def _listener():
    return FakeListener.instances[-1]


PRESS_CTRL = {"type": "press", "key": "ctrl_l"}
RELEASE_CTRL = {"type": "release", "key": "ctrl_l"}
PRESS_ALT = {"type": "press", "key": "alt_l"}
RELEASE_ALT = {"type": "release", "key": "alt_l"}


# --------------------------------------------------------------------------- #
# Edge triggering
# --------------------------------------------------------------------------- #
def test_hold_once_fires_once_despite_key_repeat(ptt_factory):
    starts, stops = [], []
    eng = ptt_factory(on_start=lambda: starts.append(1), on_stop=lambda: stops.append(1))
    lis = _listener()

    lis.feed(PRESS_ALT)
    lis.feed(PRESS_CTRL)
    for _ in range(8):  # OS auto-repeat spam on the held key
        lis.feed(PRESS_CTRL)
    assert len(starts) == 1
    assert eng.active is True

    lis.feed(RELEASE_ALT)
    assert len(stops) == 1
    assert eng.active is False
    assert eng.starts_fired == 1 and eng.stops_fired == 1


def test_rearmable_and_latency_hooks(ptt_factory):
    starts, stops = [], []
    eng = ptt_factory(
        on_start=lambda: starts.append(time.perf_counter()),
        on_stop=lambda: stops.append(time.perf_counter()),
    )
    lis = _listener()

    t_feed = time.perf_counter()
    lis.feed(PRESS_CTRL)
    lis.feed(PRESS_ALT)
    assert len(starts) == 1
    assert eng.t_press is not None and eng.t_press - t_feed < 2.0

    lis.feed(RELEASE_CTRL)
    lis.feed(RELEASE_ALT)
    assert len(stops) == 1
    assert eng.t_release is not None and eng.t_release >= eng.t_press

    lis.feed(PRESS_ALT)  # re-arm: second full press cycle fires again
    lis.feed(PRESS_CTRL)
    assert len(starts) == 2 and len(stops) == 1


def test_partial_combo_never_fires(ptt_factory):
    starts, stops = [], []
    eng = ptt_factory(on_start=lambda: starts.append(1), on_stop=lambda: stops.append(1))
    lis = _listener()

    lis.feed(PRESS_CTRL)
    lis.feed({"type": "press", "key": "x"})  # non-combo noise
    lis.feed({"type": "release", "key": "x"})
    assert starts == [] and stops == []
    assert eng.active is False and eng.t_press is None

    lis.feed(RELEASE_CTRL)
    assert stops == []


def test_release_after_stop_no_crash(ptt_factory):
    starts, stops = [], []
    eng = ptt_factory(on_start=lambda: starts.append(1), on_stop=lambda: stops.append(1))
    lis = _listener()

    lis.feed(PRESS_CTRL)
    lis.feed(PRESS_ALT)
    lis.feed(RELEASE_CTRL)
    assert len(starts) == 1 and len(stops) == 1

    eng.stop()
    lis.feed(RELEASE_ALT)  # must be swallowed harmlessly
    lis.feed(PRESS_CTRL)
    eng.stop()  # double stop
    assert len(starts) == 1 and len(stops) == 1
    assert eng.running is False and eng._thread is None


def test_stop_joins_listener_thread(ptt_factory):
    eng = ptt_factory()
    thread = eng._thread
    assert thread is not None and thread.is_alive()
    eng.stop()
    assert not thread.is_alive()
    assert _listener().ran is True and _listener().stopped is True


# --------------------------------------------------------------------------- #
# Unavailable paths
# --------------------------------------------------------------------------- #
def test_unavailable_when_pynput_missing(monkeypatch):
    monkeypatch.setattr(hk, "HAVE_PYNPUT", False)

    def _boom(**kw):
        raise AssertionError("factory must not even be consulted")

    monkeypatch.setattr(hk.GlobalPTT, "LISTENER_FACTORY", _boom)
    starts, stops = [], []
    eng = hk.GlobalPTT(on_start=lambda: starts.append(1), on_stop=lambda: stops.append(1))

    assert eng.start() is False
    assert eng.available is False
    eng.stop()  # no-op path, must not raise
    assert starts == [] and stops == []
    assert eng.t_press is None and eng.t_release is None


def test_factory_importerror_maps_to_unavailable(monkeypatch):
    monkeypatch.setattr(hk, "HAVE_PYNPUT", True)

    def _boom(**kw):
        raise ImportError("pynput blocked by test")

    monkeypatch.setattr(hk.GlobalPTT, "LISTENER_FACTORY", _boom)
    starts, stops = [], []
    eng = hk.GlobalPTT(on_start=lambda: starts.append(1), on_stop=lambda: stops.append(1))

    assert eng.start() is False
    assert eng.available is False
    assert starts == [] and stops == []
    eng.stop()


# --------------------------------------------------------------------------- #
# macOS trust probe
# --------------------------------------------------------------------------- #
def test_is_trusted_rc_mapping(monkeypatch):
    seen = {}

    def fake_osa(argv):
        seen["argv"] = list(argv)
        return seen["rc"]

    monkeypatch.setattr(hk, "_osa_check", fake_osa)

    seen["rc"] = 0
    assert hk.is_trusted() is True
    assert hk.GlobalPTT.is_trusted() is True
    assert seen["argv"][0] == "osascript"
    assert "System Events" in seen["argv"][2]

    for rc in (1, -1, 256):
        seen["rc"] = rc
        assert hk.is_trusted() is False
        assert hk.GlobalPTT.is_trusted() is False


# --------------------------------------------------------------------------- #
# Singleton helpers
# --------------------------------------------------------------------------- #
def test_acquire_release_singleton():
    a = hk.acquire()
    b = hk.acquire()
    assert a is b
    hk.release()
    c = hk.acquire()
    assert c is not a
    hk.release()
    hk.release()  # idempotent, no crash


def test_callbacks_isolated_from_engine_crashes(ptt_factory):
    def bad_cb():
        raise RuntimeError("callback blew up")

    started = threading.Event()
    eng = hk.GlobalPTT(
        on_start=bad_cb,
        on_stop=lambda: started.set(),
    )
    assert eng.start() is True
    lis = _listener()
    lis.feed(PRESS_CTRL)
    lis.feed(PRESS_ALT)
    assert eng.active is True and eng.starts_fired == 1  # engine survives
    lis.feed(RELEASE_CTRL)
    assert eng.stops_fired == 1

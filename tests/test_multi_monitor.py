"""Tests for multi_monitor.py — fully offline; seams monkeypatched."""

import base64
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multi_monitor as mm  # noqa: E402

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def make_png(w, h, color):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


TWO_DISPLAYS = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]


@pytest.fixture()
def two_displays(monkeypatch):
    monkeypatch.setattr(mm, "_quartz_bounds", lambda: list(TWO_DISPLAYS))
    monkeypatch.setattr(
        mm, "_grab_size", lambda: pytest.fail("_grab_size must not run when quartz enumerates")
    )


# ==========================================================================
# list_displays
# ==========================================================================

def test_list_displays_two_quartz_sorted_with_fields(two_displays):
    displays = mm.list_displays()
    assert displays == [
        {"index": 1, "x": 0, "y": 0, "width": 1920, "height": 1080},
        {"index": 2, "x": 1920, "y": 0, "width": 1920, "height": 1080},
    ]


def test_list_displays_sorts_unordered_quartz_bounds(monkeypatch):
    monkeypatch.setattr(
        mm, "_quartz_bounds", lambda: [(3000, 0, 1920, 1080), (0, 500, 2560, 1440)]
    )
    displays = mm.list_displays()
    assert [d["x"] for d in displays] == [0, 3000]
    assert [d["index"] for d in displays] == [1, 2]
    assert displays[0]["y"] == 500


def test_list_displays_fallback_grab_size(monkeypatch):
    monkeypatch.setattr(mm, "_quartz_bounds", lambda: [])
    monkeypatch.setattr(mm, "_grab_size", lambda: (1440, 900))
    assert mm.list_displays() == [
        {"index": 1, "x": 0, "y": 0, "width": 1440, "height": 900}
    ]


def test_list_displays_fallback_default_when_grab_fails(monkeypatch):
    monkeypatch.setattr(mm, "_quartz_bounds", lambda: [])
    monkeypatch.setattr(mm, "_grab_size", lambda: None)
    assert mm.list_displays() == [
        {"index": 1, "x": 0, "y": 0, "width": 1280, "height": 800}
    ]


def test_display_for_index_hit_and_miss(two_displays):
    assert mm.display_for_index(2)["x"] == 1920
    assert mm.display_for_index(3) is None
    assert mm.display_for_index(0) is None


# ==========================================================================
# display_for_point
# ==========================================================================

def test_display_for_point_hits_each_display(two_displays):
    assert mm.display_for_point(100, 50)["index"] == 1
    assert mm.display_for_point(1919, 1079)["index"] == 1
    assert mm.display_for_point(1920, 0)["index"] == 2
    assert mm.display_for_point(3800, 900)["index"] == 2


def test_display_for_point_miss_returns_none(two_displays):
    assert mm.display_for_point(-1, 0) is None
    assert mm.display_for_point(3840, 0) is None  # shared edge is exclusive
    assert mm.display_for_point(9999, 9999) is None
    assert mm.display_for_point(100, -5) is None


# ==========================================================================
# capture_display — Pillow path
# ==========================================================================

class RecordingGrab:
    def __init__(self, image):
        self.image = image
        self.calls = []

    def __call__(self, bbox=None, all_screens=False):
        self.calls.append({"bbox": bbox, "all_screens": all_screens})
        return self.image


def test_capture_display_uses_pillow_seam_per_display_bbox(two_displays, monkeypatch):
    grab = RecordingGrab(Image.new("RGB", (10, 6), "red"))
    monkeypatch.setattr(mm, "_pillow_grab", grab)
    monkeypatch.setattr(
        mm, "_screencapture", lambda idx: pytest.fail("fallback must not run when pillow wins")
    )

    data = mm.capture_display(2)

    assert data[:8] == PNG_MAGIC
    assert Image.open(io.BytesIO(data)).size == (10, 6)
    assert grab.calls == [{"bbox": (1920, 0, 1920, 1080), "all_screens": False}]


def test_capture_display_all_screens_skips_bbox(two_displays, monkeypatch):
    grab = RecordingGrab(Image.new("RGB", (8, 4)))
    monkeypatch.setattr(mm, "_pillow_grab", grab)

    data = mm.capture_display(all_screens=True)

    assert data is not None and data[:8] == PNG_MAGIC
    assert grab.calls == [{"bbox": None, "all_screens": True}]


def test_capture_display_nonpositive_index_normalizes_to_primary(two_displays, monkeypatch):
    grab = RecordingGrab(Image.new("RGB", (4, 4)))
    monkeypatch.setattr(mm, "_pillow_grab", grab)
    assert mm.capture_display(0)[:8] == PNG_MAGIC
    assert mm.capture_display(-5)[:8] == PNG_MAGIC
    assert grab.calls == [
        {"bbox": (0, 0, 1920, 1080), "all_screens": False},
        {"bbox": (0, 0, 1920, 1080), "all_screens": False},
    ]


def test_capture_display_unknown_secondary_goes_to_fallback(monkeypatch):
    monkeypatch.setattr(mm, "_quartz_bounds", lambda: [(0, 0, 800, 600)])
    seen = []
    monkeypatch.setattr(mm, "_pillow_grab", lambda **kw: pytest.fail("no pillow for unknown display"))
    monkeypatch.setattr(mm, "_screencapture", lambda idx: seen.append(idx) or b"cli-png")

    assert mm.capture_display(7) == b"cli-png"
    assert seen == [7]


# ==========================================================================
# capture_display — screencapture fallback (Pillow absent)
# ==========================================================================

@pytest.fixture()
def pillow_absent(monkeypatch):
    monkeypatch.setattr(mm, "Image", None)


def test_fallback_screencapture_called_when_pillow_absent(pillow_absent, monkeypatch):
    seen = []

    def fake_cli(index):
        seen.append(index)
        return make_png(30, 20, "blue") if index == 2 else None

    monkeypatch.setattr(mm, "_screencapture", fake_cli)

    data = mm.capture_display(2)
    assert data is not None and data[:8] == PNG_MAGIC
    assert seen == [2]

    assert mm.capture_display(3) is None  # CLI miss -> honest None


def test_fallback_used_when_pillow_grab_and_save_fail(two_displays, monkeypatch):
    monkeypatch.setattr(mm, "_pillow_grab", lambda **kw: None)
    monkeypatch.setattr(mm, "_screencapture", lambda idx: b"fallback-bytes")
    assert mm.capture_display(1) == b"fallback-bytes"

    monkeypatch.setattr(mm, "_save_tmp_png", lambda img: None)
    monkeypatch.setattr(mm, "_pillow_grab", lambda **kw: object())
    monkeypatch.setattr(mm, "_screencapture", lambda idx: None if idx > 1 else b"main-only")
    assert mm.capture_display(1) == b"main-only"


# ==========================================================================
# _save_tmp_png seam roundtrip
# ==========================================================================

def test_save_tmp_png_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "_tmp_png_path", lambda: str(tmp_path / "shot.png"))
    image = Image.new("RGB", (7, 5), (10, 200, 30))

    data = mm._save_tmp_png(image)

    assert data[:8] == PNG_MAGIC
    back = Image.open(io.BytesIO(data))
    assert back.size == (7, 5)
    assert back.convert("RGB").getpixel((3, 2)) == (10, 200, 30)


# ==========================================================================
# capture_all_stitched — width-cap math + tile order
# ==========================================================================

@pytest.fixture()
def stitched_fixtures(monkeypatch):
    """Two 1200x900 tiles side by side; red on the left, blue on the right."""
    monkeypatch.setattr(mm, "_quartz_bounds", lambda: [(1200, 0, 1200, 900), (0, 0, 1200, 900)])
    grabs = {
        (0, 0, 1200, 900): Image.new("RGB", (1200, 900), (255, 0, 0)),
        (1200, 0, 1200, 900): Image.new("RGB", (1200, 900), (0, 0, 255)),
    }
    monkeypatch.setattr(
        mm, "_pillow_grab", lambda bbox=None, all_screens=False: grabs[bbox]
    )
    monkeypatch.setattr(
        mm, "_screencapture", lambda idx: pytest.fail("stitch must stay on the pillow path")
    )


def test_stitched_no_downscale_at_exact_cap(stitched_fixtures):
    data = mm.capture_all_stitched(max_width=2400)
    assert data[:8] == PNG_MAGIC
    canvas = Image.open(io.BytesIO(data))
    assert canvas.size == (2400, 900)
    assert canvas.getpixel((10, 450)) == (255, 0, 0)
    assert canvas.getpixel((1300, 450)) == (0, 0, 255)


def test_stitched_scales_down_to_cap(stitched_fixtures):
    canvas = Image.open(io.BytesIO(mm.capture_all_stitched(max_width=600)))
    assert canvas.size == (600, 225)  # uniform scale 0.25 keeps aspect ratio
    assert canvas.getpixel((150, 112)) == (255, 0, 0)
    assert canvas.getpixel((450, 112)) == (0, 0, 255)


def test_stitched_returns_none_without_pillow(stitched_fixtures, monkeypatch):
    monkeypatch.setattr(mm, "Image", None)
    assert mm.capture_all_stitched() is None


def test_stitched_returns_none_when_nothing_captured(monkeypatch):
    monkeypatch.setattr(mm, "_quartz_bounds", lambda: [(0, 0, 100, 100)])
    monkeypatch.setattr(mm, "_pillow_grab", lambda **kw: None)
    monkeypatch.setattr(mm, "_screencapture", lambda idx: None)
    assert mm.capture_all_stitched() is None


# ==========================================================================
# b64_png helper
# ==========================================================================

def test_b64_png_roundtrip():
    raw = PNG_MAGIC + bytes(range(256))
    encoded = mm.b64_png(raw)
    assert isinstance(encoded, str) and encoded.isascii()
    assert encoded == base64.b64encode(raw).decode("ascii")
    assert base64.b64decode(encoded) == raw

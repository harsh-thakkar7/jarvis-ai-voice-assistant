"""JARVIS MULTI-MONITOR: Clicky-grade screen awareness across ALL displays.

Enumerates every connected monitor, captures any/all of them, and maps a
global coordinate to the display that owns it — the plumbing vision skills
need to reason about multi-screen desktops.

Public API
----------
* :func:`list_displays`      - [{index,x,y,width,height}, ...] 1-based,
  ordered left-to-right (top-to-bottom tiebreak).
* :func:`display_for_index`  - dict for a 1-based index, or ``None``.
* :func:`display_for_point`  - owning display dict for global (x, y), else
  ``None`` (Clicky-style coordinate mapping).
* :func:`capture_display`    - PNG bytes of one display (or the whole virtual
  screen with ``all_screens=True``); ``None`` when capture fails.
* :func:`capture_all_stitched` - every display side-by-side as a single PNG
  capped at ``max_width``, ready for a vision prompt.
* :func:`b64_png`            - bytes -> base64 ASCII string helper.

Implementation notes
--------------------
Display enumeration prefers Quartz (``CGGetActiveDisplayList`` +
``CGDisplayBounds`` via pyobjc) behind :func:`_quartz_bounds`; when that is
unavailable it degrades to a single main-display guess sized from Pillow's
``ImageGrab.grab().size`` (:func:`_grab_size`) or a 1280x800 default.
Capture prefers Pillow ``ImageGrab`` (bbox of the owning display, or the full
virtual screen) and falls back to macOS ``screencapture -x -D <index>``
(:func:`_screencapture`). Every external touchpoint is a small module-level
function so tests can monkeypatch seams instead of touching real hardware;
failures degrade to ``None`` rather than raising.
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageGrab  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Pillow is a hard runtime dep elsewhere
    Image = None  # type: ignore[assignment]
    ImageGrab = None  # type: ignore[assignment]

try:
    import Quartz  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - non-mac or pyobjc missing
    Quartz = None  # type: ignore[assignment]

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("multi_monitor")

FALLBACK_WIDTH = 1280
FALLBACK_HEIGHT = 800
SCREENCAPTURE_TIMEOUT = 15.0


# ==========================================================================
# Enumeration seams
# ==========================================================================

def _quartz_bounds() -> list[tuple[int, int, int, int]]:
    """Per-display ``(x, y, width, height)`` tuples via Quartz, or ``[]``."""
    if Quartz is None:
        return []
    try:
        err, display_ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
        if err or not count:
            return []
        bounds = []
        for display_id in list(display_ids)[:count]:
            rect = Quartz.CGDisplayBounds(display_id)
            bounds.append(
                (
                    int(rect.origin.x),
                    int(rect.origin.y),
                    int(rect.size.width),
                    int(rect.size.height),
                )
            )
        return bounds
    except Exception as exc:  # pragma: no cover - defensive around CoreGraphics
        log.debug("quartz display enumeration failed: %s", exc)
        return []


def _grab_size() -> tuple[int, int] | None:
    """Main-display size via ``ImageGrab.grab().size``, or ``None``."""
    if ImageGrab is None:
        return None
    try:
        return ImageGrab.grab().size
    except Exception as exc:
        log.debug("ImageGrab size probe failed: %s", exc)
        return None


# ==========================================================================
# Capture seams
# ==========================================================================

def _pillow_grab(bbox=None, all_screens: bool = False):
    """Pillow ``ImageGrab`` wrapper; returns an image or ``None``."""
    if ImageGrab is None:
        return None
    try:
        if all_screens:
            return ImageGrab.grab(all_screens=True)
        if bbox is not None:
            return ImageGrab.grab(bbox=bbox)
        return ImageGrab.grab()
    except Exception as exc:
        log.debug("ImageGrab.grab failed: %s", exc)
        return None


def _tmp_png_path() -> str:
    fd, path = tempfile.mkstemp(prefix="jarvis_mm_", suffix=".png")
    os.close(fd)
    return path


def _save_tmp_png(image) -> bytes | None:
    """Save a PIL image to a temp PNG file and return the file's bytes."""
    if Image is None or image is None:
        return None
    path = _tmp_png_path()
    try:
        image.save(path, format="PNG")
        with open(path, "rb") as fh:
            return fh.read()
    except Exception as exc:
        log.debug("_save_tmp_png failed: %s", exc)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _screencapture(index: int) -> bytes | None:
    """macOS ``screencapture -x -D <index>`` fallback; PNG bytes or ``None``."""
    if sys.platform != "darwin":
        log.debug("screencapture fallback unavailable on %s", sys.platform)
        return None
    path = _tmp_png_path()
    try:
        proc = subprocess.run(
            ["screencapture", "-x", "-D", str(int(index)), path],
            capture_output=True,
            timeout=SCREENCAPTURE_TIMEOUT,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
            log.debug("screencapture rc=%s stderr=%s", proc.returncode, stderr)
            return None
        with open(path, "rb") as fh:
            return fh.read() or None
    except Exception as exc:
        log.debug("screencapture error: %s", exc)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ==========================================================================
# Enumeration + coordinate mapping
# ==========================================================================

def list_displays() -> list[dict]:
    """All displays as ``{"index","x","y","width","height"}``, 1-based.

    Ordered left-to-right (top-to-bottom tiebreak) so indices are stable.
    Falls back to a single main display sized from ``_grab_size()`` or the
    1280x800 default when Quartz enumeration is unavailable.
    """
    bounds = _quartz_bounds()
    if not bounds:
        size = _grab_size()
        width, height = size if size else (FALLBACK_WIDTH, FALLBACK_HEIGHT)
        bounds = [(0, 0, int(width), int(height))]
    displays = []
    ordered = sorted(bounds, key=lambda b: (b[0], b[1]))
    for i, (x, y, w, h) in enumerate(ordered, start=1):
        displays.append(
            {
                "index": i,
                "x": int(x),
                "y": int(y),
                "width": int(w),
                "height": int(h),
            }
        )
    return displays


def display_for_index(index: int) -> dict | None:
    """Display dict for a 1-based ``index``, or ``None`` when unknown."""
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    for display in list_displays():
        if display["index"] == idx:
            return display
    return None


def display_for_point(x, y) -> dict | None:
    """Owning display dict for a global ``(x, y)`` coordinate, or ``None``.

    Bounds are half-open (``x`` in [dx, dx+w), ``y`` in [dy, dy+h)) so
    adjacent displays never both claim the shared edge coordinate.
    """
    try:
        px, py = float(x), float(y)
    except (TypeError, ValueError):
        return None
    for display in list_displays():
        within_x = display["x"] <= px < display["x"] + display["width"]
        within_y = display["y"] <= py < display["y"] + display["height"]
        if within_x and within_y:
            return display
    return None


# ==========================================================================
# Capture
# ==========================================================================

def capture_display(index: int = 0, all_screens: bool = False) -> bytes | None:
    """PNG bytes of one display (1-based; ``0``/negative = main), or all.

    Prefers Pillow ``ImageGrab`` with the owning display's bbox (or the full
    virtual screen when ``all_screens=True``); falls back to macOS
    ``screencapture -x -D <index>``; returns ``None`` when both fail.
    """
    idx = max(1, int(index))
    display = None if all_screens else display_for_index(idx)
    if Image is not None and (all_screens or display is not None or idx == 1):
        bbox = None
        if display is not None:
            bbox = (
                display["x"],
                display["y"],
                display["width"],
                display["height"],
            )
        image = _pillow_grab(bbox=bbox, all_screens=all_screens)
        if image is not None:
            data = _save_tmp_png(image)
            if data:
                return data
    return _screencapture(idx)


def _png_bytes(image) -> bytes | None:
    if Image is None or image is None:
        return None
    buffer = io.BytesIO()
    try:
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception as exc:
        log.debug("_png_bytes encode failed: %s", exc)
        return None


def _open_png(data: bytes):
    if Image is None or not data:
        return None
    try:
        return Image.open(io.BytesIO(data))
    except Exception as exc:
        log.debug("_open_png decode failed: %s", exc)
        return None


def capture_all_stitched(max_width: int = 2400) -> bytes | None:
    """Every display pasted side-by-side into one PNG, width-capped.

    Tiles keep their native resolution until the combined width exceeds
    ``max_width``; the canvas is then uniformly downscaled to fit. Returns
    ``None`` when Pillow is missing or nothing could be captured.
    """
    if Image is None:
        return None
    tiles = []
    for display in list_displays():
        data = capture_display(display["index"])
        tile = _open_png(data) if data else None
        if tile is not None:
            tiles.append(tile.convert("RGB"))
    if not tiles:
        return None
    native_w = sum(tile.width for tile in tiles)
    native_h = max(tile.height for tile in tiles)
    limit = int(max_width) if max_width else native_w
    target_w = min(limit, native_w) if limit > 0 else native_w
    canvas = Image.new("RGB", (native_w, native_h), (20, 20, 20))
    x_offset = 0
    for tile in tiles:
        canvas.paste(tile, (x_offset, 0))
        x_offset += tile.width
    if target_w < native_w:
        scale = target_w / float(native_w)
        canvas = canvas.resize((target_w, max(1, round(native_h * scale))))
    return _png_bytes(canvas)


# ==========================================================================
# Helpers
# ==========================================================================

def b64_png(data: bytes) -> str:
    """Raw PNG bytes -> base64 ASCII string (data-URI ready payload)."""
    return base64.b64encode(bytes(data)).decode("ascii")

"""JARVIS NETWORK DIAGNOSTICS SKILLS: bandwidth, ping, Wi-Fi, traceroute.

Four skills, all fail-soft (never raise to the user), driven through the
small patchable seams ``_fetch_bytes`` / ``_http_get`` / ``_run_ping`` /
``_run_trace`` / ``_run_cmd`` that tests monkeypatch:

    - nd_speed_test : "run a speed test" / "how fast is my internet" ->
                      streams a few MB from a CDN and reports Mbps.
                      Primary: https://speed.cloudflare.com/__down?bytes=2000000
                      Fallback: https://proof.ovh.net/files/1Mb.dat
                      Download only - no upload testing, ever.
    - nd_ping       : "ping google.com" / "ping 8.8.8.8" -> /sbin/ping,
                      parsed average RTT + packet loss, conversational.
    - nd_wifi_info  : "wifi info" / "which wifi am i on" -> SSID, signal,
                      channel via ``ipconfig getsummary en0``, local IP,
                      default gateway and public IP (api.ipify.org).
    - nd_trace      : "traceroute X" / "trace route to X" -> first hops
                      summarised.

Security: hosts are squeezed through ``_clean_host`` which strips
scheme/path/port and then allows ONLY [A-Za-z0-9.-]; subprocesses are
always invoked in argument-list form (never shell=True) and always with
timeouts. Collisions: the ping detector refuses "the api" phrasings and
bare URLs (power_skills.ps_api_test owns HTTP probes); nd_wifi_info fires
only on INFO phrasings, never bare "wifi" or on/off/toggle commands.
This module never imports main.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("net_diagnostics_brain")

IS_DARWIN = platform.system() == "Darwin"

perf_counter = time.perf_counter  # seam: tests freeze the clock

# ==========================================================================
# Tunables
# ==========================================================================

_UA = {"User-Agent": "JarvisAssistant/2.1 (personal assistant)"}

SPEED_URLS = (
    "https://speed.cloudflare.com/__down?bytes=2000000",   # primary CDN
    "https://proof.ovh.net/files/1Mb.dat",                 # fallback CDN
)
SPEED_TIMEOUT = 15.0          # per-attempt requests timeout
SPEED_ATTEMPTS = 2            # hard cap: primary + fallback, no more
SPEED_FLOOR_BYTES = 500_000   # smaller transfer counts as a failed probe
SPEED_CAP_BYTES = 8_000_000   # never buffer more than this

PING_COUNT = 4
PING_DEADLINE_ARGS = ("-t", "10")   # give up after 10 s (macOS ping flag)
PING_TIMEOUT = 16.0                 # subprocess ceiling above the -t value
TRACE_TIMEOUT = 20.0
TRACE_HOPS_SHOWN = 6
PUBLIC_IP_URL = "https://api.ipify.org"
PUBLIC_IP_TIMEOUT = 6.0
WIFI_IFACE = "en0"

_SPEED_OFFLINE = ("The wire is silent, sir - not a single byte would come "
                  "down, so either the internet has left the building or "
                  "it is sulking somewhere, sir.")


# ==========================================================================
# Seams (tests monkeypatch these)
# ==========================================================================

def _fetch_bytes(url: str, timeout: float = SPEED_TIMEOUT) -> bytes:
    """Stream a URL's body into memory; return the bytes fetched.

    Raises on any network trouble - callers translate that into persona.
    """
    if requests is None:
        raise ConnectionError("requests library unavailable")
    got = bytearray()
    with requests.get(url, stream=True, timeout=timeout,
                      headers=_UA) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            got.extend(chunk)
            if len(got) >= SPEED_CAP_BYTES:
                break
    return bytes(got)


def _http_get(url: str, timeout: float = PUBLIC_IP_TIMEOUT) -> str:
    """GET a URL and return its trimmed text body; raises on trouble."""
    if requests is None:
        raise ConnectionError("requests library unavailable")
    resp = requests.get(url, timeout=timeout, headers=_UA)
    resp.raise_for_status()
    return (resp.text or "").strip()


def _run_cmd(cmd: list[str], timeout: float) -> tuple[int, str]:
    """Run an argument-list subprocess; return ``(code, combined output)``.

    Never raises and never touches a shell.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode, out
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as exc:  # defensive containment
        return 1, str(exc)[:200]


def _ping_binary() -> str | None:
    cand = "/sbin/ping"
    if os.path.exists(cand):
        return cand
    return shutil.which("ping")


def _trace_binary() -> str | None:
    cand = "/usr/sbin/traceroute"
    if os.path.exists(cand):
        return cand
    return shutil.which("traceroute")


def _run_ping(host: str, timeout: float = PING_TIMEOUT) -> tuple[int, str]:
    """Four ICMP echoes with a 10 s deadline, argument-list form."""
    binary = _ping_binary()
    if not binary:
        return 127, "ping binary not found"
    return _run_cmd([binary, "-c", str(PING_COUNT),
                     *PING_DEADLINE_ARGS, host], timeout)


def _run_trace(host: str, timeout: float = TRACE_TIMEOUT) -> tuple[int, str]:
    """Traceroute bounded to 8 hops / one probe per hop, 20 s ceiling."""
    binary = _trace_binary()
    if not binary:
        return 127, "traceroute binary not found"
    return _run_cmd([binary, "-m", "8", "-w", "2", "-q", "1", host],
                    timeout)


# ==========================================================================
# Shared parsing helpers
# ==========================================================================

def _mbps(nbytes: float, seconds: float) -> float:
    """Raw throughput in megabits per second."""
    return (nbytes * 8.0) / (seconds * 1_000_000.0)


def _fmt_mbps(mbps: float) -> str:
    """Round sensibly: whole numbers when fast, decimals when slow."""
    if mbps >= 100:
        return f"{mbps:.0f}"
    if mbps >= 10:
        return f"{mbps:.1f}"
    return f"{mbps:.2f}"


_PING_AVG_RE = re.compile(r"=\s*\d+(?:\.\d+)?\s*/\s*(\d+(?:\.\d+)?)\s*/")
_PING_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)%\s*packet\s*loss", re.I)
_PING_RX_RE = re.compile(r"(\d+)\s+packets?\s+received", re.I)


def _parse_ping(out: str) -> dict:
    """Extract avg RTT, loss percentage and received count from ping."""
    stats: dict = {"avg_ms": None, "loss_pct": None, "received": None}
    m = _PING_AVG_RE.search(out)
    if m:
        stats["avg_ms"] = float(m.group(1))
    m = _PING_LOSS_RE.search(out)
    if m:
        stats["loss_pct"] = float(m.group(1))
    m = _PING_RX_RE.search(out)
    if m:
        stats["received"] = int(m.group(1))
    return stats


_HOP_RE = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s*$")
_HOP_TIME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ms")


def _parse_trace(out: str) -> list[dict]:
    """Traceroute lines -> [{n, addr, times, avg_ms}] sorted by hop."""
    hops = []
    for line in (out or "").splitlines():
        m = _HOP_RE.match(line)
        if not m:
            continue
        rest = m.group(2)
        times = [float(t) for t in _HOP_TIME_RE.findall(rest)]
        addr = rest.split("(")[0].strip() if "(" in rest else rest.strip()
        addr = re.sub(r"\s+", " ", addr)
        hops.append({
            "n": int(m.group(1)),
            "addr": addr or "?",
            "times": times,
            "avg_ms": sum(times) / len(times) if times else None,
        })
    return sorted(hops, key=lambda h: h["n"])


def _parse_wifi_summary(text: str) -> dict:
    """Pull SSID / RSSI / channel out of ``ipconfig getsummary en0``."""
    info: dict = {}
    for raw in (text or "").splitlines():
        if ":" not in raw:
            continue
        key, _, val = raw.partition(":")
        k, v = key.strip().lower(), val.strip()
        if not v:
            continue
        if k == "ssid" and "ssid" not in info:
            info["ssid"] = v
        elif k in ("agrctlrssi", "rssi"):
            if "rssi" not in info or k == "agrctlrssi":
                try:
                    info["rssi"] = float(v)
                except ValueError:
                    pass
        elif k == "channel" and "channel" not in info:
            info["channel"] = v
    return info


def _signal_word(rssi: float | None) -> str:
    if rssi is None:
        return ""
    if rssi >= -50:
        return "excellent"
    if rssi >= -60:
        return "good"
    if rssi >= -70:
        return "fair"
    return "weak"


def _parse_gateway(route_out: str) -> str:
    m = re.search(r"gateway:\s*(\S+)", route_out or "")
    return m.group(1) if m else ""


# ==========================================================================
# Host validation (security-critical)
# ==========================================================================

_CLEAN_TOKEN_EDGE = "\"'?!.,;:"
_URLISH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_HOST_FULL_RE = re.compile(r"(?=.{1,253}$)[A-Za-z0-9]"
                           r"(?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
_STOPWORDS = {"the", "a", "an", "to"}


def _clean_host(raw: str | None) -> str | None:
    """Reduce a spoken token to a safe hostname, or None.

    Strips surrounding punctuation, rejects anything URL-shaped (HTTP
    probes belong to power_skills.ps_api_test), drops scheme/path/port
    fragments, then allows ONLY [A-Za-z0-9.-]. Anything that survives is
    safe to hand to a subprocess as a lone argument.
    """
    tok = (raw or "").strip().strip(_CLEAN_TOKEN_EDGE).strip()
    if not tok or "://" in tok or _URLISH_RE.match(tok):
        return None
    tok = tok.split("@")[-1].split("/", 1)[0].split(":", 1)[0].strip(".")
    if not tok or tok.lower() == "api":
        return None
    if not _HOST_FULL_RE.fullmatch(tok):
        return None
    return tok


# ==========================================================================
# Skill 1 - nd_speed_test (download only, two attempts, fail soft)
# ==========================================================================

_SPEED_RE = re.compile(
    r"\bspeed\s*tests?\b"
    r"|\b(?:internet|download|connection)\s+speed\b"
    r"|\bbandwidth\b"
    r"|\bhow\s+(?:fast|quick)\s+(?:is|are|does)\s+(?:my|the|our)\s+"
    r"(?:internet|connection|net|wifi|network)\b", re.I)


def _d_speed(cmd: str):
    if _SPEED_RE.search(cmd):
        return {"cmd": cmd}
    return None


def _e_speed(app, ctx) -> str:
    if requests is None:
        return _SPEED_OFFLINE
    for idx in range(SPEED_ATTEMPTS):
        url = SPEED_URLS[idx % len(SPEED_URLS)]
        source = re.sub(r"^https?://", "", url).split("/")[0]
        started = perf_counter()
        try:
            payload = _fetch_bytes(url)
        except Exception as exc:
            log.debug("speed probe %s failed: %s", source, exc)
            continue
        elapsed = perf_counter() - started
        nbytes = len(payload)
        if elapsed <= 0 or nbytes < SPEED_FLOOR_BYTES:
            log.debug("speed probe %s unusable (%d bytes)", source, nbytes)
            continue
        mbps = _mbps(nbytes, elapsed)
        return (f"Download bandwidth clocks in at {_fmt_mbps(mbps)} Mbps "
                f"({nbytes:,} bytes in {elapsed:.2f}s via {source}), sir.")
    return _SPEED_OFFLINE


# ==========================================================================
# Skill 2 - nd_ping
# ==========================================================================

_ANCHOR = (r"^(?:(?:hey|hi|hello|yo|ok|okay|please|jarvis)[\s,]*"
           r"|(?:(?:can|could|would|will)\s+you\s+))*")
_PING_RE = re.compile(_ANCHOR + r"ping\s+(?:the\s+)?(?P<tok>\S+)", re.I)
_API_BEFORE_RE = re.compile(r"\bthe\s+api\b", re.I)


def _resolve_token(cmd: str, m: "re.Match") -> str:
    """'trace route to the api' -> bump past articles to the real token."""
    tok = m.group("tok")
    if tok.lower() in _STOPWORDS:
        following = cmd[m.end():].split()
        if following:
            tok = following[0]
    return tok


def _d_ping(cmd: str):
    if not IS_DARWIN:
        return None
    m = _PING_RE.search(cmd)
    if not m:
        return None
    if _API_BEFORE_RE.search(cmd[:m.start()]):
        return None                       # "the api" phrasing: not ours
    host = _clean_host(_resolve_token(cmd, m))
    if not host:
        return None
    return {"cmd": cmd, "host": host}


def _e_ping(app, ctx) -> str:
    host = ctx["host"]
    code, out = _run_ping(host)
    stats = _parse_ping(out)
    if stats["avg_ms"] is None and stats["loss_pct"] is None:
        first = (out.splitlines() or ["no output"])[0][:120]
        return (f"I could not get a clean answer from {host}, sir "
                f"({first}). It may be down or simply refusing ICMP, sir.")
    if stats["loss_pct"] is not None and stats["loss_pct"] >= 100.0:
        return (f"{host} is not answering at all, sir - 100% packet loss "
                f"across {PING_COUNT} probes. Either it is offline or it "
                f"dislikes ping, sir.")
    parts = []
    if stats["avg_ms"] is not None:
        parts.append(f"{stats['avg_ms']:.1f} ms average round-trip")
    if stats["loss_pct"] is not None:
        parts.append(f"{stats['loss_pct']:g}% packet loss")
    if stats["received"] is not None:
        parts.append(f"{stats['received']}/{PING_COUNT} packets back")
    return f"Ping report for {host}: " + ", ".join(parts) + ", sir."


# ==========================================================================
# Skill 3 - nd_wifi_info (INFO phrasings only; each fact independent)
# ==========================================================================

_WIFI_RE = re.compile(
    r"\bwi?-?fi\s+(?:info|information|details|status|summary|report)\b"
    r"|\b(?:which|what)\s+wi?-?fi\b"
    r"|\bwhich\s+network\s+am\s+i\s+on\b"
    r"|\bnetwork\s+(?:info|information|details|status)\b", re.I)


def _d_wifi(cmd: str):
    if not IS_DARWIN:
        return None
    if _WIFI_RE.search(cmd):
        return {"cmd": cmd}
    return None


def _e_wifi(app, ctx) -> str:
    lines: list[str] = []
    good = 0

    code, summary = _run_cmd(["ipconfig", "getsummary", WIFI_IFACE],
                             timeout=6.0)
    info = _parse_wifi_summary(summary) if code == 0 else {}
    if info.get("ssid"):
        bits = [f"SSID {info['ssid']}"]
        signal = _signal_word(info.get("rssi"))
        if signal and info.get("rssi") is not None:
            bits.append(f"{signal} signal ({info['rssi']:.0f} dBm)")
        if info.get("channel"):
            bits.append(f"channel {info['channel']}")
        lines.append("- Wi-Fi: " + ", ".join(bits))
        good += 1
    else:
        lines.append("- Wi-Fi: no association found")

    code2, ip_out = _run_cmd(["ipconfig", "getifaddr", WIFI_IFACE],
                             timeout=5.0)
    local_ip = ip_out.split()[0] if code2 == 0 and ip_out.split() else ""
    if local_ip:
        lines.append(f"- Local IP ({WIFI_IFACE}): {local_ip}")
        good += 1
    else:
        lines.append(f"- Local IP ({WIFI_IFACE}): unavailable")

    code3, route_out = _run_cmd(["route", "-n", "get", "default"],
                                timeout=5.0)
    gateway = _parse_gateway(route_out) if code3 == 0 else ""
    if gateway:
        lines.append(f"- Gateway: {gateway}")
        good += 1
    else:
        lines.append("- Gateway: unavailable")

    try:
        body = _http_get(PUBLIC_IP_URL)
        public_ip = body.split()[0] if body.split() else ""
    except Exception as exc:
        log.debug("public ip lookup failed: %s", exc)
        public_ip = ""
    if public_ip:
        lines.append(f"- Public IP: {public_ip}")
        good += 1
    else:
        lines.append("- Public IP: unavailable right now")

    if good == 0:
        return ("I can see no working network interface, sir - we appear "
                "to be completely offline, sir.")
    lines.append(f"That is everything visible from interface "
                 f"{WIFI_IFACE}, sir.")
    return "Network status report, sir:\n" + "\n".join(lines)


# ==========================================================================
# Skill 4 - nd_trace
# ==========================================================================

_TRACE_RE = re.compile(
    _ANCHOR + r"(?:traceroute|tracert|trace\s*route)\s+"
              r"(?:to\s+|for\s+|of\s+)?(?P<tok>\S+)", re.I)


def _d_trace(cmd: str):
    if not IS_DARWIN:
        return None
    m = _TRACE_RE.search(cmd)
    if not m:
        return None
    if _API_BEFORE_RE.search(cmd[:m.start()]):
        return None
    host = _clean_host(_resolve_token(cmd, m))
    if not host:
        return None
    return {"cmd": cmd, "host": host}


def _e_trace(app, ctx) -> str:
    host = ctx["host"]
    code, out = _run_trace(host)
    hops = _parse_trace(out)
    if not hops:
        reason = "timed out" if code == 124 else "no usable hops came back"
        return (f"My traceroute to {host} came back unreadable, sir "
                f"({reason}). The path may be filtered or the host "
                f"asleep, sir.")
    lines = [f"Traceroute to {host}:"]
    shown = sorted(hops, key=lambda h: h["n"])[:TRACE_HOPS_SHOWN]
    for hop in shown:
        if hop["avg_ms"] is None:
            lines.append(f"  {hop['n']}. no reply")
        else:
            lines.append(f"  {hop['n']}. {hop['addr']} "
                         f"({hop['avg_ms']:.1f} ms)")
    answered = [h for h in hops if h["avg_ms"] is not None]
    if answered:
        last = answered[-1]
        lines.append(f"Deepest answer came from hop {last['n']} "
                     f"({last['addr']}) at {last['avg_ms']:.1f} ms, sir.")
    else:
        lines.append("Not a single hop along the way answered, sir.")
    return "\n".join(lines)


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("nd_speed_test", _d_speed, _e_speed, True),
    ("nd_ping", _d_ping, _e_ping, True),
    ("nd_wifi_info", _d_wifi, _e_wifi, True),
    ("nd_trace", _d_trace, _e_trace, True),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all network-diagnostic skills with the given Brain."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("network diagnostics registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something misfired in my network diagnostics "
                    f"module ({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())

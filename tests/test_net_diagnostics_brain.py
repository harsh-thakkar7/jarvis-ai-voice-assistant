"""Tests for net_diagnostics_brain.py — fully offline.

Every external effect goes through the module seams (_fetch_bytes,
_http_get, _run_cmd, _run_ping, _run_trace, perf_counter) which these
tests monkeypatch. No real network, no real subprocesses.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import net_diagnostics_brain as nd  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {"nd_speed_test", "nd_ping", "nd_wifi_info", "nd_trace"}


@pytest.fixture()
def brain():
    b = RecorderBrain()
    nd.register(b)
    return b


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


class FakeFetch:
    """Replays results from _fetch_bytes; entries may be bytes or raises."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, url, timeout=15.0):
        self.calls.append(url)
        item = self.results.pop(0) if self.results else ConnectionError("dead")
        if isinstance(item, Exception):
            raise item
        return item


class FakeHTTP:
    """Replays text bodies (or raises) for _http_get."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, url, timeout=6.0):
        self.calls.append(url)
        item = self.results.pop(0) if self.results else ConnectionError("down")
        if isinstance(item, Exception):
            raise item
        return item


class FakeRunner:
    """Dispatches _run_cmd by argv[0]; unlisted binaries fail with code 1."""

    def __init__(self):
        self.results = {}
        self.calls = []

    def queue(self, binary, results):
        self.results[binary] = list(results)
        return self

    def __call__(self, cmd, timeout=10.0):
        self.calls.append((list(cmd), timeout))
        seq = self.results.get(cmd[0])
        if seq:
            code, out = seq.pop(0)
            return code, out
        return 1, ""


class PerfSeq:
    """Frozen clock: pops scripted timestamps."""

    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0) if self.values else 0.0


# ==========================================================================
# Fixtures of real command output
# ==========================================================================

MACOS_PING_OK = """
PING google.com (142.250.72.238): 56 data bytes
64 bytes from 142.250.72.238: icmp_seq=0 ttl=115 time=21.5 ms
64 bytes from 142.250.72.238: icmp_seq=1 ttl=115 time=22.1 ms
64 bytes from 142.250.72.238: icmp_seq=2 ttl=115 time=20.9 ms
64 bytes from 142.250.72.238: icmp_seq=3 ttl=115 time=24.3 ms

--- google.com ping statistics ---
4 packets transmitted, 4 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 20.900/22.200/24.300/1.282 ms
"""

MACOS_PING_LOSSY = """
PING flaky.example (203.0.113.9): 56 data bytes
64 bytes from 203.0.113.9: icmp_seq=0 ttl=57 time=31.2 ms

--- flaky.example ping statistics ---
4 packets transmitted, 3 packets received, 25.0% packet loss
round-trip min/avg/max/stddev = 30.100/32.400/35.900/2.100 ms
"""

MACOS_PING_DEAD = (
    "PING dead.example (198.51.100.1): 56 data bytes\n"
    "Request timeout for icmp_seq 0\n"
    "\n--- dead.example ping statistics ---\n"
    "4 packets transmitted, 0 packets received, 100.0% packet loss"
)

IPCONFIG_SUMMARY = """
addstate / Network Setup: enabled
SCHEMA: 3
DHCP SERVERS:
	V4 server: 192.168.1.1
WI-FI
	SSID : WayneManor-5G
	BSSID : ac:de:48:00:11:22
	RSSI : -53
	noise : -89
	channel : 44,80
"""

ROUTE_DEFAULT = """
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC>
"""

TRACEROUTE_OK = """
traceroute to example.com (93.184.216.34), 64 hops max, 52 byte packets
 1  192.168.1.1 (192.168.1.1)  2.512 ms  1.987 ms  2.103 ms
 2  10.10.0.1 (10.10.0.1)  8.220 ms  7.988 ms  8.101 ms
 3  * * *
 4  ae-3.core1.nyc.example.net (198.51.100.7)  15.002 ms  14.881 ms
 5  example.com (93.184.216.34)  16.402 ms  16.388 ms  16.512 ms
"""

TRACEROUTE_LONG = "traceroute to far.example (203.0.113.99), 64 hops max\n" + "\n".join(
    f" {i}  hop{i}.example.net (203.0.113.{i})  {i * 2}.000 ms"
    for i in range(1, 10)
)


# ==========================================================================
# Registration & wiring
# ==========================================================================

def test_registers_all_four_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS


    def test_register_wraps_and_priorities(brain):
        for name in EXPECTED_SKILLS:
            detect, execute, prio = brain.skills[name]
            assert callable(detect) and callable(execute)
            assert execute.__name__ == f"safe_{name}"
            # nd_speed_test is priority=True (specific intent must not be
            # shadowed); the rest are normal priority.
            assert prio is (name == "nd_speed_test")


# ==========================================================================
# nd_speed_test — math, fallback, offline
# ==========================================================================

def test_speed_math():
    assert nd._mbps(2_000_000, 2.0) == pytest.approx(8.0)
    assert nd._mbps(1_000_000, 1.0) == pytest.approx(8.0)


def test_speed_formatting_rounds_sensibly():
    assert nd._fmt_mbps(150.44) == "150"
    assert nd._fmt_mbps(87.654) == "87.7"
    assert nd._fmt_mbps(4.567) == "4.57"


def test_speed_success_primary(brain, monkeypatch):
    fake = FakeFetch([b"\x00" * 2_000_000])
    monkeypatch.setattr(nd, "_fetch_bytes", fake)
    monkeypatch.setattr(nd, "perf_counter", PerfSeq(0.0, 2.0))
    reply = run(brain, "nd_speed_test", "run a speed test")
    assert fake.calls[0] == nd.SPEED_URLS[0]
    assert "cloudflare.com" in fake.calls[0]
    assert "8.00 Mbps" in reply
    assert reply.rstrip().endswith(", sir.")


def test_speed_falls_back_to_second_cdn(brain, monkeypatch):
    fake = FakeFetch([ConnectionError("primary down"), b"\x00" * 1_000_000])
    monkeypatch.setattr(nd, "_fetch_bytes", fake)
    monkeypatch.setattr(nd, "perf_counter", PerfSeq(0.0, 5.0, 6.0))
    reply = run(brain, "nd_speed_test", "how fast is my internet")
    assert len(fake.calls) == 2
    assert fake.calls[1].startswith("https://proof.ovh.net/")
    assert "proof.ovh.net" in reply
    assert "8.00 Mbps" in reply and reply.endswith(", sir.")


def test_speed_offline_witty_after_two_attempts(brain, monkeypatch):
    fake = FakeFetch([ConnectionError("x"), ConnectionError("y")])
    monkeypatch.setattr(nd, "_fetch_bytes", fake)
    reply = run(brain, "nd_speed_test", "speed test")
    assert len(fake.calls) == 2                     # hard cap of attempts
    assert "sir" in reply.lower() and reply.endswith(", sir.")
    assert "Mbps" not in reply                      # no number fabricated


def test_speed_tiny_payload_counts_as_failure(brain, monkeypatch):
    fake = FakeFetch([b"tiny", b"\x00" * 600_000])
    monkeypatch.setattr(nd, "_fetch_bytes", fake)
    monkeypatch.setattr(nd, "perf_counter", PerfSeq(0.0, 1.0, 0.0, 1.0))
    reply = run(brain, "nd_speed_test", "internet speed")
    assert fake.calls[0] == nd.SPEED_URLS[0]        # floor rejected attempt 1
    assert fake.calls[1] == nd.SPEED_URLS[1]        # fell through to fallback
    assert "Mbps" in reply                          # second probe succeeded


# ==========================================================================
# Host validation — security-critical accept/reject table
# ==========================================================================

@pytest.mark.parametrize("raw,expected", [
    ("google.com", "google.com"),
    ("8.8.8.8", "8.8.8.8"),
    ("localhost", "localhost"),
    ("sub.domain.co.uk", "sub.domain.co.uk"),
    ("google.com?", "google.com"),
    ("google.com/path/to?x=1", "google.com"),
    ("google.com:8080", "google.com"),
    ('"example.org"', "example.org"),
])
def test_clean_host_accepts(raw, expected):
    assert nd._clean_host(raw) == expected


@pytest.mark.parametrize("raw", [
    "",
    None,
    ".",
    "-",
    "..",
    "api",
    "the api",
    "$(reboot)",
    "`id`",
    "; rm -rf /",
    "|cat /etc/passwd",
    "-c;evil",
    "a;b",
    "host_name",
    "bad host",
    "a" * 300,
    "https://api.github.com/users",
    "http://evil.com/ping",
])
def test_clean_host_rejects(raw):
    assert nd._clean_host(raw) is None


def test_ping_detector_sanitizes_trailing_injection(brain):
    ctx = brain.skills["nd_ping"][0]("ping 8.8.8.8 && rm -rf /")
    assert ctx is not None
    assert ctx["host"] == "8.8.8.8"                 # only the clean host passes on


# ==========================================================================
# nd_ping — collisions, parsing, personas
# ==========================================================================

@pytest.mark.parametrize("cmd,host", [
    ("ping google.com", "google.com"),
    ("ping 8.8.8.8", "8.8.8.8"),
    ("please ping example.org", "example.org"),
    ("hey jarvis, ping hermes.local", "hermes.local"),
    ("can you ping 1.1.1.1", "1.1.1.1"),
])
def test_ping_detector_positive(brain, cmd, host):
    ctx = brain.skills["nd_ping"][0](cmd)
    assert ctx is not None and ctx["host"] == host


@pytest.mark.parametrize("cmd", [
    "ping the api",
    "ping api",
    "check the api ping 8.8.8.8",
    "ping https://api.github.com/users",
    "map ping google.com",
    "pinging google.com",
    "ping !",
    "ping",
    "test the api",
])
def test_ping_detector_negative_and_collisions(brain, cmd):
    assert brain.skills["nd_ping"][0](cmd) is None


def test_ping_yields_urls_to_ps_api_test():
    import power_skills as ps
    cmd = "ping https://api.github.com/users/octocat"
    assert ps._API_TEST_RE.search(cmd), "power_skills should own URL probes"
    assert nd._d_ping(cmd) is None, "net_diagnostics must defer URL probes"


def test_ping_parse_avg_loss_received():
    stats = nd._parse_ping(MACOS_PING_OK)
    assert stats["avg_ms"] == pytest.approx(22.2)
    assert stats["loss_pct"] == pytest.approx(0.0)
    assert stats["received"] == 4


def test_ping_parse_lossy_fixture():
    stats = nd._parse_ping(MACOS_PING_LOSSY)
    assert stats["avg_ms"] == pytest.approx(32.4)
    assert stats["loss_pct"] == pytest.approx(25.0)
    assert stats["received"] == 3


def test_ping_executor_conversational_summary(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_ping", lambda host, timeout=16.0: (0, MACOS_PING_OK))
    reply = run(brain, "nd_ping", "ping google.com")
    assert "22.2 ms average round-trip" in reply
    assert "0% packet loss" in reply
    assert "4/4 packets back" in reply
    assert reply.endswith(", sir.")


def test_ping_partial_loss_reported(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_ping", lambda host, timeout=16.0: (0, MACOS_PING_LOSSY))
    reply = run(brain, "nd_ping", "ping flaky.example")
    assert "25% packet loss" in reply and reply.endswith(", sir.")


def test_ping_total_loss_persona(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_ping", lambda host, timeout=16.0: (2, MACOS_PING_DEAD))
    reply = run(brain, "nd_ping", "ping dead.example")
    assert "not answering" in reply and "100% packet loss" in reply
    assert reply.endswith(", sir.")


def test_ping_unparseable_output_persona(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_ping", lambda host, timeout=16.0: (1, "socket noise"))
    reply = run(brain, "nd_ping", "ping weird.host")
    assert "could not get a clean answer" in reply
    assert reply.endswith(", sir.")


# ==========================================================================
# nd_wifi_info — composition with partial failures
# ==========================================================================

def test_wifi_summary_parser():
    info = nd._parse_wifi_summary(IPCONFIG_SUMMARY)
    assert info["ssid"] == "WayneManor-5G"
    assert info["rssi"] == pytest.approx(-53.0)
    assert info["channel"] == "44,80"


def test_gateway_parser():
    assert nd._parse_gateway(ROUTE_DEFAULT) == "192.168.1.1"


def test_wifi_composes_with_partial_failures(brain, monkeypatch):
    runner = FakeRunner().queue("ipconfig", [(0, IPCONFIG_SUMMARY), (1, "")]) \
                         .queue("route", [(0, ROUTE_DEFAULT)])
    monkeypatch.setattr(nd, "_run_cmd", runner)
    monkeypatch.setattr(nd, "_http_get", FakeHTTP([ConnectionError("no uplink")]))
    reply = run(brain, "nd_wifi_info", "wifi info")
    assert "WayneManor-5G" in reply
    assert "good signal (-53 dBm)" in reply
    assert "channel 44,80" in reply
    assert "Gateway: 192.168.1.1" in reply
    assert "Local IP (en0): unavailable" in reply
    assert "Public IP: unavailable" in reply
    assert reply.endswith(", sir.")
    # every piece attempted independently despite failures
    cmds = [c for c, _t in runner.calls]
    assert ["ipconfig", "getsummary", "en0"] in cmds
    assert ["ipconfig", "getifaddr", "en0"] in cmds
    assert ["route", "-n", "get", "default"] in cmds


def test_wifi_full_success(brain, monkeypatch):
    runner = FakeRunner().queue("ipconfig", [(0, IPCONFIG_SUMMARY),
                                             (0, "192.168.1.42")]) \
                         .queue("route", [(0, ROUTE_DEFAULT)])
    monkeypatch.setattr(nd, "_run_cmd", runner)
    monkeypatch.setattr(nd, "_http_get", FakeHTTP(["203.0.113.7"]))
    reply = run(brain, "nd_wifi_info", "which wifi am i on")
    assert "Local IP (en0): 192.168.1.42" in reply
    assert "Public IP: 203.0.113.7" in reply
    assert reply.endswith(", sir.")


def test_wifi_all_pieces_fail_offline_persona(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_cmd", FakeRunner())          # everything -> (1, "")
    monkeypatch.setattr(nd, "_http_get", FakeHTTP([ConnectionError("dark")]))
    reply = run(brain, "nd_wifi_info", "network details")
    assert "offline" in reply.lower() and reply.endswith(", sir.")


# ==========================================================================
# nd_trace — summarization
# ==========================================================================

def test_trace_parser_summarizes_hops():
    hops = nd._parse_trace(TRACEROUTE_OK)
    assert [h["n"] for h in hops] == [1, 2, 3, 4, 5]
    assert hops[0]["addr"] == "192.168.1.1"
    assert hops[0]["avg_ms"] == pytest.approx((2.512 + 1.987 + 2.103) / 3)
    assert hops[2]["avg_ms"] is None                # the "* * *" hop
    assert hops[4]["addr"] == "example.com"


def test_trace_executor_lists_first_hops(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_trace", lambda host, timeout=20.0: (0, TRACEROUTE_OK))
    reply = run(brain, "nd_trace", "traceroute example.com")
    assert "Traceroute to example.com:" in reply
    assert "1. 192.168.1.1" in reply
    assert "3. no reply" in reply                   # starred hop labelled
    assert "hop 5 (example.com)" in reply
    assert reply.endswith(", sir.")


def test_trace_executor_caps_at_six_hops(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_trace", lambda host, timeout=20.0: (0, TRACEROUTE_LONG))
    reply = run(brain, "nd_trace", "trace route to far.example")
    assert "6." in reply and "7." not in reply
    assert "far.example" in reply or "far.example" in str(
        brain.skills["nd_trace"][0]("trace route to far.example"))


def test_trace_empty_output_persona(brain, monkeypatch):
    monkeypatch.setattr(nd, "_run_trace", lambda host, timeout=20.0: (124, ""))
    reply = run(brain, "nd_trace", "traceroute silent.example")
    assert "unreadable" in reply and "timed out" in reply
    assert reply.endswith(", sir.")


# ==========================================================================
# Detector sweep — positives, negatives, collisions
# ==========================================================================

def test_speed_detector_positives(brain):
    d = brain.skills["nd_speed_test"][0]
    for cmd in ["run a speed test", "how fast is my internet",
                "what's my download speed", "check my bandwidth",
                "internet speed"]:
        assert d(cmd) is not None, f"speed missed {cmd!r}"


def test_wifi_detector_positives_only_on_info_phrasing(brain):
    d = brain.skills["nd_wifi_info"][0]
    for cmd in ["wifi info", "wi-fi details", "which wifi am i on",
                "what wifi network is this", "network details",
                "network info", "wifi status"]:
        assert d(cmd) is not None, f"wifi missed {cmd!r}"


@pytest.mark.parametrize("cmd", [
    "wifi",
    "turn wifi off",
    "turn wifi on",
    "toggle wifi",
    "connect to wifi",
    "my ip",
    "what's my ip",
    "is my internet up",
    "check the internet",
    "test the api https://api.example.com",
])
def test_collision_avoidance_no_false_triggers(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


def test_trace_detector_positives(brain):
    d = brain.skills["nd_trace"][0]
    for cmd, host in [("traceroute example.com", "example.com"),
                      ("trace route to example.com", "example.com"),
                      ("tracert google.com", "google.com")]:
        ctx = d(cmd)
        assert ctx is not None and ctx["host"] == host, f"trace missed {cmd!r}"


@pytest.mark.parametrize("cmd", [
    "trace",
    "traceroute",
    "trace the api",
    "traceroute https://example.net/x",
])
def test_trace_detector_negatives(brain, cmd):
    assert brain.skills["nd_trace"][0](cmd) is None


def test_non_darwin_guard_disables_system_skills(brain, monkeypatch):
    monkeypatch.setattr(nd, "IS_DARWIN", False)
    assert brain.skills["nd_ping"][0]("ping google.com") is None
    assert brain.skills["nd_wifi_info"][0]("wifi info") is None
    assert brain.skills["nd_trace"][0]("traceroute x.com") is None
    # speed test is pure HTTP and stays available off macOS
    assert brain.skills["nd_speed_test"][0]("speed test") is not None


@pytest.mark.parametrize("cmd", ["what time is it", "tell me a joke",
                                 "send an email to dad saying hi"])
def test_detectors_ignore_unrelated_commands(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


# ==========================================================================
# Containment
# ==========================================================================

def test_wrap_contains_crashes_in_persona(brain, monkeypatch):
    def boom(host, timeout=16.0):
        raise RuntimeError("cable pulled")

    monkeypatch.setattr(nd, "_run_ping", boom)
    reply = run(brain, "nd_ping", "ping google.com")
    assert "misfired" in reply and reply.endswith(", sir.")

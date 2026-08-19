"""Tests for skills_travel.py — fully offline, tmp_path-backed state.

Every skill goes through the module seams (STATE_FILE + reset_for_tests,
_now_utc) which these tests monkeypatch, so no real state file is ever
touched and zone math is frozen deterministically.
"""

import datetime
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skills_travel as tv  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {
    "tv_pack_new", "tv_pack_add", "tv_pack_done", "tv_pack_show",
    "tv_itin_new", "tv_itin_add", "tv_itin_show",
    "tv_jetlag", "tv_roadtrip_cost", "tv_trip_summary",
}

FROZEN_NOW = datetime.datetime(2026, 1, 15, 12, 0,
                               tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    """Isolate every test: tmp STATE_FILE, frozen clock, empty cache."""
    path = tmp_path / ".jarvis_travel.json"
    monkeypatch.setattr(tv, "STATE_FILE", str(path))
    monkeypatch.setattr(tv, "_now_utc", FROZEN_NOW)
    tv.reset_for_tests()
    yield str(path)
    tv.reset_for_tests()


@pytest.fixture()
def env(iso):
    return iso


@pytest.fixture()
def brain():
    b = RecorderBrain()
    tv.register(b)
    return b


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


def read_state(env):
    with open(env, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ==========================================================================
# Registration & wiring
# ==========================================================================

def test_registers_all_ten_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS


def test_register_wraps_fail_soft(brain):
    for name in EXPECTED_SKILLS:
        detect, execute, prio = brain.skills[name]
        assert callable(detect) and callable(execute)
        assert execute.__name__ == f"safe_{name}"
        assert prio is False


# ==========================================================================
# tv_pack_new — climate-aware generation + persistence
# ==========================================================================

@pytest.mark.parametrize("cmd", [
    "make a packing list for tokyo for 7 days",
    "create a packing list for iceland for 6 days",
    "packing list for bali for 10 days",
    "what should i pack for a beach trip",
    "prepare packing list for a weekend in paris",
])
def test_pack_new_detector_positives(brain, cmd):
    assert brain.skills["tv_pack_new"][0](cmd) is not None


@pytest.mark.parametrize("cmd", [
    "show my packing list",
    "add sunscreen to my packing list",
    "mark toothbrush as packed",
    "packing status",
    "backpack review",
    "weather in paris",
])
def test_pack_new_detector_negatives(brain, cmd):
    assert brain.skills["tv_pack_new"][0](cmd) is None


def test_pack_new_cold_climate_and_persists(brain, env):
    reply = run(brain, "tv_pack_new",
                "create a packing list for iceland for 6 days")
    assert "Iceland" in reply and "cold" in reply
    assert "Winter coat" in reply and "Thermal base layers" in reply
    assert reply.rstrip().endswith(", sir.")
    state = read_state(env)
    names = [i["name"] for i in state["packing"]["items"]]
    assert "Winter coat" in names and "Passport" in names
    assert all(i["done"] is False for i in state["packing"]["items"])
    assert state["trip"]["destination"] == "Iceland"
    assert state["trip"]["days"] == 6


def test_pack_new_hot_climate_scales_with_days(brain, env):
    reply = run(brain, "tv_pack_new", "packing list for bali for 10 days")
    assert "Sunscreen SPF 50" in reply and "Swimwear" in reply
    assert "T-shirts x8" in reply            # capped scaling
    state = read_state(env)
    assert state["packing"]["climate"] == "hot"


def test_pack_new_defaults_destination_and_days(brain, env):
    reply = run(brain, "tv_pack_new", "make a packing list for 4 days")
    assert "your trip" in reply and "temperate" in reply
    assert read_state(env)["packing"]["days"] == 4


# ==========================================================================
# tv_pack_add — dedupe, cap, persistence
# ==========================================================================

@pytest.mark.parametrize("cmd,item", [
    ("add sunscreen to my packing list", "Sunscreen"),
    ("add power bank to packing list please", "Power bank"),
    ("add camera lens cloth on the packing list", "Camera lens cloth"),
])
def test_pack_add_detector_extracts_item(brain, cmd, item):
    ctx = brain.skills["tv_pack_add"][0](cmd)
    assert ctx is not None and ctx["item"] == item


@pytest.mark.parametrize("cmd", [
    "add visit museum on day 2",
    "add a reminder for tomorrow",
    "add",
    "add x to my list of grievances",
])
def test_pack_add_detector_negatives(brain, cmd):
    assert brain.skills["tv_pack_add"][0](cmd) is None


def test_pack_add_round_trip_persistence(brain, env):
    reply = run(brain, "tv_pack_add", "add drone batteries to my packing list")
    assert "Added 'Drone batteries'" in reply and reply.endswith(", sir.")
    state = read_state(env)
    assert {"name": "Drone batteries", "done": False} in \
        state["packing"]["items"]
    assert not os.path.exists(env + ".tmp")     # atomic replace, no litter


def test_pack_add_rejects_duplicates(brain):
    run(brain, "tv_pack_add", "add drone batteries to my packing list")
    again = run(brain, "tv_pack_add", "add drone batteries to my packing list")
    assert "already on the packing list" in again


# ==========================================================================
# tv_pack_done — fuzzy match + progress accounting
# ==========================================================================

def test_pack_done_exact_then_fuzzy_match(brain, env):
    run(brain, "tv_pack_new", "make a packing list for tokyo for 7 days")
    first = run(brain, "tv_pack_done", "mark passport as packed")
    assert "'Passport' checked off" in first
    second = run(brain, "tv_pack_done", "i packed the phone charger")
    assert "'Phone charger' checked off" in second
    fuzzy = run(brain, "tv_pack_done", "mark toothbrushes as packed")
    assert "'Toothbrush' checked off" in fuzzy
    state = read_state(env)
    packed = [i["name"] for i in state["packing"]["items"] if i["done"]]
    assert packed == ["Passport", "Phone charger", "Toothbrush"]
    assert "3 of" in fuzzy


def test_pack_done_unknown_item_suggests(brain):
    run(brain, "tv_pack_new", "make a packing list for tokyo for 7 days")
    reply = run(brain, "tv_pack_done", "mark grand piano as packed")
    assert "not on the packing list" in reply and reply.endswith(", sir.")


def test_pack_done_without_list_prompts_creation(brain):
    reply = run(brain, "tv_pack_done", "mark socks as packed")
    assert "no packing list yet" in reply


# ==========================================================================
# tv_pack_show — rendering + corrupt-file recovery
# ==========================================================================

def test_pack_show_progress_rendering(brain):
    run(brain, "tv_pack_new", "make a packing list for tokyo for 5 days")
    run(brain, "tv_pack_done", "i have packed the wallet")
    reply = run(brain, "tv_pack_show", "show my packing list")
    assert "[x] Wallet" in reply
    assert "[ ] Passport" in reply
    assert "still out of the suitcase" in reply
    assert reply.endswith(", sir.")


def test_pack_show_empty_state_persona(brain):
    reply = run(brain, "tv_pack_show", "check my packing list")
    assert "No packing list on file yet" in reply


def test_corrupt_state_file_recovers_fresh(brain, env):
    with open(env, "w", encoding="utf-8") as fh:
        fh.write("{this is definitely not json,,,")
    tv.reset_for_tests()                          # simulate a restart
    reply = run(brain, "tv_pack_add", "add snorkel to my packing list")
    assert "Added 'Snorkel'" in reply             # did not crash
    state = read_state(env)                       # file healed on save
    assert state["packing"]["items"] == [{"name": "Snorkel",
                                          "done": False}]


def test_state_survives_simulated_restart(brain, env):
    run(brain, "tv_pack_new", "make a packing list for oslo for 3 days")
    run(brain, "tv_pack_add", "add hand warmers to my packing list")
    tv.reset_for_tests()                          # forget cached state
    reply = run(brain, "tv_pack_show", "show my packing list")
    assert "[ ] Hand warmers" in reply and "Oslo" not in reply
    assert "cold" not in reply                    # render only, no meta leak
    state = read_state(env)
    assert state["packing"]["destination"] == "Oslo"


# ==========================================================================
# Itinerary — build, extend, show, persist
# ==========================================================================

@pytest.mark.parametrize("cmd", [
    "plan a 4 day trip to rome",
    "create an itinerary for paris for 5 days",
    "new trip to san francisco",
    "map out a vacation for a weekend",
])
def test_itin_new_detector_positives(brain, cmd):
    ctx = brain.skills["tv_itin_new"][0](cmd)
    assert ctx is not None


@pytest.mark.parametrize("cmd", [
    "plan a 300 mile road trip",          # cost territory -> stand down
    "road trip cost estimate",
    "show my itinerary",
    "add dinner on day 3",
    "how much does gas cost",
])
def test_itin_new_detector_negatives(brain, cmd):
    assert brain.skills["tv_itin_new"][0](cmd) is None


def test_itin_flow_add_show_persist(brain, env):
    made = run(brain, "tv_itin_new", "plan a 4 day trip to rome")
    assert "4 day(s) in Rome" in made
    add1 = run(brain, "tv_itin_add", "add colosseum tour on day 2")
    assert "Day 2" in add1 and "colosseum tour" in add1
    run(brain, "tv_itin_add", "add day 3 vatican museums")
    overflow = run(brain, "tv_itin_add", "add venice detour on day 6")
    assert "beyond the 4-day plan" in overflow
    listing = run(brain, "tv_itin_show", "show my itinerary")
    assert "Itinerary for Rome" in listing
    assert "Day 2: colosseum tour" in listing
    assert "Day 3: vatican museums" in listing
    assert "Day 6: venice detour" in listing
    tv.reset_for_tests()                          # simulated restart
    listing2 = run(brain, "tv_itin_show", "show my itinerary")
    assert "Day 2: colosseum tour" in listing2
    state = read_state(env)
    assert state["itinerary"]["entries"]["2"] == ["colosseum tour"]


def test_itin_show_empty_persona(brain):
    reply = run(brain, "tv_itin_show", "whats the itinerary")
    assert "blank page" in reply


# ==========================================================================
# tv_jetlag — zoneinfo math, graceful degradation, schedule
# ==========================================================================

def test_jetlag_detector_positive_and_parse(brain):
    d = brain.skills["tv_jetlag"][0]
    ctx = d("jet lag from new york to tokyo")
    assert ctx["mode"] == "route"
    assert ctx["orig"] == "new york" and ctx["dest"] == "tokyo"


@pytest.mark.parametrize("cmd", [
    "what time is it in japan",
    "convert 3 hours to minutes",
    "weather in london",
    "time in usa",
    "jogging lag tips",
])
def test_jetlag_detector_negatives_no_time_or_weather_shadowing(brain, cmd):
    assert brain.skills["tv_jetlag"][0](cmd) is None


def test_resolve_zone_atlas_and_iana():
    assert tv.resolve_zone("tokyo") == "Asia/Tokyo"
    assert tv.resolve_zone("utc") == "UTC"
    assert tv.resolve_zone("america/new_york") == "America/New_York"
    assert tv.resolve_zone("Gotham City") is None
    assert tv.resolve_zone("") is None


def test_route_diff_math_fixed_reference():
    ref = datetime.datetime(2026, 1, 15, 12, 0,
                            tzinfo=datetime.timezone.utc)
    assert tv._route_diff("new york", "tokyo", ref) == pytest.approx(14.0)
    assert tv._route_diff("london", "new york", ref) == pytest.approx(-5.0)
    assert tv._route_diff("utc", "utc", ref) == pytest.approx(0.0)
    assert tv._route_diff("gotham city", "tokyo", ref) is None


def test_jetlag_eastward_schedule(brain):
    reply = run(brain, "tv_jetlag", "jet lag from new york to tokyo")
    assert "14 hours eastward" in reply
    assert "bedtime" in reply and "earlier" in reply
    assert "21:00" in reply                       # 23:00 shifted 120 min
    assert "120 min earlier" in reply
    assert reply.endswith(", sir.")


def test_jetlag_westward_direction_word(brain):
    reply = run(brain, "tv_jetlag", "jet lag from tokyo to new york")
    assert "westward" in reply and "later" in reply


def test_jetlag_same_zone_witty(brain):
    reply = run(brain, "tv_jetlag", "jet lag from utc to UTC")
    assert "same clock" in reply and "zero jet lag" in reply


def test_jetlag_unknown_city_degrades_gracefully(brain):
    reply = run(brain, "tv_jetlag", "jet lag from gotham city to tokyo")
    assert "gotham city" in reply
    assert "IANA" in reply and "America/New_York" in reply


def test_jetlag_general_mode_when_no_route(brain):
    cmd = "give me some jet lag tips"
    ctx = brain.skills["tv_jetlag"][0](cmd)
    assert ctx is not None and ctx["mode"] == "general"
    reply = tv._e_jetlag(DummyApp(), ctx)
    assert "playbook" in reply and reply.endswith(", sir.")


def test_jetlag_arrival_hour_shapes_advice(brain):
    morning = run(brain, "tv_jetlag",
                  "jet lag from new york to tokyo arriving at 9 am")
    assert "morning" not in morning.lower() or "hold out" in morning
    assert "90 minutes" in morning                # nap warning present
    evening = run(brain, "tv_jetlag",
                  "jet lag from new york to tokyo arriving at 11 pm")
    assert "evening arrival" in evening


# ==========================================================================
# tv_roadtrip_cost — arithmetic, units, splits, defaults
# ==========================================================================

def test_roadtrip_full_spec_arithmetic(brain):
    reply = run(brain, "tv_roadtrip_cost",
                "road trip cost 300 miles at 28 mpg with gas at 3.50 "
                "per gallon split 4 people")
    assert "10.7 gallon(s)" in reply              # 300 / 28
    assert "$37.50" in reply                      # 10.714... * 3.50
    assert "$9.38 each" in reply                  # 37.50 / 4
    assert reply.endswith(", sir.")


def test_roadtrip_round_trip_doubles_distance(brain):
    reply = run(brain, "tv_roadtrip_cost",
                "round trip road trip 300 miles at 28 mpg, gas at 3.50 "
                "per gallon")
    assert "600 mile(s)" in reply
    assert "$75.00" in reply
    assert "Round trip priced in" in reply


def test_roadtrip_km_and_kmpl_conversion(brain):
    reply = run(brain, "tv_roadtrip_cost",
                "road trip 200 km at 6 km/l with petrol at 1.80 per "
                "liter splitting between 2 people")
    assert "124.274 mile(s)" in reply             # 200 * 0.621371
    assert "Split across 2 people" in reply
    assert "gallon(s)" in reply                   # litres normalized


def test_roadtrip_defaults_disclosed(brain):
    reply = run(brain, "tv_roadtrip_cost", "road trip to boston, 120 miles")
    assert f"{tv.MPG_DEFAULT:g} mpg assumed" in reply
    assert f"{tv.PRICE_DEFAULT:.2f}" in reply


def test_roadtrip_missing_distance_polite_ask(brain):
    reply = run(brain, "tv_roadtrip_cost", "road trip cost estimate")
    assert "need a distance" in reply


@pytest.mark.parametrize("cmd", [
    "what is 30 mpg in liters per 100 km",        # brain_extra owns this
    "convert 100 kilometers to miles",
    "fuel economy of my car",
    "tell me a joke",
])
def test_roadtrip_detector_negatives(brain, cmd):
    assert brain.skills["tv_roadtrip_cost"][0](cmd) is None


# ==========================================================================
# tv_trip_summary — composition across subsystems
# ==========================================================================

def test_trip_summary_empty_persona(brain):
    reply = run(brain, "tv_trip_summary", "trip summary")
    assert "No trip is on the books yet" in reply


def test_trip_summary_composes_all_subsystems(brain):
    run(brain, "tv_pack_new", "make a packing list for kyoto for 6 days")
    run(brain, "tv_pack_done", "i packed the passport")
    run(brain, "tv_itin_new", "plan a 6 day trip to kyoto")
    run(brain, "tv_itin_add", "add fushimi shrine on day 1")
    reply = run(brain, "tv_trip_summary", "how is my trip going")
    assert "Travel briefing, sir" in reply
    assert "- Destination: Kyoto (6 days)" in reply
    assert "- Packing: 1/" in reply and "still needed" in reply
    assert "- Itinerary: 1 day(s) sketched (1 activity/ies)" in reply
    assert reply.endswith(", sir.")


# ==========================================================================
# Detector sweep — collisions with sibling packs must never fire
# ==========================================================================

@pytest.mark.parametrize("cmd", [
    "weather in paris",
    "what time is it in japan",
    "convert 2 hours to minutes",
    "tell me a joke",
    "send an email to dad saying hi",
    "ping google.com",
    "run a speed test",
    "start a focus session",
    "focus status",
    "wifi info",
    "remember that my wifi password is hunter2",
    "open youtube",
    "what is 30 mpg in liters per 100 km",
    "set a timer for 10 minutes",
])
def test_detectors_ignore_unrelated_commands(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


# ==========================================================================
# Containment — the _wrap fail-soft net
# ==========================================================================

def test_wrap_contains_crashes_in_persona(brain, monkeypatch):
    def boom():
        raise RuntimeError("suitcase exploded")

    monkeypatch.setattr(tv, "_load", boom)
    reply = run(brain, "tv_pack_show", "show my packing list")
    assert "misfired" in reply and "travel-planning" in reply
    assert reply.endswith(", sir.")

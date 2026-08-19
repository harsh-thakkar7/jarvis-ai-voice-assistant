"""Tests for skills_home.py — fully offline.

Every mutation flows through the module's core API against a
tmp_path-repointed ``.jarvis_home.json``; every date computation runs
against a frozen ``_today`` clock seam. No network, no real clock.
"""

import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skills_home as hm  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {
    "hm_add", "hm_value", "hm_room", "hm_find", "hm_remove",
    "hm_warranty", "hm_maint_add", "hm_maint_done", "hm_maint_due",
    "hm_car_service", "hm_car_next",
}

TODAY = dt.date(2026, 8, 24)  # frozen "today" for the whole suite


@pytest.fixture()
def brain():
    b = RecorderBrain()
    hm.register(b)
    return b


@pytest.fixture()
def store(tmp_path, monkeypatch):
    path = str(tmp_path / ".jarvis_home.json")
    monkeypatch.setattr(hm, "HOME_FILE", path)
    hm.reset_for_tests()
    yield path
    hm.reset_for_tests()


@pytest.fixture()
def frozen(monkeypatch):
    monkeypatch.setattr(hm, "_today", lambda: TODAY)
    return TODAY


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


# ==========================================================================
# Registration & wiring
# ==========================================================================

def test_registers_all_eleven_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS
    assert len(EXPECTED_SKILLS) == 11


def test_register_wraps_and_priorities(brain):
    for name in EXPECTED_SKILLS:
        detect, execute, prio = brain.skills[name]
        assert callable(detect) and callable(execute)
        assert execute.__name__ == f"safe_{name}"
        assert prio is True  # tightly-anchored intents must not be shadowed


# ==========================================================================
# Parsing helpers — date, interval, price, warranty span
# ==========================================================================

def test_parse_date_variants():
    assert hm.parse_date("bought on 2026-01-15 ok") == dt.date(2026, 1, 15)
    assert hm.parse_date("on aug 24 2026") == dt.date(2026, 8, 24)
    assert hm.parse_date("on March 5th, 2025") == dt.date(2025, 3, 5)
    assert hm.parse_date("no date here at all") is None
    assert hm.parse_date("2026-13-99 is nonsense") is None


def test_parse_interval_variants():
    assert hm.parse_interval("air filter every 90 days") == 90
    assert hm.parse_interval("gutters every 6 months") == 180
    assert hm.parse_interval("smoke alarm battery every year") == 365
    assert hm.parse_interval("water plants every week") == 7
    assert hm.parse_interval("no cadence mentioned") is None


def test_parse_price_and_warranty_span():
    assert hm.parse_price("add asset tv $1,299.99 in lounge") == 1299.99
    assert hm.parse_price("add asset rug for 120 in den") == 120.0
    assert hm.parse_price("add asset mystery box") is None
    assert hm.parse_warranty_span("with 2 year warranty") == 730
    assert hm.parse_warranty_span("warranty of 90 days") == 90
    assert hm.parse_warranty_span("3-month warranty included") == 90
    assert hm.parse_warranty_span("no cover") is None


# ==========================================================================
# hm_add — detection, execution, upsert
# ==========================================================================

@pytest.mark.parametrize("cmd,name", [
    ("add asset macbook pro for 1999 in the office",
     "macbook pro"),
    ("log asset desk lamp in the bedroom", "desk lamp"),
    ("register new asset espresso machine to home inventory",
     "espresso machine"),
    ("add dyson vacuum to inventory", "dyson vacuum"),
])
def test_add_detector_positives(brain, cmd, name):
    ctx = brain.skills["hm_add"][0](cmd)
    assert ctx is not None and ctx["name"] == name


@pytest.mark.parametrize("cmd", [
    "add milk to shopping list",
    "add expense coffee 4.50",
    "track my expenses",
    "remind me to buy milk",
])
def test_add_detector_never_shadows_shopping_or_expenses(brain, cmd):
    assert brain.skills["hm_add"][0](cmd) is None


def test_add_execute_roundtrip_with_room_price_warranty(frozen, store, brain):
    reply = run(brain, "hm_add",
                "add asset macbook pro for $1,999.00 in the office "
                "with 2 year warranty")
    assert "macbook pro" in reply
    assert "$1,999.00" in reply
    assert "office" in reply
    assert "warranty until 2028-08-23" in reply  # bought today + 730 days
    assert reply.rstrip().endswith(", sir.")
    with open(store, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["assets"][0]["price"] == 1999.00
    assert data["assets"][0]["room"] == "office"
    assert data["assets"][0]["warranty_end"] == "2028-08-23"


def test_add_defaults_when_details_missing(frozen, store, brain):
    reply = run(brain, "hm_add", "add asset mystery crate to inventory")
    with open(store, encoding="utf-8") as fh:
        data = json.load(fh)
    rec = data["assets"][0]
    assert rec["price"] == 0.0
    assert rec["room"] == "unassigned"
    assert rec["bought"] == TODAY.isoformat()      # injected clock used
    assert rec["warranty_end"] is None
    assert "unassigned" in reply


def test_add_upserts_same_name(frozen, store, brain):
    run(brain, "hm_add", "add asset lamp for 40 in the den")
    reply = run(brain, "hm_add", "add asset lamp for 55 in the attic")
    count, total = hm.total_value()
    assert count == 1 and total == pytest.approx(55.0)
    assert "Updated" in reply


# ==========================================================================
# hm_value / hm_room / hm_find / hm_remove
# ==========================================================================

def test_value_empty_persona(frozen, store, brain):
    reply = run(brain, "hm_value", "what is my home inventory worth")
    assert "empty" in reply.lower()


def test_value_sums_the_portfolio(frozen, store, brain):
    hm.add_asset("tv", 800.0, "living room", TODAY)
    hm.add_asset("desk", 300.25, "office", TODAY)
    reply = run(brain, "hm_value", "total value of my home inventory")
    assert "2 assets" in reply
    assert "$1,100.25" in reply


def test_value_detector_positive_phrasings(brain):
    d = brain.skills["hm_value"][0]
    for cmd in ["total value of my home inventory",
                "how much are my assets worth",
                "what is my inventory worth",
                "asset portfolio value"]:
        assert d(cmd) is not None, f"value missed {cmd!r}"


def test_room_lists_only_matching_room(frozen, store, brain):
    hm.add_asset("sofa", 900.0, "living room", TODAY)
    hm.add_asset("imac", 1800.0, "office", TODAY)
    reply = run(brain, "hm_room", "list assets in the living room")
    assert "sofa" in reply and "imac" not in reply
    assert "$900.00" in reply


def test_room_fuzzy_resolves_room_typos(frozen, store, brain):
    hm.add_asset("imac", 1800.0, "office", TODAY)
    reply = run(brain, "hm_room", "list assets in the offce")  # typo
    assert "imac" in reply and "office" in reply


def test_room_truly_unknown_lists_rooms_on_file(frozen, store, brain):
    hm.add_asset("imac", 1800.0, "office", TODAY)
    reply = run(brain, "hm_room", "list assets in the bathroom")
    assert "bathroom" in reply
    assert "Rooms on file: office" in reply


def test_find_fuzzy_matches_and_miss(frozen, store, brain):
    hm.add_asset("MacBook Pro", 1999.0, "office", TODAY)
    hit = run(brain, "hm_find", "search my inventory for macbook")
    assert "MacBook Pro" in hit and "office" in hit
    fuzzy = run(brain, "hm_find", "find macbuk pro in inventory")
    assert "MacBook Pro" in fuzzy
    miss = run(brain, "hm_find", "search my inventory for zeppelin parts")
    assert "Nothing" in miss or "nothing" in miss


def test_remove_deletes_and_reports_miss(frozen, store, brain):
    hm.add_asset("old printer", 89.0, "garage", TODAY)
    reply = run(brain, "hm_remove", "remove old printer from the inventory")
    assert "Removed" in reply and "$89.00" in reply
    count, _total = hm.total_value()
    assert count == 0
    miss = run(brain, "hm_remove", "delete ghost chair from inventory")
    assert "not on the inventory rolls" in miss


# ==========================================================================
# hm_warranty — window edges on the frozen clock
# ==========================================================================

def test_warranty_window_boundary_edges(frozen, store, brain):
    # ends exactly TODAY+30: inside (boundary inclusive)
    hm.add_asset("edge item", 100.0, "den", TODAY,
                 TODAY + dt.timedelta(days=30))
    # ends TODAY+31: outside the default window
    hm.add_asset("outside item", 100.0, "den", TODAY,
                 TODAY + dt.timedelta(days=31))
    inside = run(brain, "hm_warranty", "which warranties are expiring soon")
    assert "edge item" in inside and "30 days left" in inside
    assert "outside item" not in inside
    # widening the window to 45 days pulls the second one in
    wider = run(brain, "hm_warranty",
                "show warranties expiring within 45 days")
    assert "outside item" in wider and "31 days left" in wider


def test_warranty_flags_expired_items(frozen, store, brain):
    hm.add_asset("ancient toaster", 12.0, "kitchen", TODAY,
                 TODAY - dt.timedelta(days=5))
    reply = run(brain, "hm_warranty", "warranties expiring within 30 days")
    assert "ancient toaster" in reply
    assert "EXPIRED 5 days ago" in reply


def test_warranty_none_within_window_persona(frozen, store, brain):
    hm.add_asset("fresh tv", 800.0, "lounge", TODAY,
                 TODAY + dt.timedelta(days=400))
    reply = run(brain, "hm_warranty", "any warranties due?")
    assert "No warranties expire within 30 days" in reply


# ==========================================================================
# hm_maint_* — schedule, done-stamp, overdue math
# ==========================================================================

def test_maint_add_parses_task_and_interval(frozen, store, brain):
    reply = run(brain, "hm_maint_add",
                "add maintenance task air filter every 90 days")
    assert "air filter" in reply and "90 days" in reply
    with open(store, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["maint"]["air filter"]["interval_days"] == 90


def test_maint_done_stamps_date_and_predicts_next(frozen, store, brain):
    hm.set_task("air filter", 90)
    reply = run(brain, "hm_maint_done", "mark maintenance done for air filter")
    assert "air filter" in reply and "2026-08-24" in reply
    assert "2026-11-22" in reply  # today + 90 days
    entry = json.load(open(store, encoding="utf-8"))["maint"]["air filter"]
    assert entry["last_done"] == "2026-08-24"


def test_maint_due_overdue_math_sorted_worst_first(frozen, store, brain):
    hm.set_task("air filter", 90)
    hm.mark_done("air filter", dt.date(2026, 4, 1))       # due 06-30
    hm.set_task("gutter cleaning", 180)
    hm.mark_done("gutter cleaning", dt.date(2026, 2, 1))  # due 07-31
    hm.set_task("smoke alarm", 365)
    hm.mark_done("smoke alarm", dt.date(2026, 6, 1))      # due 2027-06-01
    reply = run(brain, "hm_maint_due", "which maintenance tasks are overdue")
    assert "OVERDUE by 55 days" in reply            # Apr 1 + 90 = Jun 30
    assert "OVERDUE by 24 days" in reply
    assert "air filter" in reply.splitlines()[1]     # worst first
    assert "gutter cleaning" in reply.splitlines()[2]
    assert "smoke alarm" not in reply                # comfortably future


def test_maint_due_today_and_all_clear(frozen, store, brain):
    hm.set_task("water heater flush", 90)
    hm.mark_done("water heater flush", TODAY - dt.timedelta(days=90))
    reply = run(brain, "hm_maint_due", "what maintenance is due")
    assert "due today" in reply
    clear_reply = run(brain, "hm_maint_due", "maintenance due list")
    assert "water heater" in clear_reply             # still due today
    hm.mark_done("water heater flush", TODAY)
    allclear = run(brain, "hm_maint_due", "maintenance due list")
    assert "within their intervals" in allclear


def test_maint_detectors_refuse_fitness_calories(brain):
    for name in ("hm_maint_add", "hm_maint_done", "hm_maint_due"):
        d = brain.skills[name][0]
        assert d("what are my maintenance calories") is None, name
        assert d("tdee maintenance calories for bulking") is None, name


# ==========================================================================
# hm_car_service / hm_car_next — odometer log & prediction
# ==========================================================================

def test_car_service_logs_odometer_and_note(frozen, store, brain):
    reply = run(brain, "hm_car_service",
                "log car service oil change at 45,000 miles on 2026-08-01")
    assert "oil change" in reply and "45,000 miles" in reply
    assert "2026-08-01" in reply
    hist = hm.service_history()
    assert len(hist) == 1
    assert hist[0]["odometer"] == 45000
    assert hist[0]["date"] == "2026-08-01"


def test_car_service_refuses_rollback(frozen, store, brain):
    hm.log_service(TODAY, 45000, "oil change")
    reply = run(brain, "hm_car_service",
                "record car service tire rotation at 44,000 miles")
    assert "44,000" in reply and "Nothing logged" in reply
    assert len(hm.service_history()) == 1           # nothing appended


def test_car_next_prediction_from_two_services(frozen, store, brain):
    hm.log_service(dt.date(2026, 6, 24), 46200, "brake pads")
    hm.log_service(dt.date(2026, 7, 24), 48000, "tire rotation")
    reply = run(brain, "hm_car_next", "when is my next car service")
    # 1,800 mi over 30 days -> 60 mi/day -> 5000/60 = 83 days after Jul 24
    assert "2026-10-15" in reply                    # mileage date wins
    assert "2027-01-20" in reply                    # calendar cap shown
    assert "60 mi/day" in reply


def test_car_next_single_entry_falls_back_to_assumption(frozen, store, brain):
    hm.log_service(dt.date(2026, 8, 1), 45000, "oil change")
    reply = run(brain, "hm_car_next", "is my car due for a service")
    # assumed 25 mi/day -> mileage lands 2027-02-18; cap 2027-01-28 wins
    assert "2027-01-28" in reply
    assert "time cap" in reply and "assumed 25 mi/day" in reply


def test_car_next_without_history_teaches(frozen, store, brain):
    reply = run(brain, "hm_car_next", "next car service prediction")
    assert "no car service history" in reply.lower()
    assert "log car service" in reply


def test_car_service_defers_maintenance_wording_to_hm_skills(brain):
    assert brain.skills["hm_car_service"][0](
        "mark oil change maintenance done") is None


# ==========================================================================
# Persistence — roundtrip, corrupt recovery, atomicity
# ==========================================================================

def test_persistence_survives_state_reset(frozen, store, brain):
    hm.add_asset("heirloom watch", 2500.0, "bedroom", TODAY)
    hm.reset_for_tests()                            # simulate restart
    count, total = hm.total_value()
    assert count == 1 and total == pytest.approx(2500.0)
    reply = run(brain, "hm_value", "total value of my home inventory")
    assert "$2,500.00" in reply


def test_corrupt_store_recovers_as_fresh(frozen, store, brain):
    with open(store, "w", encoding="utf-8") as fh:
        fh.write("{ this is absolutely not json !!!")
    hm.reset_for_tests()                            # force lazy reload
    count, total = hm.total_value()
    assert count == 0 and total == 0.0              # fresh, no crash
    hm.add_asset("replacement lamp", 15.0, "den", TODAY)
    with open(store, encoding="utf-8") as fh:
        data = json.load(fh)                        # file now valid again
    assert data["assets"][0]["name"] == "replacement lamp"


def test_atomic_save_leaves_no_temp_file(frozen, store, brain):
    hm.add_asset("lamp", 10.0, "den", TODAY)
    assert not os.path.exists(store + ".tmp")


# ==========================================================================
# Detector sweep & containment
# ==========================================================================

@pytest.mark.parametrize("cmd", [
    "what time is it",
    "tell me a joke",
    "send an email to dad saying hi",
    "add milk to the shopping list",
    "track expense coffee 4.50",
    "remind me to buy milk tomorrow",
    "what are my maintenance calories",
    "ping google.com",
])
def test_no_false_triggers_on_foreign_commands(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


def test_wrap_contains_crashes_in_persona(brain, monkeypatch):
    def boom():
        raise RuntimeError("shelf collapsed")

    monkeypatch.setattr(hm, "total_value", boom)  # seam inside the executor
    reply = run(brain, "hm_value", "total value of my home inventory")
    assert "misfired" in reply and reply.endswith(", sir.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

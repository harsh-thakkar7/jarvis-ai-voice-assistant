"""JARVIS TRIP PLANNING SKILL PACK: packing lists, itineraries, jet lag,
road-trip costs.

Ten offline skills for getting out the door, all fail-soft and backed by
one atomic JSON state file (``.jarvis_travel.json`` in the project dir):

    - tv_pack_new      : "make a packing list for tokyo for 7 days" ->
                         climate-aware checklist (cold / hot / temperate),
                         scaled by trip length.
    - tv_pack_add      : "add sunscreen to my packing list"
    - tv_pack_done     : "mark sunscreen as packed" / "i packed the charger"
                         (fuzzy item match via difflib)
    - tv_pack_show     : "show my packing list" -> progress with [x]/[ ]
    - tv_itin_new      : "plan a 5 day trip to rome" -> fresh itinerary
    - tv_itin_add      : "add colosseum tour on day 2"
    - tv_itin_show     : "show my itinerary"
    - tv_jetlag        : "jet lag from new york to tokyo" -> sleep-shift
                         schedule computed from stdlib zoneinfo offsets;
                         unknown cities degrade gracefully; bare
                         "jet lag tips" gives general advice.
    - tv_roadtrip_cost : "road trip cost 300 miles at 28 mpg gas at 3.50
                         per gallon split 4 people" -> fuel volume, cost,
                         per-person split; handles km / km-per-litre /
                         round trips.
    - tv_trip_summary  : "trip summary" -> destination, packing progress
                         and itinerary coverage in one briefing.

Collisions: every detector is tightly anchored. Jet lag requires the
literal phrase "jet lag" (never fires on country_time's "time in japan"),
road-trip costs require "road trip" plus a number or fuel word (never on
brain_extra's mpg<->L-per-100km converter), packing detectors require
"packing"/"pack for" phrasings (never bare "backpack"), and itin_new
stands down when miles/mpg/fuel words appear so cost queries route to
tv_roadtrip_cost. This module never imports main. Stdlib only.
"""

from __future__ import annotations

import datetime
import difflib
import json
import math
import os
import re
import threading

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - pre-3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("skills_travel")

# ==========================================================================
# Tunables
# ==========================================================================

DEFAULT_TRIP_DAYS = 3
MAX_TRIP_DAYS = 30
MAX_PACK_ITEMS = 40
MAX_ITIN_DAYS = MAX_TRIP_DAYS

MPG_DEFAULT = 28.0          # assumed efficiency when not spoken
PRICE_DEFAULT = 3.55        # $ per gallon when not spoken
KM_TO_MI = 0.621371
KML_TO_MPG = 2.35215

BASE_BEDTIME_MIN = 23 * 60  # assumed current bedtime, minutes past midnight
MAX_SHIFT_NIGHTS = 7

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".jarvis_travel.json")

_lock = threading.RLock()
_state: dict | None = None


# ==========================================================================
# Storage plumbing (atomic JSON, lazy load, corrupt-safe)
# ==========================================================================

def _fresh_state() -> dict:
    return {
        "trip": {"destination": None, "days": None},
        "packing": {"climate": None, "days": 0, "destination": None,
                    "items": []},
        "itinerary": {"destination": None, "days": 0, "entries": {}},
    }


def _load() -> dict:
    global _state
    if _state is not None:
        return _state
    data: dict = {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data = loaded
    except FileNotFoundError:
        pass
    except Exception as exc:            # corrupt file: start fresh
        log.warning("travel state unreadable, starting fresh: %s", exc)
        data = {}
    if not isinstance(data.get("trip"), dict):
        data["trip"] = _fresh_state()["trip"]
    if not isinstance(data.get("packing"), dict):
        data["packing"] = _fresh_state()["packing"]
    if not isinstance(data.get("itinerary"), dict):
        data["itinerary"] = _fresh_state()["itinerary"]
    if not isinstance(data["packing"].get("items"), list):
        data["packing"]["items"] = []
    if not isinstance(data["itinerary"].get("entries"), dict):
        data["itinerary"]["entries"] = {}
    _state = data
    return _state


def _save() -> None:
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_state or {}, fh)
        os.replace(tmp, STATE_FILE)
    except Exception as exc:
        log.warning("travel state save failed: %s", exc)


def reset_for_tests(path: str | None = None) -> None:
    """Test seam: drop cached state and optionally repoint the file."""
    global _state, STATE_FILE
    if path is not None:
        STATE_FILE = path
    _state = None


# ==========================================================================
# Shared parsing helpers
# ==========================================================================

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_FILLER_WORDS_RE = re.compile(
    r"\b(?:a|an|the|my|me|for|to|trip|vacation|holiday|journey|getaway"
    r"|beach|skiing?|safari|cruise|honeymoon|business|wedding|conference"
    r"|week)\b", re.I)
_DAYS_RE = re.compile(r"\b(\d{1,2})\s*days?\b", re.I)

_COLD_WORDS = ("cold", "winter", "snow", "ski", "alps", "iceland", "norway",
               "sweden", "finland", "alaska", "canada", "russia",
               "antarctica", "greenland", "chile", "scotland")
_HOT_WORDS = ("beach", "tropical", "hot", "summer", "hawaii", "bali", "goa",
              "maldives", "caribbean", "desert", "dubai", "thailand",
              "mexico", "cancun", "jamaica", "bahamas", "sri lanka",
              "philippines")


def _parse_days(cmd: str) -> int | None:
    m = _DAYS_RE.search(cmd or "")
    if m:
        return max(1, min(MAX_TRIP_DAYS, int(m.group(1))))
    if re.search(r"\bweekend\b", cmd, re.I):
        return 2
    if re.search(r"\bweeks?\b", cmd, re.I):
        return 7
    return None


def _infer_climate(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in _COLD_WORDS):
        return "cold"
    if any(w in t for w in _HOT_WORDS):
        return "hot"
    return "temperate"


def _clean_item(raw: str) -> str | None:
    name = re.sub(r"\s+", " ", (raw or "")).strip().strip(" .,!?'\"-")
    name = re.sub(r"^(?:a|an|the|my|some)\s+", "", name, flags=re.I)
    name = name.strip(" .,!?'\"-")
    if not (2 <= len(name) <= 40):
        return None
    return name[:1].upper() + name[1:]


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_hours(diff_h: float) -> str:
    rounded = round(abs(diff_h) * 2) / 2.0
    if float(rounded).is_integer():
        return f"{int(rounded)} hours"
    return f"{rounded:g} hours"


# ==========================================================================
# Skill 1 - tv_pack_new
# ==========================================================================

_PACK_NEW_RE = re.compile(
    r"\b(?:make|create|generate|prepare|start|draft|build|new)\b"
    r"[^;.!?]{0,24}?\bpacking\s+list\b"
    r"|\bpacking\s+list\s+for\b"
    r"|\bwhat\s+(?:should\s+i\s+)?pack\s+for\b", re.I)


def _d_pack_new(cmd: str):
    m = _PACK_NEW_RE.search(cmd or "")
    if not m:
        return None
    days = _parse_days(cmd) or DEFAULT_TRIP_DAYS
    tail = ""
    fm = re.search(r"(?:packing\s+list\s+for|pack\s+for)\s+(.+?)\s*$",
                   cmd, re.I)
    if fm:
        tail = fm.group(1)
    dest_raw = _FILLER_WORDS_RE.sub(" ", tail)
    dest_raw = _DAYS_RE.sub(" ", dest_raw)
    dest_raw = re.sub(r"\b(?:weekend|weeks?)\b", " ", dest_raw, flags=re.I)
    dest = re.sub(r"\s+", " ", dest_raw).strip(" ,.-")
    climate = _infer_climate(f"{cmd}")
    return {"cmd": cmd, "destination": dest.title() if dest else "",
            "days": days, "climate": climate}


_BASE_ITEMS = ["Passport", "Wallet", "Phone charger", "Keys",
               "Medications", "Toothbrush", "Deodorant"]

_CLIMATE_ITEMS = {
    "cold": ["Winter coat", "Thermal base layers", "Gloves", "Beanie",
             "Scarf", "Boots"],
    "hot": ["Sunscreen SPF 50", "Sunglasses", "Hat", "Swimwear",
            "Flip flops", "Insect repellent"],
    "temperate": ["Light jacket", "Umbrella", "Comfortable walking shoes"],
}


def _build_packing(climate: str, days: int) -> list[str]:
    items = list(_BASE_ITEMS)
    items.extend(_CLIMATE_ITEMS.get(climate, _CLIMATE_ITEMS["temperate"]))
    items.append(f"T-shirts x{min(days + 1, 8)}")
    items.append(f"Underwear x{min(days + 1, 8)}")
    items.append(f"Socks x{min(max(2, days // 2 + 1), 6)}")
    items.append(f"Pants x{min(max(2, days // 3 + 1), 4)}")
    return items


def _e_pack_new(app, ctx) -> str:
    climate = ctx["climate"]
    days = ctx["days"]
    names = _build_packing(climate, days)
    with _lock:
        state = _load()
        state["packing"] = {"climate": climate, "days": days,
                            "destination": ctx["destination"], "items": [
                                {"name": n, "done": False} for n in names]}
        if ctx["destination"]:
            state["trip"]["destination"] = ctx["destination"]
            state["trip"]["days"] = days
        _save()
    where = ctx["destination"] or "your trip"
    listing = "; ".join(names)
    return (f"Packing list generated, sir - {days} day(s), {climate} "
            f"conditions for {where}: {listing}. Say 'mark X as packed' "
            f"or 'add Y to my packing list' and I shall keep score, sir.")


# ==========================================================================
# Skill 2 - tv_pack_add
# ==========================================================================

_PACK_ADD_RE = re.compile(
    r"\badd\s+(?P<item>.{2,60}?)\s+(?:to|on)\s+(?:the\s+|my\s+)?"
    r"(?:packing(?:\s+list)?|list\b)", re.I)
_PACK_ADD_TAIL_RE = re.compile(
    r"\badd\s+(?:to\s+(?:the\s+|my\s+)?)?(?:packing\s+list\s+)"
    r"(?P<item>.{2,60})\s*$", re.I)


def _d_pack_add(cmd: str):
    m = _PACK_ADD_RE.search(cmd or "")
    if m:
        item = _clean_item(m.group("item"))
        if item:
            return {"cmd": cmd, "item": item}
    m = _PACK_ADD_TAIL_RE.search(cmd or "")
    if m:
        item = _clean_item(m.group("item"))
        if item:
            return {"cmd": cmd, "item": item}
    return None


def _e_pack_add(app, ctx) -> str:
    item = ctx["item"]
    with _lock:
        state = _load()
        items = state["packing"]["items"]
        if len(items) >= MAX_PACK_ITEMS:
            return (f"The packing list is at capacity ({MAX_PACK_ITEMS} "
                    f"items), sir - even I have limits on luggage, sir.")
        if any(i["name"].lower() == item.lower() for i in items):
            return (f"'{item}' is already on the packing list, sir - "
                    f"duly noted once is quite enough, sir.")
        items.append({"name": item, "done": False})
        packed = sum(1 for i in items if i["done"])
        _save()
    return (f"Added '{item}' to the packing list, sir - that makes "
            f"{len(items)} item(s) with {packed} already packed, sir.")


# ==========================================================================
# Skill 3 - tv_pack_done
# ==========================================================================

_PACK_DONE_AS_RE = re.compile(
    r"\b(?:mark|tick|check)\s+(?:off\s+)?(?P<item>.{2,40}?)"
    r"\s+as\s+packed\b", re.I)
_PACK_DONE_I_RE = re.compile(
    r"\bi\s+(?:have\s+)?packed\s+(?:up\s+)?(?:the\s+|my\s+)?"
    r"(?P<item>.{2,40})\s*$", re.I)


def _d_pack_done(cmd: str):
    m = _PACK_DONE_AS_RE.search(cmd or "")
    raw = m.group("item") if m else None
    if not raw:
        m = _PACK_DONE_I_RE.search(cmd or "")
        raw = m.group("item") if m else None
    if not raw:
        return None
    item = _clean_item(raw)
    if not item:
        return None
    return {"cmd": cmd, "item": item}


def _find_item(name: str, items: list[dict]) -> dict | None:
    exact = next((i for i in items if i["name"].lower() == name.lower()),
                 None)
    if exact:
        return exact
    close = difflib.get_close_matches(
        name.lower(), [i["name"].lower() for i in items], n=1, cutoff=0.5)
    if close:
        target = close[0]
        return next(i for i in items if i["name"].lower() == target)
    return None


def _e_pack_done(app, ctx) -> str:
    item = ctx["item"]
    with _lock:
        state = _load()
        items = state["packing"]["items"]
        found = _find_item(item, items)
        if found is None:
            if not items:
                return ("There is no packing list yet, sir - say 'make a "
                        "packing list for ...' first, sir.")
            near = difflib.get_close_matches(
                item.lower(), [i["name"].lower() for i in items],
                n=2, cutoff=0.3)
            hint = f" Did you mean {near[0]}?" if near else ""
            return (f"'{item}' is not on the packing list, sir.{hint} "
                    f"Add it first and I shall tick it off, sir.")
        found["done"] = True
        packed = sum(1 for i in items if i["done"])
        _save()
    return (f"'{found['name']}' checked off, sir - {packed} of "
            f"{len(items)} items packed, sir.")


# ==========================================================================
# Skill 4 - tv_pack_show
# ==========================================================================

_PACK_SHOW_RE = re.compile(
    r"\b(?:show|view|see|read|display|check|review)\b[^;.!?]{0,16}?"
    r"\bpacking(?:\s+list)?\b"
    r"|\bwhats?\s+(?:on\s+|in\s+)(?:the\s+|my\s+)?packing"
    r"|\bpacking\s+(?:status|progress)\b", re.I)


def _d_pack_show(cmd: str):
    return {"cmd": cmd} if _PACK_SHOW_RE.search(cmd or "") else None


def _e_pack_show(app, ctx) -> str:
    with _lock:
        items = list(_load()["packing"]["items"])
    if not items:
        return ("No packing list on file yet, sir - say 'make a packing "
                "list for paris for 5 days' and I shall draft one, sir.")
    lines = ["Packing status, sir:"]
    for it in items:
        mark = "[x]" if it["done"] else "[ ]"
        lines.append(f"  {mark} {it['name']}")
    packed = sum(1 for i in items if i["done"])
    left = len(items) - packed
    tail = (f"All {len(items)} items packed, sir - splendid."
            if left == 0 else
            f"{left} item(s) still out of the suitcase, sir.")
    lines.append(tail)
    return "\n".join(lines)


# ==========================================================================
# Skill 5 - tv_itin_new
# ==========================================================================

_COST_CONTEXT_RE = re.compile(
    r"\b(?:miles?|kilometers?|kms?|km\b|mpg|gallons?|fuel|gas|petrol)\b",
    re.I)
_ITIN_NEW_RE = re.compile(
    r"\b(?:plan|create|make|start|new|draft|map\s+out)\b[^;.!?]{0,24}?"
    r"\b(?:itinerar(?:y|ies)|trips?|vacation|holiday)\b", re.I)
_ITIN_DEST_RE = re.compile(
    r"\bto\s+(?P<dest>[a-z][a-z .'-]{1,30}?)(?:\s+for\b|\s*,\s*|\s*$)",
    re.I)


def _d_itin_new(cmd: str):
    text = cmd or ""
    if not _ITIN_NEW_RE.search(text):
        return None
    if _COST_CONTEXT_RE.search(text):
        return None                       # road-trip cost territory
    if _PACK_NEW_RE.search(text):
        return None                       # packing phrasing wins there
    m = _ITIN_DEST_RE.search(text)
    dest = re.sub(r"\s+", " ", m.group("dest")).strip(" .,-") if m else ""
    return {"cmd": cmd, "destination": dest.title() if dest else "",
            "days": _parse_days(text)}


def _e_itin_new(app, ctx) -> str:
    days = max(1, min(MAX_ITIN_DAYS, ctx["days"] or DEFAULT_TRIP_DAYS))
    dest = ctx["destination"]
    with _lock:
        state = _load()
        state["itinerary"] = {"destination": dest, "days": days,
                              "entries": {}}
        if dest:
            state["trip"]["destination"] = dest
            state["trip"]["days"] = days
        _save()
    where = dest or "your trip"
    return (f"Itinerary drafted, sir - {days} day(s) in {where}. Add "
            f"plans with 'add <activity> on day <N>' and say 'show my "
            f"itinerary' anytime, sir.")


# ==========================================================================
# Skill 6 - tv_itin_add
# ==========================================================================

_ITIN_ADD_RE = re.compile(
    r"\badd\s+(?P<act>.{2,80}?)\s*(?:on|to|for)\s+day\s*(?P<day>\d{1,2})\b"
    r"|\badd\s+day\s*(?P<day2>\d{1,2})\s*:?\s*(?P<act2>.{2,80})", re.I)


def _d_itin_add(cmd: str):
    m = _ITIN_ADD_RE.search(cmd or "")
    if not m:
        return None
    day = int(m.group("day") or m.group("day2"))
    act = m.group("act") or m.group("act2") or ""
    act = re.sub(r"\s+", " ", act).strip(" .,!?'\"-")
    if not act or len(act) > 80:
        return None
    return {"cmd": cmd, "day": day, "activity": act[:80]}


def _e_itin_add(app, ctx) -> str:
    day = max(1, min(MAX_ITIN_DAYS + 10, ctx["day"]))
    act = ctx["activity"]
    with _lock:
        state = _load()
        entries = state["itinerary"]["entries"]
        bucket = entries.setdefault(str(day), [])
        bucket.append(act)
        plan_days = state["itinerary"].get("days") or 0
        dest = state["itinerary"].get("destination") or "your trip"
        _save()
    overflow = ""
    if plan_days and day > plan_days:
        overflow = (f" That stretches beyond the {plan_days}-day plan - "
                    f"a man of ambition, sir.")
    return (f"Day {day} in {dest} updated, sir: '{act}' added."
            f"{overflow}")


# ==========================================================================
# Skill 7 - tv_itin_show
# ==========================================================================

_ITIN_SHOW_RE = re.compile(
    r"\b(?:show|view|see|read|display|review)\b[^;.!?]{0,16}?"
    r"\bitinerar(?:y|ies)\b"
    r"|\bitinerar(?:y|ies)\s*$"
    r"|\b(?:my|the)\s+travel\s+plans?\b", re.I)


def _d_itin_show(cmd: str):
    return {"cmd": cmd} if _ITIN_SHOW_RE.search(cmd or "") else None


def _e_itin_show(app, ctx) -> str:
    with _lock:
        itin = _load()["itinerary"]
        entries = {str(k): list(v) for k, v in itin["entries"].items()}
        days = itin.get("days") or 0
        dest = itin.get("destination") or ""
    if not entries:
        return ("The itinerary is a blank page so far, sir - plan a trip "
                "with 'plan a 5 day trip to rome', sir.")
    lines = [f"Itinerary{' for ' + dest if dest else ''}, sir:"]
    for key in sorted(entries, key=lambda k: int(k)):
        acts = "; ".join(entries[key])
        lines.append(f"  Day {key}: {acts}")
    filled = len(entries)
    if days and filled < days:
        lines.append(f"{days - filled} of {days} day(s) still open, sir.")
    return "\n".join(lines)


# ==========================================================================
# Timezone atlas (offline alias table + graceful zoneinfo resolution)
# ==========================================================================

_TZ_ALIASES = {
    "new york": "America/New_York", "nyc": "America/New_York",
    "ny": "America/New_York", "boston": "America/New_York",
    "miami": "America/New_York", "philadelphia": "America/New_York",
    "washington dc": "America/New_York", "toronto": "America/Toronto",
    "vancouver": "America/Vancouver",
    "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles", "las vegas": "America/Los_Angeles",
    "chicago": "America/Chicago", "dallas": "America/Chicago",
    "houston": "America/Chicago", "denver": "America/Denver",
    "phoenix": "America/Phoenix", "anchorage": "America/Anchorage",
    "honolulu": "Pacific/Honolulu", "hawaii": "Pacific/Honolulu",
    "london": "Europe/London", "dublin": "Europe/Dublin",
    "lisbon": "Europe/Lisbon", "paris": "Europe/Paris",
    "berlin": "Europe/Berlin", "munich": "Europe/Berlin",
    "madrid": "Europe/Madrid", "barcelona": "Europe/Madrid",
    "rome": "Europe/Rome", "milan": "Europe/Rome",
    "amsterdam": "Europe/Amsterdam", "brussels": "Europe/Brussels",
    "vienna": "Europe/Vienna", "prague": "Europe/Prague",
    "warsaw": "Europe/Warsaw", "budapest": "Europe/Budapest",
    "stockholm": "Europe/Stockholm", "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen", "helsinki": "Europe/Helsinki",
    "athens": "Europe/Athens", "istanbul": "Europe/Istanbul",
    "kyiv": "Europe/Kyiv", "kiev": "Europe/Kyiv",
    "moscow": "Europe/Moscow", "zurich": "Europe/Zurich",
    "geneva": "Europe/Zurich", "tokyo": "Asia/Tokyo",
    "seoul": "Asia/Seoul", "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei", "singapore": "Asia/Singapore",
    "bangkok": "Asia/Bangkok", "jakarta": "Asia/Jakarta",
    "manila": "Asia/Manila", "kuala lumpur": "Asia/Kuala_Lumpur",
    "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata", "kolkata": "Asia/Kolkata",
    "chennai": "Asia/Kolkata", "bangalore": "Asia/Kolkata",
    "goa": "Asia/Kolkata", "karachi": "Asia/Karachi",
    "dhaka": "Asia/Dhaka", "colombo": "Asia/Colombo",
    "kathmandu": "Asia/Kathmandu", "dubai": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai", "doha": "Asia/Qatar",
    "riyadh": "Asia/Riyadh", "tehran": "Asia/Tehran",
    "baghdad": "Asia/Baghdad", "tel aviv": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem", "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne", "brisbane":
        "Australia/Brisbane", "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide", "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland", "fiji": "Pacific/Fiji",
    "cairo": "Africa/Cairo", "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi", "johannesburg":
        "Africa/Johannesburg", "capetown": "Africa/Johannesburg",
    "casablanca": "Africa/Casablanca", "accra": "Africa/Accra",
    "sao paulo": "America/Sao_Paulo", "rio de janeiro":
        "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago", "lima": "America/Lima",
    "bogota": "America/Bogota", "caracas": "America/Caracas",
    "mexico city": "America/Mexico_City", "cancun":
        "America/Cancun", "utc": "UTC", "gmt": "UTC",
}


def resolve_zone(name: str) -> str | None:
    """Spoken city (or IANA key) -> canonical tz key, or None."""
    if ZoneInfo is None:                 # pragma: no cover
        return None
    key = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not key:
        return None
    iana = _TZ_ALIASES.get(key)
    candidates = [iana] if iana else []
    titled = "/".join(
        "_".join(word.capitalize() for word in seg.split("_"))
        for seg in key.split("/"))
    for cand in (titled, key):           # canonical casing wins if both work
        if cand and cand not in candidates:
            candidates.append(cand)
    candidates[:] = [cand for cand in dict.fromkeys(candidates) if cand]
    for cand in candidates:
        try:
            ZoneInfo(cand)               # validate before trusting
            return cand
        except Exception:
            continue
    return None


_now_utc = datetime.datetime.now(datetime.timezone.utc)  # seam: tests freeze


def _offset_hours(zone_key: str, ref: datetime.datetime) -> float:
    off = ZoneInfo(zone_key).utcoffset(ref)
    return (off.total_seconds() / 3600.0) if off else 0.0


def _route_diff(orig: str, dest: str,
                ref: datetime.datetime | None = None) -> float | None:
    """Destination minus origin UTC offset in hours; None if unknown."""
    o_key, d_key = resolve_zone(orig), resolve_zone(dest)
    if not o_key or not d_key:
        return None
    ref = ref or _now_utc
    return _offset_hours(d_key, ref) - _offset_hours(o_key, ref)


# ==========================================================================
# Skill 8 - tv_jetlag
# ==========================================================================

_JETLAG_RE = re.compile(r"\bjet\s*-?\s*lags?\b", re.I)
_JET_ROUTE_RE = re.compile(
    r"\bfrom\s+(?P<orig>[a-z][a-z .'-]{1,40}?)\s+to\s+"
    r"(?P<dest>[a-z][a-z .'-]{1,40}?)(?:\s+(?:arriving|landing|at|on|next)"
    r"\b.*)?\s*$", re.I)
_JET_ARRIVE_RE = re.compile(
    r"\b(?:arriving|landing|getting\s+in)\s+(?:at\s+)?(?P<h>\d{1,2})"
    r"(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?\b", re.I)


def _d_jetlag(cmd: str):
    text = cmd or ""
    if not _JETLAG_RE.search(text):
        return None
    ctx: dict = {"cmd": text, "mode": "general"}
    m = _JET_ROUTE_RE.search(text)
    if m:
        orig = m.group("orig").strip(" .,-")
        dest = m.group("dest").strip(" .,-")
        ctx.update({"mode": "route", "orig": orig, "dest": dest})
    am = _JET_ARRIVE_RE.search(text)
    if am:
        hour = int(am.group("h"))
        ap = (am.group("ap") or "").lower()
        if am.group("ap"):
            hour = hour % 12 + (12 if ap == "pm" else 0)
        if 0 <= hour <= 23:
            ctx["arrive_hour"] = hour
    return ctx


_JET_TIPS = (
    "Jet-lag playbook, sir: shift your sleep toward the destination one "
    "hour per day before departure; hydrate aggressively and skip alcohol "
    "aloft; set your watch to arrival time the moment you board; and hunt "
    "bright morning light eastward, evening light westward, sir.")


def _fmt_bed(mins: int) -> str:
    mins %= 24 * 60
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _arrival_advice(hour: int, diff: float) -> str:
    local_morning = 5 <= hour < 12
    if local_morning:
        return (f"With a {hour:02d}:00-ish arrival, hold out until local "
                f"bedtime - naps beyond 90 minutes will sabotage night one, "
                f"sir.")
    return (f"With an evening arrival, allow yourself one nap of at most "
            f"90 minutes before pushing through to local bedtime, sir.")


def _e_jetlag(app, ctx) -> str:
    if ctx["mode"] == "general":
        return _JET_TIPS
    orig, dest = ctx["orig"], ctx["dest"]
    o_zone, d_zone = resolve_zone(orig), resolve_zone(dest)
    if not o_zone or not d_zone:
        bad = orig if not o_zone else dest
        return (f"My atlas has no entry for '{bad}', sir - give me the "
                f"IANA zone name such as America/New_York and I shall "
                f"compute the shift precisely, sir.")
    diff = _route_diff(orig, dest)
    if diff is None:                      # pragma: no cover - defensive
        return (_JET_TIPS)
    if abs(diff) < 0.25:
        return (f"{orig.title()} and {dest.title()} share effectively the "
                f"same clock, sir - zero jet lag to engineer. Your only "
                f"enemy is the middle seat, sir.")
    direction = "eastward" if diff > 0 else "westward"
    nights = max(1, min(int(math.ceil(abs(diff))), MAX_SHIFT_NIGHTS))
    step_min = int(round(abs(diff) * 60 / nights))
    earlier = diff > 0
    word = "earlier" if earlier else "later"
    base = BASE_BEDTIME_MIN
    targets = [_fmt_bed(base + (-step_min if earlier else step_min) * k)
               for k in range(1, nights + 1)]
    light = ("bright light within an hour of waking and none after "
             "mid-afternoon" if earlier else
             "bright light in the evening and a dim morning")
    lines = [f"Jet-lag briefing, sir - {orig.title()} to {dest.title()} "
             f"is {_fmt_hours(diff)} {direction}, sir.",
             f"Plan: for the {nights} night(s) before departure move "
             f"bedtime ~{step_min} min {word} each night "
             f"(targets {', '.join(targets)}); seek {light}; slide meals "
             f"in the same direction."]
    if "arrive_hour" in ctx:
        lines.append(_arrival_advice(ctx["arrive_hour"], diff))
    else:
        lines.append("On arrival, adopt the local clock immediately - "
                     "no heroic naps, sir.")
    return "\n".join(lines)


# ==========================================================================
# Skill 9 - tv_roadtrip_cost
# ==========================================================================

_ROADTRIP_RE = re.compile(r"\broads?\s*-?\s*trips?\b|\broadtrip\b", re.I)
_DIST_MI_RE = re.compile(
    r"\b(\d{1,5}(?:\.\d+)?)\s*(?:miles?|mi\b|mi\.|milers?)\b", re.I)
_DIST_KM_RE = re.compile(
    r"\b(\d{1,5}(?:\.\d+)?)\s*(?:kilometers?|kilometres?|kms?\b|km\b)",
    re.I)
_MPG_RE = re.compile(
    r"\b(\d{1,2}(?:\.\d+)?)\s*(?:mpg|miles\s+per\s+gallon)\b", re.I)
_KML_RE = re.compile(
    r"\b(\d{1,2}(?:\.\d+)?)\s*(?:km\s*/\s*l|kmpl|kilometers?\s+per\s+"
    r"lit(?:re|er))\b", re.I)
_L100_RE = re.compile(
    r"\b(\d{1,2}(?:\.\d+)?)\s*(?:l\s*/\s*100\s*km|liters?\s+per\s+100\s*km"
    r"|litres?\s+per\s+100\s*km)\b", re.I)
_PRICE_GAL_RE = re.compile(
    r"\$\s*(\d{1,3}(?:\.\d{1,4})?)\s*(?:per\s+gallon|a\s+gallon|/?gal\b)"
    r"|(?:\$|at|gas|petrol)\s*\$?\s*(\d{1,3}(?:\.\d{1,3})?)\s*"
    r"(?:per\s+gallon\b|a\s+gallon\b)", re.I)
_PRICE_L_RE = re.compile(
    r"\$\s*(\d{1,3}(?:\.\d{1,4})?)\s*(?:per\s+lit(?:re|er)|/?l\b)", re.I)
_PAX_RE = re.compile(
    r"(\d{1,2})\s*(?:passengers?|people|persons?|of\s+us|splitting|split\b)",
    re.I)


def _d_roadtrip_cost(cmd: str):
    text = cmd or ""
    if not _ROADTRIP_RE.search(text):
        return None
    if not (_NUM_RE.search(text) or
            re.search(r"\b(?:cost|price|expense|budget|estimate)\b", text,
                      re.I)):
        return None                       # planning talk, not arithmetic
    dist_mi: float | None = None
    m = _DIST_MI_RE.search(text)
    if m:
        dist_mi = float(m.group(1))
    else:
        m = _DIST_KM_RE.search(text)
        if m:
            dist_mi = float(m.group(1)) * KM_TO_MI
    mpg: float | None = None
    m = _MPG_RE.search(text)
    if m:
        mpg = float(m.group(1))
    else:
        m = _KML_RE.search(text)
        if m:
            mpg = float(m.group(1)) * KML_TO_MPG
        else:
            m = _L100_RE.search(text)
            if m and float(m.group(1)) > 0:
                mpg = 235.215 / float(m.group(1))
    price: float | None = None
    per_litre = False
    m = _PRICE_GAL_RE.search(text)
    if m:
        price = float(m.group(1) or m.group(2))
    else:
        m = _PRICE_L_RE.search(text)
        if m:
            price = float(m.group(1))
            per_litre = True
    pax_m = _PAX_RE.search(text)
    return {"cmd": text,
            "dist_mi": dist_mi,
            "mpg": mpg,
            "price": price,
            "per_litre": per_litre,
            "pax": max(1, int(pax_m.group(1))) if pax_m else 1,
            "round_trip": bool(re.search(r"\bround\s*trips?\b|\bthere\s+and"
                                         r"\s+back\b", text, re.I))}


def _e_roadtrip_cost(app, ctx) -> str:
    dist_mi = ctx["dist_mi"]
    if not dist_mi or dist_mi <= 0:
        return ("I need a distance to work the numbers, sir - try "
                "'road trip cost 300 miles at 28 mpg with gas at 3.50 "
                "per gallon split 4 people', sir.")
    mpg = ctx["mpg"] or MPG_DEFAULT
    price = ctx["price"] if ctx["price"] is not None else PRICE_DEFAULT
    if ctx["per_litre"]:
        price *= 3.78541                  # US gallons
    total_mi = dist_mi * (2.0 if ctx["round_trip"] else 1.0)
    if mpg <= 0:                          # defensive: division guard
        return ("A car that drinks negative fuel defies physics, sir - "
                "give me a sensible mpg figure, sir.")
    gallons = total_mi / mpg
    cost = gallons * price
    parts = [f"Road-trip fuel estimate, sir: {total_mi:g} mile(s) at "
             f"{mpg:g} mpg burns about {gallons:.1f} gallon(s), roughly "
             f"{_fmt_money(cost)} at {_fmt_money(price)} per gallon."]
    defaults = []
    if ctx["mpg"] is None:
        defaults.append(f"{MPG_DEFAULT:g} mpg assumed")
    if ctx["price"] is None:
        defaults.append(f"{_fmt_money(PRICE_DEFAULT)} per gallon assumed")
    if defaults:
        parts.append("(" + ", ".join(defaults) + ")")
    if ctx["pax"] > 1:
        parts.append(f"Split across {ctx['pax']} people that is "
                     f"{_fmt_money(cost / ctx['pax'])} each, sir.")
    if ctx["round_trip"]:
        parts.append("Round trip priced in, sir.")
    return " ".join(parts)


# ==========================================================================
# Skill 10 - tv_trip_summary
# ==========================================================================

_TRIP_SUMMARY_RE = re.compile(
    r"\btrips?\s+(?:summary|status|overview|report|recap)\b"
    r"|\btravel\s+(?:summary|overview|status)\b"
    r"|\bhow\s+is\s+my\s+trip\b|\bhow\s+are\s+my\s+travel\s+plans\b", re.I)


def _d_trip_summary(cmd: str):
    return {"cmd": cmd} if _TRIP_SUMMARY_RE.search(cmd or "") else None


def _e_trip_summary(app, ctx) -> str:
    with _lock:
        state = _load()
        trip = state["trip"]
        pack_items = list(state["packing"]["items"])
        itin_entries = {str(k): list(v)
                        for k, v in state["itinerary"]["entries"].items()}
        itin_days = state["itinerary"].get("days") or 0
        itin_dest = state["itinerary"].get("destination") or ""
    if not trip.get("destination") and not pack_items and not itin_entries:
        return ("No trip is on the books yet, sir - start one with 'make "
                "a packing list for kyoto for 6 days' or 'plan a trip to "
                "rome', sir.")
    lines = ["Travel briefing, sir:"]
    dest = trip.get("destination")
    if dest:
        lines.append(f"- Destination: {dest}"
                     f"{' (' + str(trip['days']) + ' days)' if trip.get('days') else ''}")
    if pack_items:
        packed = sum(1 for i in pack_items if i["done"])
        pending = [i["name"] for i in pack_items if not i["done"]][:3]
        line = (f"- Packing: {packed}/{len(pack_items)} packed")
        if pending:
            line += f", still needed: {', '.join(pending)}"
        lines.append(line)
    else:
        lines.append("- Packing: no list yet, sir.")
    if itin_entries:
        acts = sum(len(v) for v in itin_entries.values())
        span = (f" across {itin_days} planned day(s)" if itin_days else "")
        who = f" for {itin_dest}" if itin_dest else ""
        lines.append(f"- Itinerary: {len(itin_entries)} day(s) sketched "
                     f"({acts} activity/ies){span}{who}.")
    else:
        lines.append("- Itinerary: blank so far, sir.")
    lines.append("Anything else before wheels-up, sir.")
    return "\n".join(lines)


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("tv_pack_new", _d_pack_new, _e_pack_new, False),
    ("tv_pack_add", _d_pack_add, _e_pack_add, False),
    ("tv_pack_done", _d_pack_done, _e_pack_done, False),
    ("tv_pack_show", _d_pack_show, _e_pack_show, False),
    ("tv_itin_new", _d_itin_new, _e_itin_new, False),
    ("tv_itin_add", _d_itin_add, _e_itin_add, False),
    ("tv_itin_show", _d_itin_show, _e_itin_show, False),
    ("tv_jetlag", _d_jetlag, _e_jetlag, False),
    ("tv_roadtrip_cost", _d_roadtrip_cost, _e_roadtrip_cost, False),
    ("tv_trip_summary", _d_trip_summary, _e_trip_summary, False),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all trip-planning skills with the given Brain."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("trip-planning skills registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something misfired in my travel-planning module "
                    f"({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())

"""JARVIS HOME INVENTORY & MAINTENANCE LOGGER SKILLS.

An asset register for the manor, sir - eleven fail-soft skills backed by
one atomically-persisted JSON file (``.jarvis_home.json``, temp +
``os.replace``, lock-guarded, lazy loaded, corrupt -> fresh):

    - hm_add        : "add asset macbook pro for 1999 in the office"
                      -> purchase price/date/room, optional warranty
                         ("with 2 year warranty"); upserts by name.
    - hm_value      : "total value of my home inventory" ->
                      portfolio count + dollar sum.
    - hm_room       : "list assets in the living room" -> room roster.
    - hm_find       : "search my inventory for headphones" -> fuzzy
                      difflib ranking over asset names.
    - hm_remove     : "remove desk lamp from the inventory".
    - hm_warranty   : "warranties expiring within 30 days" -> expiry
                      watch with a configurable day window (default 30,
                      boundary day included, expired items flagged).
    - hm_maint_add  : "add maintenance task air filter every 90 days"
                      -> recurring task with interval (days/weeks/
                         months/years accepted).
    - hm_maint_done : "mark maintenance done for air filter" ->
                      stamps last-done date (explicit date allowed).
    - hm_maint_due  : "which maintenance tasks are overdue" ->
                      overdue/due-today/due-soon board, worst first.
    - hm_car_service: "log car service oil change at 45,000 miles" ->
                      service log keyed by odometer; refuses readings
                      that would rewind the clock.
    - hm_car_next   : "when is my next car service" -> interval-based
                      prediction from miles-per-day rate between the
                      last two services (fallback assumption), capped
                      by a 180-day calendar limit.

Collisions: every detector demands domain vocabulary ("asset",
"inventory", "warranty", "maintenance", "car service" / "service log"),
so shopping lists, expenses, reminders and the fitness "maintenance
calories" skill are never shadowed; the maintenance detectors explicitly
refuse "calor*" commands and the car logger refuses the word
"maintenance". All date math flows through the injectable ``_today``
clock seam; this module never imports main and never touches network.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import threading
from datetime import date, timedelta
from typing import Optional

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("skills_home")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
HOME_FILE = os.path.join(PROJECT_DIR, ".jarvis_home.json")

WARRANTY_WINDOW_DAYS = 30     # hm_warranty default horizon
MAINT_DUE_SOON_DAYS = 7       # "due soon" band on the board
CAR_INTERVAL_MILES = 5000     # suggested service spacing in miles
CAR_INTERVAL_DAYS = 180       # hard calendar cap between services
DEFAULT_MILES_PER_DAY = 25.0  # assumed rate with only one data point

_NAME_CAP = 40

_lock = threading.RLock()
_state: Optional[dict] = None


# ==========================================================================
# Clock seam (tests freeze this)
# ==========================================================================

def _today() -> date:
    """Injectable clock: everything date-related asks this seam."""
    return date.today()


# ==========================================================================
# Storage plumbing (atomic, lazy, corrupt-proof)
# ==========================================================================

def _fresh_state() -> dict:
    return {"assets": [], "maint": {}, "car": {"history": []}}


def _load() -> dict:
    global _state
    if _state is not None:
        return _state
    try:
        with open(HOME_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except Exception as exc:
        log.debug("home store unreadable (%s); starting fresh", exc)
        data = {}
    if not isinstance(data.get("assets"), list):
        data["assets"] = []
    if not isinstance(data.get("maint"), dict):
        data["maint"] = {}
    car = data.get("car")
    if not isinstance(car, dict) or not isinstance(car.get("history"), list):
        data["car"] = {"history": []}
    _state = data
    return _state


def _save() -> None:
    tmp = HOME_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_state or _fresh_state(), fh)
        os.replace(tmp, HOME_FILE)
    except Exception as exc:
        log.warning("home store save failed: %s", exc)


def reset_for_tests(path: Optional[str] = None) -> None:
    """Test seam: drop cached state, optionally repoint the store file."""
    global _state, HOME_FILE
    _state = None
    if path:
        HOME_FILE = path


# ==========================================================================
# Core API (executors and tests share these; all mutations save)
# ==========================================================================

def _money(value: float) -> str:
    """Plain currency formatting - no locale tricks."""
    return f"${value:,.2f}"


def add_asset(name: str, price: float, room: str,
              bought: date, warranty_end: Optional[date] = None) -> dict:
    """Insert or update an asset record; upserts on case-folded name."""
    record = {
        "name": name[:_NAME_CAP],
        "price": round(float(price), 2),
        "room": (room or "unassigned").strip().lower()[:30],
        "bought": bought.isoformat(),
        "warranty_end": warranty_end.isoformat() if warranty_end else None,
    }
    with _lock:
        state = _load()
        replaced = False
        for idx, old in enumerate(state["assets"]):
            if old.get("name", "").casefold() == record["name"].casefold():
                state["assets"][idx] = record
                replaced = True
                break
        if not replaced:
            state["assets"].append(record)
        _save()
    return record | {"updated": replaced}


def remove_asset(name: str) -> Optional[dict]:
    """Exact (case-folded) removal first, then fuzzy; None on a miss."""
    with _lock:
        state = _load()
        wanted = name.strip().casefold()
        for idx, old in enumerate(state["assets"]):
            if old.get("name", "").strip().casefold() == wanted:
                del state["assets"][idx]
                _save()
                return old
        names = [a.get("name", "") for a in state["assets"]]
        near = difflib.get_close_matches(name.strip(), names, n=1, cutoff=0.5)
        if near:
            for idx, old in enumerate(state["assets"]):
                if old.get("name") == near[0]:
                    del state["assets"][idx]
                    _save()
                    return old
    return None


def find_assets(query: str, limit: int = 5) -> list[tuple[dict, float]]:
    """Fuzzy-ranked matches ``[(record, score)]``, best first."""
    q = query.strip().casefold()
    scored: list[tuple[dict, float]] = []
    with _lock:
        records = list(_load()["assets"])
    for rec in records:
        name = rec.get("name", "")
        score = difflib.SequenceMatcher(None, q, name.casefold()).ratio()
        if q and q in name.casefold():
            score = max(score, 0.95)
        if score >= 0.35:
            scored.append((rec, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:max(1, limit)]


def assets_in_room(room: str) -> list[dict]:
    """Assets whose room fuzzy-matches the request."""
    want = (room or "").strip().casefold()
    with _lock:
        records = list(_load()["assets"])
    if not want:
        return []
    exact = [r for r in records if r.get("room", "") == want]
    if exact:
        return exact
    rooms = sorted({r.get("room", "") for r in records})
    near = difflib.get_close_matches(want, rooms, n=1, cutoff=0.5)
    if near:
        return [r for r in records if r.get("room") == near[0]]
    return []


def known_rooms() -> list[str]:
    with _lock:
        return sorted({a.get("room", "") for a in _load()["assets"]
                       if a.get("room")})


def total_value() -> tuple[int, float]:
    with _lock:
        records = list(_load()["assets"])
    return len(records), sum(float(a.get("price", 0.0)) for a in records)


def warranties_due(window_days: int, today: Optional[date] = None
                   ) -> list[tuple[dict, date, int]]:
    """``[(record, end_date, days_left)]`` inside the window.

    ``days_left`` may be negative for already-expired cover; the window
    boundary day itself is included.
    """
    today = today or _today()
    out: list[tuple[dict, date, int]] = []
    with _lock:
        records = list(_load()["assets"])
    for rec in records:
        raw = rec.get("warranty_end")
        if not raw:
            continue
        try:
            end = date.fromisoformat(raw)
        except ValueError:
            continue
        left = (end - today).days
        if left <= max(0, window_days):
            out.append((rec, end, left))
    out.sort(key=lambda item: item[2])
    return out


def set_task(task: str, interval_days: int) -> None:
    """Register/re-register a recurring maintenance task."""
    key = task.strip().lower()[:40]
    if not key:
        return
    interval_days = max(1, int(interval_days))
    with _lock:
        state = _load()
        old = state["maint"].get(key) or {}
        state["maint"][key] = {
            "interval_days": interval_days,
            "last_done": old.get("last_done"),
        }
        _save()


def mark_done(task: str, done: Optional[date] = None) -> Optional[dict]:
    """Stamp a task's last-done date; None if the task is unknown."""
    key = task.strip().lower()[:40]
    done = done or _today()
    with _lock:
        state = _load()
        entry = state["maint"].get(key)
        if entry is None:
            return None
        entry["last_done"] = done.isoformat()
        _save()
        return {"task": key, "interval_days": int(entry["interval_days"]),
                "next_due": done + timedelta(days=int(entry["interval_days"]))}


def _task_status(entry: dict, today: date) -> tuple[int, date]:
    """``(days_until_due, next_due)`` for a maintained task entry."""
    interval = max(1, int(entry.get("interval_days", 1)))
    raw = entry.get("last_done")
    if raw:
        try:
            last = date.fromisoformat(raw)
        except ValueError:
            last = today - timedelta(days=interval)
    else:
        last = today - timedelta(days=interval)  # never done: due now
    nxt = last + timedelta(days=interval)
    return (nxt - today).days, nxt


def due_tasks(today: Optional[date] = None) -> list[dict]:
    """Tasks at or past their due date, worst (most overdue) first."""
    today = today or _today()
    out: list[dict] = []
    with _lock:
        items = list(_load()["maint"].items())
    for key, entry in items:
        left, nxt = _task_status(entry, today)
        if left <= MAINT_DUE_SOON_DAYS:
            out.append({
                "task": key,
                "interval_days": max(1, int(entry.get("interval_days", 1))),
                "last_done": entry.get("last_done"),
                "days_until_due": left,
                "next_due": nxt,
            })
    out.sort(key=lambda row: row["days_until_due"])
    return out


def scheduled_task_count() -> int:
    with _lock:
        return len(_load()["maint"])


def log_service(day: date, odometer: int, note: str) -> tuple[bool, str]:
    """Append a car service entry; refuses rewinding the odometer.

    Returns ``(accepted, reason)``.
    """
    odometer = int(odometer)
    with _lock:
        state = _load()
        history = state["car"]["history"]
        last_odo = int(history[-1]["odometer"]) if history else -1
        if history and odometer <= last_odo:
            return False, f"below the last recorded reading ({last_odo:,})"
        history.append({
            "date": day.isoformat(),
            "odometer": odometer,
            "note": (note or "").strip()[:80],
        })
        del history[:-100]
        _save()
    return True, ""


def service_history() -> list[dict]:
    with _lock:
        return list(_load()["car"]["history"])


def predict_next_service(today: Optional[date] = None
                         ) -> Optional[dict]:
    """Interval-based next-service prediction, or None with no history.

    Miles-per-day rate comes from the last two services when available,
    otherwise ``DEFAULT_MILES_PER_DAY``. The earlier of the mileage
    date and the ``CAR_INTERVAL_DAYS`` calendar cap wins.
    """
    today = today or _today()
    history = service_history()
    if not history:
        return None
    try:
        last_day = date.fromisoformat(history[-1]["date"])
        last_odo = int(history[-1]["odometer"])
    except (KeyError, ValueError):
        return None
    rate: Optional[float] = None
    if len(history) >= 2:
        try:
            prev_day = date.fromisoformat(history[-2]["date"])
            prev_odo = int(history[-2]["odometer"])
            span_days = (last_day - prev_day).days
            span_miles = last_odo - prev_odo
            if span_days > 0 and span_miles > 0:
                rate = span_miles / span_days
        except (KeyError, ValueError):
            rate = None
    assumed = rate is None
    if rate is None:
        rate = DEFAULT_MILES_PER_DAY
    by_miles = last_day + timedelta(
        days=max(1, int(CAR_INTERVAL_MILES / rate)))
    by_time = last_day + timedelta(days=CAR_INTERVAL_DAYS)
    return {
        "next": min(by_miles, by_time),
        "by_miles": by_miles,
        "by_time": by_time,
        "rate": rate,
        "assumed_rate": assumed,
        "last_date": last_day,
        "last_odometer": last_odo,
    }


# ==========================================================================
# Shared parsing helpers
# ==========================================================================

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}

_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_TEXT_RE = re.compile(
    r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_DATE_TEXT_REV_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")


def parse_date(text: str) -> Optional[date]:
    """Best-effort date hunt: ISO first, then 'Aug 24 2026'-style."""
    m = _DATE_ISO_RE.search(text or "")
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    for rx, order in ((_DATE_TEXT_RE, "mdy"), (_DATE_TEXT_REV_RE, "dmy")):
        m = rx.search(text or "")
        if not m:
            continue
        mon_txt, day_txt, year_txt = (
            (m.group(1), m.group(2), m.group(3)) if order == "mdy"
            else (m.group(2), m.group(1), m.group(3)))
        month = _MONTHS.get(mon_txt.lower())
        if not month:
            continue
        try:
            return date(int(year_txt), month, int(day_txt))
        except ValueError:
            continue
    return None


_UNIT_DAYS = {
    "day": 1, "days": 1, "daily": 1,
    "week": 7, "weeks": 7, "weekly": 7,
    "month": 30, "months": 30, "monthly": 30,
    "quarter": 91, "quarters": 91, "quarterly": 91,
    "year": 365, "years": 365, "annual": 365, "annually": 365,
    "yearly": 365,
}

_INTERVAL_RE = re.compile(r"\bevery\s+(?:(\d+)\s+)?([A-Za-z]+)\b")


def parse_interval(text: str) -> Optional[int]:
    """'every 90 days' -> 90, 'every 6 months' -> 180, 'every year' -> 365."""
    m = _INTERVAL_RE.search(text or "")
    if not m:
        return None
    count = int(m.group(1)) if m.group(1) else 1
    unit = m.group(2).lower()
    mult = _UNIT_DAYS.get(unit)
    if mult is None:
        return count if m.group(1) else None
    return count * mult


_MONEY_NUM = r"(\d[\d,]*(?:\.\d{1,2})?)"
_PRICE_DOLLAR_RE = re.compile(r"\$\s*" + _MONEY_NUM)
_PRICE_FOR_RE = re.compile(r"\bfor\s+(?:about\s+|around\s+)?"
                           r"(?:\$)?\s*" + _MONEY_NUM, re.I)


def parse_price(text: str) -> Optional[float]:
    """'$1999' preferred, then 'for 1999'; commas tolerated."""
    m = _PRICE_DOLLAR_RE.search(text or "") or _PRICE_FOR_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


_WARRANTY_AFTER_RE = re.compile(
    r"\bwarranty\s+(?:of\s+|for\s+)?(\d+)\s*"
    r"(days?|weeks?|months?|years?)\b", re.I)
_WARRANTY_BEFORE_RE = re.compile(
    r"(\d+)\s*[-\s]\s*(days?|weeks?|months?|years?)\s+warrant", re.I)
_SPAN_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7,
              "month": 30, "months": 30, "year": 365, "years": 365}


def parse_warranty_span(text: str) -> Optional[int]:
    """Warranty length in days ('2 year warranty', 'warranty 90 days')."""
    for rx in (_WARRANTY_AFTER_RE, _WARRANTY_BEFORE_RE):
        m = rx.search(text or "")
        if m:
            mult = _SPAN_DAYS.get(m.group(2).lower())
            if mult:
                try:
                    return int(m.group(1)) * mult
                except ValueError:
                    return None
    return None


_ROOM_RE = re.compile(
    r"\bin\s+(?:the\s+|my\s+)?([A-Za-z][A-Za-z ]{1,25}?)"
    r"(?=\s+(?:for|with|on|worth|bought|and)\b|[,.!?;:]|$)", re.I)

_NAME_STOP = re.compile(
    r"\s+(?:to\s+(?:the\s+|my\s+)?(?:home\s+)?(?:asset\s+)?inventory\b"
    r"|in\s|for\s|with\s|on\s|worth\s|bought\b|,|;|!)", re.I)


def _clean_text(raw: str) -> str:
    txt = re.sub(r"\s+", " ", (raw or "").strip().strip("\"'"))
    return txt.strip(" .!?,").strip()


def _clean_name(raw: str) -> str:
    txt = _clean_text(raw)
    txt = re.sub(r"^(?:the|my|a|an|new)\s+", "", txt, flags=re.I)
    txt = re.sub(r"\s+bought$", "", txt, flags=re.I)
    return txt[:_NAME_CAP]


# ==========================================================================
# Skill 1 - hm_add
# ==========================================================================

_ADD_ASSET_RE = re.compile(
    r"\b(?:add|log|record|register)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?"
    r"(?:home\s+)?asset\s+(?P<name>.+)$", re.I)
_ADD_INV_RE = re.compile(
    r"\b(?:add|log|record|register)\s+(?:my\s+|the\s+|a\s+|an\s+)?"
    r"(?P<name>.{2,60}?)\s+to\s+(?:the\s+)?(?:home\s+)?(?:asset\s+)?"
    r"inventory\b", re.I)


def _d_add(cmd: str):
    if re.search(r"\bshopping\b|\bgrocer", cmd, re.I):
        return None
    m = _ADD_ASSET_RE.match(cmd.strip()) or _ADD_INV_RE.search(cmd.strip())
    if not m:
        return None
    name = _clean_name(_NAME_STOP.split(m.group("name"), 1)[0])
    if len(name) < 2:
        return None
    return {"cmd": cmd, "name": name}


def _e_add(app, ctx) -> str:
    cmd = ctx["cmd"]
    price = parse_price(cmd)
    room_m = _ROOM_RE.search(cmd)
    room = _clean_text(room_m.group(1)) if room_m else ""
    bought = parse_date(cmd) or _today()
    span = parse_warranty_span(cmd)
    warranty_end = bought + timedelta(days=span) if span else None
    rec = add_asset(ctx["name"], price or 0.0, room or "unassigned",
                    bought, warranty_end)
    clause = f" (warranty until {rec['warranty_end']})" \
        if rec["warranty_end"] else ""
    verb = "Updated" if rec.get("updated") else "Logged"
    return (f"{verb} asset '{rec['name']}' in the {rec['room']} at "
            f"{_money(rec['price'])}{clause}, sir.")


# ==========================================================================
# Skill 2 - hm_value
# ==========================================================================

_VALUE_RE = re.compile(
    r"\b(?:total\s+|combined\s+|overall\s+)?(?:value|worth)\s+of\s+"
    r"(?:my|the|our)?\s*(?:home\s+)?(?:assets?|inventory|belongings|stuff)\b"
    r"|\bhow\s+much\s+(?:are|is)\s+(?:my|the|our)\s+(?:home\s+)?"
    r"(?:assets|inventory|belongings|stuff)\s+worth\b"
    r"|\b(?:assets?|inventory)\s+(?:portfolio\s+)?value\b"
    r"|\bwhat(?:'s| is)\s+my\s+(?:home\s+)?inventory\s+worth\b", re.I)


def _d_value(cmd: str):
    return {"cmd": cmd} if _VALUE_RE.search(cmd) else None


def _e_value(app, ctx) -> str:
    count, total = total_value()
    if count == 0:
        return ("The home asset register is empty, sir - say "
                "'add asset ... for ... in the ...' and I shall start "
                "tracking the estate.")
    return (f"The home inventory holds {count} assets valued at "
            f"{_money(total)}, sir.")


# ==========================================================================
# Skill 3 - hm_room
# ==========================================================================

_ROOM_LIST_RE = re.compile(
    r"\b(?:list|show|enumerate)\s+(?:the\s+|all\s+|my\s+)*"
    r"(?:assets?|items?|inventory)\s+(?:in|for|from)\s+(?:the\s+|my\s+)?"
    r"(?P<room>[A-Za-z][A-Za-z ]{1,25}?)\s*[?.!]*$", re.I)
_ROOM_WHATS_RE = re.compile(
    r"\bwhat(?:'s| is|\s+are)\s+(?:there\s+)?in\s+(?:the\s+|my\s+)?"
    r"(?P<room>[A-Za-z][A-Za-z ]{1,25}?)\s+(?:inventory|asset register)\b",
    re.I)


def _d_room(cmd: str):
    m = _ROOM_LIST_RE.search(cmd) or _ROOM_WHATS_RE.search(cmd)
    if not m:
        return None
    return {"cmd": cmd, "room": _clean_text(m.group("room"))}


def _e_room(app, ctx) -> str:
    room = ctx["room"]
    hits = assets_in_room(room)
    if hits:
        lines = [f"- {a['name']} - {_money(a['price'])}" for a in hits]
        return f"Assets in the {hits[0]['room']}, sir:\n" + "\n".join(lines)
    rooms = known_rooms()
    if rooms:
        near = difflib.get_close_matches(room.casefold(), rooms,
                                         n=2, cutoff=0.4)
        hint = f" Nearest rooms on file: {', '.join(near)}." if near \
            else f" Rooms on file: {', '.join(rooms)}."
        return (f"Nothing catalogued under '{room}', sir.{hint}")
    return (f"Nothing catalogued under '{room}' yet, sir - the whole "
            "register is empty.")


# ==========================================================================
# Skill 4 - hm_find
# ==========================================================================

_FIND_RE = re.compile(
    r"\b(?:find|search)\s+(?:the\s+|my\s+)?(?:home\s+)?"
    r"(?:assets?|inventory)\s+(?:for\s+)?(?P<q>.+?)[?.!]*$"
    r"|\b(?:find|search)\s+(?:for\s+)?(?P<q2>.{2,60}?)\s+"
    r"(?:in|across)\s+(?:my\s+|the\s+)?(?:home\s+)?(?:asset\s+)?"
    r"inventory\b[?.!]*", re.I)


def _d_find(cmd: str):
    m = _FIND_RE.search(cmd)
    if not m:
        return None
    q = m.group("q") or m.group("q2") or ""
    q = re.sub(r"\s+(?:in|across)\s+(?:my\s+|the\s+)?(?:home\s+)?"
               r"(?:asset\s+)?inventory\s*$", "", q, flags=re.I)
    q = _clean_text(q)
    if len(q) < 2:
        return None
    return {"cmd": cmd, "query": q}


def _e_find(app, ctx) -> str:
    q = ctx["query"]
    hits = find_assets(q)
    if hits:
        lines = [f"- {rec['name']} - {_money(rec['price'])} - "
                 f"{rec['room']}" for rec, _score in hits]
        return (f"Found {len(hits)} match(es) for '{q}', sir:\n"
                + "\n".join(lines))
    with _lock:
        all_names = [a.get("name", "") for a in _load()["assets"]]
    near = difflib.get_close_matches(q.casefold(),
                                     [n.casefold() for n in all_names],
                                     n=3, cutoff=0.4)
    if near:
        return (f"Nothing precise on '{q}', sir - closest entries: "
                + ", ".join(near) + ".")
    return f"Nothing resembling '{q}' in the inventory, sir."


# ==========================================================================
# Skill 5 - hm_remove
# ==========================================================================

_REMOVE_RE = re.compile(
    r"\b(?:remove|delete|drop|retire)\s+(?:the\s+|my\s+)?(?:asset\s+)?"
    r"(?P<name>.{2,60}?)\s+from\s+(?:the\s+|my\s+)?(?:home\s+)?"
    r"(?:asset\s+)?inventory\b[?.!]*", re.I)


def _d_remove(cmd: str):
    m = _REMOVE_RE.search(cmd)
    if not m:
        return None
    name = _clean_name(m.group("name"))
    if len(name) < 2:
        return None
    return {"cmd": cmd, "name": name}


def _e_remove(app, ctx) -> str:
    removed = remove_asset(ctx["name"])
    if removed:
        return (f"Removed '{removed['name']}' "
                f"({_money(removed['price'])}) from the register, sir.")
    return (f"'{ctx['name']}' is not on the inventory rolls, sir - "
            "'hm find' can locate the exact wording.")


# ==========================================================================
# Skill 6 - hm_warranty
# ==========================================================================

_WARRANTY_RE = re.compile(
    r"\bwarranties?\s+expiring\b"
    r"|\bwarrant(?:y|ies)\b.{0,40}\b(?:expir\w*|due|runs?\s*out|running"
    r"\s*out|soon|left|remaining|status|report|watch)\b"
    r"|\b(?:which|what|list|show)\s+(?:assets?\s+)?warrant(?:y|ies)\b",
    re.I)
_WINDOW_RE = re.compile(
    r"\b(?:within|in|next|following)\s+(?:the\s+)?(\d+)\s*days?\b", re.I)


def _d_warranty(cmd: str):
    m = _WARRANTY_RE.search(cmd)
    if not m:
        return None
    win = _WINDOW_RE.search(cmd)
    window = int(win.group(1)) if win else WARRANTY_WINDOW_DAYS
    return {"cmd": cmd, "window": max(1, min(window, 3650))}


def _e_warranty(app, ctx) -> str:
    window = ctx["window"]
    rows = warranties_due(window)
    if not rows:
        return f"No warranties expire within {window} days, sir."
    lines = []
    for rec, end, left in rows:
        rel = f"{left} days left" if left >= 0 \
            else f"EXPIRED {-left} days ago"
        lines.append(f"- {rec['name']}: ends {end.isoformat()} ({rel})")
    return f"Warranty watch ({window}-day horizon), sir:\n" + \
        "\n".join(lines)


# ==========================================================================
# Skill 7 - hm_maint_add
# ==========================================================================

_MAINT_ADD_TRIGGER_RE = re.compile(
    r"\b(?:add|create|register|schedule|set\s+up)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:recurring\s+|periodic\s+)?(?:home\s+)?maintenance\s+"
    r"(?:task|job|chore|schedule|reminder)\b", re.I)
_MAINT_TASK_RE = re.compile(
    r"maintenance\s+(?:task|job|chore|schedule|reminder)\s+"
    r"(?:called\s+|named\s+|for\s+)?(?P<task>.+?)\s*\bevery\b", re.I)


def _d_maint_add(cmd: str):
    if re.search(r"calor", cmd, re.I):
        return None
    if not _MAINT_ADD_TRIGGER_RE.search(cmd):
        return None
    if not re.search(r"\bevery\b", cmd, re.I):
        return None
    tm = _MAINT_TASK_RE.search(cmd)
    if not tm:
        return None
    interval = parse_interval(cmd)
    if interval is None:
        return None
    task = _clean_name(tm.group("task"))
    if len(task) < 2:
        return None
    return {"cmd": cmd, "task": task, "interval": interval}


def _e_maint_add(app, ctx) -> str:
    set_task(ctx["task"], ctx["interval"])
    return (f"Scheduled '{ctx['task']}' every {ctx['interval']} days, "
            "sir - I shall track its rhythm from here.")


# ==========================================================================
# Skill 8 - hm_maint_done
# ==========================================================================

_DONE_PATTERNS = (
    re.compile(r"\b(?:mark|log|record)\s+(?:the\s+|my\s+)?maintenance\s+"
               r"(?:as\s+)?done\s+(?:for|on|with)\s+"
               r"(?P<t>[A-Za-z0-9' \-]{2,40})", re.I),
    re.compile(r"\bmaintenance\s+(?:on\s+|for\s+)?"
               r"(?P<t>[A-Za-z0-9' \-]{2,40}?)\s+"
               r"(?:was\s+|is\s+|has\s+been\s+)?(?:done|completed|finished)"
               r"\b", re.I),
    re.compile(r"\b(?P<t>[A-Za-z0-9' \-]{2,40}?)\s+maintenance\s+"
               r"(?:is\s+|was\s+|has\s+been\s+)?(?:done|completed|finished)"
               r"\b", re.I),
)


def _d_maint_done(cmd: str):
    if re.search(r"calor", cmd, re.I):
        return None
    task = ""
    for rx in _DONE_PATTERNS:
        m = rx.search(cmd)
        if m:
            task = m.group("t")
            break
    task = _clean_name(re.sub(r"\s+on\s+\S.*$", "", task or "", flags=re.I))
    task = re.sub(r"\s+(?:task|job|chore)$", "", task, flags=re.I).strip()
    if len(task) < 2:
        return None
    return {"cmd": cmd, "task": task}


def _e_maint_done(app, ctx) -> str:
    done = parse_date(ctx["cmd"]) or _today()
    result = mark_done(ctx["task"], done)
    if result is None:
        return (f"I hold no maintenance schedule called "
                f"'{ctx['task']}', sir - register it first with "
                "'add maintenance task ... every ... days'.")
    return (f"'{result['task']}' marked done for "
            f"{done.isoformat()}, sir. Next due around "
            f"{result['next_due'].isoformat()}.")


# ==========================================================================
# Skill 9 - hm_maint_due
# ==========================================================================

_MAINT_DUE_RE = re.compile(
    r"\b(?:which|what)\s+(?:home\s+)?maintenance\s+(?:tasks?\s+|jobs?\s+"
    r"|chores?\s+)?(?:are\s+|is\s+)?(?:due|overdue)\b"
    r"|\boverdue\s+(?:home\s+)?maintenance\b"
    r"|\b(?:any|list|show)\s+(?:home\s+)?maintenance\s+(?:tasks?\s+)?"
    r"(?:due|overdue)\b"
    r"|\bmaintenance\s+due\s+(?:board|list|report)\b", re.I)


def _d_maint_due(cmd: str):
    if re.search(r"calor", cmd, re.I):
        return None
    return {"cmd": cmd} if _MAINT_DUE_RE.search(cmd) else None


def _e_maint_due(app, ctx) -> str:
    total = scheduled_task_count()
    if total == 0:
        return ("No maintenance schedule registered yet, sir - try "
                "'add maintenance task air filter every 90 days'.")
    rows = due_tasks()
    if not rows:
        return (f"All {total} scheduled maintenance tasks are within "
                "their intervals, sir. The estate hums along.")
    lines = []
    for row in rows:
        left = row["days_until_due"]
        if left < 0:
            state = f"OVERDUE by {-left} days"
        elif left == 0:
            state = "due today"
        else:
            state = f"due in {left} days"
        last = row["last_done"] or "never"
        lines.append(f"- {row['task']}: {state} "
                     f"(last done {last}, every "
                     f"{row['interval_days']} days)")
    return "Maintenance board, sir:\n" + "\n".join(lines)


# ==========================================================================
# Skill 10 - hm_car_service
# ==========================================================================

_CAR_SERVICE_RE = re.compile(
    r"\b(?:log|record|add)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:car|vehicle|auto)\s+service\b"
    r"|\b(?:cars?|vehicles?)\s+service\s+log\b"
    r"|\b(?:log|record)\s+(?:an?\s+)?(?:oil\s+change|tire\s+rotation|"
    r"tyre\s+rotation|brake\s+(?:service|pads)|transmission\s+service)\b"
    r"|\bservice\s+log\b", re.I)
_ODO_RE = re.compile(
    r"\b(?:odometer|odo|mileage|odometer reading)\D{0,12}(\d[\d,]{2,})"
    r"|\bat\s+(\d[\d,]{2,})\s*(?:miles|mi|km)?\b"
    r"|\b(\d[\d,]{2,})\s*(?:miles|mi|km)\b", re.I)
_CAR_NOTE_RE = re.compile(
    r"\b(?:car|vehicle|auto)\s+service\s*:?\s*(?P<note>.+?)"
    r"(?:\s+(?:at|with|on|odometer|mileage)\b|$)", re.I)


def _d_car_service(cmd: str):
    if re.search(r"\bmaintenance\b", cmd, re.I):
        return None
    m = _CAR_SERVICE_RE.search(cmd)
    if not m:
        return None
    om = _ODO_RE.search(cmd)
    if not om:
        return None
    raw = next(g for g in om.groups() if g)
    try:
        odometer = int(raw.replace(",", ""))
    except ValueError:
        return None
    nm = _CAR_NOTE_RE.search(cmd)
    note = _clean_text(nm.group("note")) if nm else ""
    return {"cmd": cmd, "odometer": odometer, "note": note}


def _e_car_service(app, ctx) -> str:
    day = parse_date(ctx["cmd"]) or _today()
    ok, reason = log_service(day, ctx["odometer"], ctx["note"])
    if not ok:
        return (f"That odometer reading ({ctx['odometer']:,}) is "
                f"{reason}, sir - even my finest clocks only run "
                "forward. Nothing logged.")
    label = ctx["note"] or "general service"
    return (f"Service logged, sir: {label} at "
            f"{ctx['odometer']:,} miles on {day.isoformat()}.")


# ==========================================================================
# Skill 11 - hm_car_next
# ==========================================================================

_CAR_NEXT_RE = re.compile(
    r"\bwhen(?:'s|\u2019s|\s+is)\s+(?:my|the)\s+next\s+"
    r"(?:car|vehicle|auto)\s+service\b"
    r"|\bnext\s+(?:car|vehicle|auto)\s+service\b"
    r"|\b(?:car|vehicle|auto)\s+service\s+(?:next|due|prediction|forecast)"
    r"\b"
    r"|\bis\s+my\s+(?:car|vehicle)\s+due\s+for\s+(?:a\s+)?service\b",
    re.I)


def _d_car_next(cmd: str):
    return {"cmd": cmd} if _CAR_NEXT_RE.search(cmd) else None


def _e_car_next(app, ctx) -> str:
    pred = predict_next_service()
    if pred is None:
        return ("I hold no car service history yet, sir - log one with "
                "'log car service oil change at 45,000 miles'.")
    if pred["assumed_rate"]:
        basis = (f"assumed {pred['rate']:.0f} mi/day; log two services "
                 "and I shall refine the rate")
    else:
        basis = f"{pred['rate']:.0f} mi/day from the last two services"
    if pred["next"] == pred["by_time"]:
        return (f"Next car service predicted {pred['next'].isoformat()}, "
                f"sir - the 180-day time cap bites first (mileage date "
                f"would be {pred['by_miles'].isoformat()}; {basis}).")
    return (f"Next car service predicted {pred['next'].isoformat()}, "
            f"sir - mileage limit first: 5,000 miles at {basis} "
            f"(time cap {pred['by_time'].isoformat()}).")


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("hm_add", _d_add, _e_add, True),
    ("hm_value", _d_value, _e_value, True),
    ("hm_room", _d_room, _e_room, True),
    ("hm_find", _d_find, _e_find, True),
    ("hm_remove", _d_remove, _e_remove, True),
    ("hm_warranty", _d_warranty, _e_warranty, True),
    ("hm_maint_add", _d_maint_add, _e_maint_add, True),
    ("hm_maint_done", _d_maint_done, _e_maint_done, True),
    ("hm_maint_due", _d_maint_due, _e_maint_due, True),
    ("hm_car_service", _d_car_service, _e_car_service, True),
    ("hm_car_next", _d_car_next, _e_car_next, True),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all home-inventory skills with the given Brain."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("home inventory & maintenance registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something misfired in my home-inventory module "
                    f"({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())

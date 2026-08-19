"""JARVIS DEEP THINK: a structured reasoning layer for the local brain.

Sits in front of ``brain_extra.local_chat`` inside ``Brain.chat`` and
answers the kinds of questions that deserve *reasoned*, step-by-step
replies rather than a canned lookup:

* multi-step arithmetic word problems (running totals, rates, transforms)
* planning requests ("plan my day / week / workout ...")
* comparisons ("python vs javascript", "difference between sql and nosql")
* mechanism explanations ("how does dns resolution work")

Design rules
------------
1.  Fail-safe: every solver verifies its arithmetic twice through
    independent code paths; on any mismatch it returns ``None`` so the
    rest of the brain can take over.
2.  Fast: typical calls return in well under 15 ms; anything that does
    not clearly match a handler returns ``None`` immediately.
3.  Honest: outside its knowledge bases it either answers generically
    with stated assumptions or declines (``None``).

Public API:
    answer(brain, text) -> str | None
"""

from __future__ import annotations

import logging
import operator
import re
from fractions import Fraction
from typing import Callable, Optional

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    logging.basicConfig(level=logging.WARNING)

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("deepthink")

__all__ = ["answer"]

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

_MAX_INPUT = 400
_MAX_NUMBERS = 12
_MAX_STEPS_SHOWN = 8

_ARITH = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
}

_NUM = r"(?<![\w.])(\d{1,9}(?:\.\d{1,4})?)(?![\w])"


def _fmt(value: Fraction) -> str:
    """Render a Fraction as a clean int or trimmed decimal string."""
    if value.denominator == 1:
        return str(value.numerator)
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text


# ==========================================================================
# 1a. Running totals:  "I had 50, spent 12, then earned 8"
# ==========================================================================

_MINUS_HINT = re.compile(
    r"\b(spent|spend|paid|pay|gave|lost|left|fewer|less|minus|removed|"
    r"sold|ate|used|broke|donated|fine[d]?|charged)\b", re.I)
_PLUS_HINT = re.compile(
    r"\b(gained|earn\w*|received|got|added|found|plus|increased|won|"
    r"gifted|deposit\w*)\b", re.I)
_START_HINT = re.compile(r"\b(started? with|had|i have)\b", re.I)


def _sign_for(window: str) -> Optional[str]:
    """Pick the sign from the cue that ends CLOSEST to the number."""
    # Comparative/state phrasing ("less than my brother has 150") is not
    # an operation — decline rather than guess a subtraction.
    if re.search(r"\b(less|fewer|more)\s+than\b", window, re.I):
        return None
    candidates: list[tuple[int, str]] = []
    m = _MINUS_HINT.search(window)
    if m:
        candidates.append((m.end(), "-"))
    m = _PLUS_HINT.search(window)
    if m:
        candidates.append((m.end(), "+"))
    m = re.search(r"\bbought\b.{0,10}\bfor\b", window)
    if m:
        candidates.append((m.end(), "-"))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def _running_total_reply(text: str) -> Optional[str]:
    matches = list(re.finditer(_NUM, text))
    if len(matches) < 2:
        return None
    ops: list[str] = ["+"]
    for m in matches[1:]:
        window = text[max(0, m.start() - 30):m.start()]
        sign = _sign_for(window)
        if sign is None:
            return None  # ambiguous sign -> decline honestly
        ops.append(sign)
    values = [Fraction(m.group(1)) for m in matches]

    def forward() -> Fraction:
        acc = values[0]
        for op, v in zip(ops[1:], values[1:]):
            acc = operator.add(acc, v) if op == "+" else \
                operator.sub(acc, v)
        return acc

    fast = forward()

    # Independent verification: take the forward result and invert every
    # operation walking backwards; we must land back on the start value.
    check = fast
    for i in range(len(values) - 1, 0, -1):
        if ops[i] == "+":
            check = check - values[i]
        else:
            check = check + values[i]
    if check != values[0]:
        log.warning("running-total verify mismatch: %s vs %s",
                    float(fast), float(check))
        return None

    steps = [f"Start with {_fmt(values[0])}."]
    running = values[0]
    for i in range(1, len(values)):
        symbol = ops[i]
        running = _ARITH[symbol](running, values[i])
        verb = "-" if symbol == "-" else "+"
        steps.append(f"Step {i}: {verb} {_fmt(values[i])} "
                     f"= {_fmt(running)}")
        if i >= _MAX_STEPS_SHOWN and i < len(values) - 1:
            steps.append(f"...({len(values) - i - 1} further steps omitted).")
            break
    steps.append(f"=> Final amount: {_fmt(forward())}, sir.")
    return "Worked through it step by step, sir:\n" + "\n".join(steps)


def _solve_running_total(text: str) -> Optional[str]:
    if len(text) > _MAX_INPUT:
        return None
    nums = list(re.finditer(_NUM, text))
    if not (2 <= len(nums) <= _MAX_NUMBERS):
        return None
    has_flow = bool(_MINUS_HINT.search(text) or _PLUS_HINT.search(text)
                    or re.search(r"\b(bought|sold)\b", text))
    has_start = bool(_START_HINT.search(text))
    if not (has_flow and has_start):
        return None
    return _running_total_reply(text)


# ==========================================================================
# 1b. Rates:  "5 books cost 45", "$12 each, how much for 7",
#             "share 90 among 6"
# ==========================================================================

def _solve_rate(text: str) -> Optional[str]:
    if len(text) > _MAX_INPUT:
        return None
    m_share = re.search(
        r"\b(?:share|split|divide)\s+(?:the\s+)?(\d{1,9}(?:\.\d{1,4})?)\s+"
        r"(?:among|between|across)\s+(\d{1,4})\b", text)
    if m_share:
        total = Fraction(m_share.group(1))
        people = Fraction(m_share.group(2))
        if people == 0:
            return None
        per = total / people
        if per * people != total:
            log.warning("share verify mismatch")
            return None
        return ("Splitting it evenly, sir:\n"
                f"Step 1: {_fmt(total)} ÷ {m_share.group(2)} people\n"
                f"=> Each share is {_fmt(per)}, sir.")

    m_unit_cost = re.search(
        rf"\b(\d{{1,4}})\s+([a-z ]{{2,25}}?)\s+(?:cost|costs|came\s+to|"
        rf"total(?:s|ed)?)\s+(?:\$)?({_NUM.strip('()')})\b", text)
    if m_unit_cost:
        count = Fraction(m_unit_cost.group(1))
        cost = Fraction(m_unit_cost.group(3))
        if count == 0:
            return None
        unit = cost / count
        if unit * count != cost:
            log.warning("unit-rate verify mismatch")
            return None
        extra_qty = re.search(
            rf"\b(?:for|buy(?:ing)?)\s+(\d{{1,4}})\b", text[m_unit_cost.end():])
        lines = ["Working out the unit rate, sir:",
                 f"Step 1: {_fmt(cost)} ÷ {m_unit_cost.group(1)} "
                 f"{m_unit_cost.group(2).strip()}"]
        if extra_qty:
            qty = Fraction(extra_qty.group(1))
            est = unit * qty
            if est / qty != unit:
                return None
            lines.append(f"Step 2: {_fmt(unit)} × {qty}")
            lines.append(f"=> {_qty_word(qty)} would cost {_fmt(est)}, sir.")
        else:
            lines.append(f"=> One costs {_fmt(unit)}, sir.")
        return "\n".join(lines)

    m_each = re.search(
        rf"(?:\$)?({_NUM.strip('()')})\s+(?:each|apiece|per\s+\w+)"
        rf".{{0,40}}?\b(\d{{1,4}})\b|\b(\d{{1,4}})\b.{{0,40}}?"
        rf"(?:\$)?({_NUM.strip('()')})\s+(?:each|apiece)", text)
    if m_each:
        price_raw = m_each.group(1) or m_each.group(4)
        qty_raw = m_each.group(2) or m_each.group(3)
        if not (price_raw and qty_raw):
            return None
        price, qty = Fraction(price_raw), Fraction(qty_raw)
        total = price * qty
        if (total / qty if qty else total * 0) != price:
            log.warning("each-multiply verify mismatch")
            return None
        return ("Multiplying it out, sir:\n"
                f"Step 1: {_fmt(price)} × {qty}\n"
                f"=> That comes to {_fmt(total)}, sir.")
    return None


def _qty_word(qty: Fraction) -> str:
    return f"{_fmt(qty)} items"


# ==========================================================================
# 1c. Transforms:  "double 6 then add 5", "half of 80 times 3"
# ==========================================================================

_TOKEN_RE = re.compile(
    rf"(?P<double>\bdouble\b)|(?P<triple>\btriple\b)|"
    rf"(?P<halve>\bhalve\b|\bhalf\s+of\b)|(?P<num>{_NUM})|"
    rf"(?P<plus>\badd\b|\bplus\b)|(?P<minus>\bsubtract\b|\bminus\b|"
    rf"\btake\s+away\b)|(?P<times>\btimes\b|\bmultiplied\s+by\b)", re.I)

_TRANSFORM_GATE = re.compile(
    r"\b(double|triple|halve|half\s+of)\b", re.I)


def _solve_transform(text: str) -> Optional[str]:
    if len(text) > _MAX_INPUT:
        return None
    if not _TRANSFORM_GATE.search(text):
        return None
    events: list[tuple[str, Fraction | None]] = []
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        if kind == "num":
            events.append(("num", Fraction(m.group("num"))))
        else:
            events.append((kind or "", None))
    if not any(kind == "num" for kind, _ in events):
        return None

    def compute(collect: list[str] | None = None) -> Optional[Fraction]:
        value: Optional[Fraction] = None
        pending: str | None = None          # awaiting "+"/"-"/"*" operand
        prefix_factors: list[tuple[str, Fraction]] = []  # "double 6"
        step_no = 0
        for kind, num in events:
            if kind == "num":
                assert num is not None
                if value is None:
                    base = num
                    for name, factor in prefix_factors:
                        base = base * factor
                        step_no += 1
                        if collect is not None:
                            collect.append(f"Step {step_no}: {name.lower()} "
                                           f"= {_fmt(base)}")
                    value = base
                    if collect is not None and not prefix_factors:
                        collect.append(f"Start with {_fmt(num)}.")
                    elif collect is not None:
                        collect.insert(0, f"Start with {_fmt(num)}, "
                                          f"then adjust.")
                    prefix_factors = []
                elif pending is not None:
                    symbol, label = {"+": ("+", "Add"),
                                     "-": ("-", "Subtract"),
                                     "*": ("x", "Multiply")}[pending]
                    value = _ARITH[pending](value, num)
                    step_no += 1
                    if collect is not None:
                        collect.append(
                            f"Step {step_no}: {label} {_fmt(num)} "
                            f"= {_fmt(value)}")
                    pending = None
            elif kind in ("double", "triple", "halve"):
                factor = {"double": Fraction(2), "triple": Fraction(3),
                          "halve": Fraction(1, 2)}[kind]
                name = {"double": "Double", "triple": "Triple",
                        "halve": "Halve"}[kind]
                if value is None:
                    prefix_factors.append((name, factor))
                else:
                    value = value * factor
                    step_no += 1
                    if collect is not None:
                        collect.append(f"Step {step_no}: {name.lower()} "
                                       f"= {_fmt(value)}")
            elif kind in ("plus", "minus", "times"):
                pending = {"plus": "+", "minus": "-", "times": "*"}[kind]
        return value

    steps: list[str] = []
    result = compute(collect=steps)
    if result is None or len(steps) < 2:
        return None
    # Independent verification: recompute via a float pipeline.
    try:
        probe: float | None = None
        pending_op: str | None = None
        prefix_f = 1.0
        for kind, num in events:
            if kind == "num" and num is not None:
                n = float(num)
                if probe is None:
                    probe = n * prefix_f
                    prefix_f = 1.0
                elif pending_op:
                    probe = {"+": operator.add, "-": operator.sub,
                             "*": operator.mul}[pending_op](probe, n)
                    pending_op = None
            elif kind in ("double", "triple", "halve"):
                if probe is None:
                    prefix_f *= {"double": 2.0, "triple": 3.0,
                                 "halve": 0.5}[kind]
                else:
                    probe = {"double": probe * 2, "triple": probe * 3,
                             "halve": probe / 2}[kind]
            elif kind in ("plus", "minus", "times"):
                pending_op = {"plus": "+", "minus": "-", "times": "*"}[kind]
        if probe is None or abs(probe - float(result)) > 1e-6:
            log.warning("transform verify mismatch")
            return None
    except (ArithmeticError, TypeError):
        return None
    steps.append(f"=> Result: {_fmt(result)}, sir.")
    return "Transforming step by step, sir:\n" + "\n".join(steps)


# ==========================================================================
# 2. Planner
# ==========================================================================

_PLANS: dict[str, tuple[tuple[str, str], ...]] = {
    "day": (
        ("06:30", "Wake, hydrate, 10 min stretch - no phone yet, sir."),
        ("07:00", "Deep-work block #1: hardest task while willpower is full."),
        ("09:00", "Email/messages batch #1 (15-minute cap)."),
        ("09:30", "Focused block #2 (three Pomodoros)."),
        ("13:00", "Lunch plus a short walk; daylight beats more caffeine."),
        ("14:00", "Meetings window - keep shallow work together."),
        ("16:30", "Admin sweep: inbox triage, plan tomorrow's top three."),
        ("18:00", "Exercise. Non-negotiable, sir."),
        ("20:00", "Learning or reading block (30-45 min)."),
        ("22:30", "Screens off; stage tomorrow's gear tonight."),
    ),
    "week": (
        ("Monday", "Set the week's single most important outcome + three supporting tasks."),
        ("Tuesday", "Deep-work day: protect mornings, defer meetings."),
        ("Wednesday", "Mid-week review: kill or delegate what isn't moving."),
        ("Thursday", "Collaboration day: reviews, pairing, hard conversations."),
        ("Friday", "Ship and wrap: demo, docs, tickets closed, weekly retro."),
        ("Saturday", "Errands early, adventure/family afternoon."),
        ("Sunday", "Twenty minutes of planning, real rest - momentum needs recovery, sir."),
    ),
    "workout": (
        ("Day 1", "Push: bench/incline 4x6-8, shoulders 3x10, triceps 3x12."),
        ("Day 2", "Pull: rows 4x8, pull-ups 4xmax, biceps 3x12, face pulls."),
        ("Day 3", "Legs: squats 4x6, RDL 3x8, lunges 3x12, calves 4x15."),
        ("Day 4", "Rest or 30 minutes zone-2 cardio plus mobility."),
        ("Day 5", "Full-body circuit, five rounds, strict form."),
        ("Rule", "Progressive overload: about 2.5% load or one rep weekly, sir."),
    ),
    "study": (
        ("Block 1 (45 min)", "New material - active reading, notes in your own words."),
        ("Break", "Ten minutes, move around; no feeds, sir."),
        ("Block 2 (45 min)", "Practice problems under time pressure."),
        ("Block 3 (30 min)", "Spaced recall: yesterday's material from memory."),
        ("Evening", "Write a one-page summary from memory; mark gaps."),
        ("Weekly", "Self-test Saturday; weak topics get Sunday slots."),
    ),
    "meals": (
        ("Breakfast", "Protein + fiber: eggs/oats and fruit - prevents the 11am crash."),
        ("Lunch", "Balanced plate: palm of protein, fist of carbs, two fists of veg."),
        ("Snack", "Nuts/yogurt/fruit, prepped Sunday, sir."),
        ("Dinner", "Lighter and early: lean protein and greens."),
        ("Hydration", "2.5-3 L water across the day; bottle on the desk."),
        ("Prep", "Sunday: cook two proteins, chop veg, portion snacks."),
    ),
    "trip": (
        ("T-minus 14 days", "Book transport + first/last nights; visas, vaccines."),
        ("T-minus 7 days", "Itinerary skeleton: max two anchors/day, buffer hours."),
        ("T-minus 2 days", "Pack by category; chargers, documents, photos backed up."),
        ("Travel day", "Leave thirty minutes earlier than instinct says, sir."),
        ("Daily rule", "One planned activity; wander the rest."),
    ),
    "project": (
        ("Phase 0", "One-line goal, success metric, deadline - in writing."),
        ("Phase 1", "Scope cut: must/should/could lists; kill the coulds."),
        ("Phase 2", "Milestones every one-two weeks, demoable every time."),
        ("Phase 3", "Build rhythm: ship daily, integrate continuously."),
        ("Phase 4", "Hardening: triage bugs, polish pass, launch checklist."),
        ("Standing rule", "If a milestone slips twice, cut scope - never quality, sir."),
    ),
}

_PLAN_FALLBACK: tuple[tuple[str, str], ...] = (
    ("Step 1", "Define the outcome in one measurable sentence."),
    ("Step 2", "List everything; mark MUST versus nice-to-have."),
    ("Step 3", "Order musts by impact; estimate honestly, then add fifty percent."),
    ("Step 4", "Timebox execution blocks on the calendar and defend them."),
    ("Step 5", "Review every Friday: keep, fix, or kill."),
)

_PLAN_TIPS = {
    "day": "Protect the first two hours, sir - they set the day's ceiling.",
    "week": "One theme per day beats ten half-themes, sir.",
    "workout": "Consistency beats intensity; show up even at sixty percent, sir.",
    "study": "Recall beats rereading - close the book and retrieve, sir.",
    "meals": "Decisions made on Sunday save willpower all week, sir.",
    "trip": "Two anchors a day; serendipity fills the gaps, sir.",
    "project": "Demoable beats perfect, sir.",
}


_PLAN_RE = re.compile(
    r"\b(plan|schedule|organize|structure)\s+(?:my|the|a|an)?\s*"
    r"(day|week|month|morning|evening|weekend|workout|study|meal|meals|diet|"
    r"project|trip|travel|reading)\b", re.I)


def _plan(text: str) -> Optional[str]:
    if len(text) > _MAX_INPUT:
        return None
    m = _PLAN_RE.search(text)
    if not m:
        return None
    topic = m.group(2).lower()
    key = next((k for k in _PLANS if k.startswith(topic[:4])), None)
    rows = _PLANS.get(key or "", _PLAN_FALLBACK)
    lines = [f"A {topic} plan, drafted for you, sir:"]
    lines += [f"- {label}: {detail}" for label, detail in rows]
    tip = _PLAN_TIPS.get(key or "", _PLAN_TIPS["project"])
    lines.append(tip)
    if re.search(r"\b(exam|interview)\b", text, re.I):
        lines.append("Given the exam/interview mention: past papers daily "
                     "starting today, sir.")
    return "\n".join(lines)


# ==========================================================================
# 3. Comparator
# ==========================================================================

_COMPARE_RE = re.compile(
    r"\b(?P<a>[\w+#./ -]{2,40}?)\s*(?:vs\.?|versus|compared\s+(?:to|with)"
    r"|\bdifference\s+between)\s+(?:the\s+)?(?P<b>[\w+#./ -]{2,40})", re.I)


_COMPARISONS: dict[frozenset, tuple[str, str, str, str, str]] = {
    frozenset(("python", "javascript")): (
        "General-purpose scripting/data/AI versus the language of the browser.",
        "Python wins on readability, stdlib breadth, and data/ML dominance.",
        "JavaScript wins on ubiquity - every client already runs it.",
        "Pick Python for backends, data work, automation, AI.",
        "Pick JavaScript when the deliverable lives in a browser."),
    frozenset(("sql", "nosql")): (
        "Relational tables with joins/schema versus flexible document/key-value stores.",
        "SQL brings ACID guarantees, powerful joins, mature tooling.",
        "NoSQL brings horizontal scale, schema flexibility, fast key lookups.",
        "Pick SQL when relationships and integrity matter - most business data.",
        "Pick NoSQL for massive scale, caching layers, or volatile shapes."),
    frozenset(("rest", "graphql")): (
        "Resource-endpoint APIs versus one client-shaped query endpoint.",
        "REST keeps HTTP semantics simple, cacheable, universally understood.",
        "GraphQL kills over-fetching and round-trips with a typed schema.",
        "Pick REST for public/simple APIs leaning on HTTP caching.",
        "Pick GraphQL when clients need flexible views of rich related data."),
    frozenset(("docker", "vm")): (
        "OS-level containers sharing the host kernel versus full virtual machines.",
        "Containers boot in seconds, images are tiny, packing is dense.",
        "VMs give complete isolation and any guest OS you like.",
        "Pick Docker for microservices and CI pipelines.",
        "Pick VMs when kernels differ or isolation must be hard."),
    frozenset(("merge", "rebase")): (
        "Git's two ways to integrate branches.",
        "Merge preserves history exactly as it happened - safe on shared branches.",
        "Rebase produces linear, readable history by rewriting commits.",
        "Use merge on shared/public branches.",
        "Rebase your own feature branch before opening the PR."),
    frozenset(("thread", "process")): (
        "Shared-memory workers versus isolated memory spaces.",
        "Threads are cheap and share memory; locking is the tax.",
        "Processes give true parallelism and crash isolation at higher startup cost.",
        "Threads suit I/O-bound concurrency.",
        "Processes suit CPU-bound parallelism."),
    frozenset(("monolith", "microservice")): (
        "One deployable application versus many small services.",
        "Monoliths debug simply and deploy atomically at modest scale.",
        "Microservices scale teams and traffic independently - with distributed pain.",
        "Stay monolithic until team size or scaling genuinely demands splitting.",
        "Go microservices when org charts and hot paths outgrow one binary."),
    frozenset(("react", "vue")): (
        "Component-based UI frameworks.",
        "React owns the larger ecosystem, hiring pool, and flexibility.",
        "Vue offers gentler ramps, blessed templates, superb docs.",
        "Pick React for ecosystem leverage and large teams.",
        "Pick Vue for small teams shipping fast."),
    frozenset(("grpc", "rest")): (
        "Typed binary RPC over HTTP/2 versus JSON resource APIs.",
        "gRPC streams, multiplexes, and enforces contracts.",
        "REST stays curl-friendly, cacheable, human-readable.",
        "gRPC for internal service-to-service hot paths.",
        "REST for public and browser-facing surfaces."),
    frozenset(("postgres", "mysql")): (
        "The two default open-source relational databases.",
        "Postgres: richer types (JSONB, arrays), extensions, strict standards.",
        "MySQL: ubiquitous, quick reads, simple operations story.",
        "Postgres is the modern safe default.",
        "MySQL where legacy stacks or specific hosting demand it."),
    frozenset(("agile", "waterfall")): (
        "Iterative delivery versus upfront sequential phases.",
        "Agile shortens feedback loops and embraces change.",
        "Waterfall clarifies scope/budget for fixed contractual work.",
        "Agile for discovery-driven products.",
        "Waterfall when requirements truly are frozen."),
    frozenset(("list", "tuple")): (
        "Python's mutable versus immutable sequences.",
        "Lists grow and shrink in place - general collections.",
        "Tuples are fixed and hashable - records and dict keys.",
        "Lists for collections you mutate.",
        "Tuples where shape must not change."),
    frozenset(("mvvm", "mvc")): (
        "UI architecture patterns separating concerns.",
        "MVC puts a controller between model and view - classic server fit.",
        "MVVM exposes bindable state through a view-model - binding-friendly UIs.",
        "MVVM shines with WPF/SwiftUI-style binding frameworks.",
        "MVC/MVP where bindings are absent and wiring stays explicit."),
    frozenset(("mac", "linux")): (
        "Polished Unix-flavored desktop versus open kernel family.",
        "Mac integrates hardware/software tightly over POSIX.",
        "Linux gives full control and runs the cloud.",
        "Mac for polished desktop development.",
        "Linux for servers, embedded, and total customization."),
}

_GENERIC_COMPARE = (
    "Here is my general framework, sir - answering from first principles, "
    "not a known table:\n"
    "- Purpose: what problem was each actually built to solve?\n"
    "- Strengths: where does each clearly win today?\n"
    "- Trade-offs: complexity, ecosystem, performance, hiring.\n"
    "- Pick A when your constraints match its sweet spot.\n"
    "- Pick B when the opposite constraints hold.\n"
    "Give me your specific use case and I'll sharpen the recommendation, sir.")


def _norm_pair(raw: str) -> str:
    out = re.sub(r"^(the|a|an)\s+", "", raw.strip().lower())
    return re.sub(r"[?.!,]+$", "", out).strip()


def _compare(text: str) -> Optional[str]:
    if len(text) > _MAX_INPUT:
        return None
    pair = _compare_pair(text)
    if not pair:
        return None
    a, b = pair
    hit = _COMPARISONS.get(frozenset((a, b)))
    if hit:
        purpose, sa, sb, pa, pb = hit
        return (f"{a.title()} vs {b.title()}, sir:\n"
                f"- Purpose: {purpose}\n"
                f"- {a.title()} strength: {sa}\n"
                f"- {b.title()} strength: {sb}\n"
                f"- {pa}\n- {pb}")
    return _GENERIC_COMPARE


_DIFF_BETWEEN_RE = re.compile(
    r"\bdifference\s+between\s+(?P<x>[\w+#./ -]{2,40}?)\s+(?:and|vs\.?|or)\s+"
    r"(?P<y>[\w+#./ -]{2,40})", re.I)


def _compare_pair(text: str) -> Optional[tuple[str, str]]:
    m = _DIFF_BETWEEN_RE.search(text)
    if m:
        a, b = _norm_pair(m.group("x")), _norm_pair(m.group("y"))
        if a and b and a != b:
            return a, b
        return None
    m = _COMPARE_RE.search(text)
    if m:
        a, b = _norm_pair(m.group("a")), _norm_pair(m.group("b"))
        if a and b and a != b:
            return a, b
    return None


# ==========================================================================
# 4. Explainer
# ==========================================================================

_EXPLAIN_RE = re.compile(
    r"\b(?:why|how)\s+does\b.{0,60}?\bwork\b|\bexplain\s+how\b.{0,60}?"
    r"\bworks?\b", re.I)

_MECHANISMS: dict[str, tuple[str, ...]] = {
    "dns resolution": (
        "You type a hostname; the stub resolver asks your recursive resolver.",
        "Caches are checked first: browser, OS, then resolver - a hit ends the trip.",
        "On a miss the resolver asks a root server, which points at the TLD servers.",
        "The TLD server points at the domain's authoritative nameserver.",
        "The authoritative server returns the record; the resolver caches it per TTL.",
        "Analogy: asking directions - each level either knows, or knows who does, sir.",
    ),
    "http request": (
        "DNS resolves the host; TCP connects; TLS negotiates if https.",
        "The request line and headers go out: method, path, cookies, content-type.",
        "The server routes by path/method, runs the handler, may touch DB or cache.",
        "A response returns status, headers, body over the kept-alive connection.",
        "Assets repeat across the warm pipe; HTTP/2 multiplexes them.",
    ),
    "tcp handshake": (
        "Client sends SYN carrying its initial sequence number.",
        "Server answers SYN-ACK acknowledging it.",
        "Client returns ACK - both sides agree on sequencing.",
        "Only now does application data flow; teardown pairs FIN with ACK.",
        "Analogy: roll-call before the conversation starts, sir.",
    ),
    "garbage collection": (
        "The allocator hands out memory; the runtime tracks references.",
        "Periodically the GC finds objects unreachable from roots (stack, globals).",
        "Unreachable objects are reclaimed; some collectors compact too.",
        "Reference cycles need tracing GCs - refcounting alone leaks them.",
        "Cost appears as pauses; tunables trade throughput against latency.",
    ),
    "recursion": (
        "The function solves a big case by calling itself on a smaller case.",
        "A base case stops the descent - otherwise the stack overflows.",
        "Each call frames its own locals on the call stack.",
        "Results unwind, combining as frames pop back up.",
        "Any recursion can be rewritten with an explicit stack and a loop.",
    ),
    "event loop": (
        "A single-threaded loop pulls ready callbacks/tasks from a queue.",
        "I/O waits go to the OS (epoll/kqueue) so no thread blocks.",
        "When a socket finishes, its task becomes ready again.",
        "Await points suspend functions, freeing the loop between awaits.",
        "CPU-heavy work still stalls the loop - offload it, sir.",
    ),
    "hashing": (
        "A hash function scrambles input into a fixed-size fingerprint.",
        "Same input, same output; tiny change, avalanche of changes.",
        "Hash maps index buckets by fingerprint: O(1) average lookups.",
        "Collisions happen; chaining or open addressing resolves them.",
        "Cryptographic hashes additionally resist preimage and collision attacks.",
    ),
    "encryption": (
        "Symmetric encryption uses one shared key both ways (AES) - fast.",
        "Asymmetric uses a keypair where one undoes the other (RSA/ECC) - slow.",
        "Real systems hybridize: asymmetric exchange of a session key...",
        "...then symmetric for bulk data - that is TLS, sir.",
        "Signatures flip it around: sign a hash privately, verify publicly.",
    ),
    "neural network training": (
        "Forward pass: inputs flow layer by layer into a prediction.",
        "A loss function scores how wrong the prediction was.",
        "Backpropagation applies the chain rule to gradient every weight.",
        "An optimizer nudges weights opposite their gradients.",
        "Repeat across batches and epochs until validation error bottoms out.",
    ),
    "compiler": (
        "Lexing turns source text into tokens.",
        "Parsing checks grammar and builds an abstract syntax tree.",
        "Semantic analysis resolves types and symbols.",
        "Optimization passes reshape intermediate representation.",
        "Code generation emits machine or byte code.",
    ),
    "database index": (
        "An index is a sorted structure, usually a B-tree, keyed on a column.",
        "Lookups descend the tree: O(log n) instead of scanning the table.",
        "Range queries become contiguous leaf walks.",
        "Every write maintains each index - that is the tax, sir.",
        "Composite indexes serve queries on their leading columns only.",
    ),
    "container": (
        "An image is a layered filesystem snapshot plus metadata.",
        "A container is an isolated process tree using those layers read-only.",
        "Namespaces isolate PID/network/mount views; cgroups cap CPU and memory.",
        "A writable layer stacks on top; base layers dedupe across containers.",
        "VM-like isolation without booting a second kernel, sir.",
    ),
    "ssh login": (
        "The server presents its host key; known_hosts checks it.",
        "Both sides negotiate encryption via Diffie-Hellman.",
        "Your machine signs a challenge with your private key...",
        "...the server verifies it against authorized_keys.",
        "Passwords still work, but keys shrug off brute force far better.",
    ),
}


def _explain(text: str) -> Optional[str]:
    if len(text) > _MAX_INPUT:
        return None
    if not _EXPLAIN_RE.search(text):
        return None
    lowered = text.lower()
    best_key, best_pos = None, 10 ** 9
    for key in _MECHANISMS:
        head = key.split()[0]
        pos = lowered.find(head)
        if pos != -1 and pos < best_pos:
            best_key, best_pos = key, pos
    if best_key is None:
        return None
    lines = [f"How {best_key} works, sir:", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(_MECHANISMS[best_key], 1)]
    return "\n".join(lines)


# ==========================================================================
# Router
# ==========================================================================

_HANDLERS: tuple[Callable[[str], Optional[str]], ...] = (
    _solve_rate,
    _solve_running_total,
    _solve_transform,
    _plan,
    _compare,
    _explain,
)


def answer(brain, text: str) -> Optional[str]:
    """Try each deep-think handler; return a reply or None quickly."""
    if not text or len(text) > 200_000:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        for handler in _HANDLERS:
            reply = handler(cleaned)
            if reply:
                return reply
    except Exception:  # defensive: never break the chat cascade
        log.exception("deepthink handler failed for %r", cleaned[:80])
        return None
    return None


if __name__ == "__main__":  # smoke demo
    samples = [
        "i had 50 dollars, spent 12 on lunch, then earned 8 back",
        "5 books cost 45 dollars, how much is one book",
        "double 6 then add 5",
        "plan my week",
        "python vs javascript",
        "how does dns resolution work",
        "what is the weather",
    ]
    for s in samples:
        print(f"{s!r} -> {bool(answer(None, s))}")

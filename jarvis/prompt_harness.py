"""prompt_harness.py -- harness-engineering layer for the JARVIS assistant.

Sits between the voice front-end and the Groq chat call. Responsibilities:

- build_messages(): assemble the chat payload (persona system prompt,
  compact context block, trimmed history, intent contract).
- classify_intent(): cheap anchored-regex intent routing.
- clean_reply(): post-process model output (strip fences, butler chatter).
- wrap_code_prompt() / wrap_website_prompt(): structured prompt builders
  for the code-generation and AI Studio website/app flows.

Dependency-free (stdlib only). Every public function is total: it must
never raise, regardless of the garbage it is handed. main.py already
guards the call with try/except and a legacy fallback, but the contract
here is stricter: return something useful or nothing at all.
"""

import datetime
import re

__all__ = [
    "PROMPT_CONTRACTS",
    "build_messages",
    "classify_intent",
    "clean_reply",
    "wrap_code_prompt",
    "wrap_website_prompt",
    "selftest",
]

# ---------------------------------------------------------------------------
# Persona and contracts
# ---------------------------------------------------------------------------

_PERSONA = (
    'You are JARVIS, the AI assistant from Iron Man: a formal, warm and highly '
    'capable digital butler. Address the user as "sir". Be concise: at most '
    "three sentences unless the user asked for code or a longer answer. "
    "No emoji. Confident, plain, spoken-word-friendly prose."
)


def _today() -> str:
    """Human-readable date, freshly computed so long sessions stay accurate."""
    try:
        return datetime.date.today().strftime("%A, %B %d, %Y")
    except Exception:
        return ""

_UNCERTAINTY = "If you are not sure, say so plainly rather than guessing."

PROMPT_CONTRACTS = {
    "code": (
        "Output ONLY the requested code with no prose, no markdown fences, "
        "no commentary."
    ),
    "explain": (
        "Explain clearly in plain prose; define jargon on first use; no filler."
    ),
    "summarize": (
        "Summarize faithfully in a few tight sentences; keep key facts, names "
        "and numbers; add nothing new."
    ),
    "translate": (
        "Output ONLY the translation in the requested language, preserving "
        "tone and formatting; no notes."
    ),
    "rewrite": (
        "Return ONLY the rewritten text, preserving meaning and voice; no "
        "commentary before or after."
    ),
    "question": (
        "Answer the question directly in the first sentence, then at most one "
        "line of supporting detail."
    ),
    "command": (
        "Acknowledge the action in one short sentence and state the result or "
        "next step; do not restate the request verbatim."
    ),
    "smalltalk": (
        "Reply warmly in one or two short sentences; no task output."
    ),
}

_HISTORY_MAX_TURNS = 8
_HISTORY_MAX_CHARS = 3000

_CONTEXT_LABELS = (
    ("frontmost_app", "Frontmost app"),
    ("recent_commands", "Recent commands"),
    ("ai_mode", "AI mode"),
    ("time", "Time"),
)

# ---------------------------------------------------------------------------
# Intent classification (anchored regex heuristics, first match wins)
# ---------------------------------------------------------------------------

_INTENT_RULES = (
    ("code", re.compile(
        r"^\s*(?:write|create|generate|make|build|implement|refactor|debug|fix|"
        r"optimize|convert)\b.*\b(code|script|program|function|class|method|"
        r"module|regex|snippet|algorithm|query|sql|api|app|game|bot|website)\b",
        re.I)),
    ("code", re.compile(r"^\s*(?:code|script)\s+(?:for|to)\b", re.I)),
    ("code", re.compile(
        r"\b(?:function|class|method)\s+(?:that|which|to)\b", re.I)),
    ("translate", re.compile(
        r"^\s*(?:translate|translating|translation of|how do (?:you|i) say)\b",
        re.I)),
    ("summarize", re.compile(
        r"^\s*(?:summar(?:ize|ise)|tl;?dr|give me (?:a|the) summary|"
        r"shorten this)\b", re.I)),
    ("summarize", re.compile(
        r"\b(?:summary|summarize|summarise)\s+of\b", re.I)),
    ("rewrite", re.compile(
        r"^\s*(?:rewrite|rephrase|reword|paraphrase|proofread|polish this)\b",
        re.I)),
    ("command", re.compile(
        r"^\s*(?:open|launch|start|run|play|pause|resume|stop|close|quit|kill|"
        r"terminate|set|turn (?:up|down|on|off)|mute|unmute|increase|decrease|"
        r"type|press|click|search(?: for)?|google|browse|navigate|go to|"
        r"restart|reboot|shut ?down|sleep|lock|screenshot|take a (?:screenshot|"
        r"photo)|remind me|call|message|email|text)\b", re.I)),
    ("smalltalk", re.compile(
        r"^\s*(?:hi+|hello+|hey+|yo|greetings|good (?:morning|afternoon|"
        r"evening|day)|thanks|thank you|thx|bye+|goodbye|see (?:you|ya)|"
        r"what'?s up|who are you|how are you)\b[\s!.?]*$", re.I)),
    ("explain", re.compile(
        r"^\s*(?:explain|describe|tell me about|what is|what are|what's|whats|"
        r"why is|why do(?:es)?|how do(?:es)?|how can|difference between|"
        r"compare|define)\b", re.I)),
    ("question", re.compile(
        r"^\s*(?:who|whom|whose|what|when|where|which|why|how|is|are|was|were|"
        r"do|does|did|can|could|should|will|would|may|might|shall)\b", re.I)),
)


def classify_intent(text):
    """Map free text to one intent keyword. Never raises; defaults to question."""
    try:
        s = "" if text is None else str(text)
        if not s.strip():
            return "question"
        for intent, rule in _INTENT_RULES:
            if rule.search(s):
                return intent
        return "question"
    except Exception:
        return "question"


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------

def _render_context(context):
    """Render only the context keys that are actually present and non-empty."""
    if not isinstance(context, dict):
        return ""
    lines = []
    for key, label in _CONTEXT_LABELS:
        if key not in context:
            continue
        val = context[key]
        if key == "recent_commands" and isinstance(val, (list, tuple, set)):
            items = [str(v).strip() for v in val if str(v).strip()][:5]
            val = "; ".join(items)
        else:
            val = str(val)
        val = val.strip()
        if not val:
            continue
        lines.append("- %s: %s" % (label, val[:200]))
    if not lines:
        return ""
    return "Context (may be stale; ignore what is irrelevant):\n" + "\n".join(lines)


def _trim_history(history):
    """Keep the last 8 valid turns within ~3000 chars, oldest dropped first."""
    turns = []
    for item in history or []:
        try:
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", ""))
        except AttributeError:
            continue
        except Exception:
            continue
        if role not in ("user", "assistant") or not content.strip():
            continue
        turns.append({"role": role, "content": content})
    turns = turns[-_HISTORY_MAX_TURNS:]
    while turns and sum(len(t["content"]) for t in turns) > _HISTORY_MAX_CHARS:
        turns.pop(0)
    while len(turns) > 1 and turns[0]["role"] == "assistant":
        turns.pop(0)
    return turns


def build_messages(user_text, history=None, context=None, intent=None,
                   persona_extra=None):
    """Assemble the chat payload. First message is always the system persona.

    *intent* may be "code" to pull in the full code-generator harness contract
    (only-code, first-line-is-code, never-truncate) instead of the terse
    per-intent contract. *persona_extra* is appended to the system message
    verbatim (injected by callers that know session state the model should
    see). Never raises; on any internal failure falls back to a minimal
    two-message payload.
    """
    try:
        prompt = "" if user_text is None else str(user_text)
        if not isinstance(intent, str) or intent not in PROMPT_CONTRACTS:
            intent = classify_intent(prompt)
        if intent == "code":
            contract, _unused = wrap_code_prompt("")
        else:
            contract = PROMPT_CONTRACTS.get(intent, PROMPT_CONTRACTS["question"])
        parts = [_PERSONA]
        ctx = _render_context(context)
        if ctx:
            parts.append(ctx)
        if persona_extra:
            parts.append(str(persona_extra).strip())
        today = _today()
        if today:
            parts.append("Today is %s." % today)
        parts.append(_UNCERTAINTY)
        parts.append("Response contract: " + contract)
        messages = [{"role": "system", "content": "\n\n".join(parts)}]
        messages.extend(_trim_history(history))
        messages.append({"role": "user", "content": prompt})
        return messages
    except Exception:
        try:
            return [
                {"role": "system", "content": _PERSONA + " " + _UNCERTAINTY},
                {"role": "user",
                 "content": "" if user_text is None else str(user_text)},
            ]
        except Exception:
            return [{"role": "system", "content": "You are JARVIS, a formal "
                                                  "AI butler."},
                    {"role": "user", "content": ""}]


# ---------------------------------------------------------------------------
# clean_reply
# ---------------------------------------------------------------------------

_FENCE_BLOCK_RE = re.compile(r"```[ \t]*[\w+#.\-]*[ \t]*\r?\n(.*?)```", re.S)
_FENCE_LINE_RE = re.compile(r"^\s*```[\w+#.\-]*[ \t]*$", re.M)
_LEAD_POLITE_RE = re.compile(
    r"^\s*(?:certainly|of course|sure|alright|very good|absolutely|"
    r"happy to help)[,!.]?\s*(?:sir)?[!.]?\s*", re.I)
_LEAD_HERE_RE = re.compile(
    r"^\s*here(?:'s|\s+is)(?:\s+the|\s+a|\s+your)?\s[^:\n]{0,100}:\s*\n?", re.I)
_TRAIL_CHATTER_RE = re.compile(
    r"\s*(?:let me know if[^.\n]*[.\n]*|i hope (?:this|that) helps[!.]?|"
    r"feel free to[^.\n]*[.\n]*|anything else(?:,? sir)?\?!!?)\s*$", re.I)


def _strip_chatter(text):
    """Strip stacked polite openers, 'Here is ...:' leads and trailing offers."""
    for _ in range(3):
        stripped = _LEAD_POLITE_RE.sub("", text, count=1)
        if stripped != text:
            text = stripped
            continue
        stripped = _LEAD_HERE_RE.sub("", text, count=1)
        if stripped != text:
            text = stripped
            continue
        break
    for _ in range(3):
        stripped = _TRAIL_CHATTER_RE.sub("", text, count=1)
        if stripped != text:
            text = stripped
        else:
            break
    return text


def clean_reply(text, intent=None):
    """Post-process a model reply: strip fences and butler chatter, collapse
    blank-line runs. intent "code" keeps only the code body. Never raises."""
    try:
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        out = text.strip()
        blocks = _FENCE_BLOCK_RE.findall(out)
        if intent == "code":
            if blocks:
                out = max(blocks, key=len).strip()
            else:
                out = _FENCE_LINE_RE.sub("", out).strip()
            out = _strip_chatter(out)
            # A code body should not end in a prose paragraph about itself.
            lines = out.splitlines()
            while lines and not lines[-1].strip():
                lines.pop()
            out = "\n".join(lines).strip()
        else:
            if blocks:
                out = _FENCE_BLOCK_RE.sub(lambda m: m.group(1), out)
                out = _FENCE_LINE_RE.sub("", out)
            out = _strip_chatter(out)
        out = re.sub(r"[ \t]+\n", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()
    except Exception:
        try:
            return str(text or "").strip()
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Structured prompt builders
# ---------------------------------------------------------------------------

def wrap_code_prompt(topic, lang="Python"):
    """Return (system_contract, user_prompt) for code generation. The system
    contract enforces only-code output; the user prompt repeats it so the
    instruction survives either placement."""
    try:
        topic = str(topic).strip() if topic is not None else ""
        topic = topic or "a general purpose program"
        lang = str(lang).strip() if lang is not None else ""
        lang = lang or "Python"
        system_contract = (
            "You are a code generator. Output ONLY the requested code with no "
            "prose, no markdown fences, no commentary. The first line must be "
            "code, not prose. The code must be complete and runnable: include "
            "every import, definition and entry point it needs. Never truncate "
            "with ellipses, '...' or TODO placeholders."
        )
        user_prompt = (
            "Write complete, working %s code for: %s.\n"
            "Requirements:\n"
            "- Output ONLY the code: no prose, no markdown fences, no "
            "commentary before or after.\n"
            "- The first line must be code, not prose.\n"
            "- Complete and runnable: all imports, definitions and a usable "
            "entry point.\n"
            "- Handle obvious edge cases; inline comments only where the "
            "logic is non-obvious.\n"
            "- Never truncate: no ellipses, no TODO placeholders." % (lang, topic)
        )
        return system_contract, user_prompt
    except Exception:
        return PROMPT_CONTRACTS["code"], "Write working code for the request."


def wrap_website_prompt(topic, kind="web"):
    """Return a structured Google AI Studio prompt (role, constraints, Layout /
    Interactions / Styling / Responsiveness sections, quality bar, one-line
    spec summary) for a single-file web page or an Android Kotlin app."""
    try:
        topic = str(topic).strip() if topic is not None else ""
        topic = topic or "a modern personal site"
        kind_l = str(kind or "web").strip().lower()
        if kind_l in ("app", "android", "mobile"):
            deliverable = "Android application written in Kotlin with XML layouts"
            constraints = (
                "Deliver ONE complete runnable app: MainActivity plus at most "
                "two supporting screens. Kotlin and XML only (Jetpack view "
                "system) with Material Design 3. All strings, colors and "
                "dimensions in res/ resources; no external paid services."
            )
        else:
            deliverable = "website delivered as one self-contained HTML file"
            constraints = (
                "Deliver ONE .html file containing all HTML, embedded CSS and "
                "embedded JavaScript. No frameworks, no build step, no external "
                "CSS or JS beyond a Google Fonts link. Valid semantic HTML5 a "
                "browser can open directly from disk."
            )
        prompt = (
            "You are a senior product engineer shipping production-quality "
            "user interfaces.\n"
            "Task: design and build a %s about %s.\n\n"
            "Layout - a navigation bar, one hero section, two or three content "
            "sections and a footer; clear hierarchy with a single primary "
            "heading per section and generous spacing.\n\n"
            "Interactions - smooth-scroll navigation, hover and focus states on "
            "every interactive element, plus at least one tasteful behavior "
            "such as a theme toggle, tab switcher or contact form.\n\n"
            "Styling - a modern professional palette with one accent color, "
            "consistent typography, rounded cards and subtle shadows; no lorem "
            "ipsum or clip-art filler.\n\n"
            "Responsiveness - mobile-first and usable at 360 px wide; the "
            "navigation collapses on small screens and grids and images reflow "
            "cleanly on tablet and desktop.\n\n"
            "Quality bar - %s. Accessibility: AA contrast, alt text and visible "
            "keyboard focus.\n\n"
            "Spec: %s - %s, complete and ready to run."
            % (deliverable, topic, constraints, topic, deliverable)
        )
        return prompt
    except Exception:
        return "Create a complete single-file website about %s." % (topic or "a site")


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def selftest():
    """Run offline assertions. Returns (ok: bool, report: str). Never raises."""
    checks = []

    def check(name, fn):
        try:
            fn()
            checks.append((name, None))
        except Exception as exc:
            checks.append((name, "%s: %s" % (type(exc).__name__, exc)))

    def _assert(cond, msg="assertion failed"):
        if not cond:
            raise AssertionError(msg)

    def t_build_basic():
        m = build_messages("hello")
        _assert(isinstance(m, list) and m, "empty payload")
        _assert(m[0]["role"] == "system", "first message not system")
        _assert(m[-1] == {"role": "user", "content": "hello"}, "user msg last")
        _assert("JARVIS" in m[0]["content"], "persona missing")
        _assert("sir" in m[0]["content"], "'sir' missing")
        _assert("not sure" in m[0]["content"], "uncertainty clause missing")
        _assert(len(m) == 2, "expected system+user only")

    def t_build_history():
        hist = [{"role": "user", "content": "msg %d" % i} for i in range(12)]
        hist += [{"role": "assistant", "content": "ans %d" % i} for i in range(12)]
        m = build_messages("next", history=hist)
        _assert(len(m) <= 1 + _HISTORY_MAX_TURNS + 1, "history not trimmed")
        _assert(all(set(x) == {"role", "content"} for x in m), "bad shape")
        long_hist = [{"role": "user", "content": "x" * 900} for _ in range(8)]
        m2 = build_messages("next", history=long_hist)
        total = sum(len(x["content"]) for x in m2[1:-1])
        _assert(total <= _HISTORY_MAX_CHARS + 900, "char budget not applied")

    def t_build_context():
        m = build_messages("hello", context={
            "frontmost_app": "Safari", "ai_mode": "code_gen",
            "recent_commands": ["open safari", "play music"],
            "time": "12:00", "ignored_key": "nope"})
        sys_txt = m[0]["content"]
        _assert("Frontmost app: Safari" in sys_txt, "frontmost_app missing")
        _assert("AI mode: code_gen" in sys_txt, "ai_mode missing")
        _assert("Recent commands: open safari; play music" in sys_txt,
                "recent_commands missing")
        _assert("Time: 12:00" in sys_txt, "time missing")
        _assert("ignored_key" not in sys_txt, "unknown key rendered")
        m2 = build_messages("hello", context=None)
        _assert("Context" not in m2[0]["content"], "context rendered when None")

    def t_never_raises():
        for bad_args in ((None, None), (123, [None, 7, "junk"]),
                         ("x", {"not": "a list"}, {"bad": object()}),
                         ("y", [("tuple", "history")], None)):
            m = build_messages(*bad_args[:1], history=bad_args[1] if len(bad_args) > 1 else None,
                               context=bad_args[2] if len(bad_args) > 2 else None)
            _assert(isinstance(m, list) and m[0]["role"] == "system",
                    "raise-guards failed for %r" % (bad_args,))

    def t_build_advanced():
        m = build_messages("hello")
        sys_txt = m[0]["content"]
        _assert("Today is" in sys_txt, "date missing from persona")
        m2 = build_messages("hello", persona_extra="The user is testing the build.")
        _assert("testing the build" in m2[0]["content"], "persona_extra dropped")
        m3 = build_messages("write a python function to sort a list")
        _assert("first line must be code" in m3[0]["content"],
                "code intent did not use harness contract")
        m4 = build_messages("what is a black hole")
        _assert("first line must be code" not in m4[0]["content"],
                "non-code intent leaked code contract")

    def t_classify():
        cases = {
            "write a python function to sort a list": "code",
            "generate code for a snake game": "code",
            "translate hello into French": "translate",
            "summarize this article for me": "summarize",
            "rewrite this paragraph to sound formal": "rewrite",
            "open chrome": "command",
            "play some music": "command",
            "hi": "smalltalk",
            "hello": "smalltalk",
            "what is a black hole": "explain",
            "explain how TCP works": "explain",
            "Is Paris the capital of France?": "question",
            "why does it rain": "explain",
        }
        for text, want in cases.items():
            got = classify_intent(text)
            _assert(got == want, "%r -> %s, want %s" % (text, got, want))
        _assert(classify_intent("") == "question", "empty text")
        _assert(classify_intent(None) == "question", "None text")

    def t_clean_reply():
        _assert(clean_reply("```\nprint(1)\n```", intent="code") == "print(1)",
                "fence not stripped")
        _assert(clean_reply("```python\nx = 1\n```\nLet me know if you need "
                            "more.", intent="code") == "x = 1",
                "code chatter not stripped")
        out = clean_reply("Certainly, sir! Here is the summary:\n\nSome text.\n"
                          "I hope this helps.")
        _assert(out == "Some text.", "prose chatter not stripped: %r" % out)
        out2 = clean_reply("a\n\n\n\n\n\nb")
        _assert("\n\n\n" not in out2, "blank lines not collapsed: %r" % out2)
        _assert(clean_reply(None) == "", "None not handled")
        _assert(clean_reply(42) == "42", "non-str not handled")

    def t_wrap_code():
        sys_c, user_p = wrap_code_prompt("a snake game", "Python")
        _assert(isinstance(sys_c, str) and isinstance(user_p, str), "not strings")
        _assert("Output ONLY the requested code" in sys_c, "contract missing")
        _assert("first line must be code" in sys_c, "first-line rule missing")
        _assert("Python" in user_p and "snake game" in user_p, "topic/lang")
        _assert("first line must be code" in user_p, "rule not echoed")

    def t_wrap_website():
        for kind in ("web", "app"):
            p = wrap_website_prompt("a portfolio for a photographer", kind)
            words = len(p.split())
            _assert(120 <= words <= 200, "%s prompt %d words" % (kind, words))
            for section in ("Layout", "Interactions", "Styling",
                            "Responsiveness", "Quality bar"):
                _assert(section in p, "%s: missing %s" % (kind, section))
            _assert(p.strip().splitlines()[-1].startswith("Spec:"),
                    "%s: no spec line" % kind)
            _assert("senior product engineer" in p, "%s: no role" % kind)
        web = wrap_website_prompt("x", "web")
        _assert("HTML" in web, "web: no single-file HTML constraint")
        app = wrap_website_prompt("x", "app")
        _assert("Kotlin" in app, "app: no Kotlin constraint")

    check("build_messages basic shape/persona", t_build_basic)
    check("build_messages history trimming", t_build_history)
    check("build_messages context block", t_build_context)
    check("build_messages advanced (date/extra/code contract)", t_build_advanced)
    check("build_messages never raises", t_never_raises)
    check("classify_intent heuristics", t_classify)
    check("clean_reply fence/chatter/collapse", t_clean_reply)
    check("wrap_code_prompt contract", t_wrap_code)
    check("wrap_website_prompt structure", t_wrap_website)

    failed = [(n, e) for n, e in checks if e]
    if failed:
        lines = ["FAILED %d/%d checks:" % (len(failed), len(checks))]
        lines.extend("  - %s -> %s" % (n, e) for n, e in failed)
        return False, "\n".join(lines)
    return True, "ALL PASS (%d/%d): build_messages, classify_intent, " \
                 "clean_reply, wrap_code_prompt, wrap_website_prompt" \
                 % (len(checks), len(checks))


if __name__ == "__main__":
    ok, report = selftest()
    print(report)
    raise SystemExit(0 if ok else 1)

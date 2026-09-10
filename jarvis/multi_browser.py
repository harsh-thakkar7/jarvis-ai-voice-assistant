"""jarvis.multi_browser -- drive the major macOS browsers over AppleScript.

Gives JARVIS the power to "open any browser and work with it". Chrome, Safari,
Microsoft Edge and Brave Browser support AppleScript JavaScript injection;
Firefox and Arc do not and must rely on the pyautogui fallback helpers.

FUNCTION INVENTORY
    normalize(name)                friendly alias -> real app name
    is_running(name)               (bool, str) osascript "application NAME is running"
    running_browsers()             list[str] running browsers in table order
    pick(name=None)                app name to use, never raises
    activate(name)                 (bool, str) tell application "NAME" to activate
    open_url(name, url)            (bool, str) activate + open location, LaunchServices fallback
    run_js(name, js)               (bool, str) AppleScript JS injection (or pyautogui-needed refusal)
    page_text(name, max_chars)     (bool, str) <body>.innerText slice
    click_by_text(name, label)     (bool, str) click first element matching label text, "clicked:..."/"missing"
    scroll(name, dy)               (bool, str) window.scrollBy(0, dy)
    go_back(name)                  (bool, str) history.back()
    go_forward(name)               (bool, str) history.forward()
    refresh(name)                  (bool, str) location.reload()
    front_url(name)                (bool, str) document.location.href
    click_coords(name, x, y)       (bool, str) pyautogui fallback
    type_keys(name, text, interval)(bool, str) pyautogui fallback
    press_key(name, key)           (bool, str) pyautogui fallback

CAPABILITY_TABLE
    A module-level dict keyed by the exact macOS application name. Every entry:

        exec_slot   AppleScript fragment used by run_js to inject JS, with the
                    literal placeholder "{js}" where the escaped script goes, or
                    None when the browser has no AppleScript JS-injection verb.
        open_via    AppleScript fragment used by open_url to open a URL, with the
                    literal placeholder "{url}", or None when the app supports
                    neither open location nor AppleScript at all.
        note        Free-text caveat.

    Importing this module performs NO browser interaction and has no side
    effects; pyautogui and subprocess are only touched inside functions.
"""

import subprocess

__all__ = [
    "CAPABILITIES",
    "CAPABILITY_TABLE",
    "normalize",
    "is_running",
    "running_browsers",
    "pick",
    "activate",
    "open_url",
    "run_js",
    "page_text",
    "click_by_text",
    "scroll",
    "go_back",
    "go_forward",
    "refresh",
    "front_url",
    "click_coords",
    "type_keys",
    "press_key",
    "_apple_escape",
]

CAPABILITIES = {
    "Google Chrome": {
        "exec_slot": 'execute "{js}" in active tab of front window',
        "open_via": 'open location "{url}"',
        "note": (
            "Chrome needs 'Allow JavaScript from Apple Events' enabled in the "
            "View > Developer menu for JS injection; open location always works."
        ),
    },
    "Safari": {
        "exec_slot": 'do JavaScript "{js}" in current tab in front window',
        "open_via": 'open location "{url}"',
        "note": (
            "Safari needs 'Allow JavaScript from Apple Events' ticked in the "
            "Develop menu for JS injection; open location always works."
        ),
    },
    "Microsoft Edge": {
        "exec_slot": 'execute "{js}" in active tab of front window',
        "open_via": 'open location "{url}"',
        "note": (
            "Chromium-based (same dialect as Chrome) but frequently requires "
            "toggling the browser's own 'Allow JavaScript from Apple Events' "
            "setting; always keep the fallback path ready."),
    },
    "Firefox": {
        "exec_slot": None,
        "open_via": 'open location "{url}"',
        "note": "No AppleScript JS-injection verb; use the pyautogui fallback helpers.",
    },
    "Brave Browser": {
        "exec_slot": 'execute "{js}" in active tab of front window',
        "open_via": 'open location "{url}"',
        "note": (
            "Chromium-based (same dialect as Chrome) but frequently requires "
            "toggling the browser's own 'Allow JavaScript from Apple Events' "
            "setting; always keep the fallback path ready."),
    },
    "Arc": {
        "exec_slot": None,
        "open_via": None,
        "note": (
            "No AppleScript JS-injection verb and no open location; open URLs "
            "through the Arc URL scheme arc://open/?url= via LaunchServices, "
            "and drive the page with the pyautogui fallback helpers."),
    },
}

CAPABILITY_TABLE = CAPABILITIES

_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "googlechrome": "Google Chrome",
    "safari": "Safari",
    "edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "ms edge": "Microsoft Edge",
    "msedge": "Microsoft Edge",
    "firefox": "Firefox",
    "mozilla firefox": "Firefox",
    "firefox browser": "Firefox",
    "brave": "Brave Browser",
    "brave browser": "Brave Browser",
    "bravebrowser": "Brave Browser",
    "arc": "Arc",
}


def normalize(name):
    """Return the real macOS app name for a friendly alias (or the input)."""
    if not name:
        return "Google Chrome"
    key = str(name).strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    canonical = {a.lower(): a for a in CAPABILITY_TABLE}
    return canonical.get(key, key)


def _run_osascript(script, timeout=30):
    """Run a single `osascript -e SCRIPT` and return (ok, stdout-or-error).

    Always built with -e (never a heredoc); never raises.
    """
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, "osascript error: %s" % exc
    if proc.returncode == 0:
        out = (proc.stdout or "").strip()
        return True, out if out else "ok"
    err = ((proc.stderr or "").strip() or (proc.stdout or "").strip()
           or "osascript exit %s" % proc.returncode)
    return False, err


def _apple_escape(js):
    """Escape text for use inside a double-quoted AppleScript string literal.

    Backslash -> `\\`, double-quote -> `\"`, newline -> `\n`.
    Applied to the JS payload in run_js so the script survives the trip into
    `osascript -e 'tell application "X" to execute "..." in active tab ...'`.
    """
    s = js.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return s


def is_running(name):
    """(bool, str) -- `application "NAME" is running`. Read-only, never raises."""
    app = normalize(name)
    ok, out = _run_osascript('application "%s" is running' % app)
    if not ok:
        return False, "is_running failed for %s: %s" % (app, out)
    running = out.strip().lower() == "true"
    return running, "%s %s" % (app, "running" if running else "not running")


def running_browsers():
    """Return the names of running browsers, in CAPABILITY_TABLE order."""
    return [app for app in CAPABILITY_TABLE if is_running(app)[0]]


def pick(name=None):
    """Return the app name to use: given name (even if not running), else the
    first running browser, else 'Google Chrome'. Never raises."""
    try:
        if name:
            return normalize(name)
        running = running_browsers()
        return running[0] if running else "Google Chrome"
    except Exception:
        return "Google Chrome"


def activate(name):
    """(bool, str) -- bring the browser to the front via AppleScript."""
    app = normalize(name)
    return _run_osascript('tell application "%s" to activate' % app)


def _launch_via_ls(app, url):
    """LaunchServices fallback: `open -a APP <url or scheme>`. Never raises."""
    try:
        subprocess.Popen(
            ["open", "-a", app, str(url)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True, "opened %s in %s (LaunchServices)" % (url, app)
    except Exception as exc:
        return False, "failed to open %s in %s: %s" % (url, app, exc)


def open_url(name, url):
    """(bool, str) -- activate then open the URL. AppleScript open location for
    every browser except Arc (which uses its arc:// scheme); everything falls
    back to LaunchServices `open -a APP URL`."""
    app = normalize(name)
    url = str(url)
    ok, msg = activate(app)
    if not ok:
        return False, "cannot activate %s: %s" % (app, msg)
    if app == "Arc":
        return _launch_via_ls(app, "arc://open/?url=%s" % url)
    template = CAPABILITY_TABLE.get(app, {}).get("open_via")
    if template:
        script = 'tell application "%s" to %s' % (
            app, template.format(url=_apple_escape(url)))
        ok, msg = _run_osascript(script)
        if ok:
            return True, "opened %s in %s" % (url, app)
        err = msg
    else:
        err = "no open_via verb for %s" % app
    ok, msg = _launch_via_ls(app, url)
    if ok:
        return True, msg + " (AppleScript open location failed: %s)" % err
    return False, "open_url failed for %s: %s; fallback also failed: %s" % (app, err, msg)


def run_js(name, js):
    """(bool, str) -- inject JS via AppleScript, or refuse for browsers without
    an exec_slot verb (Firefox, Arc) pointing at the pyautogui fallback."""
    app = normalize(name)
    template = CAPABILITY_TABLE.get(app, {}).get("exec_slot")
    if not template:
        return False, (
            "%s has NO AppleScript JS-injection verb; this browser needs the "
            "pyautogui fallback (JARVIS will use coordinates/keyboard)."
            % app
        )
    script = 'tell application "%s" to %s' % (
        app, template.format(js=_apple_escape(js)))
    return _run_osascript(script)


def page_text(name, max_chars=2000):
    """(bool, str) -- pull document.body.innerText (capped at max_chars)."""
    app = normalize(name)
    try:
        n = max(0, int(max_chars))
    except (TypeError, ValueError):
        n = 2000
    return run_js(app, "document.body ? document.body.innerText.slice(0, %d) : ''" % n)


def _js_string(s):
    """JSON-ish quoting for embedding a string inside a JS expression:
    wrap in double quotes and escape backslash, double-quote, newline."""
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"%s"' % s


def click_by_text(name, label):
    """(bool, str) -- click the first button/link/role=button/[aria-label] whose
    aria-label, title or textContent equals OR starts with the label
    (case-insensitive, trimmed). Returns 'clicked:LABEL' or 'missing'."""
    app = normalize(name)
    needle = _js_string(str(label))
    js = (
        "(() => { const l = %s.toUpperCase().toLowerCase();"
        " const els = document.querySelectorAll('button, a, [role=\"button\"],"
        " [aria-label]'); for (const e of els) {"
        " const aria = (e.getAttribute('aria-label') || '').trim().toLowerCase();"
        " const title = (e.getAttribute('title') || '').trim().toLowerCase();"
        " const text = (e.textContent || '').trim().toLowerCase();"
        " if ((aria && (aria === l || aria.startsWith(l))) ||"
        "     (title && (title === l || title.startsWith(l))) ||"
        "     (text && (text === l || text.startsWith(l)))) { e.click();"
        " return 'clicked:' + l; } } return 'missing'; })()"
    ) % needle
    return run_js(app, js)


def scroll(name, dy):
    """(bool, str) -- window.scrollBy(0, dy)."""
    app = normalize(name)
    try:
        delta = int(dy)
    except (TypeError, ValueError):
        return False, "bad scroll delta: %r" % (dy,)
    return run_js(app, "window.scrollBy(0, %d)" % delta)


def go_back(name):
    """(bool, str) -- history.back()."""
    return run_js(normalize(name), "history.back()")


def go_forward(name):
    """(bool, str) -- history.forward()."""
    return run_js(normalize(name), "history.forward()")


def refresh(name):
    """(bool, str) -- location.reload()."""
    return run_js(normalize(name), "location.reload()")


def front_url(name):
    """(bool, str) -- best-effort document.location.href."""
    return run_js(normalize(name), "document.location.href")


def _lazy_pyautogui():
    """Return (True, module) on success, (False, reason) otherwise. Imported
    lazily so importing multi_browser never touches pyautogui."""
    try:
        import pyautogui
        return True, pyautogui
    except Exception as exc:
        return False, str(exc)


def click_coords(name, x, y):
    """(bool, str) -- activate the browser, then pyautogui move+click. Honest
    (False, ...) refusal when pyautogui is unavailable."""
    app = normalize(name)
    ok, msg = activate(app)
    if not ok:
        return False, "cannot activate %s: %s" % (app, msg)
    ok, py = _lazy_pyautogui()
    if not ok:
        return False, (
            "pyautogui unavailable (%s) so click refused -- not faking success."
            % py
        )
    try:
        py.moveTo(float(x), float(y))
        py.click()
        return True, "clicked (%s, %s) in %s via pyautogui" % (x, y, app)
    except Exception as exc:
        return False, "pyautogui click failed in %s: %s" % (app, exc)


def type_keys(name, text, interval=0.02):
    """(bool, str) -- activate the browser, then pyautogui typewrite text."""
    app = normalize(name)
    ok, msg = activate(app)
    if not ok:
        return False, "cannot activate %s: %s" % (app, msg)
    ok, py = _lazy_pyautogui()
    if not ok:
        return False, (
            "pyautogui unavailable (%s) so typing refused -- not faking success."
            % py
        )
    try:
        py.typewrite(str(text), interval=interval)
        return True, "typed %d chars into %s via pyautogui" % (len(str(text)), app)
    except Exception as exc:
        return False, "pyautogui typing failed in %s: %s" % (app, exc)


def press_key(name, key):
    """(bool, str) -- activate the browser, then pyautogui press a key."""
    app = normalize(name)
    ok, msg = activate(app)
    if not ok:
        return False, "cannot activate %s: %s" % (app, msg)
    ok, py = _lazy_pyautogui()
    if not ok:
        return False, (
            "pyautogui unavailable (%s) so key press refused -- not faking success."
            % py
        )
    try:
        py.press(str(key))
        return True, "pressed '%s' in %s via pyautogui" % (key, app)
    except Exception as exc:
        return False, "pyautogui key press failed in %s: %s" % (app, exc)


if __name__ == "__main__":
    print("=== multi_browser dry self-test (no browser interaction) ===")
    assert normalize("chrome") == "Google Chrome"
    assert normalize("arc") == "Arc"
    assert pick("edge") == "Microsoft Edge"
    print("PASS: normalize('chrome')='Google Chrome' / normalize('arc')='Arc' / pick('edge')='Microsoft Edge'")

    assert _apple_escape('say "hi"\n') == 'say \\"hi\\"\\n'
    print("PASS: _apple_escape('say \"hi\"\\n') == %r" % _apple_escape('say "hi"\n'))

    print("\nCAPABILITY_TABLE:")
    for _app, _cap in CAPABILITY_TABLE.items():
        print("  %-16s exec_slot=%-52r open_via=%-28r note=%s"
              % (_app, _cap["exec_slot"], _cap["open_via"], _cap["note"]))
    print("PASS: CAPABILITY_TABLE contains %d entries" % len(CAPABILITY_TABLE))

    _real_run = subprocess.run
    def _spy_run(*_args, **_kwargs):
        raise AssertionError("run_js must NOT invoke subprocess when exec_slot is None")
    subprocess.run = _spy_run
    try:
        _ok, _msg = run_js("Firefox", "alert(1)")
        assert _ok is False, "Firefox run_js should refuse with False"
        assert "pyautogui" in _msg.lower(), "refusal should mention the pyautogui fallback"
        print("PASS: run_js('Firefox', ...) -> (%r, %r) without touching subprocess" % (_ok, _msg))
        _ok2, _msg2 = run_js("Arc", "alert(1)")
        assert _ok2 is False and "pyautogui" in _msg2.lower()
        print("PASS: run_js('Arc', ...) -> (%r, %r) without touching subprocess" % (_ok2, _msg2))
    finally:
        subprocess.run = _real_run

    print("\nALL SELF-TESTS OK")
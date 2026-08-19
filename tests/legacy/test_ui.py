import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import os
import sys
import time

import main

passed = 0
failed = 0


def check(name, cond, info=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {info}")


def pump(seconds, cond=lambda: False):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


opened = []
main.webbrowser.open = lambda u: opened.append(u)
main.ask_ai = lambda p, history=None: "MOCK_AI"
main.load_api_key = lambda: "k"
main.get_weather = lambda loc: "clear"

app = main.JarvisApp()
app._say_fallback = lambda t: app.ui_q.put(("say_done", None))
root = app.root
root.update()
pump(0.5)

submitted = []
app._submit_text_orig = app._submit_text


def spy(cmd):
    submitted.append(cmd)


try:
    print("== 1. HINT CLICK (right panel voice commands) ==")
    rects = [(i, a) for i, (t, a) in app._hint_map.items()
             if app.canvas.type(i) == "rectangle"]
    check("7 clickable hints exist", len(rects) == 7, str(len(rects)))
    for iid, act in rects:
        x0, y0, x1, y1 = app.canvas.bbox(iid)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        submitted.clear()
        app._submit_text = spy
        app.canvas.event_generate("<ButtonPress-1>", x=cx, y=cy)
        root.update()
        app.canvas.event_generate("<ButtonRelease-1>", x=cx, y=cy)
        root.update()
        check(f"click hint -> '{act}'", submitted == [act], f"got {submitted}")

    print("== 2. NON-HINT AREA DOES NOT SUBMIT ==")
    submitted.clear()
    app._submit_text = spy
    app.canvas.event_generate("<ButtonPress-1>", x=app._X(640), y=app._Y(200))
    root.update()
    check("click on empty area submits nothing", submitted == [], str(submitted))

    print("== 3. HOVER HIGHLIGHT + CURSOR ==")
    iid, act = rects[0]
    t, _ = app._hint_map[iid]
    x0, y0, x1, y1 = app.canvas.bbox(iid)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    app.canvas.event_generate("<Motion>", x=cx, y=cy)
    root.update()
    check("hover highlights text", app.canvas.itemcget(t, "fill") == "#eaffff",
          app.canvas.itemcget(t, "fill"))
    check("hover sets hand cursor", app.canvas.cget("cursor") == "hand2",
          app.canvas.cget("cursor"))
    app.canvas.event_generate("<Motion>", x=5, y=5)
    root.update()
    check("leave clears highlight", app.canvas.itemcget(t, "fill") == "#5fb3c8",
          app.canvas.itemcget(t, "fill"))

    print("== 4. QUICK COMMAND BUTTONS (invoke) ==")
    check("5 quick buttons", len(app.quick_btns) == 5, str(len(app.quick_btns)))
    for b in app.quick_btns:
        submitted.clear()
        app._submit_text = spy
        b.invoke()
        if b.cget("text") == "CLEAR TXT":
            check("quick button 'CLEAR TXT' runs", True, "invoked")
        else:
            expected = main.QUICK_CMDS[app.quick_btns.index(b)][1]
            check(f"quick button '{b.cget('text')}' submits",
                  submitted == [expected], f"got {submitted}")

    print("== 5. REAL BUTTON CLICK (pointer + press/release) ==")
    b = app.quick_btns[0]
    submitted.clear()
    app._submit_text = spy
    bx, by = b.winfo_rootx(), b.winfo_rooty()
    bw, bh = b.winfo_width(), b.winfo_height()
    root.event_generate("<Motion>", x=bx + bw // 2, y=by + bh // 2, warp=True)
    root.update()
    time.sleep(0.2)
    root.update()
    b.event_generate("<ButtonPress-1>", x=bw // 2, y=bh // 2)
    root.update()
    b.event_generate("<ButtonRelease-1>", x=bw // 2, y=bh // 2)
    root.update()
    check("real click fires quick button", submitted == ["what time is it"],
          f"got {submitted}")

    print("== 6. ENTRY RETURN BINDING ==")
    submitted.clear()
    app._submit_text = spy
    app.cmd_entry.delete(0, "end")
    app.cmd_entry.insert(0, "open gmail")
    app.cmd_entry.focus_force()
    root.update()
    time.sleep(0.1)
    root.event_generate("<Return>")
    root.update()
    check("Return submits entry text", submitted == ["open gmail"],
          f"got {submitted}")

    print("== 7. REAL SUBMIT END-TO-END ==")
    app._submit_text = app._submit_text_orig
    app.cmd_history.clear()
    opened.clear()
    app._submit_text("open youtube")
    ok = pump(6, lambda: bool(opened))
    check("end-to-end opens youtube", ok and "https://www.youtube.com" in opened,
          str(opened))

    print("== 8. CLEAR TXT BUTTON ==")
    app._quick_cmd("__clear__")
    pump(1.5)
    body = app.tx.get("1.0", "end").strip()
    check("transcript cleared then SYS note", "Transcript cleared" in body,
          repr(body[:60]))

finally:
    app.quit_app()

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

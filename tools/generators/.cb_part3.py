
    # ---- C. CODE DEBUGGING SKILLS ----------------------------------------

    def _cb_debug_request_detect(cmd):
        if re.search(r"\bwhy\s+(?:is|does|do|won't|dont|don't|doesn't)\s+"
                     r"my\s+(?:code|script|program|app)\b", cmd, re.I) or \
           re.search(r"\bwhat(?:'s|\s+is)\s+wrong\s+with\s+(?:this|my|the)"
                     r"\s*(?:code|script|program|function)?\b", cmd, re.I) or \
           re.search(r"\bhelp\s+me\s+debug\b|\bmy\s+code\s+(?:is\s+)?"
                     r"(?:broken|crashing|failing)\b", cmd, re.I) or \
           re.search(r"\b(?:fix|repair)\s+(?:this|that|my|the)\s+"
                     r"(?:broken\s+|buggy\s+)?(?:code|script|program)\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    COMMON_BUG_CHECKLIST = (
        "Send me the code and the exact error message, sir - paste it "
        "after your request and I will pinpoint the bug.\n"
        "Meanwhile, the usual suspects:\n"
        "1. Typos in variable/function names (case matters).\n"
        "2. Wrong indentation or missing colons/semicolons.\n"
        "3. Off-by-one loop bounds and index ranges.\n"
        "4. Comparing incompatible types ('5' vs 5).\n"
        "5. Mutable default arguments or shared mutable state.\n"
        "6. Using a variable before assignment or outside its scope.")

    def _cb_debug_request_fn(app, cmd):
        code = _cb_payload(cmd,
                           r"\bwhy\b.{0,60}?\b(?:code|script|program)\b",
                           r"\bwhat(?:'s|\s+is)\s+wrong\b.*",
                           r"\b(?:fix|repair|debug)\b.{0,40}?"
                           r"\b(?:code|script|program)\b")
        if code:
            return _llm_reply(app, "Debug this code. Identify the bug, "
                                   "explain the cause briefly, then give "
                                   "the corrected version: %s" % code)
        return COMMON_BUG_CHECKLIST

    def _cb_improve_request_detect(cmd):
        if re.search(r"\b(?:improve|optimize|clean\s+up|tidy)\s+(?:this|my|"
                     r"the)\s+(?:code|script|program|function)\b", cmd,
                     re.I) or \
           re.search(r"\brefactor\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_improve_request_fn(app, cmd):
        code = _cb_payload(cmd, r"\b(?:refactor|improve|optimize|clean\s+up|"
                                r"tidy)\b.{0,40}?(?:code|script|program|"
                                r"function)?\b")
        if code:
            return _llm_reply(app, "Refactor this code to be cleaner, "
                                   "faster, and more idiomatic. Explain the "
                                   "key improvements: %s" % code)
        return ("Happy to refactor, sir. Paste the code after your request "
                "('refactor this code: ...').\nQuick wins I look for: "
                "duplicate logic to extract, long functions to split, magic "
                "numbers to name, and comprehension opportunities, sir.")

    ERROR_GUIDES = [
        (("nameerror",),
         "NameError means a name was used before it exists - typo, missing "
         "import, or use-before-define. Check spelling and move the "
         "definition above the usage, sir."),
        (("typeerror",),
         "TypeError means mismatched operation types, like '5' + 5. Convert"
         " explicitly (int('5')) or check what the function actually "
         "receives, sir."),
        (("valueerror",),
         "ValueError means the type fits but the value does not - int('abc')"
         ", or removing an item absent from a list. Validate inputs before "
         "converting, sir."),
        (("indexerror",),
         "IndexError means an index is outside the list - often len(items) "
         "used as a subscript, or looping to <= length. Remember valid "
         "indices end at len - 1, sir."),
        (("keyerror",),
         "KeyError means the dictionary lacks that key. Use d.get('k', "
         "default), or check 'k' in d first, sir."),
        (("attributeerror",),
         "AttributeError means the object lacks that attribute/method - "
         "often None where an object was expected, or a wrong import. "
         "Print(type(obj)) to see what actually arrived, sir."),
        (("modulenotfounderror", "module not found"),
         "ModuleNotFoundError means Python cannot find the package - install"
         " it (pip install name) into the SAME environment running your "
         "script; check spelling and virtual-env activation, sir."),
        (("filenotfounderror", "file not found error"),
         "FileNotFoundError means the path does not exist relative to the "
         "working directory. Print(os.getcwd()), build paths with os.path."
         "join, and wrap reads in try/except with clear messages, sir."),
        (("permissionerror", "permission denied"),
         "PermissionError means the OS refused access - file locked, "
         "read-only, or a protected port. Check modes and ownership; ports "
         "below 1024 need admin privileges, sir."),
        (("zerodivisionerror", "division by zero"),
         "ZeroDivisionError is dividing by zero. Guard with if denom != 0:, "
         "or catch ZeroDivisionError and choose a sane fallback, sir."),
        (("indentationerror", "indentation error"),
         "IndentationError means inconsistent whitespace blocks. Pick spaces"
         " (PEP8 says 4), never mix tabs, and let the editor auto-format - "
         "Shift+Option+F in VS Code, sir."),
        (("syntaxerror",),
         "SyntaxError means the parser cannot read the line at all - missing"
         " colon, unclosed bracket, stray character. The caret ^ points near"
         " the real mistake, often on the previous line, sir."),
        (("recursionerror", "maximum recursion depth", "stack overflow"),
         "RecursionError/stack overflow means recursion never reached its "
         "base case. Verify the base case fires and each call shrinks the "
         "input, sir."),
        (("segmentation fault", "segfault"),
         "A segfault is illegal memory access in native code - bad C "
         "pointers, or a bug in an extension library. Reproduce minimally, "
         "update the library, and run under gdb/faulthandler, sir."),
        (("nullpointerexception", "null pointer"),
         "NullPointerException means Java/Kotlin dereferenced null - a "
         "method called on an uninitialized reference. Null-check, use "
         "Optional, or Kotlin's ?. safe call, sir."),
        (("undefined is not a function", "not a function javascript",
          "cannot read property"),
         "'x is not a function'/'cannot read property of undefined' means "
         "the object is undefined or lacks the method - usually a typo, "
         "wrong import, or async timing. Console.log the object right "
         "before the call, sir."),
        (("unhandled promise rejection", "promise rejection"),
         "Unhandled promise rejection means an async failure had no .catch/"
         "try-await wrapper. Always pair await with try/catch in JS or "
         "try/except in Python, sir."),
        (("cors error", "cors policy"),
         "CORS errors mean the browser blocked cross-origin responses - the"
         " SERVER must send Access-Control-Allow-Origin. In Flask: pip "
         "install flask-cors, then CORS(app), sir."),
        (("npm err", "npm install fails"),
         "npm ERR shows the failing package above the noise: delete "
         "node_modules and package-lock.json, run npm install again, check "
         "Node version compatibility, and retry with --verbose, sir."),
        (("pip install fails", "pip install error"),
         "pip failures are usually environment mix-ups: use python -m pip "
         "install pkg with the same interpreter, upgrade pip first, and "
         "read the 'Could not find/build' line for the missing system "
         "library, sir."),
        (("git merge conflict",),
         "Merge conflicts mark both versions between <<<<<<< and >>>>>>>. "
         "Edit to keep the right code, delete the markers, then git add the"
         " file and continue the merge or rebase, sir."),
    ]

    def _cb_register_error(idx, triggers, reply):
        alts = "|".join(re.escape(t) for t in triggers)
        pat = re.compile(
            r"(?:\b%s\b[^.?!]{0,30}\b(?:mean|means|error|fix|why)\b"
            r"|\b(?:fix|explain|understand|handle|resolve|what is|whats|"
            r"what's|about|how to)\b[^.?!]{0,30}\b%s\b)" % (alts, alts), re.I)

        def detect(cmd, _pat=pat):
            if _pat.search(cmd):
                return {"cmd": cmd}
            return None

        def execute(app, cmd, _reply=reply):
            return _reply

        brain.reg_fn("cb_err_%02d" % idx, detect, execute)

    for _i, (_trg, _rep) in enumerate(ERROR_GUIDES):
        _cb_register_error(_i, _trg, _rep)

    reg_fn("cb_debug_request", _cb_debug_request_detect,
           _cb_debug_request_fn)
    reg_fn("cb_improve_request", _cb_improve_request_detect,
           _cb_improve_request_fn)

    # ---- D. CODE CONVERSION SKILLS ---------------------------------------

    PY_TO_JS_CHEATSHEET = (
        "Python to JavaScript quick map, sir:\n"
        "  print(x)             ->  console.log(x)\n"
        "  def f(a, b):         ->  function f(a, b) {\n"
        "  len(xs)              ->  xs.length\n"
        "  range(n)             ->  [...Array(n).keys()]\n"
        "  [x*2 for x in xs]    ->  xs.map(x => x * 2)\n"
        "  [x for x in xs if x] ->  xs.filter(Boolean)\n"
        "  d = {'a': 1}         ->  obj = {a: 1}\n"
        "  None / True / False  ->  null / true / false\n"
        "  elif                 ->  else if\n"
        '  f"hi {name}"         ->  `hi ${name}`\n'
        "  int(s) / str(x)      ->  parseInt(s) / String(x)\n"
        "  for k, v in d.items()->  for (const [k, v] of Object.entries(d))\n"
        "Paste your code after the request and I will translate it "
        "directly, sir.")

    def _cb_py_to_js_detect(cmd):
        if re.search(r"\b(?:convert|translate|port|rewrite)\s+(?:this\s+|"
                     r"my\s+|the\s+)?(?:python|py).{0,20}\b(?:java\s?script|"
                     r"js)\b", cmd, re.I) or \
           re.search(r"\b(?:python|py)\s+(?:code\s+)?to\s+(?:java\s?script|"
                     r"js)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_py_to_js_fn(app, cmd):
        code = _cb_payload(cmd, r"\b(?:convert|translate|port|rewrite)\b.*?")
        if code:
            return _llm_reply(app, "Translate this Python code to modern "
                                   "JavaScript (ES6+). Output only the "
                                   "JavaScript: %s" % code)
        return PY_TO_JS_CHEATSHEET

    _TARGET_LANGS = (r"python|java\s?script|js|typescript|ts|java|c\+\+|cpp|c|"
                     r"go(lang)?|rust|ruby|php|swift|kotlin|bash|shell|sql")

    def _cb_translate_detect(cmd):
        if re.search(r"\b(?:convert|translate|port|migrate|rewrite)\s+"
                     r"(?:this|that|my|the)?\s*(?:code|snippet|script|"
                     r"function|program|logic)?\s*(?:from\s+\w+\s+)?to\s+"
                     r"(?:%s)\b" % _TARGET_LANGS, cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_translate_fn(app, cmd):
        m = re.search(r"\bto\s+(%s)\b" % _TARGET_LANGS, cmd, re.I)
        lang = m.group(1) if m else "the target language"
        code = _cb_payload(cmd, r"\b(?:convert|translate|port|migrate|"
                                r"rewrite)\b.*?")
        if code:
            return _llm_reply(app, "Translate this code to %s, keeping "
                                   "behavior identical. Output only the "
                                   "translated code: %s" % (lang, code))
        return ("Ready to translate, sir. Paste the code after the "
                "request, like: 'convert this code to rust: <paste>'.\n"
                "I will keep behavior identical and flag language features "
                "with no direct equivalent, sir.")

    reg_fn("cb_py_to_js", _cb_py_to_js_detect, _cb_py_to_js_fn)
    reg_fn("cb_translate", _cb_translate_detect, _cb_translate_fn)

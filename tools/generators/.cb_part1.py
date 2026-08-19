    # -- CODING BRAIN (batch 4, injected by gen_coding_brain.py) --
    # Dedicated coding intelligence: code generation, explanation,
    # debugging, conversion, plus web / app / data-science / systems
    # knowledge bases.

    def _cb_ident(task, fallback="my_thing"):
        words = re.sub(r"[^a-zA-Z0-9 ]+", " ", task or "").split()
        stop = {"a", "an", "the", "that", "this", "to", "which", "for",
                "with", "from", "of", "in", "on", "and", "or", "my", "me",
                "some", "it", "is", "are", "be", "can", "using", "use",
                "new"}
        parts = [w.lower() for w in words if w.lower() not in stop][:4]
        return "_".join(parts) or fallback

    def _cb_payload(cmd, *phrase_pats):
        """Return the trailing code/text payload after a trigger phrase."""
        for p in phrase_pats:
            m = re.search(p + r"\s*[:,-]?\s*(.+)", cmd, re.I | re.S)
            if m and len(m.group(1).strip()) >= 12:
                return m.group(1).strip()
        return None

    def _cb_llm_offline(app, prompt, offline):
        code = _llm(app, prompt)
        if code:
            return code
        return offline() if callable(offline) else offline

    # ---- A. CODE GENERATION SKILLS ---------------------------------------

    def _cb_py_function_detect(cmd):
        if re.search(r"\b(?:write|create|make|define|generate)\s+(?:a\s+|"
                     r"an\s+|me\s+a\s+)?(?:python|py)\s+(?:function|method)"
                     r"\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_py_function_fn(app, cmd):
        task = _after(cmd, r"\b(?:python|py)\s+(?:function|method)\s+that\s+",
                      r"\b(?:python|py)\s+(?:function|method)\s+(?:to|for|"
                      r"which)\s+",
                      r"\b(?:python|py)\s+(?:function|method)\s+")
        task = task or cmd
        prompt = ("Write a clean, well-documented Python function for this "
                  "task: %s. Include the function with a docstring and one "
                  "example call. Output code first, brief notes after."
                  % task)

        def offline():
            fname = _cb_ident(task, "my_function")
            return ('Here is a Python function scaffold, sir:\n\n'
                    'def %s(*args, **kwargs):\n'
                    '    """%s"""\n'
                    '    # TODO: implement the logic\n'
                    '    result = None\n'
                    '    return result\n\n'
                    '# Example:\n'
                    '# print(%s())\n\n'
                    'Add my Groq API key and ask again for a fully '
                    'implemented version, sir.' % (fname, task[:80], fname))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_js_code_detect(cmd):
        if re.search(r"\b(?:write|create|generate|make)\s+(?:a\s+|some\s+|"
                     r"me\s+a\s+)?(?:java\s?script|js)\s+(?:code|script|"
                     r"function|program|snippet)\b", cmd, re.I) or \
           re.search(r"\b(?:java\s?script|js)\s+code\s+for\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_js_code_fn(app, cmd):
        task = _after(cmd, r"\b(?:java\s?script|js)\s+(?:code|script|"
                      r"function|program|snippet)\s+(?:that\s+|to\s+|for\s+)",
                      r"\b(?:java\s?script|js)\s+(?:code|script|function|"
                      r"program|snippet)\s+") or cmd
        prompt = ("Write modern JavaScript (ES6+) for this task: %s. Output "
                  "code first, brief notes after." % task)

        def offline():
            jname = _cb_ident(task, "my_task").replace("_", "")
            return ('Here is a JavaScript starting point, sir:\n\n'
                    'function %s(input) {\n'
                    '  // %s\n'
                    '  // TODO: implement the logic\n'
                    '  return input;\n'
                    '}\n\n'
                    '// Example:\n'
                    '// console.log(%s("test"));\n\n'
                    'Add my Groq API key and ask again for a fully '
                    'implemented version, sir.' % (jname, task[:80], jname))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_class_detect(cmd):
        if re.search(r"\b(?:create|write|make|define|generate|design)\s+"
                     r"(?:a\s+|an\s+|me\s+a\s+)?class\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_class_fn(app, cmd):
        thing = _after(cmd, r"\bclass\s+(?:for|called|named|of)\s+",
                       r"\bclass\s+") or "thing"
        cname = "".join(w.capitalize()
                        for w in _cb_ident(thing, "Thing").split("_"))
        prompt = ("Design a clean Python class for: %s. Include __init__, "
                  "useful methods, __repr__, and an example. Output code "
                  "first." % thing)

        def offline():
            return ('Here is a Python class blueprint, sir:\n\n'
                    'class %s:\n'
                    '    """Represents %s."""\n\n'
                    '    def __init__(self, name="", value=0):\n'
                    '        self.name = name\n'
                    '        self.value = value\n\n'
                    '    def __repr__(self):\n'
                    '        return "%s(name=%%r, value=%%r)" %% '
                    '(self.name, self.value)\n\n'
                    '# Example:\n'
                    '# obj = %s("sample", 42)'
                    % (cname, thing, cname, cname))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_script_detect(cmd):
        if re.search(r"\b(?:write|create|make|generate)\s+(?:a\s+|an\s+|"
                     r"me\s+a\s+)?script\s+(?:to|that|for|which)\b", cmd,
                     re.I):
            return {"cmd": cmd}
        return None

    def _cb_script_fn(app, cmd):
        task = _after(cmd, r"\bscript\s+(?:to|that|for|which)\s+") or cmd
        prompt = ("Write a complete, runnable Python script for this task: "
                  "%s. Use argparse and a main() guard. Output the full "
                  "script." % task)

        def offline():
            t = task[:70].replace('"', "'")
            return ('Here is a complete script template for "%s", sir:\n\n'
                    '#!/usr/bin/env python3\n'
                    '"""%s"""\n'
                    'import argparse\n\n\n'
                    'def main():\n'
                    '    parser = argparse.ArgumentParser(\n'
                    '        description="%s")\n'
                    '    parser.add_argument("target", nargs="?", '
                    'default=".",\n'
                    '                        help="what to process")\n'
                    '    args = parser.parse_args()\n'
                    '    print(f"Processing {args.target} ...")\n'
                    '    # TODO: implement the task here\n\n\n'
                    'if __name__ == "__main__":\n'
                    '    main()' % (t, t, t))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_gen_feature_detect(cmd):
        if re.search(r"\b(?:generate|create|build|write|give me|show me)\s+"
                     r"(?:the\s+|some\s+|me\s+)?(?:starter\s+|boilerplate\s+)"
                     r"?code\s+(?:for|of)\b", cmd, re.I) or \
           re.search(r"\b(?:generate|create|build|scaffold)\s+(?:a\s+|an\s+|"
                     r"me\s+a\s+)?(?:api|app|application|feature|module|"
                     r"endpoint|service|library)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_gen_feature_fn(app, cmd):
        topic = _after(cmd, r"\bcode\s+(?:for|of)\s+",
                       r"\b(?:generate|create|build|scaffold)\s+(?:a\s+|an\s+|"
                       r"me\s+a\s+)?(?:api|app|application|feature|module|"
                       r"endpoint|service|library)\s+(?:for|that|to|which)?\s*")
        topic = topic or cmd
        prompt = ("Generate production-quality starter code for: %s. Include "
                  "structure, comments, and usage notes." % topic)

        def offline():
            return ('Here is a build plan for "%s", sir:\n'
                    '1. Define the data model (inputs, outputs, storage).\n'
                    '2. Create project layout: src/, tests/, README.\n'
                    '3. Implement the smallest working core first.\n'
                    '4. Add error handling and logging.\n'
                    '5. Write tests, then polish the interface.\n'
                    'Tell me the language and I will tailor the scaffold, '
                    'sir.' % topic[:80])
        return _cb_llm_offline(app, prompt, offline)

    def _cb_api_flask_detect(cmd):
        if re.search(r"\b(?:flask|fastapi|express)\s+(?:rest\s+)?api\b", cmd,
                     re.I) or \
           re.search(r"\b(?:create|write|build|make|generate)\b[^.?!]{0,40}"
                     r"\brest\s+api\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_api_flask_fn(app, cmd):
        return ('Here is a ready-to-run Flask REST API skeleton, sir:\n\n'
                'from flask import Flask, jsonify, request\n\n'
                'app = Flask(__name__)\n'
                'items = [{"id": 1, "name": "first"}]\n\n\n'
                '@app.get("/api/items")\n'
                'def list_items():\n'
                '    return jsonify(items)\n\n\n'
                '@app.get("/api/items/<int:item_id>")\n'
                'def get_item(item_id):\n'
                '    item = next((i for i in items\n'
                '                 if i["id"] == item_id), None)\n'
                '    return (jsonify(item) if item\n'
                '            else (jsonify({"error": "not found"}), 404))\n\n\n'
                '@app.post("/api/items")\n'
                'def create_item():\n'
                '    data = request.get_json() or {}\n'
                '    item = {"id": len(items) + 1,\n'
                '             "name": data.get("name", "unnamed")}\n'
                '    items.append(item)\n'
                '    return jsonify(item), 201\n\n\n'
                'if __name__ == "__main__":\n'
                '    app.run(debug=True)\n\n'
                'Run with: pip install flask, then python app.py, sir.')

    reg_fn("cb_py_function", _cb_py_function_detect, _cb_py_function_fn)
    reg_fn("cb_js_code", _cb_js_code_detect, _cb_js_code_fn)
    reg_fn("cb_class", _cb_class_detect, _cb_class_fn)
    reg_fn("cb_script", _cb_script_detect, _cb_script_fn)
    reg_fn("cb_gen_feature", _cb_gen_feature_detect, _cb_gen_feature_fn)
    reg_fn("cb_api_flask", _cb_api_flask_detect, _cb_api_flask_fn)

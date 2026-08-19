#!/usr/bin/env python3
"""Batch 4: inject the CODING BRAIN into brain_extra.py right before the
OFFLINE CHAT ENGINE marker."""
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "brain_extra.py")
MARKER = "# OFFLINE CHAT ENGINE"
BATCH_TAG = "# -- CODING BRAIN (batch 4, injected by gen_coding_brain.py) --"
END_TAG = "# -- END CODING BRAIN --"

PARTS = [".cb_part%d.py" % i for i in range(1, 9)]


def main():
    src = open(OUT, encoding="utf-8").read()

    if BATCH_TAG in src:
        print("ERROR: coding brain already injected")
        return 1

    block = "\n"
    for p in PARTS:
        path = os.path.join(BASE, p)
        if not os.path.exists(path):
            print("ERROR: missing part %s" % p)
            return 1
        block += open(path, encoding="utf-8").read()
    block += "\n\n"

    # Sanity check: the block must compile as a function body.
    try:
        compile("def _cb_wrapper():\n" +
                "\n".join("    " + ln if ln.strip() else ln
                          for ln in block.splitlines()),
                "<coding-brain-block>", "exec")
    except SyntaxError as e:
        print("ERROR: block does not compile: %s" % e)
        return 1

    # Surgical fix 1: _debug_code_detect must require a trailing payload,
    # otherwise "fix this code" (no code given) dead-ends before our
    # cb_debug_request skill can ask for it.
    old_debug = (
        "    def _debug_code_detect(cmd):\n"
        "        if re.search(r\"\\b(?:debug|fix)\\s+(?:this|my|the)?\\s*(?:code|\"\n"
        "                     r\"script)\\b\", cmd, re.I):\n"
        "            return {\"cmd\": cmd}\n"
        "        return None\n")
    new_debug = (
        "    def _debug_code_detect(cmd):\n"
        "        if re.search(r\"\\b(?:debug|fix)\\s+(?:this|my|the)?\\s*(?:code|\"\n"
        "                     r\"script)\\b\", cmd, re.I):\n"
        "            code = _after(cmd, r\"\\b(?:debug|fix)\\s+(?:this|my|the)?\\s*\"\n"
        "                         r\"(?:code|script)?\\s*[:]?\")\n"
        "            return {\"cmd\": cmd} if code else None\n"
        "        return None\n")
    if old_debug in src:
        src = src.replace(old_debug, new_debug)
        print("patched _debug_code_detect to require a payload")
    else:
        print("NOTE: _debug_code_detect pattern not found; skipping patch")

    # Surgical fix 2: same idea for _refactor_code_detect.
    old_refactor = (
        "    def _refactor_code_detect(cmd):\n"
        "        if re.search(r\"\\brefactor\\b\", cmd, re.I):\n"
        "            return {\"cmd\": cmd}\n"
        "        return None\n")
    new_refactor = (
        "    def _refactor_code_detect(cmd):\n"
        "        if re.search(r\"\\brefactor\\b\", cmd, re.I):\n"
        "            code = _after(cmd, r\"\\brefactor\\s+(?:this|the)?\\s*\"\n"
        "                         r\"(?:code|script)?\\s*[:]?\")\n"
        "            return {\"cmd\": cmd} if code else None\n"
        "        return None\n")
    if old_refactor in src:
        src = src.replace(old_refactor, new_refactor)
        print("patched _refactor_code_detect to require a payload")
    else:
        print("NOTE: _refactor_code_detect pattern not found; skipping patch")

    idx = src.find(MARKER)
    if idx < 0:
        print("ERROR: marker not found")
        return 1
    src = src[:idx] + BATCH_TAG + "\n" + block.replace(
        BATCH_TAG + "\n", "") .lstrip("\n") + src[idx:]

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(src)
    print("injected coding brain (%d lines added)" %
          len(block.splitlines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

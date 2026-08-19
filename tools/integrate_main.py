#!/usr/bin/env python3
"""Post-merge integration patches + base import strip. Idempotent-ish."""
import re
src = open("main_merged.py").read()

old = """        try:
            pass  # merged
            register_extra(self)
            self._extra_registered = True
            return True"""
new = """        try:
            reg_fn = globals().get("register_extra") or globals().get(
                "register_extra__brain_extra")
            reg_fn(self)
            self._extra_registered = True
            return True"""
assert old in src, "A"
src = src.replace(old, new)

old2 = """            try:
                __import__(mod_name).register(self)
            except Exception as exc:
                print("WARNING: %s failed to load: %s" % (mod_name, exc))
        self._load_skill_packs()"""
new2 = """            fn = globals().get("register__" + mod_name)
            if fn is None:
                print("WARNING: pack %s missing registrar" % mod_name)
                continue
            try:
                fn(self)
            except Exception as exc:
                import traceback as _tb
                print("WARNING: %s failed: %s" % (mod_name, exc))
                _tb.print_exc()
        self._load_skill_packs_local()"""
assert old2 in src, "B"
src = src.replace(old2, new2)

i = src.index("    def _load_skill_packs(self):")
j = src.index("\n    def ", i + 10)
src = src[:i] + '''    def _load_skill_packs_local(self):
        for name in ("skills_habits", "skills_home", "skills_travel",
                     "skills_games"):
            fn = globals().get("register__" + name)
            if fn is None:
                continue
            try:
                fn(self)
            except Exception as exc:
                print("WARNING: %s failed to load: %s" % (name, exc))
''' + src[j:]

pats = [r"^from brain import .*$", r"^import brain as .*$",
        r"^import brain\s*(#.*)?$", r"^import brain_extra as .*$",
        r"^import brain_extra\s*(#.*)?$"]
out = []; skip = False
for line in src.splitlines():
    if skip:
        skip = line.rstrip().endswith("\\"); continue
    if any(re.match(p, line) for p in pats):
        skip = line.rstrip().endswith("\\"); continue
    out.append(line)
open("main.py", "w").write("\n".join(out) + "\n")
print("main.py integrated:", len(out), "lines")

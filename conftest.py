"""Import main FIRST so merged-module aliases resolve for all tests."""
import os

os.environ.setdefault("JARVIS_TEST", "1")
import sys as _sys, os as _os
_jdir = _os.path.join(_os.path.dirname(os.path.abspath('conftest.py')), 'jarvis')
if _jdir not in _sys.path:
    _sys.path.insert(0, _jdir)
import main  # noqa: E402,F401

"""CLICKY ENHANCEMENT PACK for JarvisBot.

Single integration point used by main.py's JarvisBot.__init__:

    try:
        import bot_clicky; bot_clicky.attach(self)
    except Exception:
        pass

Each add-on lives in its own module exposing ``attach(bot)`` and is loaded
fail-soft here: a broken add-on can never take down the orb. Add-ons are
responsible for their own idempotency guards (attach twice == no-op) and
must expose a controller with ``detach()`` for clean teardown.
"""

_MODULES = ("bot_quick_bar", "bot_reply_bubble", "bot_status_panel")


def _discover():
    """Auto-discover extra ``bot_*.py`` add-ons dropped beside this file.

    Anything matching ``bot_*.py`` that is not part of the built-in
    ``_MODULES`` list (and not this loader itself) is treated as an add-on,
    so new packs can be installed without editing anything.
    """
    import glob
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    _packs_dir = here
    skip = set(_MODULES) | {"bot_clicky"}
    found = []
    for path in sorted(glob.glob(os.path.join(_packs_dir, "bot_*.py"))):
        name = os.path.splitext(os.path.basename(path))[0]
        if name not in skip:
            found.append(name)
    return tuple(found)


def attach(bot):
    """Load every clicky add-on against the given JarvisBot instance."""
    loaded, seen = [], set()
    for name in _MODULES + _discover():
        if name in seen:
            continue
        seen.add(name)
        try:
            mod = __import__(name)
            controller = mod.attach(bot)
            loaded.append((name, controller))
        except Exception as exc:  # fail-soft, orb must survive
            print("WARNING: clicky add-on %s failed to load: %s" % (name, exc))
    return loaded


def detach(loaded):
    """Teardown helper (mainly for tests / restart flows)."""
    for name, controller in loaded:
        try:
            if controller is not None and hasattr(controller, "detach"):
                controller.detach()
        except Exception as exc:
            print("WARNING: clicky add-on %s failed to detach: %s" % (name, exc))

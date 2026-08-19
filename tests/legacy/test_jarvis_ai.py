import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import sys
import time

from main import ask_ai, load_api_key, GROQ_MODEL

PROMPTS = [
    "What time is it?",
    "Who are you?",
    "Tell me a one-line joke.",
    "What is 12 times 8?",
    "Explain the internet in two sentences.",
    "Name three planets.",
    "What is the capital of France?",
    "Say hello to my friends.",
    "Give me a motivational quote.",
    "What should I name a pet robot?"
]


def main():
    if not load_api_key():
        print("NO API KEY SET")
        sys.exit(1)
    print(f"Using model: {GROQ_MODEL}")
    passed = 0
    for i, prompt in enumerate(PROMPTS, 1):
        print(f"\n[{i}/10] PROMPT: {prompt}")
        try:
            reply = ask_ai(prompt)
            if not reply or reply.startswith("I hit an error") or reply == "__UNAUTHORIZED__":
                print(f"[{i}] FAILED: {reply}")
            else:
                print(f"[{i}] OK: {reply[:180]}")
                passed += 1
        except Exception as e:
            print(f"[{i}] ERROR: {e}")
        time.sleep(1)
    print(f"\nRESULT: {passed}/10 succeeded")


if __name__ == "__main__":
    main()

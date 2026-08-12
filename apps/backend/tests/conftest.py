import os
import sys

# Make `src.*` and the shared-types `models` importable regardless of cwd.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_BACKEND, "..", "..", "packages", "shared-types", "src"))

# test_demo_flow.py is an end-to-end script that needs a live server on :8000;
# run it directly with `python tests/test_demo_flow.py`.
collect_ignore = ["test_demo_flow.py"]

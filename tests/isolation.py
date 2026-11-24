"""Keeps the test suite away from the user's real runtime state.

Tools record undo entries and other transient state under
``$XDG_RUNTIME_DIR/happy-bot`` (``runtime_paths.runtime_root``), and
spending under ``$XDG_DATA_HOME`` (``spend.py``). Every test module imports
this first, which points both at one private temporary directory for the
whole test process, so running the tests never adds to, or reads, the
logged-in user's undo journal, action log or spending record. Tests that need their own runtime directory still patch it themselves.
The directory is removed when the process exits.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

if not os.environ.get("HAPPY_BOT_TEST_RUNTIME"):
    _runtime = tempfile.mkdtemp(prefix="happy-bot-tests-")
    os.chmod(_runtime, 0o700)
    os.environ["XDG_RUNTIME_DIR"] = _runtime
    os.makedirs(os.path.join(_runtime, "data"), mode=0o700)
    os.environ["XDG_DATA_HOME"] = os.path.join(_runtime, "data")
    os.environ["HAPPY_BOT_TEST_RUNTIME"] = _runtime
    atexit.register(shutil.rmtree, _runtime, True)

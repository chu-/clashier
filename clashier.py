#!/usr/bin/env python3
"""
Clashier source launcher.

Run through ``uv run clashier`` or an environment with this project's
dependencies installed. The package lives under ``src/``.
"""

import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
_VENV = os.path.join(_HERE, ".venv")
_PYTHON = os.path.join(_VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(_VENV, "bin", "python")
if __name__ == "__main__" and os.path.isfile(_PYTHON) and os.path.realpath(sys.prefix) != os.path.realpath(_VENV):
    os.execv(_PYTHON, [_PYTHON, os.path.realpath(__file__)] + sys.argv[1:])  # noqa: S606 - managed interpreter

_SRC = os.path.join(_HERE, "src")
# This file shares its name with the package; make sure the package wins.
sys.path[:] = [p for p in sys.path if os.path.realpath(p or os.curdir) != _HERE]
if os.path.isdir(_SRC):
    sys.path.insert(0, _SRC)
if not hasattr(sys.modules.get("clashier"), "__path__"):
    sys.modules.pop("clashier", None)

from clashier.cli.main import main  # noqa: E402

if __name__ == "__main__":
    main()

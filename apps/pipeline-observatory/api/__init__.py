"""Pipeline Observatory HTTP API (Mode A, verified backend; docs/api-contract.md).

Importing the package makes the pure domain (``domain/``) and the data layer (``data/``) importable when the app runs outside pytest
(pytest.ini already adds ``domain`` to the path).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "domain", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

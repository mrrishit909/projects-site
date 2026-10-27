"""ChangeWorks API (FastAPI, prefix /api/v1/changeworks)."""
import sys
from pathlib import Path

_DOMAIN = str(Path(__file__).resolve().parents[1] / "domain")
if _DOMAIN not in sys.path:
    sys.path.insert(0, _DOMAIN)

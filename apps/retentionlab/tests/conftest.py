"""Test configuration: a fixed API clock, so no test depends on the date it runs on (the fixtures are dated 2025-2026)."""
from datetime import datetime, timezone

import pytest

#: The server's "now" for every test unless a test freezes another instant: half a day after the golden fixture's ``as_of``, so a
#: command stamped by the server (a score, a publication) is already known when a report is read at READ_AS_OF (worlds.py).
T0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_clock():
    from api import clock
    clock.freeze(T0)
    yield T0
    clock.freeze(None)

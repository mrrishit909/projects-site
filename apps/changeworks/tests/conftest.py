"""Test configuration: a fixed API clock, so no test depends on the date it runs on (the fixtures are dated 2026-2028)."""
from datetime import datetime, timezone

import pytest

T0 = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_clock():
    from api import clock
    clock.freeze(T0)
    yield T0
    clock.freeze(None)

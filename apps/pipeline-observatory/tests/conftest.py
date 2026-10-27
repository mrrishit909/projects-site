"""Test configuration: a fixed API clock, so no test depends on the date it runs on (the fixtures are dated October 2026)."""
from datetime import datetime, timezone

import pytest

T0 = datetime(2026, 10, 26, 22, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_clock():
    from api import clock
    clock.freeze(T0)
    yield T0
    clock.freeze(None)


@pytest.fixture(autouse=True)
def sandbox_environment(monkeypatch):
    """C07 fault injection is allowed only when PIPELINE_ENVIRONMENT equals "sandbox" (D-09, R8-13): the tests say so explicitly."""
    monkeypatch.setenv("PIPELINE_ENVIRONMENT", "sandbox")

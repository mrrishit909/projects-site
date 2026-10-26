"""Every test starts and ends on the real server clock (``api.clock.now``): tests that need a decision stamped at a given
instant call ``support_db.set_now`` (decisions are stamped by the server, D-09, so a test cannot send ``decided_at``)."""
import pytest


@pytest.fixture(autouse=True)
def _real_server_clock():
    from api import clock
    real = clock.now
    yield
    clock.now = real

"""Instant-commissioning fixtures for historical financial-calculation tests.

The old economy tests assert exact market, staffing and ledger outputs *immediately*
after a build. They deliberately test a complete building; the new construction
integration suite independently tests the real delayed commissioning policy.
"""
from unittest import mock
import construction_stages


def _commission_immediately(db, marker, object_id, now):
    construction_stages.ensure(db, marker)
    db.execute(f'INSERT INTO construction_stages(object_id,stage,next_at) VALUES({marker},{marker},{marker})',
               (object_id, 'complete', 0))


def fast_construction(test_method):
    return mock.patch('construction_stages.register', new=_commission_immediately)(test_method)
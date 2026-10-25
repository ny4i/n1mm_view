"""
Tests for hooks.py - new_multiplier detection for zones and countries.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hooks import EventHooks


def _hooks():
    """EventHooks with no scripts configured and fire() captured."""
    h = EventHooks(SimpleNamespace())
    h.fired = []
    h.fire = lambda event, fields: h.fired.append((event, fields))
    return h


def _contact(**kw):
    fields = {'station': 'RADIO1', 'operator': 'NY4I', 'band': '20M',
              'callsign': 'VP2MAA', 'mult_value': '8', 'mult_is_new': False,
              'country': 'VP2M', 'country_is_new': False}
    fields.update(kw)
    return fields


class TestNewMultiplierEvent:

    def test_no_event_when_nothing_new(self):
        h = _hooks()
        h.on_contact(_contact())
        assert h.fired == []

    def test_new_zone_fires(self):
        h = _hooks()
        h.on_contact(_contact(mult_is_new=True))
        assert [e for e, _ in h.fired] == ['new_multiplier']

    def test_new_country_alone_fires(self):
        h = _hooks()
        h.on_contact(_contact(country_is_new=True))
        assert [e for e, _ in h.fired] == ['new_multiplier']

    def test_new_zone_and_country_fire_once(self):
        h = _hooks()
        h.on_contact(_contact(mult_is_new=True, country_is_new=True))
        assert [e for e, _ in h.fired] == ['new_multiplier']


class TestMultiplierEnv:

    def test_only_new_values_exported(self):
        h = EventHooks(SimpleNamespace())
        env = h._build_env('new_multiplier', _contact(country_is_new=True))
        assert env['N1MMV_NEW_MULTIPLIER'] == ''
        assert env['N1MMV_NEW_COUNTRY'] == 'VP2M'
        assert env['N1MMV_COUNTRY'] == 'VP2M'

    def test_new_zone_exported(self):
        h = EventHooks(SimpleNamespace())
        env = h._build_env('new_multiplier', _contact(mult_is_new=True))
        assert env['N1MMV_NEW_MULTIPLIER'] == '8'
        assert env['N1MMV_NEW_COUNTRY'] == ''

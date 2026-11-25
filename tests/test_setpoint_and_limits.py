"""Unit tests for the pure setpoint policy and current limits.

These modules have no Home Assistant imports, so the tests run with the
standard library only:  python3 -m unittest discover tests
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "unifi_ev_station"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"uev_{name}", PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


setpoint = _load("setpoint")
limits = _load("limits")

SetpointPolicy = setpoint.SetpointPolicy
SetpointState = setpoint.SetpointState
decide = setpoint.decide

POLICY = SetpointPolicy(min_amps=6, max_amps=32, min_increase_interval=30, reassert_interval=300)


def sent(state: SetpointState, value: int, now: float) -> None:
    state.record_sent(value, now, state.last_sent)


class LimitsTests(unittest.TestCase):
    def test_unknown_breaker_falls_back_to_32a_not_80a(self):
        self.assertEqual(limits.max_allowed(None, None), 32.0)

    def test_user_limit_wins_when_lower(self):
        self.assertEqual(limits.max_allowed(None, 16), 16.0)
        self.assertEqual(limits.max_allowed(60, 20), 20.0)

    def test_user_limit_cannot_raise_above_breaker(self):
        self.assertEqual(limits.max_allowed(40, 50), 32.0)

    def test_north_american_table_still_applies(self):
        self.assertEqual(limits.max_allowed(60, None), 48.0)
        self.assertEqual(limits.max_allowed(45, None), 36.0)

    def test_never_below_minimum(self):
        self.assertEqual(limits.max_allowed(None, 3), 6.0)


class ClampTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(POLICY.clamp(2), 6)
        self.assertEqual(POLICY.clamp(40), 32)
        self.assertEqual(POLICY.clamp(15.6), 16)


class DecisionTests(unittest.TestCase):
    def test_nothing_desired(self):
        self.assertFalse(decide(POLICY, SetpointState(), 0).send)

    def test_unknown_state_always_sends(self):
        d = decide(POLICY, SetpointState(desired=20), 0)
        self.assertEqual((d.send, d.value, d.reason), (True, 20, "unknown_state"))

    def test_decrease_is_immediate(self):
        s = SetpointState(desired=32)
        sent(s, 32, 0)
        s.desired = 10
        d = decide(POLICY, s, 1)
        self.assertEqual((d.send, d.value, d.reason), (True, 10, "decrease"))

    def test_increase_rate_limited_after_recent_increase(self):
        s = SetpointState(desired=10)
        sent(s, 10, 0)
        s.desired = 16
        sent(s, 16, 5)  # an increase at t=5
        s.desired = 20
        d = decide(POLICY, s, 20)
        self.assertEqual((d.send, d.reason), (False, "increase_rate_limited"))
        d = decide(POLICY, s, 36)
        self.assertEqual((d.send, d.value, d.reason), (True, 20, "increase"))

    def test_first_increase_after_decrease_is_allowed(self):
        s = SetpointState(desired=16)
        sent(s, 16, 0)
        s.desired = 8
        sent(s, 8, 1)
        s.desired = 12
        self.assertTrue(decide(POLICY, s, 2).send)

    def test_decrease_not_blocked_by_rate_limit(self):
        s = SetpointState(desired=10)
        sent(s, 10, 0)
        s.desired = 20
        sent(s, 20, 1)
        s.desired = 6
        d = decide(POLICY, s, 2)
        self.assertEqual((d.send, d.value), (True, 6))

    def test_unchanged_value_reasserted_periodically(self):
        s = SetpointState(desired=16)
        sent(s, 16, 0)
        self.assertEqual(decide(POLICY, s, 100).reason, "unchanged")
        d = decide(POLICY, s, 300)
        self.assertEqual((d.send, d.reason), (True, "reassert"))

    def test_failure_makes_state_unknown_and_retries(self):
        s = SetpointState(desired=16)
        sent(s, 16, 0)
        s.record_failure("timeout")
        self.assertTrue(s.pending)
        d = decide(POLICY, s, 1)
        self.assertEqual((d.send, d.reason), (True, "unknown_state"))

    def test_reconnect_forces_reassert(self):
        s = SetpointState(desired=16)
        sent(s, 16, 0)
        s.mark_unknown()
        self.assertEqual(decide(POLICY, s, 1).reason, "unknown_state")

    def test_desired_above_policy_is_clamped(self):
        s = SetpointState(desired=80)
        self.assertEqual(decide(POLICY, s, 0).value, 32)

    def test_pending_flag(self):
        s = SetpointState(desired=16)
        self.assertTrue(s.pending)
        sent(s, 16, 0)
        self.assertFalse(s.pending)


if __name__ == "__main__":
    unittest.main()

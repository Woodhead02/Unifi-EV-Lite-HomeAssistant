"""Charging-current setpoint policy.

This module has no Home Assistant imports so it can be unit-tested on its own.

The EV Station Lite does not report its active ``maxOutput`` back on every
firmware, so the integration cannot read what the charger is actually using.
To make the value trustworthy for load management, the coordinator keeps the
*desired* setpoint per charger and uses this policy to decide when to send it:

* Decreases are sent immediately. Lowering current is the safe direction.
* Increases are rate limited, so a noisy automation cannot make the charger
  oscillate and the household load has time to settle between steps.
* An unchanged value is re-sent ("re-asserted") periodically, and whenever
  the charger state is unknown (startup, reconnect, failed command), so a
  charger that rebooted or lost its setting converges back to the desired value.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SetpointPolicy:
    """Tunable limits for sending maximum-output commands."""

    min_amps: int = 6
    max_amps: int = 32
    min_increase_interval: float = 30.0
    reassert_interval: float = 300.0

    def clamp(self, amps: float) -> int:
        """Round and clamp a requested current into the allowed range."""
        value = int(round(amps))
        return max(self.min_amps, min(self.max_amps, value))


@dataclass
class SetpointState:
    """What Home Assistant wants and what it last sent to one charger."""

    desired: int | None = None
    last_sent: int | None = None
    last_sent_at: float | None = None
    last_increase_at: float | None = None
    last_error: str | None = None
    history: list[str] = field(default_factory=list)

    @property
    def pending(self) -> bool:
        """True when the desired value has not been confirmed as sent."""
        return self.desired is not None and self.desired != self.last_sent

    def mark_unknown(self) -> None:
        """Forget what the charger has, forcing the next decision to send."""
        self.last_sent = None
        self.last_sent_at = None

    def record_sent(self, value: int, now: float, previous: int | None) -> None:
        """Record a successful command."""
        if previous is not None and value > previous:
            self.last_increase_at = now
        self.last_sent = value
        self.last_sent_at = now
        self.last_error = None

    def record_failure(self, error: str) -> None:
        """Record a failed command; the charger's value is now unknown."""
        self.last_error = error
        self.mark_unknown()


@dataclass(frozen=True)
class Decision:
    """Outcome of evaluating a desired setpoint."""

    send: bool
    value: int | None
    reason: str


def decide(policy: SetpointPolicy, state: SetpointState, now: float) -> Decision:
    """Decide whether the desired setpoint should be sent now."""
    if state.desired is None:
        return Decision(False, None, "no_desired_value")

    value = policy.clamp(state.desired)

    if state.last_sent is None:
        # Unknown charger state: always (re)send. Sending the desired value is
        # the only way to know what the charger is limited to.
        return Decision(True, value, "unknown_state")

    if value < state.last_sent:
        return Decision(True, value, "decrease")

    if value == state.last_sent:
        if (
            state.last_sent_at is None
            or now - state.last_sent_at >= policy.reassert_interval
        ):
            return Decision(True, value, "reassert")
        return Decision(False, value, "unchanged")

    # value > last_sent: increase, rate limited.
    if (
        state.last_increase_at is None
        or now - state.last_increase_at >= policy.min_increase_interval
    ):
        return Decision(True, value, "increase")
    return Decision(False, value, "increase_rate_limited")

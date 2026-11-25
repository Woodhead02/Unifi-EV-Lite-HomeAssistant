"""Maximum-output limits. No Home Assistant imports, so it is unit-testable."""

from __future__ import annotations

# North American EVSE continuous-load table from the UniFi EV Station
# installation guide: breaker rating -> maximum continuous output (80% rule).
NEC_BREAKER_MAX_OUTPUT: dict[int, float] = {
    20: 16.0,
    30: 24.0,
    40: 32.0,
    50: 40.0,
    60: 48.0,
    80: 64.0,
    100: 80.0,
}

# IEC 61851 / SAE J1772: a charger cannot signal less than 6 A. If the
# verified limit is below this, charging has to stay off.
MIN_CHARGING_AMPS = 6.0
ABSOLUTE_MIN_AMPS = MIN_CHARGING_AMPS  # backwards-compatible name

NO_LIMIT_MESSAGE = (
    "No verified current limit for this charger: the console does not report "
    "a breaker size. Set 'Maximum current per charger' in the integration "
    "options to the limit your electrician approved."
)


def breaker_limited_max(breaker: float | None) -> float | None:
    """Return the maximum output implied by the configured breaker, if known."""
    if breaker is None or breaker <= 0:
        return None
    breaker_int = int(round(breaker))
    if breaker_int in NEC_BREAKER_MAX_OUTPUT:
        return NEC_BREAKER_MAX_OUTPUT[breaker_int]
    return breaker * 0.8


def max_allowed(breaker: float | None, user_max: float | None) -> float | None:
    """Return the highest current the integration may request, or None.

    The limit comes only from verified sources: the breaker size configured
    on the console, and the user's limit from the integration options. The
    lower one wins. If neither is known, return None; the integration then
    refuses to send any setpoint instead of guessing.

    The result is never raised to the 6 A minimum. A limit below 6 A means
    charging must stay off; see ``limit_problem``.
    """
    candidates: list[float] = []
    from_breaker = breaker_limited_max(breaker)
    if from_breaker is not None:
        candidates.append(from_breaker)
    if user_max is not None and user_max > 0:
        candidates.append(float(user_max))
    if not candidates:
        return None
    return min(candidates)


def limit_problem(limit: float | None) -> str | None:
    """Explain why no setpoint may be sent for ``limit``, or return None."""
    if limit is None:
        return NO_LIMIT_MESSAGE
    if limit < MIN_CHARGING_AMPS:
        return (
            f"The verified current limit is {limit:g} A, below the {MIN_CHARGING_AMPS:g} A "
            "minimum a charger can signal. Charging must stay off; no setpoint is sent."
        )
    return None

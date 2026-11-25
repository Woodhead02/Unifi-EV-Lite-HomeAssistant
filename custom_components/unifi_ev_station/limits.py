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

# The EU EV Station Lite is a 22 kW, 3 x 32 A charger. When nothing better is
# known, never offer more than this.
SAFE_FALLBACK_MAX_AMPS = 32.0
ABSOLUTE_MIN_AMPS = 6.0


def breaker_limited_max(breaker: float | None) -> float | None:
    """Return the maximum output implied by the configured breaker, if known."""
    if breaker is None or breaker <= 0:
        return None
    breaker_int = int(round(breaker))
    if breaker_int in NEC_BREAKER_MAX_OUTPUT:
        return NEC_BREAKER_MAX_OUTPUT[breaker_int]
    return breaker * 0.8


def max_allowed(breaker: float | None, user_max: float | None) -> float:
    """Return the highest current the integration will ever request.

    ``user_max`` is the installer's limit from the integration options and
    always wins when it is lower. Without breaker metadata the cap falls back
    to 32 A instead of the 80 A top of the North American table.
    """
    candidates = [SAFE_FALLBACK_MAX_AMPS]
    from_breaker = breaker_limited_max(breaker)
    if from_breaker is not None:
        candidates = [from_breaker]
    if user_max is not None and user_max > 0:
        candidates.append(user_max)
    return max(ABSOLUTE_MIN_AMPS, min(candidates))

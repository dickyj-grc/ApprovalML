# approvalml/duration.py
"""
Human-readable SLA duration parser for ApprovalML.

Converts duration strings to a float number of hours so all downstream SQL
and scoring logic (which works in hours) stays unchanged.

Supported units:
    ms  milliseconds
    s   seconds
    m   minutes
    h   hours
    d   days
    w   weeks
    M   months  (approximated as 30 days)
    y   years   (approximated as 365 days)

Examples:
    "4h"     → 4.0
    "10m"    → 0.16667
    "2d"     → 48.0
    "1h30m"  → 1.5
    "2d4h"   → 52.0
    "30s"    → 0.00833
    4        → 4.0   (plain numeric treated as hours — backwards compat)
    "4"      → 4.0   (plain numeric string)
"""

import re
from typing import Union

_UNIT_TO_HOURS: dict = {
    "ms": 1 / 3_600_000,
    "s":  1 / 3_600,
    "m":  1 / 60,
    "h":  1.0,
    "d":  24.0,
    "w":  24.0 * 7,
    "M":  24.0 * 30,
    "y":  24.0 * 365,
}

# Longest alternatives first (ms before m/s) to avoid partial matches.
_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|y|M|w|d|h|m|s)", re.ASCII)


def parse_sla_duration(value: Union[str, int, float, None]) -> float:
    """
    Parse an SLA duration value and return the equivalent number of hours.

    Raises ValueError for unrecognisable formats.
    Returns 0.0 for None / empty string (caller should treat 0 as "no SLA").
    """
    if value is None:
        return 0.0

    # Plain numeric — treat as hours (backwards compatibility with sla_hours: 4)
    if isinstance(value, (int, float)):
        return float(value)

    value = str(value).strip()
    if not value:
        return 0.0

    # Plain numeric string — same backwards compat
    try:
        return float(value)
    except ValueError:
        pass

    tokens = _TOKEN_RE.findall(value)
    if not tokens:
        raise ValueError(
            f"Unrecognised SLA duration: {value!r}. "
            "Use a duration string like '4h', '10m', '2d', '1h30m'."
        )

    # Guard against extra characters (e.g. "4h garbage")
    reconstructed = "".join(f"{num}{unit}" for num, unit in tokens)
    stripped = re.sub(r"\s+", "", value)
    if reconstructed != stripped:
        raise ValueError(
            f"Unrecognised SLA duration: {value!r}. "
            "Use a duration string like '4h', '10m', '2d', '1h30m'."
        )

    return sum(float(num) * _UNIT_TO_HOURS[unit] for num, unit in tokens)


def format_sla_hours(hours: float) -> str:
    """
    Convert a float hours value back to a human-readable duration string.
    Used for display in reports and notifications.
    """
    if hours <= 0:
        return "0h"
    total_seconds = round(hours * 3600)
    parts = []
    for unit, secs in [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]:
        if total_seconds >= secs:
            n, total_seconds = divmod(total_seconds, secs)
            parts.append(f"{n}{unit}")
    return "".join(parts) or "0s"

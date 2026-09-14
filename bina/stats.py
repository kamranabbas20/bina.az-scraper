"""Small statistics helpers.

Medians throughout, not means: Baku listing prices have a long right tail and a
handful of penthouses would drag every average off the market.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence


def clean(values: Iterable[Optional[float]]) -> list[float]:
    return [float(v) for v in values if v is not None]


def median(values: Iterable[Optional[float]]) -> Optional[float]:
    data = sorted(clean(values))
    if not data:
        return None
    middle = len(data) // 2
    if len(data) % 2:
        return data[middle]
    return (data[middle - 1] + data[middle]) / 2


def quantile(values: Iterable[Optional[float]], q: float) -> Optional[float]:
    """Linear-interpolation quantile, ``q`` in [0, 1]."""
    data = sorted(clean(values))
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    position = q * (len(data) - 1)
    low = int(position)
    high = min(low + 1, len(data) - 1)
    weight = position - low
    return data[low] * (1 - weight) + data[high] * weight


def nice_ticks(maximum: float, count: int = 5) -> list[float]:
    """Ticks at 1/2/2.5/5×10^n covering ``[0, maximum]``."""
    if maximum <= 0:
        return [0.0, 1.0]
    raw_step = maximum / max(count, 1)
    magnitude = 10 ** _floor_log10(raw_step)
    for multiple in (1, 2, 2.5, 5, 10):
        step = multiple * magnitude
        if step >= raw_step:
            break
    # Run past the maximum by one tick, so the top of the scale always
    # contains the largest value rather than clipping it.
    ticks, value = [], 0.0
    while True:
        ticks.append(round(value, 10))
        if value >= maximum:
            return ticks
        value += step


def nice_ticks_between(low: float, high: float, count: int = 5) -> list[float]:
    """Ticks covering ``[low, high]`` on a scale that need not start at zero.

    Bars must be measured from zero; a price *level* over time must not be, or
    every real movement is squashed into a flat line near the top.
    """
    if high <= low:
        high = low + max(abs(low) * 0.1, 1.0)
    raw_step = (high - low) / max(count, 1)
    magnitude = 10 ** _floor_log10(raw_step)
    for multiple in (1, 2, 2.5, 5, 10):
        step = multiple * magnitude
        if step >= raw_step:
            break
    start = (low // step) * step
    ticks, value = [], start
    while True:
        ticks.append(round(value, 10))
        if value >= high:
            return ticks
        value += step


def _floor_log10(value: float) -> int:
    exponent = 0
    if value <= 0:
        return 0
    while value < 1:
        value *= 10
        exponent -= 1
    while value >= 10:
        value /= 10
        exponent += 1
    return exponent


def trimmed(values: Sequence[float], low_q: float = 0.02, high_q: float = 0.98) -> list[float]:
    """Drop the extreme tails so a scatter or axis is not set by one outlier."""
    if not values:
        return []
    low = quantile(values, low_q)
    high = quantile(values, high_q)
    if low is None or high is None:
        return list(values)
    return [v for v in values if low <= v <= high]

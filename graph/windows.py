"""The windows of the monitoring of a benchmark: their range, from their 5th percentile to their 95th, and
the warm up of a curve over time."""

from __future__ import annotations

import numpy as np

# The range of the windows of a curve: the warm up of a long benchmark makes its lowest windows far
# from the others, the percentiles leave its first ones out
RANGE_PERCENTILES = (5, 95)


def finite_windows(serie) -> np.ndarray:
    """The windows of a serie, without the gaps of a device that did not answer, NaN."""
    windows = np.asarray(serie if serie is not None else [], dtype=float)
    return windows[np.isfinite(windows)]


def low_window(serie) -> float:
    windows = finite_windows(serie)
    return float(np.percentile(windows, RANGE_PERCENTILES[0])) if len(windows) else np.nan


def high_window(serie) -> float:
    windows = finite_windows(serie)
    return float(np.percentile(windows, RANGE_PERCENTILES[1])) if len(windows) else np.nan


def in_range(serie) -> np.ndarray:
    """Whether each window of a serie is from its 5th percentile to its 95th; all of them, but the gaps,
    when they are too few to tell."""
    windows = np.asarray(serie if serie is not None else [], dtype=float)
    finite = np.isfinite(windows)
    # The comparisons of a NaN being false, the gaps are out of the range
    with np.errstate(invalid="ignore"):
        kept = (windows >= low_window(windows)) & (windows <= high_window(windows))
    return kept if kept.sum() > 1 else finite


def kept_windows(serie) -> np.ndarray:
    """The windows of a serie from its 5th percentile to its 95th, all of them when they are too few to tell."""
    windows = np.asarray(serie if serie is not None else [], dtype=float)
    return windows[in_range(windows)]


def warm_up(serie) -> np.ndarray:
    """Whether each window of a curve over time is of its warm up: its first windows below its 5th percentile,
    after its first gaps, like the ramp up of the load; none when its windows are too few to tell, see
    in_range(). A dip or a peak later in the benchmark is not part of it."""
    windows = np.asarray(serie, dtype=float)
    warming = np.zeros(len(windows), dtype=bool)
    if np.array_equal(in_range(windows), np.isfinite(windows)):
        return warming
    low = low_window(windows)
    for index, value in enumerate(windows):
        if np.isnan(value) and not warming.any():
            continue
        # A gap or a window from the 5th percentile ends the warm up
        if not value < low:
            break
        warming[index] = True
    return warming


def without_warm_up(serie) -> np.ndarray:
    """A curve over time without its warm up, see warm_up(): NaN, a gap, in place of its windows."""
    windows = np.asarray(serie, dtype=float)
    return np.where(warm_up(windows), np.nan, windows)

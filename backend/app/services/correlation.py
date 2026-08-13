"""Correlation primitives for behavioral analytics.

Pure functions over paired numeric samples. No dependency beyond numpy so
the analytics engine keeps working in the existing container image.

Significance uses the Fisher z-transformation, the standard normal
approximation for the sampling distribution of a correlation coefficient:

    z = artanh(r) * sqrt(n - 3)          ~ N(0, 1) under H0: rho = 0
    p = erfc(|z| / sqrt(2))              (two-sided)

This needs ``n >= 4``; callers additionally enforce ``min_pairs``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Below this many complete observation pairs a coefficient is not reported
DEFAULT_MIN_PAIRS = 5

# Two-sided significance level
ALPHA = 0.05

# |r| thresholds -> qualitative label
_STRENGTH_BANDS = (
    (0.2, "negligible"),
    (0.4, "weak"),
    (0.6, "moderate"),
    (0.8, "strong"),
)


def clean_pairs(
    x: Sequence[Any], y: Sequence[Any]
) -> Tuple[np.ndarray, np.ndarray]:
    """Drop observation pairs where either side is missing or non-finite."""
    xs = np.asarray(list(x), dtype=float)
    ys = np.asarray(list(y), dtype=float)
    if xs.size == 0 or ys.size == 0:
        return np.empty(0), np.empty(0)
    size = min(xs.size, ys.size)
    xs, ys = xs[:size], ys[:size]
    mask = np.isfinite(xs) & np.isfinite(ys)
    return xs[mask], ys[mask]


def pearson(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Pearson product-moment correlation, or None when undefined."""
    if x.size < 2 or y.size < 2:
        return None
    xd = x - x.mean()
    yd = y - y.mean()
    denom = math.sqrt(float(np.dot(xd, xd)) * float(np.dot(yd, yd)))
    if denom == 0.0:
        # At least one series is constant — correlation is undefined
        return None
    r = float(np.dot(xd, yd)) / denom
    return float(np.clip(r, -1.0, 1.0))


def rank_average(values: np.ndarray) -> np.ndarray:
    """1-based ranks with ties resolved to their average rank."""
    n = values.size
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)

    ordered = values[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1] == ordered[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Spearman rank correlation — monotonic, robust to outliers."""
    if x.size < 2 or y.size < 2:
        return None
    return pearson(rank_average(x), rank_average(y))


def p_value(r: Optional[float], n: int) -> Optional[float]:
    """Two-sided p-value for H0: rho = 0 via the Fisher z-transformation."""
    if r is None or n < 4:
        return None
    bounded = float(np.clip(r, -0.999999, 0.999999))
    z = math.atanh(bounded) * math.sqrt(n - 3)
    return round(float(math.erfc(abs(z) / math.sqrt(2.0))), 6)


def strength(r: Optional[float]) -> str:
    if r is None:
        return "undefined"
    magnitude = abs(r)
    for threshold, label in _STRENGTH_BANDS:
        if magnitude < threshold:
            return label
    return "very_strong"


def direction(r: Optional[float]) -> str:
    if r is None:
        return "undefined"
    if r > 0:
        return "positive"
    if r < 0:
        return "negative"
    return "none"


def correlate(
    x: Sequence[Any],
    y: Sequence[Any],
    *,
    min_pairs: int = DEFAULT_MIN_PAIRS,
) -> Dict[str, Any]:
    """Correlate two aligned samples and describe the result.

    ``status`` is one of:
      - ``ok`` — a coefficient was computed
      - ``insufficient_data`` — fewer than ``min_pairs`` complete pairs
      - ``no_variance`` — enough pairs, but a series never changes
    """
    xs, ys = clean_pairs(x, y)
    n = int(xs.size)

    if n < max(2, min_pairs):
        return {
            "status": "insufficient_data",
            "n": n,
            "min_pairs": min_pairs,
            "pearson_r": None,
            "spearman_rho": None,
            "p_value": None,
            "significant": False,
            "strength": "undefined",
            "direction": "undefined",
        }

    r = pearson(xs, ys)
    if r is None:
        return {
            "status": "no_variance",
            "n": n,
            "min_pairs": min_pairs,
            "pearson_r": None,
            "spearman_rho": None,
            "p_value": None,
            "significant": False,
            "strength": "undefined",
            "direction": "undefined",
        }

    rho = spearman(xs, ys)
    p = p_value(r, n)
    return {
        "status": "ok",
        "n": n,
        "min_pairs": min_pairs,
        "pearson_r": round(r, 4),
        "spearman_rho": round(rho, 4) if rho is not None else None,
        "p_value": p,
        "significant": bool(p is not None and p < ALPHA),
        "strength": strength(r),
        "direction": direction(r),
    }


def significant_findings(pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Significant results, strongest first."""
    hits = [p for p in pairs if p.get("significant") and p.get("pearson_r") is not None]
    return sorted(hits, key=lambda p: abs(p["pearson_r"]), reverse=True)

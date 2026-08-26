"""Dependency-free deterministic bootstrap confidence intervals."""

from __future__ import annotations

import bisect
import math
import random
from typing import Dict, Iterable, List, Sequence


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = min(1.0, max(0.0, probability)) * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def bootstrap_mean_ci(
    values: Iterable[float],
    *,
    samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Dict[str, float]:
    """Return mean and percentile CI using a fixed local RNG."""
    clean: List[float] = [float(value) for value in values if value is not None]
    if not clean:
        return {"mean": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    mean = sum(clean) / len(clean)
    if len(clean) == 1 or samples <= 0:
        return {"mean": mean, "ci_low": mean, "ci_high": mean}
    rng = random.Random(seed)
    size = len(clean)
    estimates = []
    if all(value in (0.0, 1.0) for value in clean):
        # A resampled binary mean is Binomial(n, empirical_p) / n.  Building
        # its CDF once gives the exact non-parametric bootstrap distribution
        # without O(samples*n) Python loops for the large full matrix.
        successes = int(sum(clean))
        probability = successes / size
        if probability in (0.0, 1.0):
            estimates = [probability] * int(samples)
        else:
            log_probs = [
                math.lgamma(size + 1)
                - math.lgamma(k + 1)
                - math.lgamma(size - k + 1)
                + k * math.log(probability)
                + (size - k) * math.log1p(-probability)
                for k in range(size + 1)
            ]
            maximum = max(log_probs)
            probs = [math.exp(value - maximum) for value in log_probs]
            total = sum(probs)
            cumulative = []
            running = 0.0
            for value in probs:
                running += value / total
                cumulative.append(running)
            cumulative[-1] = 1.0
            estimates = [
                bisect.bisect_left(cumulative, rng.random()) / size
                for _ in range(int(samples))
            ]
    else:
        for _ in range(int(samples)):
            estimates.append(sum(rng.choices(clean, k=size)) / size)
    estimates.sort()
    alpha = (1.0 - confidence) / 2.0
    return {
        "mean": mean,
        "ci_low": _quantile(estimates, alpha),
        "ci_high": _quantile(estimates, 1.0 - alpha),
    }


def paired_bootstrap_difference(
    left: Sequence[float],
    right: Sequence[float],
    *,
    samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Dict[str, float]:
    if len(left) != len(right):
        raise ValueError("paired bootstrap inputs must have equal length")
    differences = [float(a) - float(b) for a, b in zip(left, right)]
    return bootstrap_mean_ci(differences, samples=samples, confidence=confidence, seed=seed)

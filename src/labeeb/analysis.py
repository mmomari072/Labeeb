"""Dependency-light sensitivity and statistical analysis APIs."""

import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd

from .exceptions import LabeebError


class AnalysisError(LabeebError):
    """Raised when analysis inputs are invalid or incompatible."""


def _input_frame(inputs: Any, output: Sequence[float]) -> pd.DataFrame:
    frame = inputs.to_frame() if isinstance(inputs, pd.Series) else pd.DataFrame(inputs)
    values = np.asarray(output, dtype=float)
    if frame.empty or len(frame) != len(values):
        raise AnalysisError("Inputs and output must contain the same non-zero number of rows")
    if not all(np.issubdtype(dtype, np.number) for dtype in frame.dtypes):
        raise AnalysisError("Sensitivity inputs must be numeric")
    return frame.astype(float).assign(_output=values)


def correlation_analysis(inputs: Any, output: Sequence[float]) -> pd.DataFrame:
    """Return Pearson and Spearman correlations for each input parameter."""
    frame = _input_frame(inputs, output)
    inputs_frame = frame.drop(columns="_output")
    ranked = inputs_frame.rank(method="average")
    output_rank = frame["_output"].rank(method="average")
    return pd.DataFrame(
        {
            "pearson": inputs_frame.corrwith(frame["_output"], method="pearson"),
            "spearman": ranked.corrwith(output_rank, method="pearson"),
        }
    )


def morris_screening(samples: Sequence[Sequence[float]], output: Sequence[float]) -> pd.DataFrame:
    """Estimate Morris elementary-effect mean and spread from one-step paths."""
    values = np.asarray(samples, dtype=float)
    responses = np.asarray(output, dtype=float)
    if values.ndim != 2 or len(values) != len(responses) or len(values) < 2:
        raise AnalysisError("Morris samples must be a non-empty 2D matrix aligned with output")
    effects: List[List[float]] = [[] for _ in range(values.shape[1])]
    for index in range(len(values) - 1):
        changed = np.flatnonzero(~np.isclose(values[index + 1], values[index]))
        if len(changed) != 1:
            continue
        parameter = int(changed[0])
        delta = values[index + 1, parameter] - values[index, parameter]
        if delta:
            effects[parameter].append(float((responses[index + 1] - responses[index]) / delta))
    if any(not values for values in effects):
        raise AnalysisError("Morris samples must contain an adjacent one-parameter step for every input")
    return pd.DataFrame(
        {
            "mean_effect": [float(np.mean(item)) for item in effects],
            "mean_absolute_effect": [float(np.mean(np.abs(item))) for item in effects],
            "std_effect": [float(np.std(item)) for item in effects],
        },
        index=[f"x{index}" for index in range(values.shape[1])],
    )


def sobol_indices(
    model_a: Sequence[float], model_b: Sequence[float], cross_samples: Sequence[Sequence[float]]
) -> Tuple[np.ndarray, np.ndarray]:
    """Estimate Sobol first-order and total indices using Saltelli samples.

    ``cross_samples[:, i]`` must contain model evaluations with parameter ``i``
    taken from the second sample matrix and all other parameters from the first.
    """
    a = np.asarray(model_a, dtype=float)
    b = np.asarray(model_b, dtype=float)
    cross = np.asarray(cross_samples, dtype=float)
    if a.ndim != 1 or b.shape != a.shape or cross.ndim != 2 or cross.shape[0] != len(a):
        raise AnalysisError("Sobol model arrays and cross-sample matrix have incompatible shapes")
    variance = float(np.var(np.concatenate((a, b))))
    if variance <= 0:
        raise AnalysisError("Sobol model output variance must be positive")
    first = np.mean(b[:, None] * (cross - a[:, None]), axis=0) / variance
    total = 0.5 * np.mean((a[:, None] - cross) ** 2, axis=0) / variance
    return first, total


def wilks_sample_size(coverage: float = 0.95, confidence: float = 0.95, sides: int = 1) -> int:
    """Return the minimum Wilks order-statistic sample size.

    ``sides=1`` uses the one-sided maximum/minimum criterion; ``sides=2``
    uses the two-sided minimum-and-maximum criterion.
    """
    if not 0 < coverage < 1 or not 0 < confidence < 1 or sides not in (1, 2):
        raise AnalysisError("coverage and confidence must be in (0, 1), and sides must be 1 or 2")
    for size in range(1, 100000):
        tail = coverage ** size
        if sides == 2:
            tail += size * (1 - coverage) * coverage ** (size - 1)
        if 1 - tail >= confidence:
            return size
    raise AnalysisError("Wilks sample-size search exceeded its safety limit")

"""
Sampling methods for sensitivity analysis, uncertainty analysis, and parameter sweeps.
Includes Grid Sweep (Full Factorial Design) and Discrete Probability Samplers.
"""

import itertools
import logging
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

from .exceptions import SamplingError

logger = logging.getLogger(__name__)


def uniform_sample(start: float, end: float, size: int = 1) -> np.ndarray:
    """
    Generate uniform random sample(s).

    Args:
        start: Lower bound.
        end: Upper bound.
        size: Sample size.
    """
    return np.random.uniform(start, end, size)


def normal_sample(mean: float, std: float, size: int = 1) -> np.ndarray:
    """
    Generate normal random sample(s).

    Args:
        mean: Distribution mean.
        std: Distribution standard deviation.
        size: Sample size.
    """
    return np.random.normal(mean, std, size)


def latin_hypercube_sample(
    bounds: List[Any], size: int, seed: Optional[int] = None, rng: Optional[Any] = None
) -> np.ndarray:
    """Generate a reproducible Latin-hypercube design over ``(low, high)`` bounds."""
    if size < 1 or not bounds:
        raise SamplingError("Latin-hypercube size and bounds must be non-empty")
    if any(len(bound) != 2 or float(bound[0]) > float(bound[1]) for bound in bounds):
        raise SamplingError("Each Latin-hypercube bound must be an ordered (low, high) pair")
    generator = rng if rng is not None else np.random.default_rng(seed)
    design = np.empty((size, len(bounds)), dtype=float)
    for column, (low, high) in enumerate(bounds):
        strata = (np.arange(size) + generator.random(size)) / size
        generator.shuffle(strata)
        design[:, column] = float(low) + strata * (float(high) - float(low))
    return design


def halton_sample(size: int, dimensions: int, skip: int = 0) -> np.ndarray:
    """Generate a dependency-free Halton low-discrepancy design in ``[0, 1)``."""
    if size < 1 or dimensions < 1 or skip < 0:
        raise SamplingError("Halton size and dimensions must be positive; skip cannot be negative")

    def primes(count: int) -> List[int]:
        found: List[int] = []
        candidate = 2
        while len(found) < count:
            if all(candidate % prime for prime in found):
                found.append(candidate)
            candidate += 1
        return found

    def van_der_corput(index: int, base: int) -> float:
        value = 0.0
        denominator = 1.0
        while index:
            index, remainder = divmod(index, base)
            denominator *= base
            value += remainder / denominator
        return value

    bases = primes(dimensions)
    return np.array(
        [[van_der_corput(row + skip + 1, base) for base in bases] for row in range(size)],
        dtype=float,
    )


def sample(size: int = 0) -> List[int]:
    """
    Generate a list of integers from 0 to size-1.
    """
    return list(range(size))


def product(values: List[int]) -> int:
    """
    Calculate product of elements in a list. Returns 1 if empty.
    """
    p = 1
    for val in values:
        p *= val
    return p if values else 1


class DiscreteSampling:
    """
    Random object generator based on weighted probability values.
    """

    def __init__(self, rng: Optional[Any] = None):
        """Initialize empty DiscreteSampling."""
        self.name: str = "OMARI"
        self.values: List[Any] = []
        self.probs: List[float] = []
        self.cdf: List[float] = []
        self.rng: Any = rng if rng is not None else random

    def define_sample(
        self,
        values: Optional[List[Any]] = None,
        probs: Optional[List[float]] = None,
    ) -> "DiscreteSampling":
        """
        Define sample space with corresponding probabilities.

        Args:
            values: List of object values.
            probs: Weighting factors (probabilities) for each object.
        """
        self.values = values if values is not None else ["A", "B", "C", "D"]
        self.probs = probs if probs is not None else [0.2, 0.3, 0.4, 0.1]

        if len(self.values) != len(self.probs):
            raise SamplingError("Values and probabilities lists must be of the same length")
        if not self.values:
            raise SamplingError("Values and probabilities must not be empty")
        if any(not math.isfinite(float(p)) or p < 0 for p in self.probs):
            raise SamplingError("Probabilities must be finite and non-negative")

        # Calculate CDF
        self.cdf = [0.0]
        for p in self.probs:
            self.cdf.append(self.cdf[-1] + p)

        # Normalize CDF in case probabilities don't sum to exactly 1.0
        total = self.cdf[-1]
        if total <= 0:
            raise SamplingError("Probability total must be greater than zero")
        self.cdf = [val / total for val in self.cdf]
        return self

    def get_random_sample(self, n: int = 1) -> Union[Any, List[Any]]:
        """
        Get n random samples according to the defined distribution.

        Args:
            n: Number of samples to return.
        """
        if not self.cdf:
            raise SamplingError("Distribution CDF is not defined. Call define_sample first.")

        if n > 1:
            return [self.get_random_sample() for _ in range(n)]

        r = self.rng.random()
        for i in range(1, len(self.cdf)):
            if self.cdf[i - 1] <= r < self.cdf[i]:
                return self.values[i - 1]

        return self.values[-1]

    def stat(self, m: int = 100) -> Dict[Any, float]:
        """
        Generate statistical distribution of m random samples.

        Args:
            m: Iteration count to generate statistics.
        """
        samples = self.get_random_sample(m)
        if not isinstance(samples, list):
            samples = [samples]

        stats = {}
        total = len(samples)
        for val in self.values:
            count = sum(1 for item in samples if item == val)
            stats[val] = count / total if total > 0 else 0.0
        return stats


class FOATConstructor:
    """
    Grid Sweep / Full Factorial Design matrix constructor.
    Generates all combinations of parameters.
    """

    def __init__(self, case_name: Optional[str] = None):
        """
        Initialize Grid Sweep Constructor.

        Args:
            case_name: Case sweep label.
        """
        self.name: Optional[str] = case_name
        self.description: str = "Grid Sweep Factorial Constructor"
        self.cases: Dict[str, List[Any]] = {}
        self.samples: Dict[str, List[Any]] = {}

    def add_case(self, *cases: Dict[str, List[Any]]) -> None:
        """Add dict(s) mapping parameter name to its list of search values."""
        for c in cases:
            for attr, vals in c.items():
                self.cases[attr] = vals

    def construct(self) -> Dict[str, List[Any]]:
        """
        Construct the grid search design matrix.

        Returns:
            Dictionary containing mapped parameter lists and their indices.
        """
        if not self.cases:
            self.samples = {}
            return self.samples

        attrs = list(self.cases.keys())
        value_lists = [self.cases[attr] for attr in attrs]

        # Use itertools.product to cleanly compute Cartesian product
        combinations = list(itertools.product(*[range(len(vals)) for vals in value_lists]))

        self.samples = {}
        for attr in attrs:
            self.samples[f"__{attr}_index__"] = []
            self.samples[attr] = []

        for combo in combinations:
            for idx, attr in enumerate(attrs):
                val_idx = combo[idx]
                val = self.cases[attr][val_idx]
                self.samples[f"__{attr}_index__"].append(val_idx)
                self.samples[attr].append(val)

        return self.samples


class OATConstructor(FOATConstructor):
    """One-at-a-time design constructor using each parameter's first value as baseline."""

    def __init__(self, case_name: Optional[str] = None):
        super().__init__(case_name=case_name)
        self.description = "One-at-a-Time Sweep Constructor"

    def construct(self) -> Dict[str, List[Any]]:
        """Construct a baseline row plus one-parameter-at-a-time variations."""
        if not self.cases:
            self.samples = {}
            return self.samples

        attrs = list(self.cases.keys())
        for attr in attrs:
            if not self.cases[attr]:
                raise SamplingError(f"OAT values for attribute '{attr}' must not be empty")

        self.samples = {attr: [] for attr in attrs}
        self.samples.update({f"__{attr}_index__": [] for attr in attrs})
        baseline = {attr: values[0] for attr, values in self.cases.items()}
        baseline_indices = {attr: 0 for attr in attrs}

        def append_case(values: Dict[str, Any], indices: Dict[str, int]) -> None:
            for attr in attrs:
                self.samples[attr].append(values[attr])
                self.samples[f"__{attr}_index__"].append(indices[attr])

        append_case(baseline, baseline_indices)
        for attr in attrs:
            for index, value in enumerate(self.cases[attr][1:], start=1):
                values = dict(baseline)
                indices = dict(baseline_indices)
                values[attr] = value
                indices[attr] = index
                append_case(values, indices)
        return self.samples
def correlated_normal_sample(
    means: Sequence[float],
    cov: Sequence[Sequence[float]],
    size: int = 1,
    seed: Optional[int] = None,
    rng: Optional[Any] = None,
) -> np.ndarray:
    """Draw samples from a multivariate normal distribution with correlation.

    Args:
        means: Mean vector (length d).
        cov: d x d covariance matrix. Correlations enter through the off-diagonal
            entries; the matrix must be symmetric positive semi-definite (tiny
            negative eigenvalues from float rounding are tolerated).
        size: Number of joint samples to draw.
        seed: Optional reproducibility seed (local RandomState; global stream
            untouched when provided).
        rng: Optional pre-built random generator (np.random.RandomState or
            Generator). Takes precedence over ``seed``.

    Returns:
        Array of shape ``(size, d)`` — each row is one joint draw, so columns of
        the result can seed several ``Database`` attributes that stay correlated.

    Raises:
        SamplingError: On dimension mismatches, non-finite inputs, non-PSD
            covariance (beyond rounding tolerance), or invalid ``size``.
    """
    if not isinstance(size, int) or size < 1:
        raise SamplingError(f"Sample size must be a positive integer, got {size!r}")
    mean_vec = np.asarray(means, dtype=float)
    if mean_vec.ndim != 1 or mean_vec.size < 1:
        raise SamplingError("Means must be a non-empty 1D sequence")
    cov_mat = np.asarray(cov, dtype=float)
    if cov_mat.shape != (mean_vec.size, mean_vec.size):
        raise SamplingError(
            f"Covariance must be {mean_vec.size}x{mean_vec.size} to match {mean_vec.size} means, "
            f"got shape {cov_mat.shape}"
        )
    if not np.all(np.isfinite(mean_vec)) or not np.all(np.isfinite(cov_mat)):
        raise SamplingError("Means and covariance must contain only finite values")
    if not np.allclose(cov_mat, cov_mat.T):
        raise SamplingError("Covariance matrix must be symmetric")
    eigen = np.linalg.eigvalsh(cov_mat)
    if eigen.min() < -1e-8:
        raise SamplingError(
            "Covariance matrix is not positive semi-definite "
            f"(smallest eigenvalue {eigen.min():.2e}); correlations must satisfy |rho| <= 1"
        )
    if np.any(np.diag(cov_mat) < 0.0):
        raise SamplingError("Covariance diagonal (variances) must be non-negative")

    if rng is not None:
        rng_obj = rng
    elif seed is not None:
        rng_obj = np.random.RandomState(seed)
    else:
        rng_obj = np.random
    return np.asarray(rng_obj.multivariate_normal(mean_vec, cov_mat, size), dtype=float)


def truncated_normal_sample(
    mean: float,
    std: float,
    low: Optional[float] = None,
    high: Optional[float] = None,
    size: int = 1,
    seed: Optional[int] = None,
    rng: Optional[Any] = None,
) -> np.ndarray:
    """Draw from a normal distribution truncated to ``[low, high]``.

    Pure-numpy rejection sampling keeps Labeeb dependency-free (no SciPy).
    One-sided truncation is allowed by omitting the other bound.

    Args:
        mean: Distribution mean.
        std: Distribution standard deviation (must be > 0).
        low: Optional lower bound (inclusive).
        high: Optional upper bound (inclusive).
        size: Number of samples to return.
        seed: Optional reproducibility seed (local RandomState).
        rng: Optional pre-built random generator; takes precedence over ``seed``.

    Returns:
        Array of ``size`` samples all inside the truncation interval.

    Raises:
        SamplingError: On invalid bounds/std/size, or when the interval is so
            far into the tail that rejection sampling cannot fill the request.
    """
    if not isinstance(size, int) or size < 1:
        raise SamplingError(f"Sample size must be a positive integer, got {size!r}")
    if not (np.isfinite(mean) and np.isfinite(std)) or std <= 0.0:
        raise SamplingError("Mean must be finite and std must be positive")
    lo = -float("inf") if low is None else float(low)
    hi = float("inf") if high is None else float(high)
    if low is None and high is None:
        raise SamplingError("At least one truncation bound is required (low and/or high)")
    if lo > hi:
        raise SamplingError(f"Truncation bounds are inverted: low={lo} > high={hi}")
    if lo == hi:
        raise SamplingError(f"Truncation interval is degenerate: low == high == {lo}")

    if rng is not None:
        rng_obj = rng
    elif seed is not None:
        rng_obj = np.random.RandomState(seed)
    else:
        rng_obj = np.random

    accepted: List[float] = []
    chunk_size = 4096
    max_chunks = 8192  # ~33.5M proposals cap before giving up on pathological tails
    for _ in range(max_chunks):
        batch = rng_obj.normal(mean, std, chunk_size)
        mask = (batch >= lo) & (batch <= hi)
        accepted.extend(batch[mask].tolist())
        if len(accepted) >= size:
            return np.asarray(accepted[:size], dtype=float)
    raise SamplingError(
        f"Truncation interval [{lo}, {hi}] rejected too many proposals for N(mean={mean}, "
        f"std={std}); widen the interval or reduce the sample size"
    )

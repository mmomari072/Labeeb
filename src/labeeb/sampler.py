"""
Sampling methods for sensitivity analysis, uncertainty analysis, and parameter sweeps.
Includes Grid Sweep (Full Factorial Design) and Discrete Probability Samplers.
"""

import itertools
import logging
import random
from typing import Any, Dict, List, Optional, Union

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

    def __init__(self):
        """Initialize empty DiscreteSampling."""
        self.name: str = "OMARI"
        self.values: List[Any] = []
        self.probs: List[float] = []
        self.cdf: List[float] = []

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

        # Calculate CDF
        self.cdf = [0.0]
        for p in self.probs:
            self.cdf.append(self.cdf[-1] + p)

        # Normalize CDF in case probabilities don't sum to exactly 1.0
        total = self.cdf[-1]
        if total > 0:
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

        r = random.random()
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

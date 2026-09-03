"""V2-UQ-01: correlated multivariate sampling and bounded/truncated normal
sampling (plan Task 5 slice). Focused tests — written first (RED)."""

import numpy as np
import pytest

from labeeb.exceptions import SamplingError
from labeeb.sampler import (
    correlated_normal_sample,
    truncated_normal_sample,
    uniform_sample,
)

MEANS = [10.0, 100.0]
COV = [[4.0, 1.6], [1.6, 9.0]]  # correlation 1.6/sqrt(36)=0.2667


# ---------------------------------------------------------------- multivariate

def test_correlated_normal_shape_and_mean():
    samples = correlated_normal_sample(MEANS, COV, size=4000, seed=7)
    assert samples.shape == (4000, 2)
    assert np.allclose(samples.mean(axis=0), MEANS, atol=0.25)


def test_correlated_normal_covariance_and_sign():
    samples = correlated_normal_sample(MEANS, COV, size=8000, seed=11)
    empirical = np.cov(samples.T)
    assert abs(empirical[0, 1]) > 0.1  # dependency actually present
    assert empirical[0, 1] > 0  # same sign as specified correlation
    assert abs(empirical[0, 1] / np.sqrt(empirical[0, 0] * empirical[1, 1]) - 0.2667) < 0.06


def test_correlated_normal_seed_reproducible():
    a = correlated_normal_sample(MEANS, COV, size=500, seed=42)
    b = correlated_normal_sample(MEANS, COV, size=500, seed=42)
    assert np.array_equal(a, b)


def test_correlated_normal_validation_errors():
    with pytest.raises(SamplingError):
        correlated_normal_sample([1.0, 2.0], [[1.0, 0.0]], size=10)  # cov 1x2 vs 2 means
    with pytest.raises(SamplingError):
        correlated_normal_sample([1.0], [[1.0, 0.0], [0.0, 1.0]], size=10)  # mean count
    with pytest.raises(SamplingError):
        correlated_normal_sample([1.0, 2.0], [[1.0, 0.0], [0.0, -1.0]], size=10)  # -ve var
    with pytest.raises(SamplingError):
        correlated_normal_sample(MEANS, COV, size=0)


def test_correlated_normal_single_dimension():
    out = correlated_normal_sample([5.0], [[2.0]], size=200, seed=3)
    assert out.shape == (200, 1)
    assert abs(out.mean() - 5.0) < 0.5


# ---------------------------------------------------------------- truncated

def test_truncated_normal_respects_bounds():
    samples = truncated_normal_sample(0.0, 1.0, low=-1.0, high=1.0, size=4000, seed=5)
    assert samples.min() >= -1.0
    assert samples.max() <= 1.0
    assert abs(samples.mean()) < 0.15  # symmetric truncation keeps mean ~0


def test_truncated_normal_skewed_bounds_shift_mean():
    samples = truncated_normal_sample(0.0, 1.0, low=1.0, high=None, size=4000, seed=9)
    assert samples.min() >= 1.0
    assert samples.mean() > 1.2  # truncated-left tail pulls mean up
    assert samples.shape == (4000,)


def test_truncated_normal_low_only_and_high_only():
    low = truncated_normal_sample(0.0, 1.0, low=-0.5, size=2000, seed=1)
    high = truncated_normal_sample(0.0, 1.0, high=0.5, size=2000, seed=2)
    assert low.min() >= -0.5
    assert high.max() <= 0.5


def test_truncated_normal_seed_reproducible():
    a = truncated_normal_sample(2.0, 0.5, low=1.0, high=3.0, size=300, seed=8)
    b = truncated_normal_sample(2.0, 0.5, low=1.0, high=3.0, size=300, seed=8)
    assert np.array_equal(a, b)


def test_truncated_normal_validation_errors():
    with pytest.raises(SamplingError):
        truncated_normal_sample(0.0, 1.0, low=1.0, high=0.0, size=100)  # inverted
    with pytest.raises(SamplingError):
        truncated_normal_sample(0.0, -1.0, size=100)  # negative std
    with pytest.raises(SamplingError):
        truncated_normal_sample(0.0, 1.0, size=0)
    with pytest.raises(SamplingError):
        truncated_normal_sample(0.0, 1.0, low=0.0, high=0.0, size=100)  # degenerate


def test_truncated_bounds_deliver_requested_count_when_narrow():
    # heavy truncation (0.1% of the mass) must still return full size
    samples = truncated_normal_sample(0.0, 1.0, low=3.0, high=3.5, size=200, seed=4)
    assert len(samples) == 200
    assert samples.min() >= 3.0 and samples.max() <= 3.5


# ------------------------------------------------------- end-to-end with Database

def test_add_sampled_attribute_with_truncated_sampler():
    from labeeb.database import Database

    db = Database(data={"case": [0, 1, 2]})
    db.add_sampled_attribute(
        "dose", lambda count: truncated_normal_sample(10.0, 2.0, low=5.0, high=15.0, size=count, seed=2),
        size=3,
    )
    assert len(db["dose"]) == 3
    assert min(db["dose"]) >= 5.0
    assert max(db["dose"]) <= 15.0


def test_add_sampled_attribute_with_correlated_draws():
    from labeeb.database import Database

    n = 500
    # valid covariance: var 900/0.04, rho = 3/sqrt(900*0.04) = 0.5
    joint = correlated_normal_sample([300.0, 1.0], [[900.0, 3.0], [3.0, 0.04]], size=n, seed=6)
    assert float(np.corrcoef(joint[:, 0], joint[:, 1])[0, 1]) > 0.2
    db = Database(data={"temperature": joint[:, 0].tolist(), "pressure": joint[:, 1].tolist()})
    assert len(db["temperature"]) == n


def test_uniform_still_available_for_regression():
    u = uniform_sample(0.0, 1.0, 100)
    assert u.min() >= 0.0 and u.max() <= 1.0

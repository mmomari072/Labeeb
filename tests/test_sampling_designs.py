import numpy as np
import pytest

from labeeb.exceptions import SamplingError
from labeeb.sampler import SimplexDOE, halton_sample, latin_hypercube_sample


def test_latin_hypercube_is_reproducible_and_bounded():
    first = latin_hypercube_sample([(0.0, 1.0), (10.0, 20.0)], 8, seed=7)
    second = latin_hypercube_sample([(0.0, 1.0), (10.0, 20.0)], 8, seed=7)
    assert first.shape == (8, 2)
    assert (first == second).all()
    assert ((first[:, 0] >= 0.0) & (first[:, 0] <= 1.0)).all()


def test_halton_design_has_expected_shape_and_values():
    values = halton_sample(4, 2, skip=0)
    assert values.shape == (4, 2)
    assert values.tolist() == [[0.5, 1.0 / 3.0], [0.25, 2.0 / 3.0], [0.75, 1.0 / 9.0], [0.125, 4.0 / 9.0]]


def test_simplex_doe_samples_interior_of_sum_constrained_region():
    values = SimplexDOE(total=10, min_values=[1, 2], seed=7).generate(500, 2)

    assert values.shape == (500, 2)
    assert np.all(values >= np.array([1, 2]))
    assert np.all(values.sum(axis=1) <= 10)
    assert np.any(values.sum(axis=1) < 9.9)
    assert np.all(values.sum(axis=1) > 3)


def test_simplex_doe_allows_minima_equal_to_total():
    values = SimplexDOE(total=5, min_values=[2, 3], seed=7).generate(3, 2)

    assert np.array_equal(values, np.array([[2, 3], [2, 3], [2, 3]], dtype=float))


def test_simplex_doe_rejects_mismatched_or_invalid_minima():
    with pytest.raises(SamplingError, match="one minimum per variable"):
        SimplexDOE(total=10, min_values=[0, 1, 2]).generate(5, 2)
    with pytest.raises(SamplingError, match="finite"):
        SimplexDOE(total=float("inf")).generate(5, 2)

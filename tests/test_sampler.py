import random

import pytest

from labeeb.sampler import DiscreteSampling, FOATConstructor
from labeeb.exceptions import SamplingError


def test_discrete_sampling():
    ds = DiscreteSampling()
    ds.define_sample(values=["A", "B"], probs=[0.7, 0.3])
    assert len(ds.cdf) == 3
    assert ds.cdf[0] == 0.0
    assert ds.cdf[-1] == 1.0

    samples = ds.get_random_sample(100)
    assert len(samples) == 100
    assert all(s in ["A", "B"] for s in samples)

    stats = ds.stat(m=500)
    assert "A" in stats
    assert "B" in stats
    assert 0.6 <= stats["A"] <= 0.8  # Reasonable tolerance for probability


@pytest.mark.parametrize(
    "values, probs",
    [([], []), (["A"], []), (["A"], [-1.0]), (["A"], [float("nan")]), (["A"], [0.0])],
)
def test_discrete_sampling_rejects_invalid_distributions(values, probs):
    with pytest.raises(SamplingError):
        DiscreteSampling().define_sample(values=values, probs=probs)


def test_discrete_sampling_rejects_infinite_and_mismatched_probabilities():
    with pytest.raises(SamplingError):
        DiscreteSampling().define_sample(values=["A"], probs=[float("inf")])
    with pytest.raises(SamplingError):
        DiscreteSampling().define_sample(values=["A", "B"], probs=[1.0])


def test_discrete_sampling_accepts_injected_rng_for_reproducibility():
    first = DiscreteSampling(rng=random.Random(42)).define_sample(["A", "B"], [1.0, 1.0])
    second = DiscreteSampling(rng=random.Random(42)).define_sample(["A", "B"], [1.0, 1.0])

    assert first.get_random_sample(20) == second.get_random_sample(20)


def test_foat_constructor_grid_sweep():
    # FOATConstructor generates Cartesian product of parameter lists
    constructor = FOATConstructor()
    constructor.add_case(
        {"a": [1, 2], "b": ["x", "y", "z"]}
    )
    result = constructor.construct()

    # Combinations count: 2 * 3 = 6
    assert len(result["a"]) == 6
    assert len(result["b"]) == 6

    # Verify matching pairs
    expected_pairs = [
        (1, "x"), (1, "y"), (1, "z"),
        (2, "x"), (2, "y"), (2, "z")
    ]
    actual_pairs = list(zip(result["a"], result["b"]))
    assert actual_pairs == expected_pairs

    # Verify indices
    expected_indices = [
        (0, 0), (0, 1), (0, 2),
        (1, 0), (1, 1), (1, 2)
    ]
    actual_indices = list(zip(result["__a_index__"], result["__b_index__"]))
    assert actual_indices == expected_indices

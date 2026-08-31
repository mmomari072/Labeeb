from labeeb.sampler import halton_sample, latin_hypercube_sample


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

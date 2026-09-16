import numpy as np
import pytest

from labeeb.surrogates import GaussianProcessSurrogate, PolynomialSurrogate, RadialBasisSurrogate
from labeeb.exceptions import OptimizationError


def test_polynomial_surrogate_accepts_single_prediction_row_and_preserves_log_scale():
    x = np.linspace(0, 1, 10).reshape(-1, 1)
    y = np.exp(1 + 2 * x[:, 0])
    model = PolynomialSurrogate(degree=1, log_transform=True).fit(x, y)

    prediction = model.predict(np.array([0.25]))

    assert prediction.shape == (1,)
    assert prediction[0] == pytest.approx(np.exp(1.5), rel=1e-6)


def test_gp_uncertainty_uses_transformed_mean_for_delta_method():
    pytest.importorskip("sklearn")
    x = np.linspace(0, 1, 8).reshape(-1, 1)
    y = np.exp(1 + 2 * x[:, 0])
    model = GaussianProcessSurrogate(alpha=1e-5, log_transform=True).fit(x, y)
    query = np.array([[0.35], [0.65]])
    transformed_mean, transformed_std = model.gp.predict(query, return_std=True)

    mean, std = model.predict_with_uncertainty(query)

    assert np.allclose(mean, np.exp(transformed_mean))
    assert np.allclose(std, np.exp(transformed_mean) * transformed_std)


def test_surrogate_fit_rejects_empty_or_non_finite_training_data():
    for model in (PolynomialSurrogate(log_transform=False),):
        with pytest.raises(OptimizationError):
            model.fit(np.empty((0, 1)), np.array([]))
        with pytest.raises(OptimizationError):
            model.fit(np.array([[np.nan], [1.0]]), np.array([1.0, 2.0]))


def test_radial_basis_surrogate_accepts_single_prediction_row():
    pytest.importorskip("scipy")
    x = np.linspace(0, 1, 5).reshape(-1, 1)
    model = RadialBasisSurrogate(log_transform=False).fit(x, x[:, 0] ** 2)

    prediction = model.predict(np.array([0.5]))

    assert prediction.shape == (1,)
    assert prediction[0] == pytest.approx(0.25, abs=1e-2)

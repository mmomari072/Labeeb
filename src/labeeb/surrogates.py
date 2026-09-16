"""
Surrogate modeling for MCNP optimization.
Fits response surfaces to expensive simulation data for fast exploration.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import numpy as np

from .exceptions import OptimizationError


class Surrogate(ABC):
    """Base class for surrogate models."""

    def __init__(self, log_transform: bool = False):
        """
        Initialize surrogate.

        Args:
            log_transform: If True, fit to log(y) instead of y.
        """
        self.log_transform = log_transform
        self.is_fitted = False
        self._y_min = None
        self._y_shift = 0.0
        self._n_features = None

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> "Surrogate":
        """Fit surrogate to data."""
        pass

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict response(s)."""
        pass

    def predict_with_uncertainty(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Predict with uncertainty. Default: no uncertainty."""
        prediction = self.predict(X)
        return prediction, np.zeros_like(prediction)

    def _training_data(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Normalize and validate a training matrix and target vector."""
        try:
            X = np.asarray(X, dtype=float)
            y = np.asarray(y, dtype=float).ravel()
        except (TypeError, ValueError) as exc:
            raise OptimizationError("Surrogate training data must be numeric") from exc
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        if X.ndim != 2 or X.shape[0] == 0 or X.shape[1] == 0:
            raise OptimizationError("X must contain at least one row and one feature")
        if X.shape[0] != y.shape[0]:
            raise OptimizationError("X and y row counts must match")
        if not np.isfinite(X).all() or not np.isfinite(y).all():
            raise OptimizationError("Surrogate training data must contain only finite values")
        self._n_features = X.shape[1]
        return X, y

    def _prediction_data(self, X: np.ndarray) -> np.ndarray:
        """Normalize query rows and check they match the fitted feature count."""
        try:
            X = np.asarray(X, dtype=float)
        except (TypeError, ValueError) as exc:
            raise OptimizationError("Surrogate prediction data must be numeric") from exc
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if X.ndim != 2 or X.shape[0] == 0 or X.shape[1] == 0:
            raise OptimizationError("Prediction X must contain at least one row and one feature")
        if X.shape[1] != self._n_features:
            raise OptimizationError(
                f"Prediction has {X.shape[1]} features; model expects {self._n_features}"
            )
        if not np.isfinite(X).all():
            raise OptimizationError("Surrogate prediction data must contain only finite values")
        return X

    def _preprocess_y(self, y: np.ndarray) -> np.ndarray:
        """Apply log transform if enabled."""
        if self.log_transform:
            self._y_min = np.min(y)
            self._y_shift = -self._y_min + 1e-6 if self._y_min <= 0 else 0.0
            return np.log(y + self._y_shift)
        return y

    def _postprocess_y(self, y_pred: np.ndarray) -> np.ndarray:
        """Reverse log transform if needed."""
        if self.log_transform and self._y_min is not None:
            return np.exp(y_pred) - self._y_shift
        return y_pred


class PolynomialSurrogate(Surrogate):
    """Quadratic polynomial response surface.

    Fits a 2nd-order polynomial:
      ln(y) = β₀ + Σβᵢxᵢ + Σβᵢⱼxᵢxⱼ + Σβᵢᵢxᵢ²
    """

    def __init__(self, degree: int = 2, log_transform: bool = True):
        """
        Initialize polynomial surrogate.

        Args:
            degree: Polynomial degree (1 or 2).
            log_transform: Fit to log(y) for attenuation behavior.
        """
        super().__init__(log_transform=log_transform)
        if degree not in (1, 2):
            raise OptimizationError("Degree must be 1 or 2")
        self.degree = degree
        self.coefficients = None
        self.feature_names = None

    def _build_features(self, X: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        """Build polynomial feature matrix."""
        n_samples, n_features = X.shape
        features = [np.ones(n_samples)]
        feature_names = ["intercept"]

        features.append(X)
        feature_names.extend([f"x{i}" for i in range(n_features)])

        if self.degree == 2:
            for i in range(n_features):
                for j in range(i, n_features):
                    if i == j:
                        features.append(X[:, i] ** 2)
                        feature_names.append(f"x{i}^2")
                    else:
                        features.append(X[:, i] * X[:, j])
                        feature_names.append(f"x{i}*x{j}")

        return np.column_stack(features), feature_names

    def fit(self, X: np.ndarray, y: np.ndarray) -> "PolynomialSurrogate":
        """Fit polynomial surrogate via least-squares."""
        X, y = self._training_data(X, y)

        y_proc = self._preprocess_y(y)
        Phi, self.feature_names = self._build_features(X)

        self.coefficients = np.linalg.lstsq(Phi, y_proc, rcond=None)[0]
        self.is_fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict response(s)."""
        if not self.is_fitted:
            raise OptimizationError("Surrogate must be fitted first")

        X = self._prediction_data(X)
        Phi, _ = self._build_features(X)

        y_pred = Phi @ self.coefficients
        return self._postprocess_y(y_pred)


class GaussianProcessSurrogate(Surrogate):
    """Gaussian Process (Kriging) surrogate using sklearn."""

    def __init__(self, alpha: float = 1e-6, length_scale: float = 1.0, log_transform: bool = True):
        """
        Initialize GP surrogate.

        Args:
            alpha: Noise variance (small = smooth fit).
            length_scale: RBF kernel length scale.
            log_transform: Fit to log(y).
        """
        super().__init__(log_transform=log_transform)
        self.alpha = alpha
        self.length_scale = length_scale
        self.gp = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GaussianProcessSurrogate":
        """Fit GP surrogate."""
        try:
            from sklearn.gaussian_process import GaussianProcessRegressor
            from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
        except ImportError:
            raise OptimizationError("GaussianProcessSurrogate requires scikit-learn")

        X, y = self._training_data(X, y)

        y_proc = self._preprocess_y(y)

        kernel = ConstantKernel(1.0) * RBF(length_scale=self.length_scale) + WhiteKernel(noise_level=self.alpha)
        self.gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, alpha=0)
        self.gp.fit(X, y_proc)
        self.is_fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict mean response."""
        if not self.is_fitted:
            raise OptimizationError("Surrogate must be fitted first")

        X = self._prediction_data(X)
        y_pred = self.gp.predict(X)
        return self._postprocess_y(y_pred)

    def predict_with_uncertainty(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Predict mean and std."""
        if not self.is_fitted:
            raise OptimizationError("Surrogate must be fitted first")

        X = self._prediction_data(X)
        y_pred_transformed, y_std = self.gp.predict(X, return_std=True)

        if self.log_transform:
            y_std = y_std * np.exp(y_pred_transformed)
            y_pred = self._postprocess_y(y_pred_transformed)
        else:
            y_pred = y_pred_transformed

        return y_pred, y_std


class RadialBasisSurrogate(Surrogate):
    """Radial Basis Function (RBF) interpolator."""

    def __init__(self, function: str = "multiquadric", epsilon: float = 1.0, log_transform: bool = True):
        """
        Initialize RBF surrogate.

        Args:
            function: RBF type ('multiquadric', 'gaussian', 'thin_plate').
            epsilon: RBF shape parameter.
            log_transform: Fit to log(y).
        """
        super().__init__(log_transform=log_transform)
        self.function = function
        self.epsilon = epsilon
        self.rbf = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RadialBasisSurrogate":
        """Fit RBF surrogate."""
        try:
            from scipy.interpolate import Rbf
        except ImportError:
            raise OptimizationError("RadialBasisSurrogate requires scipy")

        X, y = self._training_data(X, y)

        y_proc = self._preprocess_y(y)
        coords = [X[:, i] for i in range(X.shape[1])]
        self.rbf = Rbf(*coords, y_proc, function=self.function, epsilon=self.epsilon)
        self.is_fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict response(s)."""
        if not self.is_fitted:
            raise OptimizationError("Surrogate must be fitted first")

        X = self._prediction_data(X)

        coords = [X[:, i] for i in range(X.shape[1])]
        y_pred = self.rbf(*coords)
        return self._postprocess_y(np.asarray(y_pred).ravel())

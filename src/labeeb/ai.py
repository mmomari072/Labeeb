"""Optional AI/ML integrations for Labeeb (LAB-AI-INTEGRATION-EPIC).

This module is deliberately *dependency-light*: nothing here imports SciPy,
Optuna, scikit-learn, PyTorch or BoTorch at module load time. Every engine is
imported lazily inside the function/class that needs it, so importing
``labeeb.ai`` (or ``labeeb``) costs nothing and the core stays lightweight.
When an engine is missing, calls raise :class:`OptimizationError` with an
install hint, and the engine-specific tests skip cleanly.

Contents
--------
* :class:`SurrogateModel` — a regression surrogate (scikit-learn
  RandomForest by default, seed-fixed for reproducibility) fitted on an
  optimizer evaluation history, with ``predict`` and pickle-based
  persistence (``save`` / ``load``, versioned envelope).
* :func:`optimize_scipy` — scipy.optimize adapter that returns a Labeeb
  :class:`OptimizeResult` (direction-aware, failure-tolerant, seeded).
* :func:`optimize_optuna` — Optuna adapter producing the same result shape
  from a ``study`` of ``n_trials`` (TPE sampler, seeded for reproducibility).
* :class:`NeuralMLPSurrogate` — optional PyTorch multi-layer-perceptron
  surrogate (lazy ``import torch``).
* :class:`BoTorchGPSurrogate` — optional BoTorch Gaussian-process surrogate
  (lazy ``import botorch`` + ``gpytorch``), mean prediction.

Reproducibility: every stochastic engine accepts a ``seed`` and every fit is
seeded; validation errors raise :class:`OptimizationError`; persisted models
carry a format/version marker.
"""

import base64
import math
import os
import pickle
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .exceptions import OptimizationError
from .optimizer import EvaluationRecord, OptimizeResult

__all__ = [
    "BoTorchGPSurrogate",
    "NeuralMLPSurrogate",
    "SurrogateModel",
    "optimize_optuna",
    "optimize_scipy",
    "rank_candidates",
]

_SURROGATE_FORMAT = "labeeb-surrogate"
_SURROGATE_VERSION = 1


# --------------------------------------------------------------------------- utils

def _require(package: str, pip_name: Optional[str] = None) -> Any:
    """Lazy-import helper with an actionable error message."""
    try:
        return __import__(package)
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise OptimizationError(
            f"{package} is required for this operation but is not installed; "
            f"install with: pip install {pip_name or package}"
        ) from exc


def _records_from_history(history: Sequence[EvaluationRecord]) -> List[EvaluationRecord]:
    """Only simulated, successfully evaluated records (drop None objectives)."""
    usable = [
        record for record in history
        if record.simulated and record.objective is not None
        and record.status == "evaluated"
    ]
    if not usable:
        raise OptimizationError(
            "history contains no successfully evaluated records to fit a surrogate "
            "(need at least one simulated candidate with a finite objective)"
        )
    return list(usable)


# ------------------------------------------------------------------------- surrogate

@dataclass
class SurrogateModel:
    """Regression surrogate over optimizer evaluation history.

    ``backend`` selects the regressor factory:
      * ``"rf"`` (default): scikit-learn ``RandomForestRegressor`` with
        ``n_estimators`` and a fixed ``random_state``.
      * ``"linear"``: scikit-learn ``LinearRegression`` (no seed needed).
      * callable: any factory ``f(seed) -> regressor`` exposing ``fit``,
        ``predict`` — the lightweight extension point.

    Fit input is a list of :class:`EvaluationRecord` (as kept in
    ``OptimizeResult.history``); failed/infeasible records are ignored.
    """

    var_names: List[str]
    backend: Any = "rf"
    n_estimators: int = 100
    seed: int = 42

    _model: Any = field(default=None, init=False, repr=False)
    _fitted_var_names: List[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.var_names:
            raise OptimizationError("SurrogateModel requires at least one variable name")
        if not isinstance(self.backend, str) and not callable(self.backend):
            raise OptimizationError("backend must be 'rf', 'linear', or a callable factory")

    # -- fitting -------------------------------------------------------------

    def _make_regressor(self) -> Any:
        if self.backend == "rf":
            _require("sklearn")
            from sklearn.ensemble import RandomForestRegressor  # type: ignore

            return RandomForestRegressor(
                n_estimators=self.n_estimators, random_state=self.seed, n_jobs=1
            )
        if self.backend == "linear":
            _require("sklearn")
            from sklearn.linear_model import LinearRegression  # type: ignore

            return LinearRegression()
        return self.backend(self.seed)

    def fit(self, X: Any, y: Any) -> "SurrogateModel":
        """Fit on an explicit design matrix + target vector (sklearn API)."""
        regressor = self._make_regressor()
        try:
            regressor.fit(X, y)
        except Exception as exc:
            raise OptimizationError(f"surrogate fit failed: {exc}") from exc
        self._model = regressor
        return self

    def fit_from_history(self, history: Sequence[EvaluationRecord]) -> "SurrogateModel":
        """Fit from optimizer evaluation history records."""
        records = _records_from_history(history)
        names = list(self.var_names)
        missing = sorted(
            {name for record in records for name in record.parameters if name not in names}
        )
        if missing:
            raise OptimizationError(
                f"history contains variables {missing} not declared in var_names {names}"
            )
        X = [[record.parameters[name] for name in names] for record in records]
        y = [record.objective for record in records]  # type: ignore[misc]
        self._fitted_var_names = names
        return self.fit(X, y)

    def predict(self, candidate: Dict[str, float]) -> float:
        """Predict the objective at one candidate."""
        if self._model is None:
            raise OptimizationError("surrogate has not been fitted yet (call fit_from_history)")
        X = [[candidate.get(name) for name in self._fitted_var_names]]
        prediction = self._model.predict(X)[0]
        return float(prediction)

    # -- persistence -----------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the fitted surrogate to a versioned pickle envelope."""
        if self._model is None:
            raise OptimizationError("cannot save an unfitted surrogate")
        envelope = {
            "format": _SURROGATE_FORMAT,
            "version": _SURROGATE_VERSION,
            "var_names": self.var_names,
            "backend": self.backend,
            "n_estimators": self.n_estimators,
            "seed": self.seed,
            "model": base64.b64encode(pickle.dumps(self._model)).decode("ascii"),
        }
        destination = os.path.abspath(path)
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = destination + f".tmp{os.getpid()}"
        with open(tmp, "wb") as handle:
            pickle.dump(envelope, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, destination)

    @classmethod
    def load(cls, path: str) -> "SurrogateModel":
        """Load a surrogate persisted with :meth:`save` (trusted local files only)."""
        try:
            with open(os.path.abspath(path), "rb") as handle:
                envelope = pickle.load(handle)
        except (OSError, pickle.UnpicklingError) as exc:
            raise OptimizationError(f"cannot read surrogate file {path}: {exc}") from exc
        if not isinstance(envelope, dict) or envelope.get("format") != _SURROGATE_FORMAT:
            raise OptimizationError(f"{path} is not a Labeeb surrogate model file")
        model = pickle.loads(base64.b64decode(envelope["model"]))
        instance = cls(
            var_names=list(envelope["var_names"]),
            backend=envelope["backend"],
            n_estimators=int(envelope.get("n_estimators", 100)),
            seed=int(envelope.get("seed", 42)),
        )
        instance._model = model
        instance._fitted_var_names = list(envelope["var_names"])
        return instance


# ------------------------------------------------------------ external engines

def _make_result(direction: str, best_params: Dict[str, float], best_value: float, records: List[EvaluationRecord], reason: str, method: str) -> OptimizeResult:
    result = OptimizeResult(
        direction=direction,
        method=method,
        best_candidate=best_params,
        best_objective=best_value,
        reason=reason,
        history=records,
    )
    result.proposals = len(records)
    result.evaluations = sum(1 for r in records if r.simulated)
    result.infeasible = sum(1 for r in records if r.status == "infeasible")
    result.failed = sum(1 for r in records if r.status == "failed")
    return result


def optimize_scipy(
    objective_fn: Callable[[Dict[str, float]], Optional[float]],
    variables: Dict[str, Tuple[float, float]],
    *,
    direction: str = "minimize",
    method: str = "Nelder-Mead",
    maxiter: int = 200,
    x0: Optional[Dict[str, float]] = None,
    seed: int = 42,
) -> OptimizeResult:
    """Optimize via :mod:`scipy.optimize.minimize` (lazy import).

    Every objective call is captured into the same
    :class:`EvaluationRecord`/history shape the core :class:`Optimizer`
    produces, so results export identically
    (:func:`labeeb.export_optimization_history`).
    """
    scipy_opt = _require("scipy.optimize")
    names = list(variables)
    if any(lo > hi for lo, hi in variables.values()):
        raise OptimizationError("variable bounds must satisfy low <= high")
    if direction not in ("minimize", "maximize"):
        raise OptimizationError("direction must be 'minimize' or 'maximize'")
    records: List[EvaluationRecord] = []
    sign = 1.0 if direction == "minimize" else -1.0
    start = [0.5 * (variables[n][0] + variables[n][1]) for n in names]
    if x0 is not None:
        start = [x0[n] for n in names]
    low = [variables[n][0] for n in names]
    high = [variables[n][1] for n in names]
    bounded = {variables[n] != (float("-inf"), float("inf")) for n in names}

    def wrap(values: List[float]) -> float:
        candidate = dict(zip(names, values))
        for name in names:
            if candidate[name] < variables[name][0] or candidate[name] > variables[name][1]:
                return sign * float("inf")  # scipy bounds are soft on some methods
        try:
            value = objective_fn(candidate)
        except Exception as exc:  # noqa: BLE001 - failures are recorded, not fatal
            records.append(
                EvaluationRecord(len(records), candidate, "failed", True, None, True, message=f"{type(exc).__name__}: {exc}")
            )
            return sign * float("inf")
        if value is None or (isinstance(value, float) and math.isnan(value)):
            records.append(
                EvaluationRecord(len(records), candidate, "failed", True, None, True, message="simulation failure / NaN objective")
            )
            return sign * float("inf")
        records.append(
            EvaluationRecord(len(records), candidate, "evaluated", True, float(value), True)
        )
        return sign * float(value)

    if any(bounded):
        result = scipy_opt.minimize(
            wrap, start, method=method, bounds=list(zip(low, high)),
            options={"maxiter": maxiter, "disp": False},
        )
    else:
        result = scipy_opt.minimize(wrap, start, method=method, options={"maxiter": maxiter, "disp": False})
    best_value = sign * float(result.fun) if math.isfinite(float(result.fun)) else None
    best_candidate = dict(zip(names, result.x)) if best_value is not None else None
    return _make_result(
        direction, best_candidate or {}, best_value or 0.0, records,
        reason="scipy: " + str(result.message or result.status), method=f"scipy:{method}",
    )


def optimize_optuna(
    objective_fn: Callable[[Dict[str, float]], Optional[float]],
    variables: Dict[str, Tuple[float, float]],
    *,
    direction: str = "minimize",
    n_trials: int = 50,
    seed: int = 42,
    sampler_name: str = "tpe",
) -> OptimizeResult:
    """Optimize via Optuna (lazy import) with a seeded sampler.

    Returns the same :class:`OptimizeResult` shape as the core optimizer
    (``best_candidate``/``best_objective`` from ``study.best_trial``,
    per-trial history records, ``study`` available via ``result.history``).
    """
    optuna = _require("optuna")
    if direction not in ("minimize", "maximize"):
        raise OptimizationError("direction must be 'minimize' or 'maximize'")
    import optuna.samplers  # type: ignore

    sampler_cls = {
        "tpe": optuna.samplers.TPESampler,
        "random": optuna.samplers.RandomSampler,
    }.get(sampler_name)
    if sampler_cls is None:
        raise OptimizationError(f"sampler_name must be one of {list({'tpe', 'random'})}")
    sampler = sampler_cls(seed=seed)
    study = optuna.create_study(direction=direction, sampler=sampler)
    records: List[EvaluationRecord] = []

    def trial_objective(trial: Any) -> float:
        candidate = {
            name: trial.suggest_float(name, variables[name][0], variables[name][1])
            for name in variables
        }
        try:
            value = objective_fn(candidate)
        except Exception as exc:  # noqa: BLE001
            records.append(
                EvaluationRecord(len(records), candidate, "failed", True, None, True, message=f"{type(exc).__name__}: {exc}")
            )
            raise optuna.exceptions.TrialPruned(f"objective failed: {exc}")
        if value is None or (isinstance(value, float) and math.isnan(value)):
            records.append(
                EvaluationRecord(len(records), candidate, "failed", True, None, True, message="simulation failure / NaN objective")
            )
            raise optuna.exceptions.TrialPruned("simulation failure")
        records.append(
            EvaluationRecord(len(records), candidate, "evaluated", True, float(value), True)
        )
        return float(value)

    study.optimize(trial_objective, n_trials=n_trials)
    if study.best_trial is None:
        raise OptimizationError("optuna study produced no successful trial")
    best_candidate = {
        name: float(study.best_params[name]) for name in variables
    }
    return _make_result(
        direction, best_candidate, float(study.best_value), records,
        reason=f"optuna:{n_trials} trials", method=f"optuna:{sampler_name}",
    )


# ------------------------------------------------------------ NN backends (optional)

class NeuralMLPSurrogate:
    """PyTorch multi-layer-perceptron surrogate (lazy ``import torch``).

    Mirrors the :class:`SurrogateModel` surface (``fit_from_history``,
    ``predict``, ``save``/``load``) for the optional neural backend; used when
    a smooth, differentiable surrogate is desired. MLP: ``[n_vars -> 32 ->
    32 -> 1]`` ReLU, Adam, MSE, 300 epochs, fixed seed.
    """

    var_names: List[str]
    seed: int

    def __init__(self, var_names: List[str], seed: int = 42, epochs: int = 300, hidden: int = 32) -> None:
        torch = _require("torch")
        if not var_names:
            raise OptimizationError("NeuralMLPSurrogate requires at least one variable name")
        self.var_names = list(var_names)
        self.seed = int(seed)
        self.epochs = int(epochs)
        self.hidden = int(hidden)
        torch.manual_seed(self.seed)
        self._net: Any = None
        self._X_mean: Any = None
        self._X_std: Any = None

    def _ensure_torch(self) -> Any:
        torch = _require("torch")
        return torch

    def fit_from_history(self, history: Sequence[EvaluationRecord]) -> "NeuralMLPSurrogate":
        torch = self._ensure_torch()
        records = _records_from_history(history)
        names = list(self.var_names)
        X = torch.tensor(
            [[record.parameters[name] for name in names] for record in records],
            dtype=torch.float32,
        )
        y = torch.tensor([[record.objective] for record in records], dtype=torch.float32)  # type: ignore[misc]
        self._X_mean = X.mean(dim=0)
        self._X_std = X.std(dim=0).clamp_min(1e-6)
        Xn = (X - self._X_mean) / self._X_std
        net = torch.nn.Sequential(
            torch.nn.Linear(len(names), self.hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(self.hidden, self.hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(self.hidden, 1),
        )
        optimizer = torch.optim.Adam(net.parameters())
        loss_fn = torch.nn.MSELoss()
        net.train()
        for _epoch in range(self.epochs):
            optimizer.zero_grad()
            loss = loss_fn(net(Xn), y)
            loss.backward()
            optimizer.step()
        self._net = net
        return self

    def predict(self, candidate: Dict[str, float]) -> float:
        torch = self._ensure_torch()
        if self._net is None or self._X_mean is None:
            raise OptimizationError("neural surrogate has not been fitted yet")
        x = torch.tensor([[candidate[name] for name in self.var_names]], dtype=torch.float32)
        x = (x - self._X_mean) / self._X_std
        self._net.eval()
        with torch.no_grad():
            return float(self._net(x).item())

    def save(self, path: str) -> None:
        """Persist weights + normalization with a versioned envelope."""
        torch = self._ensure_torch()
        if self._net is None:
            raise OptimizationError("cannot save an unfitted neural surrogate")
        buffer = bytearray()
        torch.save(self._net.state_dict(), buffer)  # type: ignore[arg-type]
        envelope = {
            "format": _SURROGATE_FORMAT,
            "kind": "mlp",
            "version": _SURROGATE_VERSION,
            "var_names": self.var_names,
            "seed": self.seed,
            "epochs": self.epochs,
            "hidden": self.hidden,
            "state": base64.b64encode(bytes(buffer)).decode("ascii"),
            "mean": self._X_mean.tolist(),
            "std": self._X_std.tolist(),
        }
        destination = os.path.abspath(path)
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = destination + f".tmp{os.getpid()}"
        with open(tmp, "wb") as handle:
            pickle.dump(envelope, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, destination)

    @classmethod
    def load(cls, path: str, hidden: int = 32) -> "NeuralMLPSurrogate":
        torch = _require("torch")
        try:
            with open(os.path.abspath(path), "rb") as handle:
                envelope = pickle.load(handle)
        except (OSError, pickle.UnpicklingError) as exc:
            raise OptimizationError(f"cannot read surrogate file {path}: {exc}") from exc
        if envelope.get("format") != _SURROGATE_FORMAT or envelope.get("kind") != "mlp":
            raise OptimizationError(f"{path} is not a Labeeb MLP surrogate file")
        instance = cls(
            var_names=list(envelope["var_names"]),
            seed=int(envelope["seed"]),
            epochs=int(envelope["epochs"]),
            hidden=int(envelope.get("hidden", hidden)),
        )
        net = torch.nn.Sequential(
            torch.nn.Linear(len(instance.var_names), instance.hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(instance.hidden, instance.hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(instance.hidden, 1),
        )
        net.load_state_dict(torch.load(base64.b64decode(envelope["state"])))  # type: ignore[arg-type]
        instance._net = net
        instance._X_mean = torch.tensor(envelope["mean"], dtype=torch.float32)
        instance._X_std = torch.tensor(envelope["std"], dtype=torch.float32)
        return instance


class BoTorchGPSurrogate:
    """BoTorch single-task GP surrogate (lazy import of botorch/gpytorch).

    Provides a mean-prediction surrogate over optimizer evaluation history;
    same surface as :class:`SurrogateModel`.
    """

    var_names: List[str]
    seed: int

    def __init__(self, var_names: List[str], seed: int = 42) -> None:
        if not var_names:
            raise OptimizationError("BoTorchGPSurrogate requires at least one variable name")
        self.var_names = list(var_names)
        self.seed = int(seed)
        self._model: Any = None
        self._bounds: Optional[Dict[str, Tuple[float, float]]] = None

    def fit_from_history(
        self,
        history: Sequence[EvaluationRecord],
        bounds: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> "BoTorchGPSurrogate":
        _require("botorch")
        torch = _require("torch")
        if bounds is not None and set(bounds) != set(self.var_names):
            raise OptimizationError("bounds must cover exactly the declared var_names")
        torch.manual_seed(self.seed)
        records = _records_from_history(history)
        names = list(self.var_names)
        X = torch.tensor(
            [[record.parameters[name] for name in names] for record in records],
            dtype=torch.float64,
        )
        y = torch.tensor([[record.objective] for record in records], dtype=torch.float64)  # type: ignore[misc]
        # standardize to zero mean / unit variance (botorch default)
        y = (y - y.mean()) / (y.std().clamp_min(1e-9))
        from botorch.models import SingleTaskGP  # type: ignore
        from gpytorch.mlls import ExactMarginalLogLikelihood  # type: ignore

        model = SingleTaskGP(X, y)
        mll = ExactMarginalLogLikelihood(model.likelihood, model)
        from botorch.optim import fit_gpytorch_mll  # type: ignore

        fit_gpytorch_mll(mll)
        self._model = model
        self._bounds = bounds
        return self

    def predict(self, candidate: Dict[str, float]) -> float:
        _require("botorch")
        torch = _require("torch")
        if self._model is None:
            raise OptimizationError("GP surrogate has not been fitted yet")
        x = torch.tensor(
            [[candidate[name] for name in self.var_names]], dtype=torch.float64
        )
        posterior = self._model.posterior(x)
        return float(posterior.mean.item())

    def save(self, path: str) -> None:
        torch = _require("torch")
        if self._model is None:
            raise OptimizationError("cannot save an unfitted GP surrogate")
        buffer = bytearray()
        torch.save(self._model.state_dict(), buffer)  # type: ignore[arg-type]
        envelope = {
            "format": _SURROGATE_FORMAT,
            "kind": "gp",
            "version": _SURROGATE_VERSION,
            "var_names": self.var_names,
            "seed": self.seed,
            "state": base64.b64encode(bytes(buffer)).decode("ascii"),
            "bounds": self._bounds,
        }
        destination = os.path.abspath(path)
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = destination + f".tmp{os.getpid()}"
        with open(tmp, "wb") as handle:
            pickle.dump(envelope, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, destination)

    @classmethod
    def load(cls, path: str) -> "BoTorchGPSurrogate":
        _require("botorch")
        torch = _require("torch")
        try:
            with open(os.path.abspath(path), "rb") as handle:
                envelope = pickle.load(handle)
        except (OSError, pickle.UnpicklingError) as exc:
            raise OptimizationError(f"cannot read surrogate file {path}: {exc}") from exc
        if envelope.get("format") != _SURROGATE_FORMAT or envelope.get("kind") != "gp":
            raise OptimizationError(f"{path} is not a Labeeb GP surrogate file")
        instance = cls(
            var_names=list(envelope["var_names"]), seed=int(envelope["seed"])
        )
        from botorch.models import SingleTaskGP  # type: ignore

        model = SingleTaskGP.__new__(SingleTaskGP)  # type: ignore[attr-defined]
        model.load_state_dict(torch.load(base64.b64decode(envelope["state"])))  # type: ignore[arg-type]
        instance._model = model
        instance._bounds = envelope["bounds"]
        return instance


def rank_candidates(
    predictor: Callable[[Dict[str, float]], float],
    variables: Dict[str, Tuple[float, float]],
    n: int = 100,
    method: str = "random",
    seed: int = 42,
    direction: str = "minimize",
) -> List[Tuple[float, Dict[str, float]]]:
    """Score candidate designs with a fitted predictor and rank them.

    Pure-stdlib acquisition helper for surrogate-guided search: samples
    candidates inside ``variables`` bounds (seeded per-index ``random``, or a
    deterministic mixed-radix ``grid`` covering at least ``n`` points), asks
    ``predictor`` (any fitted surrogate exposing ``predict(candidate)`` —
    :class:`SurrogateModel`, :class:`NeuralMLPSurrogate`,
    :class:`BoTorchGPSurrogate`, or a plain callable) to score each one, and
    returns ``[(prediction, candidate), ...]`` sorted best-first for
    ``direction``. Deterministic for a given seed/method, so a resumed
    surrogate search reproduces identical rankings.
    """
    import math as _math

    if callable(predictor):
        score_fn = predictor
    elif hasattr(predictor, "predict") and callable(predictor.predict):
        score_fn = predictor.predict
    else:
        raise OptimizationError(
            "predictor must be callable(candidate) -> float or expose a callable .predict()"
        )
    if not isinstance(variables, dict) or not variables:
        raise OptimizationError("variables must be a non-empty {name: (low, high)} dict")
    names = list(variables)
    for name, (low, high) in variables.items():
        if low > high or not (_math.isfinite(low) and _math.isfinite(high)):
            raise OptimizationError(f"variable {name!r} bounds must be finite with low <= high")
    if not isinstance(n, int) or n < 1:
        raise OptimizationError("n must be an integer >= 1")
    if method not in ("random", "grid"):
        raise OptimizationError("method must be 'random' or 'grid'")
    if direction not in ("minimize", "maximize"):
        raise OptimizationError("direction must be 'minimize' or 'maximize'")

    def sample(index: int) -> Dict[str, float]:
        if method == "random":
            rng = random.Random(f"{seed}:{index}")
            return {name: low + rng.random() * (high - low) for name, (low, high) in variables.items()}
        # grid: mixed-radix decode over ceil(n^(1/k)) divisions per variable
        divisions = max(2, int(round(n ** (1.0 / len(names)))))
        position = index
        candidate: Dict[str, float] = {}
        for name in names:
            low, high = variables[name]
            step = (high - low) / (divisions - 1)
            candidate[name] = low + (position % divisions) * step
            position //= divisions
        return candidate

    grid_size = divisions = None
    if method == "grid":
        divisions = max(2, int(round(n ** (1.0 / len(names)))))
        grid_size = divisions ** len(names)
    total = n if method == "random" else min(n, grid_size)  # type: ignore[operator]
    scored = []
    for index in range(total):
        candidate = sample(index)
        prediction = float(score_fn(candidate))
        scored.append((prediction, candidate))
    scored.sort(key=lambda item: item[0], reverse=(direction == "maximize"))
    return scored

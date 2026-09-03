"""Focused tests: optional AI/ML integration layer (LAB-AI-INTEGRATION-EPIC).

Core-lightweight guarantees: importing labeeb/ai never imports an external
engine; the validation/shape tests below run with zero optional dependencies,
and each engine-specific suite skips cleanly when its dependency is absent.
"""

import pickle
import subprocess
import sys

import pytest

from labeeb import (
    EvaluationRecord,
    OptimizationError,
    SurrogateModel,
    export_optimization_history,
    optimize_optuna,
    optimize_scipy,
)
from labeeb.ai import BoTorchGPSurrogate, NeuralMLPSurrogate

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")

_ENGINES = ("sklearn", "scipy", "torch", "optuna", "botorch")


def parabola_history(n=9, low=-2.0, high=2.0):
    """Deterministic evaluation history of f(x) = (x - 0.5)^2 over a grid."""
    records = []
    for i, value in enumerate([low + (high - low) * k / (n - 1) for k in range(n)]):
        records.append(
            EvaluationRecord(
                index=i, parameters={"x": value}, status="evaluated", simulated=True,
                objective=(value - 0.5) ** 2, feasible=True,
            )
        )
    return records


def engine_available(name):
    return pytest.importorskip(name) is not None


# --- core-lightweight guarantees (always run) -----------------------------------------

def test_ai_import_never_pulls_external_engines():
    probe = (
        "import labeeb.ai, sys; "
        "print(any(m in sys.modules for m in "
        "['sklearn', 'scipy', 'torch', 'optuna', 'botorch']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "False"


def test_missing_engine_raises_actionable_error():
    if _engine_installed("sklearn"):
        pytest.skip("sklearn present: hint path not exercised here")
    with pytest.raises(OptimizationError, match="pip install sklearn"):
        SurrogateModel(["x"], backend="rf").fit_from_history(parabola_history())


def test_unfitted_surrogate_predict_raises():
    model = SurrogateModel(["x"])
    with pytest.raises(OptimizationError, match="has not been fitted"):
        model.predict({"x": 1.0})
    with pytest.raises(OptimizationError, match="cannot save an unfitted"):
        model.save("/tmp/never_written_surrogate.pkl")


def test_surrogate_validation():
    with pytest.raises(OptimizationError, match="at least one variable name"):
        SurrogateModel([])
    with pytest.raises(OptimizationError, match="backend must be"):
        SurrogateModel(["x"], backend=7)


def test_surrogate_requires_successful_records():
    failed = [EvaluationRecord(0, {"x": 1.0}, "failed", True, None, True, message="boom")]
    with pytest.raises(OptimizationError, match="no successfully evaluated"):
        SurrogateModel(["x"]).fit_from_history(failed)


def test_surrogate_rejects_unknown_variables():
    records = [EvaluationRecord(0, {"x": 1.0, "y": 2.0}, "evaluated", True, 0.5, True)]
    with pytest.raises(OptimizationError, match="not declared in var_names"):
        SurrogateModel(["x"]).fit_from_history(records)


def test_surrogate_load_rejects_foreign_file(tmp_path):
    foreign = tmp_path / "foreign.pkl"
    with open(foreign, "wb") as handle:
        pickle.dump({"format": "something-else"}, handle)
    with pytest.raises(OptimizationError, match="not a Labeeb surrogate"):
        SurrogateModel.load(str(foreign))


def test_scipy_missing_install_hint():
    if _engine_installed("scipy"):
        pytest.skip("scipy present: hint path not exercised here")
    with pytest.raises(OptimizationError, match="pip install scipy"):
        optimize_scipy(lambda c: 0.0, {"x": (0.0, 1.0)})


def _engine_installed(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# --- SurrogateModel (scikit-learn, importorskip) -------------------------------------

def test_rf_surrogate_fit_predict_and_save_load(tmp_path):
    engine_available("sklearn")
    model = SurrogateModel(["x"], backend="rf", n_estimators=20, seed=7)
    model.fit_from_history(parabola_history())
    near_best = model.predict({"x": 0.5})
    far = model.predict({"x": -2.0})
    assert near_best < far  # surrogate ranks candidates like the true function

    path = tmp_path / "surrogate.pkl"
    model.save(str(path))
    restored = SurrogateModel.load(str(path))
    assert restored.var_names == ["x"]
    assert abs(restored.predict({"x": 0.5}) - near_best) < 1e-9


def test_rf_surrogate_reproducible_across_fits():
    engine_available("sklearn")
    a = SurrogateModel(["x"], n_estimators=20, seed=3)
    b = SurrogateModel(["x"], n_estimators=20, seed=3)
    a.fit_from_history(parabola_history())
    b.fit_from_history(parabola_history())
    assert a.predict({"x": 0.25}) == b.predict({"x": 0.25})


def test_linear_surrogate_backend():
    engine_available("sklearn")
    model = SurrogateModel(["x"], backend="linear")
    model.fit_from_history(parabola_history(n=5, low=-1.0, high=2.0))
    assert model.predict({"x": 0.5}) >= 0.0


# --- scipy adapter (importorskip) ------------------------------------------------------

def test_scipy_adapter_minimizes_and_exports(tmp_path):
    engine_available("scipy")
    calls = {"n": 0}

    def objective(candidate):
        calls["n"] += 1
        return (candidate["x"] - 1.25) ** 2 + candidate["y"] ** 2

    result = optimize_scipy(
        objective, {"x": (-5.0, 5.0), "y": (-5.0, 5.0)},
        method="Nelder-Mead", maxiter=120, x0={"x": 4.0, "y": 4.0}, seed=1,
    )
    assert abs(result.best_candidate["x"] - 1.25) < 0.05
    assert abs(result.best_candidate["y"]) < 0.05
    assert result.evaluations >= 1
    assert all(r.simulated for r in result.history if r.status == "evaluated")
    assert calls["n"] == result.evaluations

    path = tmp_path / "scipy.json"
    export_optimization_history(result, str(path))
    assert path.exists()


def test_scipy_adapter_direction_maximize():
    engine_available("scipy")
    result = optimize_scipy(
        lambda c: -(c["x"] ** 2), {"x": (-3.0, 3.0)},
        method="Nelder-Mead", maxiter=80, x0={"x": 1.0}, direction="maximize",
    )
    assert abs(result.best_candidate["x"]) < 0.05


def test_scipy_adapter_simulation_failure_recorded():
    engine_available("scipy")

    def flaky(candidate):
        if candidate["x"] > 1.0:
            raise RuntimeError("code crashed")
        return candidate["x"] ** 2

    result = optimize_scipy(
        flaky, {"x": (-3.0, 3.0)}, method="Nelder-Mead", maxiter=40,
        x0={"x": -1.0},
    )
    assert any(r.status == "failed" and "code crashed" in r.message for r in result.history)


# --- optuna adapter (importorskip) --------------------------------------------------------

def test_optuna_adapter_minimizes_with_seed(tmp_path):
    engine_available("optuna")

    def objective(candidate):
        return (candidate["z"] - 2.0) ** 2

    result = optimize_optuna(objective, {"z": (-10.0, 10.0)}, n_trials=30, seed=11)
    assert abs(result.best_candidate["z"] - 2.0) < 0.25
    assert result.best_objective is not None and result.best_objective < 0.1
    assert len(result.history) == 30
    path = tmp_path / "optuna.csv"
    export_optimization_history(result, str(path))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 31  # header + 30 trials


def test_optuna_adapter_deterministic():
    engine_available("optuna")
    same = lambda: optimize_optuna(  # noqa: E731
        lambda c: (c["z"] - 2.0) ** 2, {"z": (-10.0, 10.0)}, n_trials=10, seed=5,
    )
    a, b = same(), same()
    assert a.best_candidate == b.best_candidate
    assert [r.parameters for r in a.history] == [r.parameters for r in b.history]


# --- NN backends (importorskip) -----------------------------------------------------------

def test_neural_mlp_surrogate_fit_predict_save_load(tmp_path):
    engine_available("torch")
    model = NeuralMLPSurrogate(["x"], seed=9, epochs=400, hidden=16)
    model.fit_from_history(parabola_history())
    assert model.predict({"x": 0.5}) < model.predict({"x": -2.0})
    path = tmp_path / "mlp.pkl"
    model.save(str(path))
    restored = NeuralMLPSurrogate.load(str(path))
    assert abs(restored.predict({"x": 0.5}) - model.predict({"x": 0.5})) < 1e-6


def test_neural_mlp_reproducible():
    engine_available("torch")
    a = NeuralMLPSurrogate(["x"], seed=4, epochs=200)
    b = NeuralMLPSurrogate(["x"], seed=4, epochs=200)
    a.fit_from_history(parabola_history())
    b.fit_from_history(parabola_history())
    assert a.predict({"x": 0.3}) == b.predict({"x": 0.3})


def test_botorch_gp_surrogate(tmp_path):
    engine_available("botorch")
    engine_available("torch")
    model = BoTorchGPSurrogate(["x"], seed=2)
    model.fit_from_history(parabola_history(n=7), bounds={"x": (-2.0, 2.0)})
    assert model.predict({"x": 0.5}) < model.predict({"x": -2.0})
    path = tmp_path / "gp.pkl"
    model.save(str(path))
    restored = BoTorchGPSurrogate.load(str(path))
    assert abs(restored.predict({"x": 0.5}) - model.predict({"x": 0.5})) < 1e-9

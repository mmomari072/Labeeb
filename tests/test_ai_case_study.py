"""Case-study + surrogate-ranking tests for the optional AI integration layer
(LAB-AI-INTEGRATION-EPIC). The ranking helper is pure stdlib; the case study
runs a real Case per candidate via subprocess (7 simulations, ~3-5 s)."""

import subprocess
import sys

import pytest

from labeeb import OptimizationError, rank_candidates

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def linear(candidate):
    return candidate["x"]


# --- rank_candidates (no engines required) ---------------------------------------

def test_rank_candidates_grid_minimize_orders_best_first():
    ranked = rank_candidates(linear, {"x": (-2.0, 2.0)}, n=7, method="grid")
    assert ranked[0][0] == pytest.approx(-2.0)
    assert ranked[0][1] == {"x": -2.0}
    predictions = [p for p, _ in ranked]
    assert predictions == sorted(predictions)
    assert len(ranked) == 7
    xs = {c["x"] for _, c in ranked}
    assert min(xs) == -2.0 and max(xs) == 2.0  # bounds are always included
    assert len(xs) == 7  # 7 evenly spaced grid points


def test_rank_candidates_maximize_reverses_order():
    ranked = rank_candidates(linear, {"x": (-2.0, 2.0)}, n=5, method="grid",
                             direction="maximize")
    assert ranked[0][1] == {"x": 2.0}


def test_rank_candidates_random_deterministic_and_seeded():
    def make(seed):
        return rank_candidates(linear, {"x": (-5.0, 5.0)}, n=40,
                               method="random", seed=seed)
    a, b, c = make(3), make(3), make(4)
    assert a == b
    assert a != c
    assert len(a) == 40


def test_rank_candidates_validates():
    with pytest.raises(OptimizationError, match="callable"):
        rank_candidates(42, {"x": (0.0, 1.0)})
    with pytest.raises(OptimizationError, match="non-empty"):
        rank_candidates(linear, {})
    with pytest.raises(OptimizationError, match="low <= high"):
        rank_candidates(linear, {"x": (2.0, 1.0)})
    with pytest.raises(OptimizationError, match="method must be"):
        rank_candidates(linear, {"x": (0.0, 1.0)}, method="anneal")
    with pytest.raises(OptimizationError, match="direction must be"):
        rank_candidates(linear, {"x": (0.0, 1.0)}, direction="up")


def test_rank_candidates_scores_with_real_surrogate_api():
    """rank_candidates accepts anything exposing predict (no sklearn needed)."""
    class StubSurrogate:
        def predict(self, candidate):
            return candidate["x"] ** 2

    ranked = rank_candidates(StubSurrogate(), {"x": (-3.0, 3.0)}, n=7, method="grid")
    assert ranked[0][1] == {"x": 0.0}
    assert ranked[-1][1]["x"] in (-3.0, 3.0)


# --- runnable case study ------------------------------------------------------------

def test_optimize_ai_case_study_runs_standalone(tmp_path):
    """The documented example executes end-to-end (Case per candidate)."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / "optimize_ai_case_study.py"),
         str(tmp_path)],
        capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    output = proc.stdout
    assert "OPTIMIZATION COMPLETE best_T=900.0 best_objective=0.0" in output
    assert "evaluations=7 failed=0" in output
    # core path is engine-free; surrogate section reports availability either way
    assert "SURROGATE SKIPPED" in output or "SURROGATE AVAILABLE" in output
    if "SURROGATE AVAILABLE" in output:
        assert "RANKED_TOP" in output
    # artifacts were produced in the work dir
    assert (tmp_path / "optimization_history.csv").exists()
    assert (tmp_path / "opt_checkpoint.json").exists()

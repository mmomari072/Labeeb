"""Focused validation for LAB-TRAINING-CASES-01 training case studies.

Loads the two simulator-neutral examples as importable modules and validates
their workflows (design matrices, ranking semantics, UA statistics) plus an
end-to-end CLI run of each.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


def load_example(name):
    path = EXAMPLES / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sa_module = load_example("sa_training_screening.py")
ua_module = load_example("ua_training_propagation.py")


# --- SA: screening design -------------------------------------------------------

def test_sa_design_rows_and_baseline():
    summary = sa_module.run_sa()
    assert summary["design_rows"] == 7  # baseline + 2 steps x 3 parameters
    # simulator at nominal: 0.9 exactly
    assert summary["baseline_response"] == pytest.approx(0.9)


def test_sa_ranking_identifies_dominant_parameter():
    summary = sa_module.run_sa()
    top_var, _ = summary["ranking"][0]
    assert top_var == "TEMP"  # quadratic TEMP term dominates by construction
    assert summary["sensitivity"]["TEMP"] > summary["sensitivity"]["FLOW"]
    assert summary["sensitivity"]["FLOW"] > summary["sensitivity"]["PRESSURE"]
    assert [var for var, _ in summary["ranking"]] == ["TEMP", "FLOW", "PRESSURE"]


def test_sa_sensitivity_values_are_finite_and_positive():
    summary = sa_module.run_sa()
    for var, value in summary["sensitivity"].items():
        assert value > 0.0 and value == value  # finite (not NaN)


def test_sa_accepts_custom_nominal_and_steps():
    summary = sa_module.run_sa(
        nominal={"TEMP": 600.0, "FLOW": 1500.0, "PRESSURE": 160.0},
        steps={"TEMP": 10.0, "FLOW": 20.0, "PRESSURE": 5.0},
    )
    assert summary["design_rows"] == 7
    assert summary["ranking"][0][0] == "TEMP"


def test_sa_rejects_mismatched_params():
    with pytest.raises(ValueError, match="cover the same parameters"):
        sa_module.run_sa(nominal={"TEMP": 1.0}, steps={"TEMP": 1.0, "FLOW": 2.0})


# --- UA: propagation --------------------------------------------------------------

def test_ua_sample_size_and_statistics():
    summary = ua_module.run_ua(n=3000, seed=7)
    assert summary["n"] == 3000
    # analytic: mean = 2*550 - 1.5*1400 + 3 + 0 = -997.0 (sampling noise ~0.85)
    assert summary["mean"] == pytest.approx(-997.0, abs=2.0)
    # analytic std: sqrt(4*var(uniform(540,560)) + 2.25*900 + 0.5) ~= 46.5
    assert summary["std"] == pytest.approx(46.5, abs=2.0)
    assert summary["p5"] < summary["mean"] < summary["p95"]


def test_ua_deterministic_for_seed():
    a = ua_module.run_ua(n=500, seed=11)
    b = ua_module.run_ua(n=500, seed=11)
    c = ua_module.run_ua(n=500, seed=12)
    assert a == b
    assert a != c


def test_ua_rejects_bad_n():
    with pytest.raises(ValueError, match="n must be >= 1"):
        ua_module.run_ua(n=0)


# --- CLI end-to-end ----------------------------------------------------------------

@pytest.mark.parametrize(
    "script,marker",
    [
        ("sa_training_screening.py", "TRAINING-SA-COMPLETE top=TEMP"),
        ("ua_training_propagation.py", "TRAINING-UA-COMPLETE n="),
    ],
)
def test_examples_run_standalone(tmp_path, script, marker):
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES / script)],
        capture_output=True, text=True, timeout=300, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert marker in proc.stdout
    assert "sensitivity[" in proc.stdout or "expected mean" in proc.stdout

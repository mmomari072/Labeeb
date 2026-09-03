"""Focused tests: simulation-based optimization controller (LAB-OPTIMIZATION-API-01)."""

import json

import pytest

from labeeb import (
    Constraint,
    OptimizeResult,
    OptimizationError,
    Optimizer,
    export_optimization_history,
)


def sphere(**candidate):
    return sum((value - target) ** 2 for value, target in zip(candidate.values(), [0.0] * len(candidate)))


def run_sphere(candidate):
    return sphere(**candidate)


def count_runs(fn):
    """Wrap an objective with an evaluation counter."""
    state = {"n": 0}

    def wrapped(candidate):
        state["n"] += 1
        return fn(candidate)

    wrapped.state = state  # type: ignore[attr-defined]
    return wrapped


# --- validation ----------------------------------------------------------------

def test_invalid_configuration_rejected():
    with pytest.raises(OptimizationError, match="non-empty"):
        Optimizer({}, run_sphere)
    with pytest.raises(OptimizationError, match="low bound exceeds"):
        Optimizer({"x": (3.0, 1.0)}, run_sphere)
    with pytest.raises(OptimizationError, match="direction must be"):
        Optimizer({"x": (0.0, 1.0)}, run_sphere, direction="sideways")
    with pytest.raises(OptimizationError, match="method must be"):
        Optimizer({"x": (0.0, 1.0)}, run_sphere, method="anneal")
    with pytest.raises(OptimizationError, match="budget must be"):
        Optimizer({"x": (0.0, 1.0)}, run_sphere, budget=0)
    with pytest.raises(OptimizationError, match="constraints must be"):
        Optimizer({"x": (0.0, 1.0)}, run_sphere, constraints=[42])


# --- grid minimize/maximize ------------------------------------------------------

def test_grid_minimize_finds_exact_optimum():
    # 1D parabola over [-3, 3] with 7 points -> grid contains x=0 exactly
    opt = Optimizer({"x": (-3.0, 3.0)}, run_sphere, method="grid", grid_points=7, budget=20)
    result = opt.run()
    assert result.best_candidate["x"] == 0.0
    assert result.best_objective == 0.0
    assert result.evaluations == 7  # budget cap not reached; grid exhausted
    assert result.reason == "exhausted"
    assert len(result.history) == 7
    assert all(record.status == "evaluated" for record in result.history)


def test_grid_maximize_picks_largest():
    opt = Optimizer(
        {"x": (-2.0, 2.0)},
        lambda c: -(c["x"] ** 2) + 5.0,
        direction="maximize",
        method="grid",
        grid_points=5,
        budget=20,
    )
    result = opt.run()
    assert result.best_candidate["x"] == 0.0
    assert result.best_objective == 5.0


def test_budget_caps_evaluations():
    opt = Optimizer(
        {"x": (-1.0, 1.0), "y": (-1.0, 1.0)},
        run_sphere,
        method="grid",
        grid_points=5,  # 25 grid points
        budget=4,
    )
    result = opt.run()
    assert result.evaluations == 4
    assert result.reason == "budget"


# --- random determinism -----------------------------------------------------------

def test_random_seeded_determinism():
    make = lambda seed: Optimizer(  # noqa: E731
        {"x": (-5.0, 5.0), "y": (-5.0, 5.0)}, run_sphere,
        method="random", seed=seed, budget=30,
    )
    a = make(7).run()
    b = make(7).run()
    c = make(8).run()
    assert [r.parameters for r in a.history] == [r.parameters for r in b.history]
    assert [r.parameters for r in a.history] != [r.parameters for r in c.history]
    assert a.best_objective is not None and a.best_objective < 1.0


# --- constraints -------------------------------------------------------------------

def test_infeasible_candidates_skipped_without_simulation():
    sims = count_runs(run_sphere)
    opt = Optimizer(
        {"x": (0.0, 10.0), "y": (0.0, 10.0)},
        sims,
        method="grid",
        grid_points=4,  # 16 proposals; 7 with x + y > 10 are infeasible
        budget=50,
        constraints=[Constraint("x+y<=10", lambda c: c["x"] + c["y"] <= 10.0)],
    )
    # grid 4 over [0,10]^2 -> points 0, 10/3, 20/3, 10; sums > 10: 6 of 16
    result = opt.run()
    assert result.infeasible == 6
    assert sims.state["n"] == 10  # only feasible candidates were simulated
    assert result.evaluations == 10
    assert all(record.simulated for record in result.history if record.status == "evaluated")
    assert all(r.violated_constraints == ["x+y<=10"] for r in result.history if r.status == "infeasible")
    # infeasible records never become best
    assert result.best_candidate is not None and result.best_candidate["x"] + result.best_candidate["y"] <= 10.0


# --- failures ------------------------------------------------------------------------

def test_objective_failures_recorded_and_skipped():
    calls = []

    def flaky(candidate):
        calls.append(candidate["x"])
        if candidate["x"] < 0:
            raise RuntimeError("sim crashed")
        if candidate["x"] == 0:
            return None  # simulation failure (e.g. nonzero exit, missing output)
        return candidate["x"] ** 2

    opt = Optimizer({"x": (-2.0, 2.0)}, flaky, method="grid", grid_points=5, budget=50)
    result = opt.run()
    assert result.failed == 3  # -2, -1 raised; 0 returned None
    assert result.reason == "exhausted"
    assert any(r.status == "failed" and "sim crashed" in r.message for r in result.history)
    assert any(r.status == "failed" and "returned None" in r.message for r in result.history)
    # best excludes failures
    assert result.best_candidate == {"x": 1.0} or result.best_candidate == {"x": -0.0} or result.best_candidate["x"] in (1.0, 2.0)


def test_nan_objective_treated_as_failure():
    opt = Optimizer({"x": (-1.0, 1.0)}, lambda c: float("nan"), method="grid", grid_points=3)
    result = opt.run()
    assert result.failed == 3
    assert result.best_objective is None
    assert all("NaN" in r.message for r in result.history)


def test_exception_from_objective_does_not_abort_run():
    def boom_first(candidate):
        if candidate["x"] == -2.0:
            raise ValueError("kaput")
        return candidate["x"] ** 2

    opt = Optimizer({"x": (-2.0, 2.0)}, boom_first, method="grid", grid_points=3)
    result = opt.run()
    assert len(result.history) == 3
    assert result.history[0].status == "failed"


# --- patience/termination ---------------------------------------------------------------

def test_patience_terminates_flat_objective():
    opt = Optimizer(
        {"x": (0.0, 1.0)}, lambda c: 3.0, method="random", seed=1,
        budget=100, patience=2,
    )
    result = opt.run()
    assert result.reason == "patience"
    assert result.evaluations == 3  # first improves, two consecutive no-improve
    assert result.best_objective == 3.0


def test_patience_requires_min_evaluations():
    opt = Optimizer(
        {"x": (0.0, 1.0)}, lambda c: 3.0, method="random", seed=1,
        budget=100, patience=2, min_evaluations=50,
    )
    result = opt.run()
    # patience may not fire before 50 evaluations; first eval is an "improvement",
    # so the stall counter reaches patience exactly at evaluation 50.
    assert result.evaluations == 50
    assert result.reason == "patience"


# --- checkpoint / resume / caching -------------------------------------------------------

def test_resume_skips_evaluated_and_continues(tmp_path):
    checkpoint = tmp_path / "opt.json"
    sims = count_runs(run_sphere)
    opt1 = Optimizer(
        {"x": (-3.0, 3.0)}, sims, method="grid", grid_points=7,
        budget=3, checkpoint_path=str(checkpoint),
    )
    first = opt1.run()
    assert first.evaluations == 3
    assert sims.state["n"] == 3

    sims2 = count_runs(run_sphere)
    opt2 = Optimizer(
        {"x": (-3.0, 3.0)}, sims2, method="grid", grid_points=7,
        budget=7, checkpoint_path=str(checkpoint), resume=True,
    )
    second = opt2.run()
    assert second.cached == 3  # resumed candidates were not re-simulated
    assert sims2.state["n"] == 4  # only the remaining four grid points ran
    assert second.evaluations == 7
    assert second.best_objective == 0.0


def test_resume_matches_fresh_run(tmp_path):
    """Resumed run with full budget reaches the same best as a fresh full run."""
    checkpoint = tmp_path / "opt.json"
    opt = Optimizer(
        {"x": (-3.0, 3.0), "y": (-3.0, 3.0)}, run_sphere, method="grid",
        grid_points=5, budget=4, checkpoint_path=str(checkpoint),
    )
    first = opt.run()
    resumed = Optimizer(
        {"x": (-3.0, 3.0), "y": (-3.0, 3.0)}, run_sphere, method="grid",
        grid_points=5, budget=25, checkpoint_path=str(checkpoint), resume=True,
    ).run()
    fresh = Optimizer(
        {"x": (-3.0, 3.0), "y": (-3.0, 3.0)}, run_sphere, method="grid",
        grid_points=5, budget=25,
    ).run()
    assert resumed.best_objective == fresh.best_objective
    assert resumed.best_candidate == fresh.best_candidate
    assert [r.parameters for r in resumed.history][:4] == [r.parameters for r in first.history]


def test_resume_config_mismatch_rejected(tmp_path):
    checkpoint = tmp_path / "opt.json"
    Optimizer(
        {"x": (-3.0, 3.0)}, run_sphere, method="grid", grid_points=5,
        budget=2, checkpoint_path=str(checkpoint),
    ).run()
    with pytest.raises(OptimizationError, match="config mismatch on 'direction'"):
        Optimizer(
            {"x": (-3.0, 3.0)}, run_sphere, direction="maximize",
            method="grid", grid_points=5, budget=5,
            checkpoint_path=str(checkpoint), resume=True,
        ).run()
    with pytest.raises(OptimizationError, match="smaller than"):
        Optimizer(
            {"x": (-3.0, 3.0)}, run_sphere, method="grid", grid_points=5,
            budget=1, checkpoint_path=str(checkpoint), resume=True,
        ).run()


def test_checkpoint_file_written_atomically(tmp_path):
    checkpoint = tmp_path / "opt.json"
    opt = Optimizer(
        {"x": (-2.0, 2.0)}, run_sphere, method="grid", grid_points=3,
        budget=2, checkpoint_path=str(checkpoint),
    )
    result = opt.run()
    assert checkpoint.exists()
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["format"] == "labeeb-optimization-checkpoint"
    assert payload["best_objective"] == result.best_objective
    assert payload["next_index"] == 2
    assert len(payload["result"]["history"]) == 2
    assert not list(tmp_path.glob("*.tmp*"))  # no leftover tmp files


# --- export ------------------------------------------------------------------------------

def test_export_csv_json_xlsx(tmp_path):
    opt = Optimizer(
        {"x": (-2.0, 2.0)}, lambda c: c["x"] ** 2, method="grid",
        grid_points=5, budget=50,
    )
    result = opt.run()
    for suffix in (".csv", ".json", ".xlsx"):
        path = tmp_path / f"history{suffix}"
        export_optimization_history(result, str(path))
        assert path.exists() and path.stat().st_size > 0
    csv_text = (tmp_path / "history.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("index,status,simulated,objective,feasible,x,message")
    assert len(csv_text.splitlines()) == 6  # header + 5 records
    data = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert data["format"] == "labeeb-optimization-history"
    assert len(data["records"]) == 5
    assert data["best_objective"] == 0.0
    with pytest.raises(OptimizationError, match="Unsupported export format"):
        export_optimization_history(result, str(tmp_path / "history.txt"))


def test_empty_history_export(tmp_path):
    result = OptimizeResult(direction="minimize", method="grid", best_candidate=None, best_objective=None)
    path = tmp_path / "empty.json"
    export_optimization_history(result, str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["records"] == []


# --- Case/Campaign integration (simulation-backed objective) --------------------------------

def test_case_backed_objective_optimizes_over_simulation(tmp_path):
    """Each objective call runs a real Case: deck copy + output harvest."""
    import subprocess
    import sys

    solver = tmp_path / "deck_solver.py"
    solver.write_text(
        "import sys, csv\n"
        "from pathlib import Path\n"
        "deck = Path('input.deck').read_text()\n"
        "temp = float(deck.split('TEMP=')[1].split()[0])\n"
        "flux = float(deck.split('FLUX=')[1].split()[0])\n"
        "keff = 1.0 + (temp - 550.0) ** 2 * 1e-6 - flux * 1e-3\n"  # optimum ~ (550, 0)
        "with open('out.csv', 'w', newline='') as fh:\n"
        "    csv.writer(fh).writerow(['metric'])\n"
        "    csv.writer(fh).writerow([f'{keff:.6f}'])\n",
        encoding="utf-8",
    )
    deck = tmp_path / "input.deck"
    deck.write_text("TEMP=#TEMP#\nFLUX=#FLUX#\n", encoding="utf-8")
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "import labeeb\n"
        "from labeeb import Case, Database\n"
        "base = Path(sys.argv[1])\n"
        "work = Path(sys.argv[2])\n"
        "work.mkdir(exist_ok=True)\n"
        "shutil = __import__('shutil')\n"
        "shutil.copy2(base / 'deck_solver.py', work / 'deck_solver.py')\n"
        "deck_text = (base / 'input.deck').read_text()\n"
        "deck_text = deck_text.replace('#TEMP#', f'{float(sys.argv[3]):.3f}')\n"
        "deck_text = deck_text.replace('#FLUX#', f'{float(sys.argv[4]):.3f}')\n"
        "(work / 'input.deck').write_text(deck_text)\n"
        "case = Case(name='opt', output_files={'out.csv': ['metric']})\n"
        "case.database = Database(data={'X': [0.0]})\n"
        "case.main_dir = str(work)\n"
        "case.run_case_main_dir = 'run'\n"
        "case.run_type = 'new'\n"
        "case.exe_cmd = ['python deck_solver.py']\n"
        "case.objects_to_be_copied = [str(work / 'deck_solver.py'), str(work / 'input.deck')]\n"
        "case.launch_case(0)\n"
        "print(case.outputs['metric'][0][0])\n",
        encoding="utf-8",
    )

    def simulate(candidate):
        work = tmp_path / f"eval_{candidate['TEMP']:.0f}_{candidate['FLUX']:.1f}".replace(".", "_")
        work.mkdir(exist_ok=True)
        proc = subprocess.run(
            [sys.executable, str(evaluator), str(tmp_path), str(work),
             f"{candidate['TEMP']:.2f}", f"{candidate['FLUX']:.2f}"],
            capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
        )
        if proc.returncode != 0:
            return None
        return float(proc.stdout.strip().splitlines()[-1])

    opt = Optimizer(
        {"TEMP": (400.0, 700.0), "FLUX": (0.0, 10.0)},
        simulate, method="grid", grid_points=5, budget=25,
    )
    result = opt.run()
    assert result.reason in ("exhausted", "budget")  # grid(25) == budget(25)
    assert result.evaluations == 25
    assert abs(result.best_candidate["TEMP"] - 550.0) < 1e-6
    assert abs(result.best_candidate["FLUX"] - 10.0) < 1e-6  # -flux*1e-3 term -> max flux
    assert result.best_objective is not None and abs(result.best_objective - 0.99) < 1e-4

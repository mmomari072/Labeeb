"""Labeeb case study: simulation-based optimization + optional AI surrogate.

Runnable standalone (no optional engines required):

    python examples/optimize_ai_case_study.py [work_dir]

Searches a single design variable (fuel temperature) for the candidate whose
simulated response best matches a target. Every objective call runs a REAL
Case: a small Python "solver" is copied into the case directory, an input deck
is templated with the candidate, the command runs, and a CSV output is
harvested. The core Optimizer drives the grid search with an atomic
checkpoint. When scikit-learn is installed, a RandomForest surrogate is fitted
on the optimization history and used to rank additional candidates
(rank_candidates) — otherwise the surrogate section is skipped with a note.

Prints:
    OPTIMIZATION COMPLETE best_T=<float> best_objective=<float>
    SURROGATE AVAILABLE / SURROGATE SKIPPED (sklearn missing)
    RANKED_TOP <prediction> <T>
"""

import argparse
import pathlib
import sys
import tempfile

from labeeb import Optimizer, export_optimization_history


def make_workdir(base: pathlib.Path) -> None:
    """Write the solver + deck template used by every evaluation."""
    (base / "deck_solver.py").write_text(
        "import csv\n"
        "from pathlib import Path\n"
        "deck = Path('input.deck').read_text()\n"
        "temp = float(deck.split('T_FUEL=')[1].split()[0])\n"
        "# simulated reactivity response; optimum at T = 900 K\n"
        "response = (temp - 900.0) ** 2 * 1e-6\n"
        "with open('out.csv', 'w', newline='') as fh:\n"
        "    csv.writer(fh).writerow(['response'])\n"
        "    csv.writer(fh).writerow([f'{response:.8f}'])\n",
        encoding="utf-8",
    )
    (base / "input.deck").write_text("T_FUEL=#T_FUEL#\n", encoding="utf-8")


def simulate(base: pathlib.Path):
    """Return an objective_fn: one full Case run per candidate."""
    evaluator = base / "evaluator.py"
    evaluator.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "from labeeb import Case, Database\n"
        "base = Path(sys.argv[1])\n"
        "work = Path(sys.argv[2])\n"
        "work.mkdir(exist_ok=True)\n"
        "import shutil\n"
        "shutil.copy2(base / 'deck_solver.py', work / 'deck_solver.py')\n"
        "deck = (base / 'input.deck').read_text().replace(\n"
        "    '#T_FUEL#', f'{float(sys.argv[3]):.2f}')\n"
        "(work / 'input.deck').write_text(deck)\n"
        "case = Case(name='opt', output_files={'out.csv': ['response']})\n"
        "case.database = Database(data={'X': [0.0]})\n"
        "case.main_dir = str(work)\n"
        "case.run_case_main_dir = 'run'\n"
        "case.run_type = 'new'\n"
        "case.exe_cmd = ['python deck_solver.py']\n"
        "case.objects_to_be_copied = [str(work / 'deck_solver.py'), str(work / 'input.deck')]\n"
        "case.launch_case(0)\n"
        "print(case.outputs['response'][0][0])\n",
        encoding="utf-8",
    )
    import subprocess

    def objective_fn(candidate):
        work = base / f"eval_{candidate['T_FUEL']:.0f}".replace('.', '_')
        work.mkdir(exist_ok=True)
        proc = subprocess.run(
            [sys.executable, str(evaluator), str(base), str(work),
             f"{candidate['T_FUEL']:.2f}"],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            return None  # recorded as a simulation failure by the optimizer
        return float(proc.stdout.strip().splitlines()[-1])

    return objective_fn


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("work_dir", nargs="?", default=None)
    args = parser.parse_args(argv)

    base = pathlib.Path(args.work_dir) if args.work_dir else pathlib.Path(tempfile.mkdtemp(prefix="labeeb_opt_"))
    base.mkdir(parents=True, exist_ok=True)
    make_workdir(base)
    objective_fn = simulate(base)

    opt = Optimizer(
        {"T_FUEL": (600.0, 1200.0)},   # search domain [K]
        objective_fn,                   # one real Case run per evaluation
        direction="minimize",
        method="grid",
        grid_points=7,                  # 600..1200 step 100 -> 900 on grid
        budget=20,
        checkpoint_path=str(base / "opt_checkpoint.json"),
        patience=None,
    )
    result = opt.run()
    export_optimization_history(result, str(base / "optimization_history.csv"))
    best_t = result.best_candidate["T_FUEL"] if result.best_candidate else None
    print(f"OPTIMIZATION COMPLETE best_T={best_t} best_objective={result.best_objective} "
          f"evaluations={result.evaluations} failed={result.failed} reason={result.reason}")

    try:
        import sklearn  # noqa: F401
    except ImportError:
        print("SURROGATE SKIPPED (scikit-learn not installed)")
        return 0

    from labeeb import SurrogateModel, rank_candidates

    model = SurrogateModel(["T_FUEL"], backend="rf", seed=7)
    model.fit_from_history(result.history)
    model.save(str(base / "surrogate.pkl"))
    ranked = rank_candidates(model, {"T_FUEL": (600.0, 1200.0)}, n=200,
                             method="random", seed=7, direction="minimize")
    top_prediction, top_candidate = ranked[0]
    print(f"SURROGATE AVAILABLE best_prediction={top_prediction:.6f}")
    print(f"RANKED_TOP prediction={top_prediction:.6f} T={top_candidate['T_FUEL']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

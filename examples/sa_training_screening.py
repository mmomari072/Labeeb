"""SA training case study (LAB-TRAINING-CASES-01): sensitivity screening.

Simulator-neutral, API-first sensitivity analysis training example for Labeeb.
The "simulator" is a plain deterministic callable mapping input dict -> float —
swap it for any code (MCNP/RELAP5/...) run through a Case/Campaign: build the
same design matrix with OATConstructor/FOATConstructor, execute one simulation
per row, and reuse the ranking logic below on harvested metrics.

Screening design: One-at-a-Time sweep around a baseline (OATConstructor, first
value of each parameter = baseline), then a normalized local-sensitivity
ranking. Deterministic and self-contained:

    python examples/sa_training_screening.py [--print-table]

Prints:
    TRAINING-SA-COMPLETE top=<var> sensitivity=<float>
"""

import argparse

from labeeb import Database, OATConstructor


# ------------------------------------------------------------------ simulator

def simulate_response(inputs):
    """Simulator-neutral response: pure math, dominant sensitivity on 'TEMP'.

    Any real simulator can replace this callable; only its signature
    (dict[str, float] -> float) matters for the training workflow.
    """
    temp = inputs["TEMP"]
    flow = inputs["FLOW"]
    pressure = inputs["PRESSURE"]
    return (
        0.001 * (temp - 550.0) ** 2      # strong, nonlinear (T dominates)
        + 0.02 * (flow - 1400.0)          # weak linear
        + 1e-5 * (pressure - 150.0) ** 3  # negligible cubic
        + 0.9
    )


# ------------------------------------------------------------------ workflow

def run_sa(nominal=None, steps=None, print_table=False):
    """Build the OAT design, evaluate every row, rank sensitivities.

    Returns a summary dict (usable by tests): design rows, per-parameter
    normalized sensitivity (mean |dy| per unit of input), and the ranking.
    """
    nominal = nominal if nominal is not None else {
        "TEMP": 550.0, "FLOW": 1400.0, "PRESSURE": 150.0,
    }
    steps = steps if steps is not None else {
        "TEMP": 30.0, "FLOW": 50.0, "PRESSURE": 10.0,
    }
    if set(nominal) != set(steps):
        raise ValueError("nominal and steps must cover the same parameters")

    # API-first design matrix: baseline (first values) + one-at-a-time steps.
    oat = OATConstructor()
    oat.add_case({
        param: [nominal[param], nominal[param] + steps[param], nominal[param] - steps[param]]
        for param in nominal
    })
    design = oat.construct()
    db = Database(data=design)  # __<p>_index__ tracks keep rows aligned

    rows = [db.get_row(i) for i in range(len(db))]
    responses = [simulate_response(row) for row in rows]

    baseline = responses[0]
    sensitivity = {}
    for param in nominal:
        deltas = []
        for index, row in enumerate(rows):
            # row 0 = baseline; every later row moves exactly one parameter
            if index > 0 and row[param] != nominal[param] and all(
                row[other] == nominal[other] for other in nominal if other != param
            ):
                step_size = abs(row[param] - nominal[param])
                deltas.append(abs(responses[index] - baseline) / step_size)
        sensitivity[param] = sum(deltas) / len(deltas) if deltas else 0.0

    ranking = sorted(sensitivity.items(), key=lambda item: item[1], reverse=True)
    if print_table:
        for index, row in enumerate(rows):
            print(f"row {index}: {row}  -> response={responses[index]:.6f}")

    return {
        "design_rows": len(db),
        "baseline_response": baseline,
        "sensitivity": sensitivity,
        "ranking": ranking,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print-table", action="store_true",
                        help="print the full OAT design table with responses")
    args = parser.parse_args(argv)

    summary = run_sa(print_table=args.print_table)
    top_var, top_sens = summary["ranking"][0]
    print(f"TRAINING-SA-COMPLETE top={top_var} sensitivity={top_sens:.6f}")
    for var, value in summary["ranking"]:
        print(f"  sensitivity[{var}] = {value:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

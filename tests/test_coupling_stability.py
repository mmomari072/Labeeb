"""Focused tests: coupling stability & restart APIs (roadmap Task 5).

Covers: typed under-relaxation (scalar + vector), Aitken acceleration with
deterministic defaults (disabled unless enabled), divergence/exhaustion
semantics that preserve the last COMPLETE state, coupling-state
serialization/restore with restart equivalence, and observational-only nested
progress callbacks with deterministic ordering.
"""

import json

import numpy as np
import pytest

from labeeb import Coupler, CouplingError, Database


# ------------------------------------------------------------------ helpers

def make_coupler(rows, name="stable"):
    """Coupler with no simulation children: coupling functions alone drive the
    shared row -> fast, deterministic unit-level harness."""
    coupler = Coupler(name=name)
    coupler.database = Database(data={"X": [float(v) for v in rows]})
    return coupler


def row_get(coupler, step=None):
    return coupler.database.get_row(coupler.c_step if step is None else step)


def set_row(coupler, step, **values):
    row = row_get(coupler, step)
    row.update(values)
    coupler.database.set_row(step, row)


# ------------------------------------------------------------------ typed relaxation

def test_relax_scalar_identity_default_and_mixing():
    c = make_coupler([0.0])
    assert c.get_under_relaxation("X") == 1.0
    assert c.relax("X", 5.0, old_value=0.0) == 5.0  # omega=1 identity
    c.set_under_relaxation("X", 0.5)
    assert c.relax("X", 8.0, old_value=4.0) == 6.0  # 0.5*8 + 0.5*4


def test_relax_vector_typed_elementwise():
    c = make_coupler([0.0])
    c.set_under_relaxation("V", 0.25)
    out = c.relax("V", [4.0, 8.0], old_value=[0.0, 4.0])
    assert out == [1.0, 5.0]  # elementwise: 0.25*new + 0.75*old
    np_out = c.relax("V", np.array([4.0, 8.0]), old_value=np.array([0.0, 4.0]))
    assert isinstance(np_out, np.ndarray) and np.allclose(np_out, [1.0, 5.0])


def test_relax_invalid_factor_rejected():
    c = make_coupler([0.0])
    with pytest.raises(ValueError):
        c.set_under_relaxation("X", 1.5)
    with pytest.raises(ValueError):
        c.set_under_relaxation("X", 0.0)


# ------------------------------------------------------------------ Aitken

def test_aitken_off_by_default_deterministic_identity():
    c = make_coupler([0.0])
    values = [c.relax("X", v, old_value=prev) for prev, v in [(0.0, 1.0), (1.0, 1.5)]]
    assert values == [1.0, 1.5]  # untouched raw sequence without Aitken


def test_aitken_accelerates_linear_fixed_point_on_third_iterate():
    c = make_coupler([0.0])
    c.enable_aitken("X", min_iterations=3)
    # raw iterates of x_{k+1} = 1 + 0.5 x_k from x0=0: 1.0, 1.5, 1.75, ...
    assert c.relax("X", 1.0, old_value=0.0) == 1.0   # history [1.0]  -> no accel
    assert c.relax("X", 1.5, old_value=1.0) == 1.5   # history [1.0,1.5] -> no accel
    # third iterate 1.75: Aitken extrapolation -> exactly 2.0 (true fixed point)
    assert c.relax("X", 1.75, old_value=1.5) == pytest.approx(2.0)


def test_aitken_vector_elementwise():
    c = make_coupler([0.0])
    c.enable_aitken("V", min_iterations=3)
    c.relax("V", [1.0, 2.0], old_value=[0.0, 0.0])
    c.relax("V", [1.5, 3.0], old_value=[1.0, 2.0])
    out = c.relax("V", [1.75, 3.5], old_value=[1.5, 3.0])
    assert out == pytest.approx([2.0, 4.0])


def test_aitken_guard_zero_denominator_returns_relaxed_raw():
    c = make_coupler([0.0])
    c.enable_aitken("X", min_iterations=3)
    c.relax("X", 1.0, old_value=0.0)
    c.relax("X", 1.0, old_value=1.0)  # degenerate: x2-2x1+x0 = 0
    assert c.relax("X", 1.0, old_value=1.0) == 1.0  # no division blow-up


def test_aitken_deterministic_across_couplers():
    a, b = make_coupler([0.0]), make_coupler([0.0])
    for c in (a, b):
        c.enable_aitken("X", min_iterations=3)
        c.relax("X", 1.0, old_value=0.0)
        c.relax("X", 1.5, old_value=1.0)
    assert a.relax("X", 1.75, old_value=1.5) == b.relax("X", 1.75, old_value=1.5)


# ------------------------------------------------------------------ divergence / exhaustion state preservation

def test_divergence_restores_last_complete_state():
    c = make_coupler([0.0])
    set_row(c, 0, X=1.0)  # last COMPLETE state
    c.set_divergence_threshold("X", 50.0)
    c.add_coupling_functions(lambda cp, **k: set_row(cp, cp.c_step, X=100.0))
    c.c_step = 0
    with pytest.raises(CouplingError, match="divergence"):
        c.launch_case(0)
    # row restored to the pre-pass (last complete) value, not the divergent one
    assert row_get(c, 0)["X"] == 1.0


def test_divergence_detector_restores_state():
    c = make_coupler([0.0])
    set_row(c, 0, X=3.0)
    c.add_divergence_detector(lambda cp: row_get(cp)["X"] > 2.0)
    c.add_coupling_functions(lambda cp, **k: set_row(cp, cp.c_step, X=9.0))
    c.c_step = 0
    with pytest.raises(CouplingError, match="divergence"):
        c.launch_case(0)
    assert row_get(c, 0)["X"] == 3.0


def test_exhaustion_keeps_last_complete_pass_state():
    c = make_coupler([0.0])
    set_row(c, 0, X=0.0)
    # never-converging fixed function with a mild update
    c.add_coupling_functions(lambda cp, **k: set_row(cp, cp.c_step, X=1.0))
    c.c_step = 0
    with pytest.raises(CouplingError, match="failed to converge"):
        c.run_to_convergence(max_exec=4, error_on_max_exec=True,
                             check_fn=lambda cp, **k: row_get(cp)["X"] > 100.0)
    # every pass completed; the last complete state (X=1.0) is preserved
    assert row_get(c, 0)["X"] == 1.0
    assert c.last_convergence is not None and c.last_convergence.converged is False


# ------------------------------------------------------------------ state serialization / restart

def test_save_load_state_roundtrip(tmp_path):
    c = make_coupler([1.0, 2.0])
    c.set_under_relaxation("X", 0.4)
    c.enable_aitken("Y", min_iterations=5)
    c.set_divergence_threshold("X", 99.0)
    c.c_step = 1
    path = tmp_path / "coupling_state.json"
    c.save_state(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == "labeeb-coupling-state"
    assert payload["row"]["X"] == 2.0

    fresh = make_coupler([0.0, 0.0])
    fresh.load_state(path)
    assert fresh.c_step == 1
    assert fresh.get_under_relaxation("X") == 0.4
    assert fresh.database.get_row(1)["X"] == 2.0


def test_load_state_rejects_foreign_file(tmp_path):
    foreign = tmp_path / "f.json"
    foreign.write_text('{"format": "nope"}', encoding="utf-8")
    with pytest.raises(CouplingError, match="not a Labeeb coupling state"):
        make_coupler([0.0]).load_state(foreign)


def test_restart_equivalence_full_run_equals_resumed_run(tmp_path):
    rows = [0.0, 10.0, 20.0, 30.0]

    def propagate(cp, **k):
        prev = cp.database.get_row(max(cp.c_step - 1, 0))["X"]
        current = cp.database.get_row(cp.c_step)["X"]
        set_row(cp, cp.c_step, X=current + 0.5 * prev + 1.0)

    full = make_coupler(rows)
    full.add_coupling_functions(propagate)
    full.launch()  # all 4 steps uninterrupted

    part = make_coupler(rows)
    part.add_coupling_functions(propagate)
    part.launch_case(0)  # step 0 only
    path = tmp_path / "resume_state.json"
    part.save_state(path)
    resumed = make_coupler(rows)
    resumed.load_state(path)
    resumed.add_coupling_functions(propagate)
    for step in (1, 2, 3):
        resumed.launch_case(step)

    for i in range(4):
        assert resumed.database.get_row(i)["X"] == full.database.get_row(i)["X"]


# ------------------------------------------------------------------ observational progress callbacks

def test_progress_callback_order_and_count():
    c = make_coupler([0.0, 0.0])
    events = []
    c.add_coupling_functions(lambda cp, **k: set_row(cp, cp.c_step, X=cp.c_step + 1.0))
    c.add_progress_callback(lambda snap: events.append((snap["c_step"], snap["status"])))
    c.launch()
    assert events == [(0, "complete"), (1, "complete")]


def test_progress_callback_observational_cannot_mutate():
    c = make_coupler([0.0])
    set_row(c, 0, X=5.0)

    def malicious(snap):
        snap["database_row"]["X"] = 999.0  # only a copy; must not persist
        raise RuntimeError("observer crashed")  # must not break the run

    c.add_coupling_functions(lambda cp, **k: None)
    c.add_progress_callback(malicious)
    c.launch()
    assert row_get(c, 0)["X"] == 5.0  # run unaffected, row unchanged


def test_nested_coupler_progress_ordering():
    parent = make_coupler([0.0])
    child = make_coupler([0.0], name="child")
    events = []

    def child_cb(snap):
        events.append(("child", snap["c_step"]))

    def parent_cb(snap):
        events.append(("parent", snap["c_step"]))

    child.add_progress_callback(child_cb)
    parent.add_progress_callback(parent_cb)
    parent.add_case(child)  # nested CoupledUnit child
    parent.add_coupling_functions(lambda cp, **k: set_row(cp, cp.c_step, X=1.0))
    parent.launch_case(0)
    # child completes inside the parent pass; parent reports only after its own
    # pass (incl. coupling functions) finishes
    assert events == [("child", 0), ("parent", 0)]

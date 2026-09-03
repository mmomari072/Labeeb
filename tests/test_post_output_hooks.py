"""Focused tests: post-output hooks (LAB-POST-OUTPUT-HOOKS-01).

Hooks run after outputs/harvesters are read and before results finalize.
Contract under test: ordering (after _read_outputs, before post_functions),
context (live outputs + case), return-or-mutation semantics (None mutation /
dict merge), validation (callable + unique names + dict-or-None return),
failure-policy integration (harvest_failure_policy stop/continue), recording
(history intact, failures list, catalog metrics via output deltas), and
sequential/parallel safety.
"""

import csv

import pytest

from labeeb import (
    Campaign,
    CampaignManifest,
    Case,
    CaseExecutionError,
    Database,
    OutputCatalog,
)


# --- helpers -------------------------------------------------------------------

def make_csv_case(tmp_path, rows=(("x", "y"), (2.0, 3.0)), commands=()):
    data_file = tmp_path / "data.csv"
    with open(data_file, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    case = Case(name="hook_case", output_files={"data.csv": ["x", "y"]})
    case.database = Database(data={"ROW": [0.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "run"
    case.run_type = "new"
    case.exe_cmd = list(commands)
    case.objects_to_be_copied = [str(data_file)]
    return case


def ratio_hook(outputs, case):
    """Module-level (pickleable): synthesize x/y from harvested columns."""
    return {"ratio": outputs["x"][-1][0] / outputs["y"][-1][0]}


def double_x_hook(outputs, case):
    x = outputs["x"][-1][0]
    outputs["x"][-1] = [2.0 * x]  # in-place mutation of the harvested row value


def return_hook(outputs, case):
    return {"squared": outputs["x"][-1][0] ** 2, "row": case.case_id}


def ordering_hook(outputs, case):
    case.order_trace.append("hook")


def ordering_post_fn(case, **kwargs):
    case.order_trace.append("post_function")


# --- ordering & context ----------------------------------------------------------

def test_hook_runs_after_read_before_post_functions(tmp_path):
    case = make_csv_case(tmp_path)
    case.order_trace = []
    case.post_functions = [ordering_post_fn]
    case.add_post_output_hook("trace", ordering_hook)
    case.launch_case(0)
    # outputs were harvested first, the hook second, post_functions last
    assert case.order_trace == ["hook", "post_function"]
    assert case.outputs["x"] == [[2.0]]


def test_hook_sees_full_context(tmp_path):
    seen = {}

    def spy(outputs, case):
        seen["case_id"] = case.case_id
        seen["case_dir"] = case.current_case_dir
        seen["history"] = len(case.execution_history)

    case = make_csv_case(tmp_path)
    case.add_post_output_hook("spy", spy)
    case.launch_case(0)
    assert seen == {"case_id": 0, "case_dir": case.current_case_dir, "history": 0}
    assert case.outputs["x"] == [[2.0]]


# --- return-or-mutation semantics ---------------------------------------------------

def test_returned_mapping_creates_new_metric_columns(tmp_path):
    case = make_csv_case(tmp_path)
    case.add_post_output_hook("derive", return_hook)
    case.launch_case(0)
    assert case.outputs["squared"] == [4.0]
    assert case.outputs["row"] == [0]


def test_in_place_mutation_honored(tmp_path):
    case = make_csv_case(tmp_path)
    case.add_post_output_hook("double", double_x_hook)
    case.launch_case(0)
    assert case.outputs["x"] == [[4.0]]  # 2.0 mutated to 4.0 before finalization


def test_mutation_and_returned_merge_combined(tmp_path):
    case = make_csv_case(tmp_path)
    case.add_post_output_hook("ratio", ratio_hook)
    case.add_post_output_hook("derive", return_hook)
    case.launch_case(0)
    assert case.outputs["ratio"] == [2.0 / 3.0]
    assert case.outputs["squared"] == [4.0]


def test_hooks_run_in_registration_order(tmp_path):
    calls = []

    def first(outputs, case):
        calls.append("first")
        outputs["a"] = [1]

    def second(outputs, case):
        calls.append("second")

    case = make_csv_case(tmp_path)
    case.add_post_output_hook("first", first)
    case.add_post_output_hook("second", second)
    case.launch_case(0)
    assert calls == ["first", "second"]


# --- validation -----------------------------------------------------------------------

def test_non_callable_hook_rejected(tmp_path):
    case = make_csv_case(tmp_path)
    with pytest.raises(CaseExecutionError, match="must be callable"):
        case.add_post_output_hook("bad", 42)


def test_duplicate_hook_name_rejected(tmp_path):
    case = make_csv_case(tmp_path)
    case.add_post_output_hook("only", lambda o, c: None)
    with pytest.raises(CaseExecutionError, match="already registered"):
        case.add_post_output_hook("only", lambda o, c: None)


def test_invalid_return_type_raises(tmp_path):
    case = make_csv_case(tmp_path)
    case.add_post_output_hook("bad_return", lambda o, c: "nope")
    with pytest.raises(CaseExecutionError, match="must return None or a dict"):
        case.launch_case(0)


def test_constructor_hook_list_accepted_and_validated(tmp_path):
    case = make_csv_case(tmp_path)
    case.post_output_hooks = [("ratio", ratio_hook)]
    case.launch_case(0)
    assert case.outputs["ratio"] == [2.0 / 3.0]
    bad = make_csv_case(tmp_path)
    bad.post_output_hooks = [("nope", 5)]
    with pytest.raises(CaseExecutionError, match="must be callable"):
        bad.launch_case(0)


# --- failure-policy integration ---------------------------------------------------------

def test_hook_failure_stop_policy_raises(tmp_path):
    def boom(outputs, case):
        raise ValueError("hook exploded")

    case = make_csv_case(tmp_path)
    case.harvest_failure_policy = "stop"
    case.add_post_output_hook("boom", boom)
    with pytest.raises(CaseExecutionError, match="hook 'boom' failed for case 0"):
        case.launch_case(0)
    # outputs were harvested before the hook failure
    assert case.outputs["x"] == [[2.0]]


def test_hook_failure_continue_policy_records_and_continues(tmp_path):
    def boom(outputs, case):
        raise RuntimeError("hook exploded")

    def later(outputs, case):
        return {"after": "ran"}

    case = make_csv_case(tmp_path)
    case.harvest_failure_policy = "continue"
    case.add_post_output_hook("boom", boom)
    case.add_post_output_hook("later", later)
    case.launch_case(0)  # no raise under continue

    assert case._case_failed is False  # enrichment failure does not fail the case
    assert len(case.post_output_hook_failures) == 1
    assert "boom: RuntimeError: hook exploded" in case.post_output_hook_failures[0]
    assert case.outputs["x"] == [[2.0]]  # harvested outputs kept
    assert case.outputs["after"] == ["ran"]  # remaining hooks still ran


def test_hook_failure_policy_default_is_stop(tmp_path):
    case = make_csv_case(tmp_path)  # default harvest_failure_policy = stop
    case.add_post_output_hook("boom", lambda o, c: (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(CaseExecutionError, match="hook 'boom' failed"):
        case.launch_case(0)


# --- recording: history/catalog/state ---------------------------------------------------

def test_failed_launch_with_stop_records_failed_history(tmp_path):
    """Stop-policy hook failure goes through the normal failed-case recording."""
    case = make_csv_case(tmp_path)
    case.database = Database(data={"ROW": [0.0]})
    case.add_post_output_hook("boom", lambda o, c: (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(CaseExecutionError, match="1 of 1 cases failed"):
        case.launch()
    assert case.execution_history[-1]["status"] == "FAILED"


def test_hook_metrics_flow_into_catalog_rows(tmp_path):
    template = tmp_path / "input.deck"
    template.write_text("ok", encoding="utf-8")
    data_file = tmp_path / "data.csv"
    with open(data_file, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([("x", "y"), (2.0, 3.0)])
    manifest = CampaignManifest.from_dict(
        {
            "name": "hooks",
            "parameters": {"ROW": [0.0]},
            "templates": [str(template)],
            "commands": ["python -c \"pass\""],
            "execution": {"run_dir": str(tmp_path / "runs")},
        }
    )
    campaign = Campaign(manifest, output_catalog=str(tmp_path / "catalog.sqlite"))
    original_build = campaign.build_case

    def instrumented_build():
        built = original_build()
        built.objects_to_be_copied = [str(data_file)]
        built.output_files = {"data.csv": ["x", "y"]}
        built.outputs = {"x": [], "y": []}  # reset columns for the override
        built.database = Database(data={"ROW": [0.0]})
        built.add_post_output_hook("ratio", ratio_hook)
        return built

    campaign.build_case = instrumented_build  # type: ignore[method-assign]
    results = campaign.run()
    assert results[0].status == "SUCCESS"
    with OutputCatalog(tmp_path / "catalog.sqlite") as catalog:
        row = catalog.latest(0)
        assert row is not None
        assert row.metrics["x"] == [2.0]
        assert row.metrics["ratio"] == pytest.approx(2.0 / 3.0)


def _row_ok_hook(outputs, case):
    return {"row_ok": outputs["x"][-1][0] * 10 + case.case_id}


# --- sequential/parallel safety ---------------------------------------------------------

def test_parallel_launch_hooks_isolated_per_worker(tmp_path):
    data_file = tmp_path / "data.csv"
    with open(data_file, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([("x", "y"), (2.0, 3.0)])
    case = Case(name="par_hook", output_files={"data.csv": ["x", "y"]})
    case.database = Database(data={"ROW": [0.0, 1.0, 2.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "run"
    case.run_type = "new"
    case.exe_cmd = []
    case.objects_to_be_copied = [str(data_file)]
    case.add_post_output_hook("row_ok", _row_ok_hook)

    case.launch(parallel=True)
    assert case.outputs["x"] == [[2.0], [2.0], [2.0]]
    assert case.outputs["row_ok"] == [20.0, 21.0, 22.0]  # per-row, no cross-talk
    assert case.post_output_hook_failures == []


# --- post-output feedback & adaptive updates -------------------------------------------

from labeeb.utils.file_io import File


def _adaptive_feedback_hook(outputs, case):
    """Post-output hook deriving output metric and adjusting future database row parameters."""
    temp = outputs["y"][-1][0] * 20.0  # e.g. 3.0 * 20 = 60.0
    next_idx = case.case_id + 1
    if next_idx < len(case.database):
        if temp > 50.0:
            # Overheating detected: reduce next row POWER by 50%
            current_power = case.database["POWER"][next_idx]
            case.database.set_row(next_idx, {"POWER": current_power * 0.5})
    return {"temp": temp}


def test_post_output_feedback_updates_future_database_rows_sequentially(tmp_path):
    data_file = tmp_path / "data.csv"
    with open(data_file, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([("x", "y"), (2.0, 3.0)])

    deck_template = tmp_path / "deck.template"
    deck_template.write_text("POWER = #POWER#\n", encoding="utf-8")

    case = Case(name="feedback_case", output_files={"data.csv": ["x", "y"]})
    case.database = Database(data={"POWER": [100.0, 100.0, 100.0]})
    case.FlagsMap = {"#POWER#": "POWER"}
    case.add_file(File(file_path=str(deck_template)))
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = []
    case.objects_to_be_copied = [str(data_file)]
    case.add_post_output_hook("adaptive_feedback", _adaptive_feedback_hook)

    # Launch sequentially so row 0 hook updates row 1 before row 1 launches
    case.launch(parallel=False)

    # Row 0 runs with POWER=100.0, hook sees temp=60.0 > 50.0, updates row 1 POWER -> 50.0
    # Row 1 runs with POWER=50.0, hook sees temp=60.0 > 50.0, updates row 2 POWER -> 50.0
    assert list(case.database["POWER"]) == [100.0, 50.0, 50.0]
    assert case.outputs["temp"] == [60.0, 60.0, 60.0]

    # Verify rendered templates for case_1 and case_2 reflect updated POWER parameters
    deck_1 = tmp_path / "runs" / "case_1" / "deck.template"
    deck_2 = tmp_path / "runs" / "case_2" / "deck.template"
    assert "POWER = 50.0" in deck_1.read_text(encoding="utf-8")
    assert "POWER = 50.0" in deck_2.read_text(encoding="utf-8")


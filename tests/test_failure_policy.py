"""Focused tests: configurable stop/continue/retry failure policies for command
and output-harvesting failures (LAB-FAILURE-POLICY-01), preserving defaults."""

import pytest

from labeeb import (
    Campaign,
    CampaignManifest,
    Case,
    CaseExecutionError,
    Database,
    OutputCatalog,
)


def _case(tmp_path, command, output_files=None, policy=None, harvest=None, attempts=None):
    case = Case(
        name="policy_case",
        output_files=output_files if output_files is not None else {},
    )
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = [command]
    if policy is not None:
        case.command_failure_policy = policy
    if harvest is not None:
        case.harvest_failure_policy = harvest
    if attempts is not None:
        case.max_attempts = attempts
    return case


FLAPPY = "python -c \"import pathlib; p=pathlib.Path('n.txt'); n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1)); exit(0 if n >= 1 else 7)\""


# --- Defaults preserved --------------------------------------------------------

def test_default_stop_raises_and_records(tmp_path):
    case = _case(tmp_path, "python -c \"import sys; sys.exit(3)\"")
    with pytest.raises(CaseExecutionError, match="Simulation command failed"):
        case.launch_case(0)
    assert case.execution_history[-1]["status"] == "FAILED"
    assert case.execution_history[-1]["exit_code"] == 3


def test_default_harvest_stop_raises_on_missing_output(tmp_path):
    case = _case(tmp_path, "printf done", output_files={"out.csv": ["keff"]})
    with pytest.raises(CaseExecutionError, match="Required output file"):
        case.launch_case(0)


def test_invalid_policies_rejected(tmp_path):
    with pytest.raises(CaseExecutionError, match="command_failure_policy must be"):
        Case(name="x", output_files={}, command_failure_policy="explode")
    with pytest.raises(CaseExecutionError, match="harvest_failure_policy must be"):
        Case(name="x", output_files={}, harvest_failure_policy="retry")
    with pytest.raises(CaseExecutionError, match="max_attempts must be >= 2"):
        Case(name="x", output_files={}, command_failure_policy="retry", max_attempts=1)
    with pytest.raises(CaseExecutionError, match="max_attempts must be an integer"):
        Case(name="x", output_files={}, max_attempts=0)


# --- continue policy -------------------------------------------------------------

def test_continue_records_failure_and_returns(tmp_path):
    case = _case(tmp_path, "python -c \"import sys; sys.exit(4)\"", policy="continue")
    case.launch_case(0)  # no raise under continue

    assert case._case_failed is True
    assert case.failure is not None and "exit code 4" in case.failure
    assert case.execution_history[-1]["status"] == "FAILED"
    assert case.execution_history[-1]["message"] == case.failure


def test_continue_skips_remaining_commands(tmp_path):
    case = Case(name="two_cmd", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = [
        "python -c \"import sys; sys.exit(5)\"",
        "python -c \"open('ran_second','w').write('x')\"",
    ]
    case.command_failure_policy = "continue"
    case.launch_case(0)
    assert not (tmp_path / "runs" / "case_0" / "ran_second").exists()


def test_launch_aggregates_continue_failures(tmp_path):
    case = _case(tmp_path, "python -c \"import sys; sys.exit(6)\"", policy="continue")
    case.database = Database(data={"RHO": [19.0, 18.0, 20.0]})
    with pytest.raises(CaseExecutionError, match="3 of 3 cases failed"):
        case.launch()
    # outputs recorded per failing row without double-None misalignment
    assert len(case.outputs) == 0 or all(len(v) == 3 for v in case.outputs.values())


def test_harvest_continue_records_none_outputs(tmp_path):
    case = _case(tmp_path, "printf done", output_files={"out.csv": ["keff"]}, harvest="continue")
    case.launch_case(0)  # missing out.csv tolerated

    assert case._case_failed is True
    assert "was not produced" in case.failure
    assert case.outputs["keff"] == [[None]]


def test_harvester_failure_continue_records_none(tmp_path):
    case = Case(name="h_cont", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["printf done"]
    case.harvest_failure_policy = "continue"
    case.add_harvester("keff_h", pattern="zz", file_target="missing.csv")
    case.launch_case(0)
    assert case._case_failed is True
    assert case.outputs["keff_h"] == [None]


# --- retry policy -----------------------------------------------------------------

def test_retry_succeeds_after_transient_failure(tmp_path):
    case = _case(tmp_path, FLAPPY, policy="retry", attempts=2)
    case.launch_case(0)

    assert case._case_failed is False
    statuses = [entry["status"] for entry in case.execution_history]
    assert statuses == ["FAILED", "SUCCESS"]  # transient failure recorded, then success
    assert (tmp_path / "runs" / "case_0" / "n.txt").read_text() == "2"


def test_retry_exhaustion_still_stops_and_records(tmp_path):
    case = _case(tmp_path, "python -c \"import sys; sys.exit(9)\"", policy="retry", attempts=3)
    with pytest.raises(CaseExecutionError, match="Simulation command failed"):
        case.launch_case(0)
    failed_entries = [e for e in case.execution_history if e["status"] == "FAILED"]
    assert len(failed_entries) == 3  # every exhausted attempt recorded


# --- Campaign integration ----------------------------------------------------------

def _manifest(tmp_path, command, name="fail-study", command_failure_policy=None, harvest_failure_policy=None):
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    execution = {"run_dir": str(tmp_path / "runs")}
    if command_failure_policy is not None:
        execution["command_failure_policy"] = command_failure_policy
    if harvest_failure_policy is not None:
        execution["harvest_failure_policy"] = harvest_failure_policy
    return CampaignManifest.from_dict(
        {
            "name": name,
            "parameters": {"VALUE": [1.0]},
            "templates": [str(template)],
            "commands": [command],
            "execution": execution,
        }
    )


def test_campaign_records_continue_policy_failure_as_failed(tmp_path):
    manifest = _manifest(tmp_path, "python -c \"import sys; sys.exit(2)\"")
    campaign = Campaign(manifest, state_path=str(tmp_path / "state.sqlite"))

    original_build = campaign.build_case

    def instrumented_build():
        instrumented = original_build()
        instrumented.command_failure_policy = "continue"
        instrumented.harvest_failure_policy = "continue"
        return instrumented

    campaign.build_case = instrumented_build  # type: ignore[method-assign]
    results = campaign.run()
    assert results[0].status == "FAILED"
    assert "exit code 2" in results[0].failure
    # retry on the next run with a working command succeeds (attempt numbering intact)
    ok_manifest = _manifest(tmp_path, "printf ok")
    ok_campaign = Campaign(ok_manifest, state_path=str(tmp_path / "state.sqlite"))
    original_ok_build = ok_campaign.build_case

    def ok_build():
        instrumented = original_ok_build()
        instrumented.command_failure_policy = "continue"
        instrumented.harvest_failure_policy = "continue"
        return instrumented

    ok_campaign.build_case = ok_build  # type: ignore[method-assign]
    second = ok_campaign.run()
    assert second[0].status == "SUCCESS"


def test_campaign_default_stop_still_records_failed_result(tmp_path):
    manifest = _manifest(tmp_path, "python -c \"import sys; sys.exit(2)\"")
    campaign = Campaign(manifest, output_catalog=str(tmp_path / "catalog.sqlite"))
    results = campaign.run()  # default stop policy
    assert results[0].status == "FAILED"
    with OutputCatalog(tmp_path / "catalog.sqlite") as catalog:
        row = catalog.latest(0)
        assert row is not None and row.status == "FAILED"
        assert "exited with code 2" in row.message


def test_campaign_manifest_failure_policy_config(tmp_path):
    manifest = _manifest(
        tmp_path, "python -c \"import sys; sys.exit(2)\"",
        command_failure_policy="continue", harvest_failure_policy="continue",
    )
    campaign = Campaign(manifest)
    results = campaign.run()
    assert results[0].status == "FAILED"
    assert "exit code 2" in results[0].failure

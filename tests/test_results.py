import pandas as pd
import pytest

from labeeb.results import CaseResult, CampaignStateStore, export_case_results


def test_case_result_captures_success_and_failure_fields():
    result = CaseResult(
        case_id=3,
        parameters={"RHO": 19.2},
        status="FAILED",
        exit_code=7,
        duration_seconds=1.25,
        artifacts={"input": "case_3/input.i"},
        metrics={},
        failure="simulator exited with code 7",
    )

    record = result.to_record()

    assert record["case_id"] == 3
    assert record["status"] == "FAILED"
    assert record["failure"] == "simulator exited with code 7"


def test_export_case_results_retains_failed_rows(tmp_path):
    results = [
        CaseResult(0, {"RHO": 19.0}, "SUCCESS", 0, 0.5, {}, {"keff": 1.0}),
        CaseResult(1, {"RHO": 19.5}, "FAILED", 2, 0.1, {}, {}, "missing output"),
    ]
    output = tmp_path / "results.csv"

    dataframe = export_case_results(results, output)

    loaded = pd.read_csv(output)
    assert list(dataframe["case_id"]) == [0, 1]
    assert list(loaded["status"]) == ["SUCCESS", "FAILED"]
    assert loaded.loc[1, "failure"] == "missing output"


def test_export_case_results_rejects_unsupported_format(tmp_path):
    result = CaseResult(0, {"RHO": 19.0}, "SUCCESS", 0, 0.5, {}, {})

    with pytest.raises(ValueError, match="format"):
        export_case_results([result], tmp_path / "results.txt")


def test_campaign_state_persists_attempts_and_supports_resume(tmp_path):
    path = tmp_path / "state.sqlite"
    store = CampaignStateStore(path)
    failed = CaseResult(0, {"RHO": 19.0}, "FAILED", 2, 0.1, failure="transient")
    succeeded = CaseResult(0, {"RHO": 19.0}, "SUCCESS", 0, 0.2)

    store.save(failed, input_hash="abc")
    assert store.retry_allowed(0, max_retries=2) is True
    store.save(succeeded, input_hash="abc")
    store.close()

    reopened = CampaignStateStore(path)
    state = reopened.get(0)
    assert state["attempts"] == 2
    assert state["status"] == "SUCCESS"
    assert reopened.pending([0, 1]) == [1]
    reopened.close()


def test_campaign_state_reuses_only_matching_successful_input_hash(tmp_path):
    store = CampaignStateStore(tmp_path / "state.sqlite")
    result = CaseResult(4, {"RHO": 19.0}, "SUCCESS", 0, 0.2)
    store.save(result, input_hash="abc")

    assert store.should_reuse(4, "abc") is True
    assert store.should_reuse(4, "changed") is False
    store.close()

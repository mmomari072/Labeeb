import pandas as pd
import pytest

from labeeb.results import CaseResult, export_case_results


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

from pathlib import Path
import pytest
import pandas as pd

from labeeb.results import CaseResult, ExecutionStatusRegistry, StatusRegistry


def test_status_registry_record_and_lookup():
    reg = StatusRegistry()
    assert len(reg) == 0

    entry = reg.record(
        case_id=0,
        status="SUCCESS",
        exit_code=0,
        duration_seconds=1.25,
        stdout_status="captured",
        stderr_status="empty",
        stdout_bytes=100,
        stderr_bytes=0,
    )
    assert entry["case_id"] == 0
    assert entry["status"] == "SUCCESS"
    assert entry["duration_seconds"] == 1.25
    assert len(reg) == 1
    assert 0 in reg
    assert reg[0]["exit_code"] == 0
    assert reg.get(0) == entry
    assert reg.get(99) is None


def test_status_registry_validation():
    reg = StatusRegistry()
    with pytest.raises(ValueError, match="case_id"):
        reg.record(case_id=-1, status="SUCCESS")

    with pytest.raises(ValueError, match="status"):
        reg.record(case_id=0, status="")


def test_status_registry_record_result():
    reg = ExecutionStatusRegistry()
    res_success = CaseResult(0, {"x": 1}, "SUCCESS", 0, 0.5, metrics={"k": 1.0})
    res_fail = CaseResult(1, {"x": 2}, "FAILED", 1, 0.2, failure="Simulation error")

    reg.record_result(res_success)
    reg.record_result(res_fail)

    assert len(reg) == 2
    assert reg.successful_cases() == [0]
    assert reg.failed_cases() == [1]
    assert reg.summary() == {"success": 1, "failed": 1}
    assert reg.total_duration() == pytest.approx(0.7)


def test_status_registry_queries_and_filters():
    reg = StatusRegistry()
    reg.record(0, "SUCCESS", exit_code=0, duration_seconds=1.0)
    reg.record(1, "FAILED", exit_code=1, duration_seconds=0.5, error="crash")
    reg.record(2, "TIMEOUT", exit_code=-999, duration_seconds=10.0, error="timeout")
    reg.record(3, "SUCCESS", exit_code=0, duration_seconds=2.0)

    assert reg.case_ids() == [0, 1, 2, 3]
    assert reg.successful_cases() == [0, 3]
    assert reg.failed_cases() == [1, 2]
    assert len(reg.filter_by_status("success")) == 2
    assert len(reg.filter_by_status("timeout")) == 1
    assert [e["case_id"] for e in reg] == [0, 1, 2, 3]

    reg.clear()
    assert len(reg) == 0
    assert reg.summary() == {}


def test_status_registry_to_dataframe_and_export(tmp_path: Path):
    reg = StatusRegistry()
    assert reg.to_dataframe().empty

    reg.record(0, "SUCCESS", exit_code=0, duration_seconds=1.0, extra_note="test1")
    reg.record(1, "FAILED", exit_code=1, duration_seconds=0.5, error="err")

    df = reg.to_dataframe()
    assert len(df) == 2
    assert "case_id" in df.columns
    assert "status" in df.columns

    csv_path = tmp_path / "status.csv"
    json_path = tmp_path / "status.json"
    parquet_path = tmp_path / "status.parquet"

    df_csv = reg.export(csv_path)
    assert csv_path.exists()
    assert len(pd.read_csv(csv_path)) == 2

    df_json = reg.export(json_path)
    assert json_path.exists()
    assert len(pd.read_json(json_path)) == 2

    df_parquet = reg.export(parquet_path)
    assert parquet_path.exists()
    assert len(pd.read_parquet(parquet_path)) == 2

    with pytest.raises(ValueError, match="format"):
        reg.export(tmp_path / "status.txt")

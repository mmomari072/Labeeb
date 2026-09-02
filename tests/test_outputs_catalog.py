"""Focused tests for the durable per-attempt output catalog (LAB-OUTPUTS-STORE-01)."""

import json

import pytest

from labeeb import (
    CampaignStateStore,
    Case,
    Database,
    OutputCatalog,
    OutputRecord,
)
from labeeb.results import CaseResult


# --- Append-only per-attempt semantics ---------------------------------------

def test_catalog_appends_per_attempt_and_never_overwrites(tmp_path):
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        first = OutputRecord(case_id=0, attempt=0, status="FAILED", exit_code=2, message="boom")
        second = OutputRecord(case_id=0, attempt=1, status="SUCCESS", exit_code=0)
        catalog.record(first)
        catalog.record(second)

        rows = catalog.get(0)
        assert len(rows) == 2
        assert [row["attempt"] for row in rows] == [0, 1]
        assert [row["status"] for row in rows] == ["FAILED", "SUCCESS"]
        assert rows[0]["message"] == "boom"
        latest = catalog.latest(0)
        assert latest is not None and latest.status == "SUCCESS"
        assert catalog.summary() == {"failed": 1, "success": 1}
    finally:
        catalog.close()


def test_catalog_records_are_durable_across_reopen(tmp_path):
    path = tmp_path / "outputs.sqlite"
    with OutputCatalog(path) as catalog:
        catalog.record(OutputRecord(case_id=1, attempt=0, status="SUCCESS"))

    with OutputCatalog(path) as reopened:
        assert len(reopened.get(1)) == 1
        assert reopened.get(1)[0]["status"] == "SUCCESS"
        assert reopened.case_ids() == [1]


def test_catalog_links_metrics_artifacts_and_stdio(tmp_path):
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        record = OutputRecord(
            case_id=2,
            attempt=0,
            status="SUCCESS",
            unit="mcnp",
            command="mcnp6 i=deck",
            exit_code=0,
            duration_seconds=1.25,
            metrics={"keff": 1.00012, "peak_flux": 1.5e14},
            artifacts={"results_csv": "results.csv", "log": "physics.log"},
            stdout_path="run/case_2/stdout.log",
            stderr_path=None,
            stdout_bytes=512,
            stderr_bytes=0,
            started_at="2026-09-02T00:00:00+00:00",
            ended_at="2026-09-02T00:00:01+00:00",
        )
        catalog.record(record)

        stored = catalog.latest(2)
        assert stored is not None
        assert stored.metrics == {"keff": 1.00012, "peak_flux": 1.5e14}
        assert stored.artifacts == {"results_csv": "results.csv", "log": "physics.log"}
        assert stored.stdout_path == "run/case_2/stdout.log"
        assert stored.stdout_bytes == 512
        assert stored.duration_seconds == 1.25
    finally:
        catalog.close()


def test_catalog_redacts_secrets_in_command_and_message(tmp_path):
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        catalog.record(
            OutputRecord(case_id=3, attempt=0, status="FAILED", command="run --api-key sk-1234", message="password=hunter2")
        )
        stored = catalog.get(3)[0]
        assert "sk-1234" not in stored["command"]
        assert "--api-key [REDACTED]" in stored["command"]
        assert "hunter2" not in stored["message"]
        assert "[REDACTED]" in stored["message"]
    finally:
        catalog.close()


def test_catalog_record_validation(tmp_path):
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        with pytest.raises(ValueError, match="case_id must be non-negative"):
            catalog.record(OutputRecord(case_id=-1, attempt=0, status="SUCCESS"))
        with pytest.raises(ValueError, match="status must not be empty"):
            catalog.record(OutputRecord(case_id=0, attempt=0, status=""))
        # status is normalized to upper case
        catalog.record(OutputRecord(case_id=0, attempt=0, status="success"))
        latest = catalog.latest(0)
        assert latest is not None and latest.status == "SUCCESS"
    finally:
        catalog.close()


# --- Case integration ----------------------------------------------------------

def _launch_single_case(tmp_path, command="printf done"):
    case = Case(name="cat_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.capture_output = True
    case.exe_cmd = [command]
    case.launch()
    return case


def test_record_from_case_catalogs_execution(tmp_path):
    case = _launch_single_case(tmp_path)
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        row_id = catalog.record_from_case(
            case,
            metrics={"rho": 19.0},
            artifacts={"deck": "runs/case_0/deck.inp"},
        )
        assert row_id >= 1
        record = catalog.latest(0)
        assert record is not None
        assert record.case_id == 0
        assert record.status == "SUCCESS"
        assert record.exit_code == 0
        assert record.unit == "cat_case"
        assert record.command == "printf done"
        assert record.metrics == {"rho": 19.0}
        assert record.artifacts == {"deck": "runs/case_0/deck.inp"}
        # capture_output=True wrote stdout.log into the case dir
        assert record.stdout_path is not None and record.stdout_path.endswith("stdout.log")
        assert record.stdout_bytes == 4
        assert record.duration_seconds is not None and record.duration_seconds >= 0.0
        assert record.started_at and record.ended_at
    finally:
        catalog.close()


def test_record_from_case_preserves_attempt_failures(tmp_path):
    case = Case(name="failing_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["python -c \"import sys; sys.exit(4)\""]
    with pytest.raises(Exception):
        case.launch()

    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        catalog.record_from_case(case)
        record = catalog.latest(0)
        assert record is not None
        assert record.status == "FAILED"
        assert record.exit_code == 4
        assert record.message is not None and "exited with code 4" in record.message
    finally:
        catalog.close()


def test_record_from_case_requires_history(tmp_path):
    case = Case(name="fresh_case", output_files={})
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        with pytest.raises(ValueError, match="no execution_history"):
            catalog.record_from_case(case)
    finally:
        catalog.close()


def test_retries_create_multiple_attempt_rows(tmp_path):
    catalog_path = tmp_path / "outputs.sqlite"
    state_path = tmp_path / "state.sqlite"

    with OutputCatalog(catalog_path) as catalog:
        with CampaignStateStore(state_path) as state:
            # First attempt fails, retry succeeds: state store keeps one row,
            # catalog preserves both attempts.
            catalog.record(OutputRecord(case_id=0, attempt=0, status="FAILED", exit_code=1))
            state.save(CaseResult(0, {"a": 1}, "FAILED", 1, 0.5, failure="boom"), "h1")
            catalog.record(OutputRecord(case_id=0, attempt=1, status="SUCCESS", exit_code=0))
            state.save(CaseResult(0, {"a": 1}, "SUCCESS", 0, 0.4), "h1")

            assert len(catalog.get(0)) == 2
            assert state.get(0)["attempts"] == 2  # state store still counts attempts

        # Both tables coexist in their own files; catalog survives independently
        with OutputCatalog(catalog_path) as reopened:
            assert len(reopened.get(0)) == 2


def test_catalog_coexists_with_state_store_in_same_file(tmp_path):
    shared = tmp_path / "campaign.sqlite"
    with OutputCatalog(shared) as catalog, CampaignStateStore(shared) as state:
        catalog.record(OutputRecord(case_id=0, attempt=0, status="SUCCESS", exit_code=0))
        state.save(CaseResult(0, {"a": 1}, "SUCCESS", 0, 0.4), "h1")
        latest = catalog.latest(0)
        assert latest is not None and latest.status == "SUCCESS"
        assert state.get(0)["status"] == "SUCCESS"


# --- Query/export ---------------------------------------------------------------

def test_catalog_export_csv_json_and_summary(tmp_path):
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        for attempt in range(3):
            catalog.record(
                OutputRecord(
                    case_id=5, attempt=attempt, status="SUCCESS" if attempt < 2 else "FAILED",
                    exit_code=0 if attempt < 2 else 9,
                    metrics={"keff": 1.0 + attempt * 0.01},
                    artifacts={"out": f"out_{attempt}.csv"},
                )
            )
        assert catalog.summary() == {"success": 2, "failed": 1}
        assert len(catalog.all_records()) == 3
        assert [r.attempt for r in catalog.attempts(5)] == [0, 1, 2]

        csv_df = catalog.export(tmp_path / "catalog.csv")
        assert list(csv_df.columns) == [
            "case_id", "status", "attempt", "unit", "command", "exit_code",
            "duration_seconds", "metrics", "artifacts", "stdout_path",
            "stderr_path", "stdout_bytes", "stderr_bytes", "message",
            "started_at", "ended_at",
        ]
        assert len(csv_df) == 3

        json_path = tmp_path / "catalog.json"
        catalog.export(json_path)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(payload) == 3
        assert payload[0]["status"] == "SUCCESS"

        with pytest.raises(ValueError, match="must be .csv, .json, .parquet, or .xlsx"):
            catalog.export(tmp_path / "catalog.ods")
    finally:
        catalog.close()


def test_output_record_roundtrip(tmp_path):
    original = OutputRecord(
        case_id=7, attempt=2, status="SUCCESS", unit="relap5", command="relap5 -i inp",
        exit_code=0, duration_seconds=3.3, metrics={"tmax": 900.0},
        artifacts={"csv": "t.csv"}, stdout_path="s.log", stderr_path=None,
        stdout_bytes=10, stderr_bytes=0, message=None,
        started_at="a", ended_at="b",
    )
    rebuilt = OutputRecord.from_record(original.to_record())
    assert rebuilt == original

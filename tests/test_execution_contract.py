"""V2-EXEC-01: versioned execution/result contracts, tolerant readers, and
cooperative cancellation. Focused tests written first (RED)."""

import threading
import time
from pathlib import Path

import pytest

from labeeb.case import Case
from labeeb.execution import (
    EVENT_SCHEMA_VERSION,
    ExecutionBackend,
    ExecutionEvent,
)
from labeeb.results import RESULT_SCHEMA_VERSION, CaseResult


# -------------------------------------------------------------- versioned schema

def test_execution_event_carries_schema_version():
    ev = ExecutionEvent(command="ls", cwd=".", status="completed", returncode=0,
                        duration_seconds=0.1, started_at="t0", ended_at="t1")
    assert ev.schema_version == EVENT_SCHEMA_VERSION == "1"
    assert ev.to_dict()["schema_version"] == "1"


def test_execution_event_from_dict_accepts_legacy_record():
    legacy = {"command": "ls", "cwd": ".", "status": "completed", "returncode": 0,
              "duration_seconds": 0.1, "started_at": "t0", "ended_at": "t1"}
    ev = ExecutionEvent.from_dict(legacy)  # no schema_version key
    assert ev.schema_version == "1"


def test_execution_event_rejects_unknown_schema_version():
    with pytest.raises(ValueError):
        ExecutionEvent.from_dict({"command": "ls", "cwd": ".", "status": "ok",
                                  "returncode": 0, "duration_seconds": 0.1,
                                  "started_at": "t0", "ended_at": "t1",
                                  "schema_version": "999"})


def test_case_result_carries_schema_version_and_roundtrips():
    result = CaseResult(case_id=0, parameters={"x": 1}, status="COMPLETED",
                        exit_code=0, duration_seconds=1.5,
                        artifacts={"log": "x"}, metrics={"m": 2.0})
    assert result.schema_version == RESULT_SCHEMA_VERSION == "1"
    record = result.to_record()
    assert record["schema_version"] == "1"
    rebuilt = CaseResult.from_record(record)
    assert rebuilt == result


def test_case_result_from_record_accepts_legacy_record():
    legacy = {"case_id": 3, "parameters": {"a": 1}, "status": "FAILED",
              "exit_code": 1, "duration_seconds": None, "artifacts": {},
              "metrics": {}, "failure": "boom"}
    rebuilt = CaseResult.from_record(legacy)
    assert rebuilt.schema_version == "1"
    assert rebuilt.status == "FAILED"


def test_case_result_rejects_unknown_schema_version():
    with pytest.raises(ValueError):
        CaseResult.from_record({"case_id": 0, "parameters": {}, "status": "OK",
                                "exit_code": 0, "duration_seconds": None,
                                "artifacts": {}, "metrics": {}, "schema_version": "42"})


# ---------------------------------------------------------------- cancellation

def _make_case(tmp_path, commands, **kwargs):
    from labeeb import Database

    case = Case(
        name="c",
        exe_cmd=commands,
        run_case_main_dir=str(tmp_path),
        output_files={},
        database=Database(data={"A": [1.0]}),
        **kwargs,
    )
    return case


def _case_dir(tmp_path):
    return Path(tmp_path) / "case_0"


def test_pre_cancelled_case_runs_nothing(tmp_path):
    case = _make_case(tmp_path, ["echo hi > marker.txt"], shell=True)
    case.cancel()
    case.launch_case(0)
    assert not (_case_dir(tmp_path) / "marker.txt").exists()
    assert case.cancelled is True


def test_cancel_between_commands_skips_remaining(tmp_path):
    cmd1 = ('python -c "import time,pathlib; '
            'pathlib.Path(\'first.txt\').write_text(\'1\'); time.sleep(1.2)"')
    cmd2 = 'python -c "import pathlib; pathlib.Path(\'second.txt\').write_text(\'2\')"'
    case = _make_case(tmp_path, [cmd1, cmd2])

    def runner():
        case.launch_case(0)

    thread = threading.Thread(target=runner)
    thread.start()
    deadline = time.time() + 10
    while not (_case_dir(tmp_path) / "first.txt").exists() and time.time() < deadline:
        time.sleep(0.01)
    case.cancel()  # lands while cmd1 is still sleeping -> cmd2 must be skipped
    thread.join(timeout=15)
    assert (_case_dir(tmp_path) / "first.txt").exists()
    assert not (_case_dir(tmp_path) / "second.txt").exists()


def test_backend_interface_contract_present():
    assert ExecutionBackend.run is not None
    backend = ExecutionBackend()
    with pytest.raises(NotImplementedError):
        backend.run("true", cwd=".")


def test_result_roundtrip_via_export_helpers():
    result = CaseResult(case_id=1, parameters={"p": 2}, status="COMPLETED",
                        exit_code=0, duration_seconds=0.5)
    restored = CaseResult.from_record(result.to_record())
    assert restored.to_record() == result.to_record()

import logging

from pathlib import Path

from labeeb.case import Case
from labeeb.database import Database
from labeeb.execution import (
    ExecutionResult,
    LocalExecutionBackend,
    append_execution_event,
    export_execution_events,
)
from labeeb.utils.os_ops import execute
from labeeb.logging_config import CaseLoggerAdapter


def test_local_execution_backend_runs_in_requested_directory(tmp_path):
    result = LocalExecutionBackend().run("pwd", cwd=tmp_path)

    assert result.returncode == 0
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()
    assert result.timed_out is False


def test_local_execution_backend_logs_command_lifecycle(tmp_path, caplog):
    with caplog.at_level("INFO", logger="labeeb.execution"):
        result = LocalExecutionBackend().run("printf done", cwd=tmp_path)

    assert result.returncode == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any("Starting command 'printf done'" in message for message in messages)
    assert any("completed with exit code 0" in message for message in messages)


def test_local_execution_backend_logs_timeout(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="labeeb.execution"):
        result = LocalExecutionBackend().run("sleep 1", cwd=tmp_path, timeout=0.01)

    assert result.timed_out is True
    assert any("timed out" in record.getMessage() for record in caplog.records)


def test_local_execution_backend_preserves_case_context(tmp_path, caplog):
    command_logger = CaseLoggerAdapter(
        logging.getLogger("labeeb.execution"),
        {"case_id": 3, "unit": "mcnp", "attempt": 1},
    )
    with caplog.at_level("INFO", logger="labeeb.execution"):
        LocalExecutionBackend(command_logger=command_logger).run("true", cwd=tmp_path)

    record = caplog.records[-1]
    assert record.case_id == 3
    assert record.unit == "mcnp"
    assert record.attempt == 1


def test_legacy_os_execute_uses_same_command_logging(tmp_path, caplog):
    with caplog.at_level("INFO", logger="labeeb.execution"):
        assert execute("printf legacy", wkdir=str(tmp_path)) == 0

    assert any("Starting command 'printf legacy'" in record.getMessage() for record in caplog.records)


def test_execution_result_contains_typed_event_and_can_export_json(tmp_path):
    result = LocalExecutionBackend().run("printf done", cwd=tmp_path)

    assert result.event is not None
    assert result.event.status == "SUCCESS"
    assert result.event.command == "printf done"
    assert result.event.stdout_bytes == len("done")
    output = export_execution_events([result.event], tmp_path / "events.json")
    assert output[0]["status"] == "SUCCESS"
    assert '"stdout_bytes": 4' in (tmp_path / "events.json").read_text(encoding="utf-8")


def test_execution_events_can_be_appended_as_jsonl(tmp_path):
    event = LocalExecutionBackend().run("true", cwd=tmp_path).event

    append_execution_event(event, tmp_path / "events.jsonl")
    append_execution_event(event, tmp_path / "events.jsonl")

    assert len((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_case_accepts_injected_execution_backend(tmp_path):
    class RecordingBackend:
        def __init__(self):
            self.commands = []

        def run(self, command, cwd, timeout=None, log_file=None):
            self.commands.append((command, cwd, timeout, log_file))
            return ExecutionResult(returncode=0)

    backend = RecordingBackend()
    case = Case(name="backend_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["custom simulator"]
    case.execution_backend = backend

    case.launch()

    assert backend.commands[0][0] == "custom simulator"
    assert backend.commands[0][1].endswith("runs/case_0")


def test_case_history_contains_execution_event_fields(tmp_path):
    case = Case(name="event_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["printf done"]

    case.launch()

    entry = case.execution_history[0]
    assert entry["status"] == "SUCCESS"
    assert entry["command"] == "printf done"
    assert entry["stdout_bytes"] == 4
    assert entry["case_id"] == 0

from pathlib import Path

from labeeb.case import Case
from labeeb.database import Database
from labeeb.execution import ExecutionResult, LocalExecutionBackend


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

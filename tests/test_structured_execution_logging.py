"""Focused tests for structured API-first execution logging (LAB-LOGGING-01).

Covers: structured records (command/cwd/timing/exit/stdout-stderr/timeout/failure),
safe redaction (key/value and CLI-flag forms, nested payloads), failure/timeout
context on ExecutionEvent, and unchanged behavior when logging is disabled.
"""

import json
import logging

from labeeb.case import Case
from labeeb.database import Database
from labeeb.execution import (
    ExecutionEvent,
    LocalExecutionBackend,
    export_execution_events,
)
from labeeb.logging_config import (
    CaseLoggerAdapter,
    JsonFormatter,
    configure_logging,
    redact_sensitive,
    redact_tree,
)

# --- Redaction ---------------------------------------------------------------


def test_redact_sensitive_key_value_and_flag_forms():
    assert redact_sensitive("token=abc123") == "token=[REDACTED]"
    assert redact_sensitive("api_key = sk-live-999") == "api_key = [REDACTED]"
    assert redact_sensitive("password:hunter2") == "password:[REDACTED]"
    assert redact_sensitive("--api-key sk-1234") == "--api-key [REDACTED]"
    assert redact_sensitive("-password hunter2") == "-password [REDACTED]"
    assert redact_sensitive("--db-password hunter2") == "--db-password [REDACTED]"
    assert (
        redact_sensitive("run --secret value --flag 5")
        == "run --secret [REDACTED] --flag 5"
    )


def test_redact_sensitive_does_not_mangle_plain_words():
    # False-positive guards: words merely starting with a keyword stay intact
    assert (
        redact_sensitive("-secretary meeting at noon") == "-secretary meeting at noon"
    )
    assert redact_sensitive("--tokenize the input") == "--tokenize the input"
    assert redact_sensitive("the secret is safe") == "the secret is safe"


def test_redact_tree_nested_structures():
    tree = {
        "command": "sim --token abc",
        "nested": {"msg": "password=xyz"},
        "keep": [1, "plain text"],
    }
    out = redact_tree(tree)
    assert "abc" not in str(out)
    assert "xyz" not in str(out)
    assert out["keep"] == [1, "plain text"]
    assert out["command"] == "sim --token [REDACTED]"
    assert out["nested"]["msg"] == "password=[REDACTED]"


def test_json_formatter_embeds_redacted_payload():
    formatter = JsonFormatter()
    logger = logging.getLogger("labeeb.test.jsonfmt")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "execution FAILED",
        (),
        None,
        extra={"payload": {"command": "sim --token abc123", "status": "FAILED"}},
    )
    line = json.loads(formatter.format(record))
    assert line["payload"]["command"] == "sim --token [REDACTED]"
    assert "abc123" not in line["message"]


# --- Structured execution records --------------------------------------------


def test_structured_success_record(tmp_path, caplog):
    with caplog.at_level("INFO", logger="labeeb.execution"):
        result = LocalExecutionBackend().run("printf done", cwd=tmp_path)

    assert result.returncode == 0
    structured = [
        r for r in caplog.records if getattr(r, "event_type", None) == "execution"
    ]
    assert len(structured) == 1
    event = structured[0].payload
    assert event["command"] == "printf done"
    assert event["cwd"] == str(tmp_path)
    assert event["status"] == "SUCCESS"
    assert event["returncode"] == 0
    assert event["duration_seconds"] >= 0.0
    assert event["stdout_bytes"] == 4
    assert event["stderr_bytes"] == 0
    assert event["timed_out"] is False
    assert event["started_at"] and event["ended_at"]
    assert result.event.message is None


def test_structured_record_carries_case_context(tmp_path, caplog):
    command_logger = CaseLoggerAdapter(
        logging.getLogger("labeeb.execution"),
        {"case_id": 7, "unit": "relap5", "attempt": 2},
    )
    with caplog.at_level("INFO", logger="labeeb.execution"):
        LocalExecutionBackend(command_logger=command_logger).run("true", cwd=tmp_path)  # type: ignore[arg-type]

    structured = [
        r for r in caplog.records if getattr(r, "event_type", None) == "execution"
    ]
    assert structured[0].payload["case_id"] == 7
    assert structured[0].payload["unit"] == "relap5"
    assert structured[0].payload["attempt"] == 2
    assert structured[0].case_id == 7


def test_structured_timeout_record_has_context(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="labeeb.execution"):
        result = LocalExecutionBackend().run("sleep 2", cwd=tmp_path, timeout=0.05)

    assert result.timed_out is True
    assert result.returncode == -999
    event = result.event
    assert event is not None
    assert event.status == "TIMEOUT"
    assert event.timed_out is True
    assert event.message is not None and "timed out" in event.message
    structured = [
        r for r in caplog.records if getattr(r, "event_type", None) == "execution"
    ]
    assert structured and structured[0].payload["timed_out"] is True
    assert structured[0].payload["status"] == "TIMEOUT"


def test_structured_failure_record_has_stderr_context(tmp_path, caplog):
    with caplog.at_level("ERROR", logger="labeeb.execution"):
        result = LocalExecutionBackend().run(
            "python -c \"import sys; sys.stderr.write('boom password=supersecret'); sys.exit(3)\"",
            cwd=tmp_path,
        )

    assert result.returncode == 3
    event = result.event
    assert event is not None
    assert event.status == "FAILED"
    assert event.timed_out is False
    assert event.message is not None and "exited with code 3" in event.message
    assert "boom" in event.message
    # stderr tail inside the context message is redacted
    assert "supersecret" not in event.message
    assert "[REDACTED]" in event.message


def test_structured_launch_failure_record(tmp_path, caplog, monkeypatch):
    # OSError path: the shell process itself cannot be spawned
    import subprocess as _subprocess

    def _boom(*args, **kwargs):
        raise OSError("Cannot allocate pty for shell")

    monkeypatch.setattr(_subprocess, "run", _boom)
    with caplog.at_level("ERROR", logger="labeeb.execution"):
        result = LocalExecutionBackend().run("echo nope", cwd=tmp_path)

    assert result.returncode == -1
    assert result.event is not None
    assert result.event.status == "FAILED"
    assert (
        result.event.message is not None
        and "Cannot allocate pty" in result.event.message
    )
    structured = [
        r for r in caplog.records if getattr(r, "event_type", None) == "execution"
    ]
    assert structured and structured[0].payload["returncode"] == -1


def test_event_export_and_roundtrip_include_new_fields(tmp_path):
    event = LocalExecutionBackend().run("true", cwd=tmp_path).event
    assert event is not None
    records = export_execution_events([event], tmp_path / "events.json")
    assert records[0]["timed_out"] is False
    assert "message" in records[0]
    rebuilt = ExecutionEvent.from_dict(records[0])
    assert rebuilt.timed_out is False
    assert rebuilt.status == "SUCCESS"


def test_legacy_event_records_without_new_fields_still_load(tmp_path):
    old_record = {
        "command": "true",
        "cwd": str(tmp_path),
        "status": "SUCCESS",
        "returncode": 0,
        "duration_seconds": 0.1,
        "started_at": "t0",
        "ended_at": "t1",
        "stdout_bytes": 0,
        "stderr_bytes": 0,
    }
    event = ExecutionEvent.from_dict(old_record)
    assert event.timed_out is False
    assert event.message is None


# --- Disabled / unconfigured logging behavior ---------------------------------


def test_disabled_logging_keeps_execution_unchanged(tmp_path):
    logger = logging.getLogger("labeeb")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    try:
        # Explicitly disable: remove package handlers, raise threshold to CRITICAL+1
        for handler in list(logger.handlers):
            if getattr(handler, "_labeeb_handler", False):
                logger.removeHandler(handler)
        logger.setLevel(logging.CRITICAL + 1)

        result = LocalExecutionBackend().run("printf ok", cwd=tmp_path)
        assert result.returncode == 0
        assert result.stdout == "ok"
        assert result.event is not None
        assert result.event.status == "SUCCESS"
    finally:
        logger.handlers[:] = original_handlers
        logger.setLevel(original_level)


def test_configure_logging_disabled_mode_is_silent_but_functional(tmp_path):
    log_path = tmp_path / "silent.log"
    logger = configure_logging(log_file=log_path, stream=False, json_format=True)
    assert (
        len([h for h in logger.handlers if getattr(h, "_labeeb_handler", False)]) == 1
    )

    # Run an execution while a JSON file handler is attached: one structured JSON line lands
    backend = LocalExecutionBackend()
    backend.run("printf data", cwd=tmp_path)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines
    record = json.loads(lines[-1])
    assert record.get("payload", {}).get("status") == "SUCCESS"
    assert record["payload"]["stdout_bytes"] == 4


def test_case_history_command_is_redacted(tmp_path):
    case = Case(name="redact_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["printf token=supersecret123"]
    case.launch()

    entry = case.execution_history[0]
    assert entry["status"] == "SUCCESS"
    assert "supersecret123" not in entry["command"]
    assert "[REDACTED]" in entry["command"]
    assert entry["timed_out"] is False

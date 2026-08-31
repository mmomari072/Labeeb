import logging
import json

from labeeb.logging_config import CaseLoggerAdapter, configure_logging


def test_configure_logging_adds_idempotent_package_handlers_without_root_changes(tmp_path):
    root_handlers = list(logging.getLogger().handlers)
    log_path = tmp_path / "labeeb.log"

    logger = configure_logging(log_file=log_path, stream=False)
    configure_logging(log_file=log_path, stream=False)
    logger.info("case started")

    assert list(logging.getLogger().handlers) == root_handlers
    assert len([handler for handler in logger.handlers if getattr(handler, "_labeeb_handler", False)]) == 1
    assert "case started" in log_path.read_text(encoding="utf-8")


def test_case_logger_adapter_includes_case_and_attempt_context(caplog):
    logger = logging.getLogger("labeeb.test")
    adapter = CaseLoggerAdapter(logger, {"case_id": 4, "unit": "shield", "attempt": 2})

    with caplog.at_level(logging.INFO, logger="labeeb.test"):
        adapter.info("command completed")

    record = caplog.records[-1]
    assert record.case_id == 4
    assert record.unit == "shield"
    assert record.attempt == 2
    assert record.getMessage() == "[case_id=4 unit=shield attempt=2] command completed"


def test_configure_logging_supports_json_and_redacts_sensitive_values(tmp_path):
    log_path = tmp_path / "events.log"
    logger = configure_logging(log_file=log_path, stream=False, json_format=True)

    logger.warning("token=abc123 command completed")

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["level"] == "WARNING"
    assert "abc123" not in record["message"]
    assert "[REDACTED]" in record["message"]


def test_configure_logging_redacts_sensitive_values_in_plain_logs(tmp_path):
    log_path = tmp_path / "labeeb.log"
    logger = configure_logging(log_file=log_path, stream=False)

    logger.warning("password=abc123")

    content = log_path.read_text(encoding="utf-8")
    assert "abc123" not in content
    assert "password=[REDACTED]" in content

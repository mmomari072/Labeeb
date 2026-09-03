"""Execution backend abstractions for simulation commands."""

import json
import logging
import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .logging_config import redact_sensitive

logger = logging.getLogger(__name__)

EVENT_SCHEMA_VERSION = "1"
"""Version of the :class:`ExecutionEvent` record schema (V2-EXEC-01).

Readers must accept records without ``schema_version`` (v1-era exports) and
treat them as version ``"1"``; writers always stamp the field.
"""

_SUPPORTED_EVENT_SCHEMA_VERSIONS = frozenset({EVENT_SCHEMA_VERSION})


@dataclass
class ExecutionEvent:
    """Auditable record for one simulator command execution."""

    command: str
    cwd: str
    status: str
    returncode: int
    duration_seconds: float
    started_at: str
    ended_at: str
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    case_id: Optional[int] = None
    unit: Optional[str] = None
    attempt: int = 0
    event_type: str = "command"
    message: Optional[str] = None
    timed_out: bool = False
    schema_version: str = EVENT_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible event mapping (schema-stamped)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, record: Dict[str, Any]) -> "ExecutionEvent":
        """Rebuild an event from a JSON-compatible mapping.

        Legacy records without ``schema_version`` are accepted as version
        ``"1"``; unsupported versions raise :class:`ValueError`.
        """
        payload = dict(record)
        payload.setdefault("schema_version", EVENT_SCHEMA_VERSION)
        if payload["schema_version"] not in _SUPPORTED_EVENT_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported execution-event schema version "
                f"{payload['schema_version']!r}; supported: "
                f"{sorted(_SUPPORTED_EVENT_SCHEMA_VERSIONS)}"
            )
        return cls(**payload)


@dataclass
class ExecutionResult:
    """Normalized result returned by an execution backend."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    event: Optional[ExecutionEvent] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return result fields with its nested execution event."""
        result = asdict(self)
        if self.event is not None:
            result["event"] = self.event.to_dict()
        return result


class ExecutionBackend:
    """Interface implemented by local and future scheduler backends."""

    def run(
        self,
        command: Union[str, Sequence[str]],
        cwd: Union[str, Path],
        timeout: Optional[float] = None,
        log_file: Optional[Union[str, Path]] = None,
        shell: Optional[bool] = None,
    ) -> ExecutionResult:
        raise NotImplementedError


class LocalExecutionBackend(ExecutionBackend):
    """Run a command locally.

    Secure-by-default execution model:
      * a sequence (argv list) is executed WITHOUT a shell (``shell=False``);
      * a plain string is parsed with :func:`shlex.split` and executed as an
        argv list (no shell) UNLESS ``shell=True`` is given explicitly (either
        per call or as the backend's ``default_shell``) — legacy shell command
        strings (redirections, pipes, ``&&``, ``;``) must opt in to shell
        semantics explicitly.
    Timeout (-999/TIMEOUT), launch-failure (-1/FAILED, e.g. missing
    executable), logging and redaction semantics are unchanged.
    """

    def __init__(
        self,
        command_logger: Optional[logging.Logger] = None,
        *,
        default_shell: bool = False,
    ) -> None:
        self.command_logger = command_logger or logger
        self.default_shell: bool = default_shell

    def set_logger(self, command_logger: logging.Logger) -> "LocalExecutionBackend":
        """Set the logger used for command lifecycle records."""
        self.command_logger = command_logger
        return self

    @staticmethod
    def _display_command(command: Union[str, Sequence[str]]) -> str:
        """Normalized display form for events/logs (shell-joined for argv)."""
        if isinstance(command, str):
            return command
        try:
            return shlex.join(str(part) for part in command)
        except Exception:  # noqa: BLE001 - never break on display only
            return " ".join(str(part) for part in command)

    def _resolve_invocation(
        self, command: Union[str, Sequence[str]], shell: Optional[bool]
    ) -> "tuple[Union[str, List[str]], bool]":
        """Map (command, shell) onto an argv list or a shell string invocation."""
        if not isinstance(command, str):
            # argv lists never need a shell, regardless of any opt-in flag
            return [str(part) for part in command], False
        use_shell = self.default_shell if shell is None else shell
        if use_shell:
            return command, True
        return shlex.split(command), False

    def run(
        self,
        command: Union[str, Sequence[str]],
        cwd: Union[str, Path],
        timeout: Optional[float] = None,
        log_file: Optional[Union[str, Path]] = None,
        shell: Optional[bool] = None,
    ) -> ExecutionResult:
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        stream = None
        display = self._display_command(command)
        log_command = redact_sensitive(display)
        self.command_logger.info("Starting command %r in %s", log_command, cwd)
        try:
            invoke, use_shell = self._resolve_invocation(command, shell)
            if log_file is not None:
                stream = open(log_file, "a", encoding="utf-8")
                completed = subprocess.run(
                    invoke, shell=use_shell, cwd=str(cwd), stdout=stream, stderr=stream, timeout=timeout
                )
                stdout = stderr = ""
            else:
                completed = subprocess.run(
                    invoke, shell=use_shell, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
                )
                stdout, stderr = completed.stdout or "", completed.stderr or ""
            result = ExecutionResult(
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=time.monotonic() - started,
            )
            status = "SUCCESS" if result.returncode == 0 else "FAILED"
            result.event = self._event(
                display, cwd, result, started_at,
                status=status,
                message=self._failure_context(display, result),
            )
            self.command_logger.info(
                "Command %r completed with exit code %s in %.3fs",
                log_command,
                result.returncode,
                result.duration_seconds,
            )
            self._emit_structured(result.event)
            return result
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            self.command_logger.warning(
                "Command %r timed out after %s seconds in %.3fs", log_command, timeout, duration
            )
            if stream is not None:
                stream.write(f"\n[ERROR] Command timed out after {timeout} seconds.\n")
            event = self._event(
                display,
                cwd,
                ExecutionResult(-999, str(exc.stdout or ""), str(exc.stderr or ""), duration, True),
                started_at,
                status="TIMEOUT",
                message=f"Command timed out after {timeout} seconds",
            )
            result = ExecutionResult(
                returncode=-999,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                duration_seconds=duration,
                timed_out=True,
                event=event,
            )
            self._emit_structured(event)
            return result
        except (OSError, ValueError) as exc:
            # OSError: launch failure (missing executable, ...)
            # ValueError: shlex could not parse a quoted command string
            self.command_logger.error("Command %r could not be executed: %s", log_command, exc)
            result = ExecutionResult(
                returncode=-1,
                stderr=str(exc),
                duration_seconds=time.monotonic() - started,
            )
            result.event = self._event(
                display, cwd, result, started_at, status="FAILED", message=str(exc)
            )
            self._emit_structured(result.event)
            return result
        finally:
            if stream is not None:
                stream.close()

    @staticmethod
    def _failure_context(command: str, result: "ExecutionResult") -> Optional[str]:
        """Build a redacted human context message for failed commands."""
        if result.returncode == 0:
            return None
        message = f"Command exited with code {result.returncode}"
        if result.stderr:
            tail = result.stderr.strip()[-1500:]
            message += f"; stderr: {redact_sensitive(tail)}"
        return message

    def _emit_structured(self, event: "ExecutionEvent") -> None:
        """Emit the full event as a structured JSON payload on the command logger."""
        level = logging.INFO if event.status == "SUCCESS" else (
            logging.WARNING if event.status == "TIMEOUT" else logging.ERROR
        )
        if not self.command_logger.isEnabledFor(level):
            return
        try:
            self.command_logger.log(
                level,
                "execution %s: %s",
                event.status,
                event.command or event.message or "",
                extra={"event_type": "execution", "payload": event.to_dict()},
            )
        except Exception:
            # Structured emission must never break command execution.
            logger.debug("Failed to emit structured execution record", exc_info=True)

    def _event(
        self,
        command: str,
        cwd: Union[str, Path],
        result: ExecutionResult,
        started_at: str,
        status: Optional[str] = None,
        message: Optional[str] = None,
    ) -> ExecutionEvent:
        context = getattr(self.command_logger, "extra", {})
        return ExecutionEvent(
            command=redact_sensitive(command),
            cwd=str(cwd),
            status=status or ("SUCCESS" if result.returncode == 0 else "FAILED"),
            returncode=result.returncode,
            duration_seconds=result.duration_seconds,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            stdout_bytes=len(result.stdout.encode("utf-8") if isinstance(result.stdout, str) else result.stdout or b""),
            stderr_bytes=len(result.stderr.encode("utf-8") if isinstance(result.stderr, str) else result.stderr or b""),
            case_id=context.get("case_id"),
            unit=context.get("unit"),
            attempt=context.get("attempt", 0),
            message=message,
            timed_out=bool(getattr(result, "timed_out", False)),
        )


def export_execution_events(
    events: Iterable[ExecutionEvent], path: Union[str, Path]
) -> List[Dict[str, Any]]:
    """Export execution events as a JSON list and return its records."""
    records = [event.to_dict() for event in events]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
    return records


def append_execution_event(event: ExecutionEvent, path: Union[str, Path]) -> None:
    """Append one execution event to a JSON Lines event stream."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(event.to_dict(), sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(str(output), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)

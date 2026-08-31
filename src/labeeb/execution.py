"""Execution backend abstractions for simulation commands."""

import logging
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

logger = logging.getLogger(__name__)


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

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible event mapping."""
        return asdict(self)


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
        command: str,
        cwd: Union[str, Path],
        timeout: Optional[float] = None,
        log_file: Optional[Union[str, Path]] = None,
    ) -> ExecutionResult:
        raise NotImplementedError


class LocalExecutionBackend(ExecutionBackend):
    """Run a command as a local shell process."""

    def __init__(self, command_logger: Optional[logging.Logger] = None) -> None:
        self.command_logger = command_logger or logger

    def set_logger(self, command_logger: logging.Logger) -> "LocalExecutionBackend":
        """Set the logger used for command lifecycle records."""
        self.command_logger = command_logger
        return self

    def run(
        self,
        command: str,
        cwd: Union[str, Path],
        timeout: Optional[float] = None,
        log_file: Optional[Union[str, Path]] = None,
    ) -> ExecutionResult:
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        stream = None
        self.command_logger.info("Starting command %r in %s", command, cwd)
        try:
            if log_file is not None:
                stream = open(log_file, "a", encoding="utf-8")
                completed = subprocess.run(
                    command, shell=True, cwd=str(cwd), stdout=stream, stderr=stream, timeout=timeout
                )
                stdout = stderr = ""
            else:
                completed = subprocess.run(
                    command, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
                )
                stdout, stderr = completed.stdout or "", completed.stderr or ""
            result = ExecutionResult(
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=time.monotonic() - started,
            )
            result.event = self._event(command, cwd, result, started_at)
            self.command_logger.info(
                "Command %r completed with exit code %s in %.3fs",
                command,
                result.returncode,
                result.duration_seconds,
            )
            return result
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            self.command_logger.warning("Command %r timed out after %s seconds in %.3fs", command, timeout, duration)
            if stream is not None:
                stream.write(f"\n[ERROR] Command timed out after {timeout} seconds.\n")
            return ExecutionResult(
                returncode=-999,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                duration_seconds=duration,
                timed_out=True,
                event=self._event(
                    command,
                    cwd,
                    ExecutionResult(-999, exc.stdout or "", exc.stderr or "", duration, True),
                    started_at,
                    status="TIMEOUT",
                ),
            )
        except OSError as exc:
            self.command_logger.error("Command %r could not be executed: %s", command, exc)
            result = ExecutionResult(
                returncode=-1,
                stderr=str(exc),
                duration_seconds=time.monotonic() - started,
            )
            result.event = self._event(command, cwd, result, started_at, status="FAILED")
            return result
        finally:
            if stream is not None:
                stream.close()

    def _event(
        self,
        command: str,
        cwd: Union[str, Path],
        result: ExecutionResult,
        started_at: str,
        status: Optional[str] = None,
    ) -> ExecutionEvent:
        context = getattr(self.command_logger, "extra", {})
        return ExecutionEvent(
            command=command,
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

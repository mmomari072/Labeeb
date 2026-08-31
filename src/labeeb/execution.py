"""Execution backend abstractions for simulation commands."""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


@dataclass
class ExecutionResult:
    """Normalized result returned by an execution backend."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False


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

    def run(
        self,
        command: str,
        cwd: Union[str, Path],
        timeout: Optional[float] = None,
        log_file: Optional[Union[str, Path]] = None,
    ) -> ExecutionResult:
        started = time.monotonic()
        stream = None
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
            return ExecutionResult(
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            if stream is not None:
                stream.write(f"\n[ERROR] Command timed out after {timeout} seconds.\n")
            return ExecutionResult(
                returncode=-999,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )
        except OSError as exc:
            return ExecutionResult(
                returncode=-1,
                stderr=str(exc),
                duration_seconds=time.monotonic() - started,
            )
        finally:
            if stream is not None:
                stream.close()

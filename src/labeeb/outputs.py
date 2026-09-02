"""Durable, append-only catalog of per-attempt case outputs.

The :class:`OutputCatalog` persists one record per (case, attempt) execution,
linking harvested metrics, artifact paths, stdout/stderr artifacts, and run
status so that full output history survives process restarts and retries. It is
designed to coexist with :class:`~labeeb.results.CampaignStateStore` (which
tracks only the latest result per case) in the same SQLite file without
interference.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from .logging_config import redact_sensitive

_TABLE = "output_catalog"


@dataclass
class OutputRecord:
    """One durable attempt record linking a case run to its outputs."""

    case_id: int
    status: str
    attempt: int = 0
    unit: Optional[str] = None
    command: Optional[str] = None
    exit_code: Optional[int] = None
    duration_seconds: Optional[float] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    message: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.case_id < 0:
            raise ValueError("case_id must be non-negative")
        if not self.status:
            raise ValueError("status must not be empty")
        self.status = self.status.upper()
        if self.command is not None:
            self.command = redact_sensitive(self.command)
        if self.message is not None:
            self.message = redact_sensitive(self.message)

    def to_record(self) -> Dict[str, Any]:
        """Return a JSON-compatible mapping of this record."""
        return asdict(self)

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "OutputRecord":
        """Rebuild a record from a persisted or exported mapping."""
        return cls(
            case_id=int(record["case_id"]),
            status=str(record["status"]),
            attempt=int(record.get("attempt", 0)),
            unit=record.get("unit"),
            command=record.get("command"),
            exit_code=record.get("exit_code"),
            duration_seconds=record.get("duration_seconds"),
            metrics=dict(record.get("metrics", {})),
            artifacts=dict(record.get("artifacts", {})),
            stdout_path=record.get("stdout_path"),
            stderr_path=record.get("stderr_path"),
            stdout_bytes=int(record.get("stdout_bytes", 0) or 0),
            stderr_bytes=int(record.get("stderr_bytes", 0) or 0),
            message=record.get("message"),
            started_at=record.get("started_at"),
            ended_at=record.get("ended_at"),
        )


class OutputCatalog:
    """Append-only SQLite ledger of per-attempt case output records.

    Records are never overwritten: repeating a case attempt appends a new row,
    so retries, convergence passes, and failed runs all remain queryable.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                unit TEXT,
                status TEXT NOT NULL,
                command TEXT,
                exit_code INTEGER,
                duration_seconds REAL,
                metrics_json TEXT NOT NULL,
                artifacts_json TEXT NOT NULL,
                stdout_path TEXT,
                stderr_path TEXT,
                stdout_bytes INTEGER NOT NULL DEFAULT 0,
                stderr_bytes INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                started_at TEXT,
                ended_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_case_attempt "
            f"ON {_TABLE}(case_id, attempt)"
        )
        self.connection.commit()

    # -- writes ----------------------------------------------------------------

    def record(self, record: OutputRecord) -> int:
        """Persist one attempt record, returning its row id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute(
            f"""
            INSERT INTO {_TABLE}(
                case_id, attempt, unit, status, command, exit_code,
                duration_seconds, metrics_json, artifacts_json,
                stdout_path, stderr_path, stdout_bytes, stderr_bytes,
                message, started_at, ended_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.case_id,
                record.attempt,
                record.unit,
                record.status,
                record.command,
                record.exit_code,
                record.duration_seconds,
                json.dumps(record.metrics, sort_keys=True, default=str),
                json.dumps(record.artifacts, sort_keys=True, default=str),
                record.stdout_path,
                record.stderr_path,
                record.stdout_bytes,
                record.stderr_bytes,
                record.message,
                record.started_at or now,
                record.ended_at or now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def record_from_case(
        self,
        case: Any,
        *,
        metrics: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, str]] = None,
        stdout_filename: str = "stdout.log",
        stderr_filename: str = "stderr.log",
    ) -> int:
        """Catalog the most recent attempt of an executed :class:`Case`.

        Populates command/cwd-independent event fields (status, exit code,
        duration, byte counts, timing, failure message) from the case's last
        ``execution_history`` entry, and links per-case stdout/stderr files when
        they exist in the case run directory.
        """
        history = getattr(case, "execution_history", None) or []
        if not history:
            raise ValueError("Case has no execution_history entry to catalog")
        entry = history[-1]
        event = entry.get("execution_event") or {}
        case_dir = Path(getattr(case, "current_case_dir", None) or ".")

        stdout_path = self._existing(case_dir / stdout_filename)
        stderr_path = self._existing(case_dir / stderr_filename)

        record = OutputRecord(
            case_id=int(entry.get("case_id", getattr(case, "case_id", 0))),
            status=str(entry.get("status") or event.get("status") or "UNKNOWN"),
            attempt=int(event.get("attempt", getattr(case, "_attempt", 0) or 0)),
            unit=event.get("unit") or getattr(case, "name", None),
            command=event.get("command") or entry.get("command"),
            exit_code=entry.get("exit_code", event.get("returncode")),
            duration_seconds=entry.get("duration_seconds", event.get("duration_seconds")),
            metrics={**(metrics or {})},
            artifacts={**(artifacts or {})},
            stdout_path=str(stdout_path) if stdout_path else None,
            stderr_path=str(stderr_path) if stderr_path else None,
            stdout_bytes=int(event.get("stdout_bytes", 0) or 0),
            stderr_bytes=int(event.get("stderr_bytes", 0) or 0),
            message=event.get("message"),
            started_at=event.get("started_at"),
            ended_at=event.get("ended_at"),
        )
        return self.record(record)

    # -- queries ----------------------------------------------------------------

    def attempts(self, case_id: int) -> List[OutputRecord]:
        """Return all catalogued attempts for a case in chronological order."""
        rows = self.connection.execute(
            f"SELECT * FROM {_TABLE} WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, case_id: int) -> List[Dict[str, Any]]:
        """Return attempt records for a case as JSON-compatible mappings."""
        return [record.to_record() for record in self.attempts(case_id)]

    def latest(self, case_id: int) -> Optional[OutputRecord]:
        """Return the most recent catalogued attempt for a case, if any."""
        rows = self.connection.execute(
            f"SELECT * FROM {_TABLE} WHERE case_id = ? ORDER BY id DESC LIMIT 1",
            (case_id,),
        ).fetchall()
        return self._row_to_record(rows[0]) if rows else None

    def case_ids(self) -> List[int]:
        """Return all catalogued case IDs in ascending order."""
        rows = self.connection.execute(
            f"SELECT DISTINCT case_id FROM {_TABLE} ORDER BY case_id"
        ).fetchall()
        return [row[0] for row in rows]

    def all_records(self) -> List[OutputRecord]:
        """Return every catalogued attempt in insertion order."""
        rows = self.connection.execute(f"SELECT * FROM {_TABLE} ORDER BY id").fetchall()
        return [self._row_to_record(row) for row in rows]

    def summary(self) -> Dict[str, int]:
        """Return attempt counts grouped by status."""
        rows = self.connection.execute(
            f"SELECT status, COUNT(*) FROM {_TABLE} GROUP BY status"
        ).fetchall()
        return {status.lower(): count for status, count in rows}

    def to_dataframe(self) -> pd.DataFrame:
        """Return all records as a pandas DataFrame (metrics/artifacts serialized)."""
        records = [record.to_record() for record in self.all_records()]
        dataframe = pd.DataFrame(records)
        for column in ("metrics", "artifacts"):
            if column in dataframe:
                dataframe[column] = dataframe[column].map(
                    lambda value: json.dumps(value, sort_keys=True)
                    if isinstance(value, dict)
                    else value
                )
        return dataframe

    def export(self, path: Union[str, Path]) -> pd.DataFrame:
        """Export all catalog records to CSV, JSON, Parquet, or Excel and return the DataFrame."""
        output = Path(path)
        suffix = output.suffix.lower()
        if suffix not in {".csv", ".json", ".parquet", ".xlsx"}:
            raise ValueError("Catalog export format must be .csv, .json, .parquet, or .xlsx")
        dataframe = self.to_dataframe()
        output.parent.mkdir(parents=True, exist_ok=True)
        if suffix == ".csv":
            dataframe.to_csv(output, index=False)
        elif suffix == ".json":
            dataframe.to_json(output, orient="records", indent=2)
        elif suffix == ".xlsx":
            dataframe.to_excel(output, index=False, sheet_name="output_catalog")
        else:
            dataframe.to_parquet(output, index=False)
        return dataframe

    # -- internals ---------------------------------------------------------------

    def _existing(self, candidate: Path) -> Optional[Path]:
        return candidate if candidate.is_file() else None

    @staticmethod
    def _row_to_record(row: Any) -> OutputRecord:
        return OutputRecord.from_record(
            {
                "case_id": row[1],
                "attempt": row[2],
                "unit": row[3],
                "status": row[4],
                "command": row[5],
                "exit_code": row[6],
                "duration_seconds": row[7],
                "metrics": json.loads(row[8]),
                "artifacts": json.loads(row[9]),
                "stdout_path": row[10],
                "stderr_path": row[11],
                "stdout_bytes": row[12],
                "stderr_bytes": row[13],
                "message": row[14],
                "started_at": row[15],
                "ended_at": row[16],
            }
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "OutputCatalog":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

"""Structured, case-indexed result records and export helpers."""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import pandas as pd


@dataclass
class CaseResult:
    """Outcome and retained artifacts for one campaign case."""

    case_id: int
    parameters: Dict[str, Any]
    status: str
    exit_code: Optional[int]
    duration_seconds: Optional[float]
    artifacts: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    failure: Optional[str] = None

    def __post_init__(self) -> None:
        if self.case_id < 0:
            raise ValueError("case_id must be non-negative")
        if not self.status:
            raise ValueError("status must not be empty")

    def to_record(self) -> Dict[str, Any]:
        """Return the complete structured record for this case."""
        return {
            "case_id": self.case_id,
            "parameters": dict(self.parameters),
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "artifacts": dict(self.artifacts),
            "metrics": dict(self.metrics),
            "failure": self.failure,
        }

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "CaseResult":
        """Rebuild a result from a persisted or exported record."""
        return cls(
            case_id=int(record["case_id"]),
            parameters=dict(record.get("parameters", {})),
            status=str(record["status"]),
            exit_code=record.get("exit_code"),
            duration_seconds=record.get("duration_seconds"),
            artifacts=dict(record.get("artifacts", {})),
            metrics=dict(record.get("metrics", {})),
            failure=record.get("failure"),
        )


class CampaignStateStore:
    """SQLite persistence for resumable case attempts and input-hash caching."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_cases (
                case_id INTEGER PRIMARY KEY,
                input_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def save(self, result: CaseResult, input_hash: str) -> None:
        """Persist a result, incrementing its durable attempt count."""
        previous = self.connection.execute(
            "SELECT attempts FROM campaign_cases WHERE case_id = ?", (result.case_id,)
        ).fetchone()
        attempts = (previous[0] if previous else 0) + 1
        self.connection.execute(
            """
            INSERT INTO campaign_cases(case_id, input_hash, status, attempts, result_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                input_hash=excluded.input_hash,
                status=excluded.status,
                attempts=excluded.attempts,
                result_json=excluded.result_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (result.case_id, input_hash, result.status, attempts, json.dumps(result.to_record(), sort_keys=True)),
        )
        self.connection.commit()

    def get(self, case_id: int) -> Optional[Dict[str, Any]]:
        """Return persisted state for a case, or ``None`` if unseen."""
        row = self.connection.execute(
            "SELECT case_id, input_hash, status, attempts, result_json, updated_at "
            "FROM campaign_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "case_id": row[0], "input_hash": row[1], "status": row[2],
            "attempts": row[3], "result": json.loads(row[4]), "updated_at": row[5],
        }

    def pending(self, case_ids: Iterable[int]) -> List[int]:
        """Return case IDs without a successful persisted result."""
        return [case_id for case_id in case_ids if (self.get(case_id) or {}).get("status") != "SUCCESS"]

    def should_reuse(self, case_id: int, input_hash: str) -> bool:
        """Return whether a successful result matches the current input hash."""
        state = self.get(case_id)
        return bool(state and state["status"] == "SUCCESS" and state["input_hash"] == input_hash)

    def retry_allowed(self, case_id: int, max_retries: int) -> bool:
        """Return whether another attempt remains under the retry budget."""
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        state = self.get(case_id)
        return state is None or state["attempts"] < max_retries

    def summary(self) -> Dict[str, int]:
        """Return persisted case counts grouped by execution status."""
        rows = self.connection.execute(
            "SELECT status, COUNT(*) FROM campaign_cases GROUP BY status"
        ).fetchall()
        return {status.lower(): count for status, count in rows}

    def case_ids(self) -> List[int]:
        """Return all persisted case IDs in ascending order."""
        rows = self.connection.execute("SELECT case_id FROM campaign_cases ORDER BY case_id").fetchall()
        return [row[0] for row in rows]

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "CampaignStateStore":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()


def export_case_results(
    results: Iterable[CaseResult],
    path: Union[str, Path],
) -> pd.DataFrame:
    """Export all case results to CSV, JSON, or Parquet and return a DataFrame."""
    output = Path(path)
    suffix = output.suffix.lower()
    if suffix not in {".csv", ".json", ".parquet"}:
        raise ValueError("Results format must be .csv, .json, or .parquet")

    records: List[Dict[str, Any]] = [result.to_record() for result in results]
    dataframe = pd.DataFrame(records, columns=[
        "case_id", "parameters", "status", "exit_code",
        "duration_seconds", "artifacts", "metrics", "failure",
    ])
    for column in ("parameters", "artifacts", "metrics"):
        dataframe[column] = dataframe[column].map(
            lambda value: json.dumps(value, sort_keys=True) if isinstance(value, dict) else value
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        dataframe.to_csv(output, index=False)
    elif suffix == ".json":
        dataframe.to_json(output, orient="records", indent=2)
    else:
        dataframe.to_parquet(output, index=False)
    return dataframe


class StatusRegistry:
    """Detailed registry and tracking store for case execution status, timing, and streams."""

    def __init__(self) -> None:
        self._entries: Dict[int, Dict[str, Any]] = {}

    def record(
        self,
        case_id: int,
        status: str,
        exit_code: Optional[int] = None,
        duration_seconds: Optional[float] = None,
        stdout_status: Optional[str] = None,
        stderr_status: Optional[str] = None,
        stdout_bytes: int = 0,
        stderr_bytes: int = 0,
        error: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Record or update execution status details for a case."""
        if case_id < 0:
            raise ValueError("case_id must be non-negative")
        if not status:
            raise ValueError("status must not be empty")

        entry: Dict[str, Any] = {
            "case_id": case_id,
            "status": status.upper(),
            "exit_code": exit_code,
            "duration_seconds": duration_seconds,
            "stdout_status": stdout_status,
            "stderr_status": stderr_status,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "error": error,
        }
        if extra:
            entry["extra"] = extra
        self._entries[case_id] = entry
        return entry

    def record_result(self, result: CaseResult) -> Dict[str, Any]:
        """Record status directly from a CaseResult instance."""
        return self.record(
            case_id=result.case_id,
            status=result.status,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            error=result.failure,
            metrics=result.metrics,
            artifacts=result.artifacts,
        )

    def get(self, case_id: int) -> Optional[Dict[str, Any]]:
        """Get status entry for a specific case_id."""
        return self._entries.get(case_id)

    def __getitem__(self, case_id: int) -> Dict[str, Any]:
        return self._entries[case_id]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, case_id: int) -> bool:
        return case_id in self._entries

    def __iter__(self):
        return iter(self.all_entries())

    def case_ids(self) -> List[int]:
        """Return all tracked case IDs in ascending order."""
        return sorted(self._entries.keys())

    def all_entries(self) -> List[Dict[str, Any]]:
        """Return all status records ordered by case_id."""
        return [self._entries[cid] for cid in sorted(self._entries.keys())]

    def filter_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Return entries matching a given status (case-insensitive)."""
        target = status.upper()
        return [e for e in self.all_entries() if e["status"] == target]

    def successful_cases(self) -> List[int]:
        """Return list of case IDs with SUCCESS status."""
        return [e["case_id"] for e in self.filter_by_status("SUCCESS")]

    def failed_cases(self) -> List[int]:
        """Return list of case IDs with FAILED or TIMEOUT status."""
        return [e["case_id"] for e in self.all_entries() if e["status"] in {"FAILED", "TIMEOUT"}]

    def summary(self) -> Dict[str, int]:
        """Return counts grouped by status."""
        counts: Dict[str, int] = {}
        for entry in self._entries.values():
            s = entry["status"].lower()
            counts[s] = counts.get(s, 0) + 1
        return counts

    def total_duration(self) -> float:
        """Return sum of duration_seconds across all recorded cases."""
        return sum(e["duration_seconds"] or 0.0 for e in self._entries.values())

    def to_dataframe(self) -> pd.DataFrame:
        """Convert registry entries to a pandas DataFrame."""
        records = self.all_entries()
        columns = [
            "case_id", "status", "exit_code", "duration_seconds",
            "stdout_status", "stderr_status", "stdout_bytes", "stderr_bytes", "error"
        ]
        if not records:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(records)
        if "extra" in df.columns:
            df["extra"] = df["extra"].map(
                lambda x: json.dumps(x, sort_keys=True) if isinstance(x, dict) else x
            )
        return df

    def export(self, path: Union[str, Path]) -> pd.DataFrame:
        """Export registry entries to CSV, JSON, or Parquet."""
        output = Path(path)
        suffix = output.suffix.lower()
        if suffix not in {".csv", ".json", ".parquet"}:
            raise ValueError("Export format must be .csv, .json, or .parquet")
        df = self.to_dataframe()
        output.parent.mkdir(parents=True, exist_ok=True)
        if suffix == ".csv":
            df.to_csv(output, index=False)
        elif suffix == ".json":
            df.to_json(output, orient="records", indent=2)
        else:
            df.to_parquet(output, index=False)
        return df

    def clear(self) -> None:
        """Clear all recorded entries."""
        self._entries.clear()


ExecutionStatusRegistry = StatusRegistry

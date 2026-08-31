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

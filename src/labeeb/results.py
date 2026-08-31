"""Structured, case-indexed result records and export helpers."""

import json
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

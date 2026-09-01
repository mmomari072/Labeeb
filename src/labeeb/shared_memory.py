"""
Pluggable shared campaign memory for non-blocking online analysis.
Supports in-process thread-safe state storage, incremental metrics accumulation,
event listeners, and point-in-time snapshots.
"""

import threading
from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from .exceptions import LabeebError


class SharedMemoryError(LabeebError):
    """Raised when shared memory operations fail."""


class SharedMemoryBackend(ABC):
    """Abstract interface for pluggable shared memory backends."""

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Store a key-value pair."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key."""

    @abstractmethod
    def update(self, mapping: Dict[str, Any]) -> None:
        """Update multiple keys."""

    @abstractmethod
    def keys(self) -> List[str]:
        """Return all keys."""

    @abstractmethod
    def snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time read-only snapshot of all stored state."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all stored state."""

    def close(self) -> None:
        """Clean up resources on shutdown."""


class InMemorySharedBackend(SharedMemoryBackend):
    """Thread-safe, non-blocking in-process shared memory backend."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._storage: Dict[str, Any] = {}
        self._subscribers: List[Callable[[str, Any], None]] = []

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            copied = deepcopy(value)
            self._storage[key] = copied
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(key, deepcopy(copied))
            except Exception:
                pass

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            val = self._storage.get(key, default)
            return deepcopy(val)

    def update(self, mapping: Dict[str, Any]) -> None:
        with self._lock:
            copied_mapping = {k: deepcopy(v) for k, v in mapping.items()}
            self._storage.update(copied_mapping)
            subscribers = list(self._subscribers)
        for key, value in copied_mapping.items():
            for callback in subscribers:
                try:
                    callback(key, deepcopy(value))
                except Exception:
                    pass

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._storage.keys())

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._storage)

    def clear(self) -> None:
        with self._lock:
            self._storage.clear()

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Subscribe a listener to key updates."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)


class CampaignMemory:
    """
    High-level shared campaign memory for online statistical analysis and non-blocking monitoring.
    """

    def __init__(self, backend: Optional[SharedMemoryBackend] = None) -> None:
        self.backend: SharedMemoryBackend = backend if backend is not None else InMemorySharedBackend()
        self._lock = threading.RLock()
        self._case_records: Dict[int, Dict[str, Any]] = {}
        self._listeners: List[Callable[[int, Dict[str, Any]], None]] = []

    def record_case(self, case_id: int, data: Dict[str, Any]) -> None:
        """Record case parameters, outputs, and metrics non-blockingly."""
        if not isinstance(case_id, int) or case_id < 0:
            raise SharedMemoryError("case_id must be a non-negative integer")
        if not isinstance(data, dict):
            raise SharedMemoryError("case data must be a dictionary")

        with self._lock:
            copied_data = deepcopy(data)
            self._case_records[case_id] = copied_data
            self.backend.set(f"case_{case_id}", deepcopy(copied_data))
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(case_id, deepcopy(copied_data))
            except Exception:
                pass

    def get_case(self, case_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve recorded data for a specific case ID."""
        with self._lock:
            record = self._case_records.get(case_id)
            return deepcopy(record) if record is not None else None

    def get_all_cases(self) -> Dict[int, Dict[str, Any]]:
        """Return all case records ordered by case ID."""
        with self._lock:
            return deepcopy(self._case_records)

    def get_series(self, key: str) -> List[Any]:
        """Extract a 1D sequence for a specific attribute/metric across recorded cases."""
        with self._lock:
            series = []
            for case_id in sorted(self._case_records.keys()):
                val = self._case_records[case_id].get(key)
                series.append(val)
            return series

    def to_dataframe(self) -> pd.DataFrame:
        """Return tabular DataFrame of all recorded case results and parameters."""
        with self._lock:
            if not self._case_records:
                return pd.DataFrame()
            rows = []
            for case_id in sorted(self._case_records.keys()):
                row = {"case_id": case_id, **self._case_records[case_id]}
                rows.append(row)
            return pd.DataFrame(rows)

    def online_summary(self, metrics: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, float]]:
        """Compute running statistics (mean, std, min, max, count) on numeric metrics."""
        with self._lock:
            df = self.to_dataframe()
            if df.empty:
                return {}

            target_cols = list(metrics) if metrics is not None else [
                c for c in df.columns if c != "case_id" and pd.api.types.is_numeric_dtype(df[c])
            ]

            summary: Dict[str, Dict[str, float]] = {}
            for col in target_cols:
                if col in df and pd.api.types.is_numeric_dtype(df[col]):
                    series = df[col].dropna()
                    if not series.empty:
                        summary[col] = {
                            "count": float(len(series)),
                            "mean": float(series.mean()),
                            "std": float(series.std()) if len(series) > 1 else 0.0,
                            "min": float(series.min()),
                            "max": float(series.max()),
                        }
            return summary

    def add_listener(self, callback: Callable[[int, Dict[str, Any]], None]) -> "CampaignMemory":
        """Register a callback invoked when a case record is added."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
        return self

    def clear(self) -> None:
        """Clear memory and underlying backend."""
        with self._lock:
            self._case_records.clear()
            self.backend.clear()

    def snapshot(self) -> Dict[str, Any]:
        """Return complete snapshot of memory state."""
        with self._lock:
            return {
                "cases": deepcopy(self._case_records),
                "backend": self.backend.snapshot()
            }

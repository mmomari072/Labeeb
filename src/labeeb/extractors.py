"""Built-in output extractors for common simulation result formats."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

import pandas as pd

from .exceptions import LabeebError


class ExtractionError(LabeebError):
    """Raised when a declared output metric cannot be extracted."""


def extract_csv(path: Union[str, Path], column: str) -> list:
    """Read one required column from a CSV output file."""
    p = Path(path)
    if not p.exists():
        raise ExtractionError(f"CSV file '{path}' does not exist")
    try:
        dataframe = pd.read_csv(p)
    except Exception as exc:
        raise ExtractionError(f"Failed to read CSV output from '{path}': {exc}") from exc
    if column not in dataframe.columns:
        raise ExtractionError(f"Column '{column}' missing in CSV output '{path}'")
    return dataframe[column].tolist()


def extract_json(path: Union[str, Path], key: str) -> Any:
    """Read a dotted key path from a JSON output file."""
    p = Path(path)
    if not p.exists():
        raise ExtractionError(f"JSON file '{path}' does not exist")
    try:
        value: Any = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ExtractionError(f"Failed to parse JSON output from '{path}': {exc}") from exc
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ExtractionError(f"Key '{key}' (missing '{part}') not found in JSON output '{path}'")
        value = value[part]
    return value


def extract_regex(path: Union[str, Path], pattern: str) -> str:
    """Return the first capture group, or full match, from a text output."""
    p = Path(path)
    if not p.exists():
        raise ExtractionError(f"Output file '{path}' does not exist")
    try:
        match = re.search(pattern, p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ExtractionError(f"Failed to read text output '{path}': {exc}") from exc
    if match is None:
        raise ExtractionError(f"Pattern '{pattern}' was not found in '{path}'")
    return match.group(1) if match.lastindex else match.group(0)


def run_extractor(path: Union[str, Path], extractor: Union[str, Callable[[Path], Any]]) -> Any:
    """Apply a callable extractor or infer a built-in extractor from file type."""
    output_path = Path(path)
    if callable(extractor):
        return extractor(output_path)
    suffix = output_path.suffix.lower()
    if suffix == ".csv":
        return extract_csv(output_path, extractor)
    if suffix == ".json":
        return extract_json(output_path, extractor)
    return extract_regex(output_path, extractor)


@dataclass
class Harvester:
    """Base declarative harvester specification."""

    name: str
    file_target: Union[str, Path]
    pattern: Union[str, Callable[[Path], Any]]
    transform: Optional[Callable[[Any], Any]] = None

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        """Extract metric from target file relative to base_dir."""
        target = Path(self.file_target)
        if not target.is_absolute() and base_dir:
            target = Path(base_dir) / target
        if not target.exists():
            raise ExtractionError(f"Target output file '{target}' does not exist for harvester '{self.name}'")
        raw = run_extractor(target, self.pattern)
        return self.transform(raw) if self.transform is not None else raw


class CsvHarvester(Harvester):
    """Declarative CSV column harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        column: str,
        transform: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=column, transform=transform)
        self.column = column

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = Path(self.file_target)
        if not target.is_absolute() and base_dir:
            target = Path(base_dir) / target
        if not target.exists():
            raise ExtractionError(f"CSV file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_csv(target, self.column)
        return self.transform(raw) if self.transform is not None else raw


class JsonHarvester(Harvester):
    """Declarative JSON key harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        key: str,
        transform: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=key, transform=transform)
        self.key = key

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = Path(self.file_target)
        if not target.is_absolute() and base_dir:
            target = Path(base_dir) / target
        if not target.exists():
            raise ExtractionError(f"JSON file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_json(target, self.key)
        return self.transform(raw) if self.transform is not None else raw


class RegexHarvester(Harvester):
    """Declarative regex pattern harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        pattern: str,
        transform: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=pattern, transform=transform)

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = Path(self.file_target)
        if not target.is_absolute() and base_dir:
            target = Path(base_dir) / target
        if not target.exists():
            raise ExtractionError(f"Text file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_regex(target, self.pattern)
        return self.transform(raw) if self.transform is not None else raw


class CallableHarvester(Harvester):
    """Declarative callable function harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        extractor: Callable[[Path], Any],
        transform: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=extractor, transform=transform)

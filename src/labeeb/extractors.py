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


def extract_excel(
    path: Union[str, Path],
    column: Optional[str] = None,
    sheet: Union[str, int] = 0,
) -> Union[list, "pd.DataFrame"]:
    """Read a column (or the full sheet) from an Excel (.xlsx/.xls) output file.

    Args:
        path: Path to the Excel output workbook.
        column: Optional column name to return as a typed list. When omitted,
            the whole sheet is returned as a pandas DataFrame.
        sheet: Sheet name or zero-based index (default first sheet).

    Returns:
        Column values as a list, or the full sheet as a DataFrame.

    Raises:
        ExtractionError: If the file is missing/unreadable, the sheet or column
            does not exist, or the optional ``openpyxl``/``xlrd`` engine is not
            installed.
    """
    p = Path(path)
    if not p.exists():
        raise ExtractionError(f"Excel file '{path}' does not exist")
    try:
        dataframe = pd.read_excel(p, sheet_name=sheet)
    except ImportError as exc:
        raise ExtractionError(
            f"Reading Excel output '{path}' requires an Excel engine "
            f"(install with: pip install openpyxl xlrd)"
        ) from exc
    except Exception as exc:
        raise ExtractionError(f"Failed to read Excel output from '{path}': {exc}") from exc
    if column is None:
        return dataframe
    if column not in dataframe.columns:
        raise ExtractionError(f"Column '{column}' missing in Excel output '{path}'")
    return dataframe[column].tolist()


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
    """Base declarative harvester specification.

    Outputs declared via harvesters are *explicitly discovered* inside the case
    run directory at harvest time. By default a missing target file is an error
    (required output); set ``optional=True`` to declare an optional output that
    yields ``None`` when the file was not produced.
    """

    name: str
    file_target: Union[str, Path]
    pattern: Union[str, Callable[[Path], Any]]
    transform: Optional[Callable[[Any], Any]] = None
    optional: bool = False

    def _resolve_target(self, base_dir: Union[str, Path] = "") -> Path:
        target = Path(self.file_target)
        if not target.is_absolute() and base_dir:
            target = Path(base_dir) / target
        return target

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        """Extract metric from target file relative to base_dir.

        Returns ``None`` for an optional harvester whose file was not produced;
        raises :class:`ExtractionError` when a required file is missing.
        """
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
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
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=column, transform=transform, optional=optional)
        self.column = column

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
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
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=key, transform=transform, optional=optional)
        self.key = key

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
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
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=pattern, transform=transform, optional=optional)

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"Text file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_regex(target, self.pattern)
        return self.transform(raw) if self.transform is not None else raw


class ExcelHarvester(Harvester):
    """Declarative Excel (.xlsx/.xls) column harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        column: str,
        sheet: Union[str, int] = 0,
        transform: Optional[Callable[[Any], Any]] = None,
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=column, transform=transform, optional=optional)
        self.column = column
        self.sheet = sheet

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"Excel file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_excel(target, self.column, sheet=self.sheet)
        return self.transform(raw) if self.transform is not None else raw


class CallableHarvester(Harvester):
    """Declarative callable function harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        extractor: Callable[[Path], Any],
        transform: Optional[Callable[[Any], Any]] = None,
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=extractor, transform=transform, optional=optional)

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"Target file '{target}' does not exist for harvester '{self.name}'")
        raw = self.pattern(target) if callable(self.pattern) else run_extractor(target, self.pattern)
        return self.transform(raw) if self.transform is not None else raw

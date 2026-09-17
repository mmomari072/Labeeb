"""Built-in output extractors for common simulation result formats."""

import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

import pandas as pd
import numpy as np

from .exceptions import LabeebError


class ExtractionError(LabeebError):
    """Raised when a declared output metric cannot be extracted."""


def apply_aggregation(data: Any, aggregation: str = "all") -> Any:
    """Apply aggregation function to extracted data.

    Args:
        data: Extracted data (list, single value, or DataFrame)
        aggregation: Aggregation method:
            - "all" (default): Return all values as-is
            - "first": First value
            - "last": Last value
            - "min": Minimum value
            - "max": Maximum value
            - "mean"/"avg": Average/mean
            - "median": Median value
            - "std": Standard deviation
            - "sum": Sum of all values
            - "count": Number of values
            - "integration"/"integral": Sum (numerical integration)

    Returns:
        Aggregated result (single value or original data)

    Raises:
        ExtractionError: If aggregation fails
    """
    if aggregation == "all" or aggregation is None:
        return data

    # Convert to list if needed
    if isinstance(data, (int, float)):
        values = [data]
    elif isinstance(data, str):
        try:
            values = [float(data)]
        except ValueError:
            raise ExtractionError(f"Cannot aggregate non-numeric data: {data}")
    elif isinstance(data, (list, tuple)):
        # Try to convert to numeric if needed
        try:
            values = [float(v) if not isinstance(v, (int, float)) else v for v in data]
        except (ValueError, TypeError):
            # If not numeric, return as-is for some operations
            values = list(data)
    elif isinstance(data, pd.Series):
        values = data.tolist()
    elif isinstance(data, pd.DataFrame):
        # For DataFrame, return as-is (can't aggregate entire dataframe)
        return data
    else:
        return data

    if not values:
        raise ExtractionError("Cannot aggregate empty data")

    try:
        if aggregation == "first":
            return values[0]
        elif aggregation == "last":
            return values[-1]
        elif aggregation in ("min", "minimum"):
            return min(values)
        elif aggregation in ("max", "maximum"):
            return max(values)
        elif aggregation in ("mean", "avg", "average"):
            return statistics.mean(values) if len(values) > 0 else None
        elif aggregation == "median":
            return statistics.median(values)
        elif aggregation == "std":
            return statistics.stdev(values) if len(values) > 1 else 0
        elif aggregation in ("sum", "integration", "integral"):
            return sum(values)
        elif aggregation == "count":
            return len(values)
        else:
            raise ExtractionError(f"Unknown aggregation method: {aggregation}")
    except (TypeError, ValueError) as exc:
        raise ExtractionError(f"Aggregation '{aggregation}' failed: {exc}") from exc


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

    Aggregation options enable extracting summaries instead of all values:
    - "all" (default): Return all extracted values
    - "first", "last": First or last value
    - "min", "max": Minimum or maximum
    - "mean", "median": Average or median value
    - "sum", "integration": Sum of all values
    - "std": Standard deviation
    - "count": Number of values
    """

    name: str
    file_target: Union[str, Path]
    pattern: Union[str, Callable[[Path], Any]]
    filter: Optional[Callable[[Any], Any]] = None
    transform: Optional[Callable[[Any], Any]] = None
    aggregation: str = "all"
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
        # Apply filter first, then transform, then aggregation
        if self.filter is not None:
            raw = self.filter(raw)
        if self.transform is not None:
            raw = self.transform(raw)
        # Apply aggregation
        raw = apply_aggregation(raw, self.aggregation)
        return raw


class CsvHarvester(Harvester):
    """Declarative CSV column harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        column: str,
        filter: Optional[Callable[[Any], Any]] = None,
        transform: Optional[Callable[[Any], Any]] = None,
        aggregation: str = "all",
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=column, filter=filter, transform=transform, optional=optional)
        self.column = column
        self.aggregation = aggregation

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"CSV file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_csv(target, self.column)
        if self.filter is not None:
            raw = self.filter(raw)
        if self.transform is not None:
            raw = self.transform(raw)
        return apply_aggregation(raw, self.aggregation)


class JsonHarvester(Harvester):
    """Declarative JSON key harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        key: str,
        filter: Optional[Callable[[Any], Any]] = None,
        transform: Optional[Callable[[Any], Any]] = None,
        aggregation: str = "all",
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=key, filter=filter, transform=transform, optional=optional)
        self.key = key
        self.aggregation = aggregation

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"JSON file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_json(target, self.key)
        if self.filter is not None:
            raw = self.filter(raw)
        if self.transform is not None:
            raw = self.transform(raw)
        return apply_aggregation(raw, self.aggregation)


class RegexHarvester(Harvester):
    """Declarative regex pattern harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        pattern: str,
        filter: Optional[Callable[[Any], Any]] = None,
        transform: Optional[Callable[[Any], Any]] = None,
        aggregation: str = "all",
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=pattern, filter=filter, transform=transform, optional=optional)
        self.aggregation = aggregation

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"Text file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_regex(target, self.pattern)
        if self.filter is not None:
            raw = self.filter(raw)
        if self.transform is not None:
            raw = self.transform(raw)
        return apply_aggregation(raw, self.aggregation)


class ExcelHarvester(Harvester):
    """Declarative Excel (.xlsx/.xls) column harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        column: str,
        sheet: Union[str, int] = 0,
        filter: Optional[Callable[[Any], Any]] = None,
        transform: Optional[Callable[[Any], Any]] = None,
        aggregation: str = "all",
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=column, filter=filter, transform=transform, optional=optional)
        self.column = column
        self.sheet = sheet
        self.aggregation = aggregation

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"Excel file '{target}' does not exist for harvester '{self.name}'")
        raw = extract_excel(target, self.column, sheet=self.sheet)
        if self.filter is not None:
            raw = self.filter(raw)
        if self.transform is not None:
            raw = self.transform(raw)
        return apply_aggregation(raw, self.aggregation)


class CallableHarvester(Harvester):
    """Declarative callable function harvester."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        extractor: Callable[[Path], Any],
        filter: Optional[Callable[[Any], Any]] = None,
        transform: Optional[Callable[[Any], Any]] = None,
        aggregation: str = "all",
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=extractor, filter=filter, transform=transform, optional=optional)
        self.aggregation = aggregation

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"Target file '{target}' does not exist for harvester '{self.name}'")
        raw = self.pattern(target) if callable(self.pattern) else run_extractor(target, self.pattern)
        if self.filter is not None:
            raw = self.filter(raw)
        if self.transform is not None:
            raw = self.transform(raw)
        return apply_aggregation(raw, self.aggregation)


class BulkCsvHarvester(Harvester):
    """Harvest all columns from a CSV file as a dictionary."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        filter: Optional[Callable[[dict], dict]] = None,
        transform: Optional[Callable[[dict], Any]] = None,
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern="*", filter=filter, transform=transform, optional=optional)

    def harvest(self, base_dir: Union[str, Path] = "") -> dict:
        """Return all columns as {column_name: [values], ...}"""
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return {}
            raise ExtractionError(f"CSV file '{target}' does not exist for harvester '{self.name}'")
        try:
            dataframe = pd.read_csv(target)
            result = {col: dataframe[col].tolist() for col in dataframe.columns}
        except Exception as exc:
            raise ExtractionError(f"Failed to read CSV output from '{target}': {exc}") from exc
        if self.filter is not None:
            result = self.filter(result)
        return self.transform(result) if self.transform is not None else result


class MultiColumnCsvHarvester(Harvester):
    """Harvest specific columns from a CSV file as a dictionary."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        columns: list,
        filter: Optional[Callable[[dict], dict]] = None,
        transform: Optional[Callable[[dict], Any]] = None,
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=columns, filter=filter, transform=transform, optional=optional)
        self.columns = columns

    def harvest(self, base_dir: Union[str, Path] = "") -> dict:
        """Return specified columns as {column_name: [values], ...}"""
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return {}
            raise ExtractionError(f"CSV file '{target}' does not exist for harvester '{self.name}'")
        try:
            dataframe = pd.read_csv(target)
            missing = [col for col in self.columns if col not in dataframe.columns]
            if missing:
                raise ExtractionError(f"Columns {missing} missing in CSV output '{target}'")
            result = {col: dataframe[col].tolist() for col in self.columns}
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to read CSV output from '{target}': {exc}") from exc
        if self.filter is not None:
            result = self.filter(result)
        return self.transform(result) if self.transform is not None else result


class PatternCsvHarvester(Harvester):
    """Harvest columns matching a regex pattern from a CSV file."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        column_pattern: str,
        filter: Optional[Callable[[dict], dict]] = None,
        transform: Optional[Callable[[dict], Any]] = None,
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=column_pattern, filter=filter, transform=transform, optional=optional)
        self.column_pattern = column_pattern

    def harvest(self, base_dir: Union[str, Path] = "") -> dict:
        """Return columns matching pattern as {column_name: [values], ...}"""
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return {}
            raise ExtractionError(f"CSV file '{target}' does not exist for harvester '{self.name}'")
        try:
            dataframe = pd.read_csv(target)
            pattern = re.compile(self.column_pattern)
            matching_cols = [col for col in dataframe.columns if pattern.search(col)]
            if not matching_cols:
                raise ExtractionError(f"No columns matching pattern '{self.column_pattern}' in '{target}'")
            result = {col: dataframe[col].tolist() for col in matching_cols}
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to read CSV output from '{target}': {exc}") from exc
        if self.filter is not None:
            result = self.filter(result)
        return self.transform(result) if self.transform is not None else result


class DataFrameHarvester(Harvester):
    """Harvest entire DataFrame from a CSV file for custom processing."""

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        filter: Optional[Callable[[Any], Any]] = None,
        transform: Optional[Callable[[Any], Any]] = None,
        optional: bool = False,
    ) -> None:
        super().__init__(name=name, file_target=file_target, pattern=None, filter=filter, transform=transform, optional=optional)

    def harvest(self, base_dir: Union[str, Path] = "") -> "pd.DataFrame":
        """Return entire DataFrame for custom processing"""
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return pd.DataFrame()
            raise ExtractionError(f"CSV file '{target}' does not exist for harvester '{self.name}'")
        try:
            dataframe = pd.read_csv(target)
        except Exception as exc:
            raise ExtractionError(f"Failed to read CSV output from '{target}': {exc}") from exc
        if self.filter is not None:
            dataframe = self.filter(dataframe)
        return self.transform(dataframe) if self.transform is not None else dataframe


def detect_file_type(file_path: Union[str, Path]) -> str:
    """Detect file type based on extension.

    Args:
        file_path: Path to the file

    Returns:
        Detected file type: 'csv', 'json', 'excel', 'text', or 'unknown'
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    file_type_map = {
        '.csv': 'csv',
        '.tsv': 'csv',
        '.dat': 'csv',
        '.json': 'json',
        '.xlsx': 'excel',
        '.xls': 'excel',
        '.txt': 'text',
        '.log': 'text',
        '.out': 'text',
    }

    return file_type_map.get(extension, 'unknown')


class AutoHarvester(Harvester):
    """Automatically detect and extract data based on file type.

    Automatically detects file type by extension and applies appropriate
    extraction logic. Supports CSV, JSON, Excel, and text files.
    Optionally allows explicit file_type specification.
    """

    def __init__(
        self,
        name: str,
        file_target: Union[str, Path],
        column: Optional[str] = None,
        key: Optional[str] = None,
        pattern: Optional[str] = None,
        sheet: Union[str, int] = 0,
        file_type: Optional[str] = None,
        transform: Optional[Callable[[Any], Any]] = None,
        optional: bool = False,
    ) -> None:
        """Initialize AutoHarvester.

        Args:
            name: Harvester name
            file_target: Path to output file
            column: Column name (for CSV/Excel)
            key: JSON key path with dot notation (e.g. "results.temperature")
            pattern: Regex pattern (for text files) or column pattern (for CSV)
            sheet: Sheet name or index (for Excel, default 0)
            file_type: Explicit file type ('csv', 'json', 'excel', 'text')
                       If None, auto-detected from extension
            transform: Optional post-processing function
            optional: If True, missing files return None
        """
        super().__init__(
            name=name,
            file_target=file_target,
            pattern=pattern or "",
            transform=transform,
            optional=optional
        )
        self.column = column
        self.key = key
        self.sheet = sheet
        self.explicit_file_type = file_type

    def _get_file_type(self) -> str:
        """Determine file type: explicit or auto-detected."""
        if self.explicit_file_type:
            return self.explicit_file_type.lower()
        return detect_file_type(self.file_target)

    def harvest(self, base_dir: Union[str, Path] = "") -> Any:
        """Extract data using appropriate method for file type."""
        target = self._resolve_target(base_dir)
        if not target.exists():
            if self.optional:
                return None
            raise ExtractionError(f"Target file '{target}' does not exist for harvester '{self.name}'")

        file_type = self._get_file_type()

        try:
            if file_type == 'csv':
                return self._harvest_csv(target)
            elif file_type == 'json':
                return self._harvest_json(target)
            elif file_type == 'excel':
                return self._harvest_excel(target)
            elif file_type == 'text':
                return self._harvest_text(target)
            else:
                raise ExtractionError(
                    f"Unknown file type for '{target}'. "
                    f"Detected: {file_type}. "
                    f"Explicitly set file_type to 'csv', 'json', 'excel', or 'text'."
                )
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to harvest data from '{target}': {exc}") from exc

    def _harvest_csv(self, target: Path) -> Any:
        """Extract from CSV file."""
        if self.column:
            # Single column
            raw = extract_csv(target, self.column)
        else:
            # All columns as DataFrame
            raw = pd.read_csv(target)
        return self.transform(raw) if self.transform is not None else raw

    def _harvest_json(self, target: Path) -> Any:
        """Extract from JSON file."""
        if not self.key:
            raise ExtractionError(
                f"JSON harvester requires 'key' parameter (e.g., 'results.temperature')"
            )
        raw = extract_json(target, self.key)
        return self.transform(raw) if self.transform is not None else raw

    def _harvest_excel(self, target: Path) -> Any:
        """Extract from Excel file."""
        raw = extract_excel(target, column=self.column, sheet=self.sheet)
        return self.transform(raw) if self.transform is not None else raw

    def _harvest_text(self, target: Path) -> Any:
        """Extract from text/log file."""
        if not self.pattern:
            raise ExtractionError(
                f"Text file harvester requires 'pattern' parameter (regex pattern)"
            )
        raw = extract_regex(target, self.pattern)
        return self.transform(raw) if self.transform is not None else raw

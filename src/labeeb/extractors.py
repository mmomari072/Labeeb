"""Built-in output extractors for common simulation result formats."""

import json
import re
from pathlib import Path
from typing import Any, Callable, Union

import pandas as pd

from .exceptions import LabeebError


class ExtractionError(LabeebError):
    """Raised when a declared output metric cannot be extracted."""


def extract_csv(path: Union[str, Path], column: str) -> list:
    """Read one required column from a CSV output file."""
    try:
        dataframe = pd.read_csv(path, usecols=[column])
    except Exception as exc:
        raise ExtractionError(f"Failed to extract CSV column '{column}' from '{path}': {exc}") from exc
    return dataframe[column].tolist()


def extract_json(path: Union[str, Path], key: str) -> Any:
    """Read a dotted key path from a JSON output file."""
    try:
        value: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        for part in key.split("."):
            value = value[part]
        return value
    except Exception as exc:
        raise ExtractionError(f"Failed to extract JSON key '{key}' from '{path}': {exc}") from exc


def extract_regex(path: Union[str, Path], pattern: str) -> str:
    """Return the first capture group, or full match, from a text output."""
    try:
        match = re.search(pattern, Path(path).read_text(encoding="utf-8"))
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

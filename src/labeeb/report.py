"""Small, reproducible HTML report writer for campaign results."""

from html import escape
from pathlib import Path
from typing import Iterable, Union

from .results import CaseResult


def write_html_report(results: Iterable[CaseResult], path: Union[str, Path], title: str = "Labeeb Campaign") -> Path:
    """Write a self-contained HTML summary and return its path."""
    records = [result.to_record() for result in results]
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(record[column]))}</td>" for column in ("case_id", "status", "exit_code", "failure")) + "</tr>"
        for record in records
    )
    document = (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        + escape(title)
        + "</title></head><body><h1>"
        + escape(title)
        + "</h1><p>Cases: "
        + str(len(records))
        + "</p><table><thead><tr><th>case_id</th><th>status</th><th>exit_code</th><th>failure</th></tr></thead><tbody>"
        + rows
        + "</tbody></table></body></html>"
    )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output

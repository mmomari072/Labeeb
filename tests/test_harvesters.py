from pathlib import Path
import pytest
import pandas as pd

from labeeb.case import Case
from labeeb.database import Database
from labeeb.exceptions import CaseExecutionError
from labeeb.extractors import (
    CallableHarvester,
    CsvHarvester,
    ExtractionError,
    Harvester,
    JsonHarvester,
    RegexHarvester,
)


def test_csv_harvester_extracts_column_and_transforms(tmp_path: Path):
    csv_file = tmp_path / "metrics.csv"
    pd.DataFrame({"keff": [1.0025, 1.0030], "flux": [2.5e14, 2.6e14]}).to_csv(csv_file, index=False)

    harvester = CsvHarvester(name="keff_vals", file_target=csv_file, column="keff", transform=lambda vals: [round(v, 3) for v in vals])
    extracted = harvester.harvest()

    assert extracted == [1.002, 1.003]


def test_csv_harvester_raises_on_missing_file_or_column(tmp_path: Path):
    csv_file = tmp_path / "metrics.csv"
    pd.DataFrame({"keff": [1.0]}).to_csv(csv_file, index=False)

    h_missing_file = CsvHarvester("missing", tmp_path / "nonexistent.csv", "keff")
    with pytest.raises(ExtractionError, match="does not exist"):
        h_missing_file.harvest()

    h_missing_col = CsvHarvester("missing_col", csv_file, "unknown_col")
    with pytest.raises(ExtractionError, match="Column.*missing"):
        h_missing_col.harvest()


def test_json_harvester_extracts_nested_key_and_transforms(tmp_path: Path):
    json_file = tmp_path / "summary.json"
    json_file.write_text('{"results": {"peak_temp": 1250.5}}', encoding="utf-8")

    harvester = JsonHarvester("peak", json_file, "results.peak_temp", transform=float)
    assert harvester.harvest() == 1250.5


def test_json_harvester_raises_on_missing_file_or_key(tmp_path: Path):
    json_file = tmp_path / "summary.json"
    json_file.write_text('{"results": {"val": 10}}', encoding="utf-8")

    h_missing_file = JsonHarvester("missing", tmp_path / "nonexistent.json", "results.val")
    with pytest.raises(ExtractionError, match="does not exist"):
        h_missing_file.harvest()

    h_missing_key = JsonHarvester("missing_key", json_file, "results.unknown")
    with pytest.raises(ExtractionError, match="not found"):
        h_missing_key.harvest()


def test_regex_harvester_extracts_capture_group_and_transforms(tmp_path: Path):
    log_file = tmp_path / "solver.out"
    log_file.write_text("Iterations converged: final residual = 3.45e-5", encoding="utf-8")

    harvester = RegexHarvester("res", log_file, r"residual = ([0-9.e-]+)", transform=float)
    assert harvester.harvest() == 3.45e-5


def test_regex_harvester_raises_on_missing_pattern(tmp_path: Path):
    log_file = tmp_path / "solver.out"
    log_file.write_text("Run completed normally", encoding="utf-8")

    harvester = RegexHarvester("missing", log_file, r"residual = ([0-9]+)")
    with pytest.raises(ExtractionError, match="Pattern.*not found"):
        harvester.harvest()


def test_callable_harvester_runs_custom_function(tmp_path: Path):
    custom_file = tmp_path / "custom.dat"
    custom_file.write_text("10 20 30 40", encoding="utf-8")

    def parse_sum(path: Path) -> int:
        return sum(int(x) for x in path.read_text().split())

    harvester = CallableHarvester("sum_val", custom_file, parse_sum)
    assert harvester.harvest() == 100


def test_case_integration_with_typed_harvesters(tmp_path: Path):
    case = Case(name="harvester_case", output_files={})
    case.database = Database(data={"RHO": [19.0, 19.5]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ['echo "residual = 5.0e-4" > solver.log && echo \'{"keff": 1.005}\' > out.json']

    case.add_harvester(RegexHarvester("residual", "solver.log", r"residual = ([0-9.e-]+)", transform=float))
    case.add_harvester(JsonHarvester("keff", "out.json", "keff", transform=float))

    case.launch()

    assert case.outputs["residual"] == [5.0e-4, 5.0e-4]
    assert case.outputs["keff"] == [1.005, 1.005]


def test_case_harvester_missing_field_fails_case_execution(tmp_path: Path):
    case = Case(name="harvester_fail", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["echo 'no match' > solver.log"]

    case.add_harvester(RegexHarvester("residual", "solver.log", r"residual = ([0-9.e-]+)"))

    with pytest.raises(CaseExecutionError, match="cases failed"):
        case.launch()

    assert case.outputs["residual"] == [None]
    assert "Failed to harvest 'residual'" in case.execution_history[-1]["error"]

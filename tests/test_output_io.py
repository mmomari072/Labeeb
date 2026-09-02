"""Focused tests for Excel result/output I/O, output discovery contract, and
case copy/render semantics (LAB-OUTPUT-IO-01)."""

import pandas as pd
import pytest

from labeeb import (
    Case,
    CaseExecutionError,
    CsvHarvester,
    Database,
    ExcelHarvester,
    JsonHarvester,
    OutputCatalog,
    RegexHarvester,
)
from labeeb.extractors import ExtractionError, extract_excel
from labeeb.results import CaseResult, export_case_results


def _write_xlsx(path, data, sheet_name="Sheet1"):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(data).to_excel(path, index=False, sheet_name=sheet_name)
    return path


# --- Excel result export -------------------------------------------------------

def test_export_case_results_to_xlsx_roundtrips(tmp_path):
    results = [
        CaseResult(0, {"RHO": 19.0}, "SUCCESS", 0, 1.2, metrics={"keff": 1.0001}),
        CaseResult(1, {"RHO": 18.5}, "FAILED", 2, 0.3, failure="boom"),
    ]
    path = tmp_path / "results.xlsx"
    dataframe = export_case_results(results, path)

    assert path.is_file()
    assert len(dataframe) == 2
    read_back = pd.read_excel(path, sheet_name="case_results")
    assert list(read_back["case_id"]) == [0, 1]
    assert list(read_back["status"]) == ["SUCCESS", "FAILED"]
    assert '"keff": 1.0001' in read_back.loc[0, "metrics"]


def test_export_case_results_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError, match=r"\.csv, \.json, \.parquet, or \.xlsx"):
        export_case_results([], tmp_path / "results.ods")


def test_output_catalog_exports_xlsx(tmp_path):
    catalog = OutputCatalog(tmp_path / "outputs.sqlite")
    try:
        from labeeb.outputs import OutputRecord

        catalog.record(OutputRecord(case_id=0, attempt=0, status="SUCCESS", exit_code=0, metrics={"keff": 1.01}))
        path = tmp_path / "catalog.xlsx"
        catalog.export(path)
        read_back = pd.read_excel(path, sheet_name="output_catalog")
        assert len(read_back) == 1
        assert read_back.loc[0, "status"] == "SUCCESS"
    finally:
        catalog.close()


# --- Excel output parsing --------------------------------------------------------

def test_extract_excel_column_and_typed_values(tmp_path):
    path = _write_xlsx(tmp_path / "out.xlsx", {"keff": [1.0, 1.02, 0.99], "temp": [300.0, 310.0, 320.0]})
    values = extract_excel(path, column="keff")
    assert values == pytest.approx([1.0, 1.02, 0.99])
    # Whole-sheet mode
    frame = extract_excel(path)
    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == ["keff", "temp"]


def test_extract_excel_sheet_selection(tmp_path):
    path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="first", index=False)
        pd.DataFrame({"a": [2, 3]}).to_excel(writer, sheet_name="second", index=False)
    assert extract_excel(path, column="a", sheet="second") == [2, 3]
    assert extract_excel(path, column="a", sheet=1) == [2, 3]


def test_extract_excel_errors(tmp_path):
    with pytest.raises(ExtractionError, match="does not exist"):
        extract_excel(tmp_path / "missing.xlsx", column="a")
    path = _write_xlsx(tmp_path / "out.xlsx", {"a": [1]})
    with pytest.raises(ExtractionError, match="Column 'zz' missing"):
        extract_excel(path, column="zz")


def test_excel_harvester_required_and_optional(tmp_path):
    required = ExcelHarvester(name="keff_xl", file_target="missing.xlsx", column="keff")
    with pytest.raises(ExtractionError, match="does not exist"):
        required.harvest(tmp_path)

    optional = ExcelHarvester(name="keff_xl", file_target="missing.xlsx", column="keff", optional=True)
    assert optional.harvest(tmp_path) is None

    _write_xlsx(tmp_path / "present.xlsx", {"keff": [1.001]})
    assert ExcelHarvester(name="keff_xl", file_target="present.xlsx", column="keff").harvest(tmp_path) == pytest.approx([1.001])


def test_case_harvests_excel_output(tmp_path):
    case = Case(name="xl_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["python -c \"import pandas as pd; pd.DataFrame({'keff': [1.0001, 1.0002]}).to_excel('results.xlsx', index=False)\""]
    case.add_harvester(ExcelHarvester(name="keff_xl", file_target="results.xlsx", column="keff", transform=list))
    case.launch()

    assert case.outputs["keff_xl"][0] == pytest.approx([1.0001, 1.0002])


# --- Explicit/optional output discovery contract ----------------------------------

def test_case_add_harvester_optional_skips_missing_file(tmp_path):
    case = Case(name="opt_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["python -c \"open('deck.csv','w').write('d\\n1\\n')\""]
    case.add_harvester("present_col", pattern="d", file_target="deck.csv", optional=True)
    case.add_harvester("absent_col", pattern="zz", file_target="missing.csv", optional=True)
    case.launch()

    assert case.outputs["absent_col"][0] is None
    assert case.outputs["present_col"][0] == [1]


def test_case_add_harvester_required_missing_fails(tmp_path):
    case = Case(name="req_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["printf done"]
    case.add_harvester("required_col", pattern="zz", file_target="missing.csv")
    with pytest.raises(CaseExecutionError, match="Failed to harvest 'required_col'"):
        case.launch_case(0)


def test_optional_flags_on_all_harvester_families(tmp_path):
    assert CsvHarvester("c", "gone.csv", "x", optional=True).harvest(tmp_path) is None
    assert JsonHarvester("j", "gone.json", "x", optional=True).harvest(tmp_path) is None
    assert RegexHarvester("r", "gone.txt", "x", optional=True).harvest(tmp_path) is None
    assert ExcelHarvester("e", "gone.xlsx", "x", optional=True).harvest(tmp_path) is None


def test_required_csv_output_file_still_enforced(tmp_path):
    # output_files (CSV columns) remain the strict explicit contract
    case = Case(name="strict_case", output_files={"out.csv": ["keff"]})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["printf done"]
    with pytest.raises(CaseExecutionError, match="Required output file '.*out.csv' was not produced"):
        case.launch_case(0)


# --- Case copy/render semantics ---------------------------------------------------

def test_case_copies_and_renders_template_per_case_without_touching_original(tmp_path):
    template = tmp_path / "deck.template"
    template.write_text(
        "TITLE run #RHO#\n"
        "POWER_W = ${RHO * 1000 : .1f}\n",
        encoding="utf-8",
    )
    original_bytes = template.read_bytes()

    case = Case(name="render_case", output_files={})
    case.database = Database(data={"RHO": [18.5, 19.2]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.FlagsMap = {"#RHO#": "RHO"}
    from labeeb.utils.file_io import File

    case.add_file(File(file_path=str(template)))
    case.set_expression_context()
    case.exe_cmd = ["printf ok"]

    case.launch()

    # Original template is untouched
    assert template.read_bytes() == original_bytes
    # Per-case rendered copies exist with row-specific values
    deck_0 = (tmp_path / "runs" / "case_0" / "deck.template").read_text(encoding="utf-8")
    deck_1 = (tmp_path / "runs" / "case_1" / "deck.template").read_text(encoding="utf-8")
    assert "TITLE run 18.5" in deck_0
    assert "POWER_W = 18500.0" in deck_0
    assert "TITLE run 19.2" in deck_1
    assert "POWER_W = 19200.0" in deck_1
    assert "#RHO#" not in deck_0 and "${" not in deck_0


def test_case_attempt_runs_use_iter_suffixed_dirs(tmp_path):
    case = Case(name="iter_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["printf done"]
    case.initialization()

    case.case_id = 0
    case.current_case_dir = str(tmp_path / "runs" / "case_0_iter1")
    from pathlib import Path as _Path

    _Path(case.current_case_dir).mkdir(parents=True, exist_ok=True)
    case._attempt = 1
    case._execute()

    assert case.execution_history[0]["case_id"] == 0

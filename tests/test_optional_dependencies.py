"""Focused tests: optional Excel/Parquet dependencies are NOT required for a
core Labeeb install (packaging + import-path refactor).

Core import and core data flows must work with openpyxl/pyarrow/xlrd/matplotlib
unavailable; feature-specific errors must remain clear. TDD anchor: metadata
test fails while openpyxl/pyarrow sit in core pyproject dependencies.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

CORE = {"pandas", "numpy", "pyyaml"}
OPTIONAL = {"openpyxl", "pyarrow", "matplotlib", "xlrd"}


def _core_deps():
    with open(PYPROJECT, "rb") as handle:
        data = tomllib.load(handle)
    project = data["project"]
    return set(project["dependencies"]), project.get("optional-dependencies", {})


def test_core_dependencies_do_not_require_optional_integrations():
    core, extras = _core_deps()
    names = {dep.split(">=")[0].split("==")[0].lower() for dep in core}
    for package in OPTIONAL:
        assert package not in names, f"{package} must not be a required core dependency"


def test_core_dependencies_keep_required_minimal_set():
    core, _ = _core_deps()
    names = {dep.split(">=")[0].split("==")[0].lower() for dep in core}
    assert CORE <= names
    assert len(names - CORE) <= 0  # no unexpected extras in core


def test_optional_dependency_extras_declared():
    _, extras = _core_deps()
    assert extras, "optional-dependencies must declare integration groups"
    all_names = {
        item.split(">=")[0].split("==")[0].lower()
        for group in extras.values() for item in group
    }
    for package in OPTIONAL - {"matplotlib", "xlrd"}:
        assert package in all_names, f"{package} missing from extras"


# --- runtime: core import works with optional engines blocked --------------------

BLOCK_SCRIPT = """
import sys
for mod in ["openpyxl", "pyarrow", "xlrd", "matplotlib"]:
    sys.modules[mod] = None  # import attempt -> ImportError
import labeeb
from labeeb import Database, Case, Optimizer, OutputCatalog, export_case_results
db = Database(data={"A": [1.0, 2.0]})
assert list(db["A"]) == [1.0, 2.0]
assert labeeb.__version__
print("CORE-OK", labeeb.__version__)
"""


def test_core_import_and_dataflow_without_optional_engines():
    proc = subprocess.run(
        [sys.executable, "-c", BLOCK_SCRIPT],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "CORE-OK" in proc.stdout


# --- runtime: feature-specific errors when optional engines are absent ------------

EXCEL_SCRIPT = """
import sys, tempfile, pathlib
sys.modules["openpyxl"] = None
import labeeb
from labeeb import Database, Case, Optimizer, OutputCatalog
from labeeb.results import export_case_results
from labeeb.extractors import extract_excel
from labeeb.optimizer import OptimizeResult, export_optimization_history
base = pathlib.Path(tempfile.mkdtemp())
# 1) excel harvest path
try:
    extract_excel(base / "missing.xlsx")
    print("EXCEL-HARVEST-NO-ERROR")
except Exception as exc:
    msg = str(exc).lower()
    ok = ("openpyxl" in msg) or ("xlrd" in msg) or ("exist" in msg) or ("not found" in msg)
    print("EXCEL-HARVEST", type(exc).__name__, ok)
# 2) optimizer history xlsx export
res = OptimizeResult(direction="minimize", method="grid", best_candidate=None, best_objective=None)
try:
    export_optimization_history(res, str(base / "h.xlsx"))
    print("OPT-XLSX-NO-ERROR")
except Exception as exc:
    print("OPT-XLSX", type(exc).__name__, "openpyxl" in str(exc).lower())
# 3) results xlsx export (pandas engine path)
case = Case(name="x", output_files={})
case.database = Database(data={"A": [1.0]})
from labeeb.results import CaseResult
try:
    export_case_results([], str(base / "r.xlsx"))
    print("RESULTS-XLSX-NO-ERROR")
except Exception as exc:
    print("RESULTS-XLSX", type(exc).__name__, "openpyxl" in str(exc).lower())
"""

PARQUET_SCRIPT = """
import sys, tempfile, pathlib
sys.modules["pyarrow"] = None
from labeeb.results import export_case_results
from labeeb.outputs import OutputCatalog
base = pathlib.Path(tempfile.mkdtemp())
try:
    export_case_results([], str(base / "r.parquet"))
    print("PARQUET-NO-ERROR")
except Exception as exc:
    print("PARQUET", type(exc).__name__, "pyarrow" in str(exc).lower())
"""


@pytest.mark.parametrize("script", [EXCEL_SCRIPT, PARQUET_SCRIPT])
def test_optional_feature_errors_are_clear(script):
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    for line in proc.stdout.splitlines():
        assert not line.endswith("-NO-ERROR"), f"expected a guarded error: {line}"
        if "-" in line and any(tag in line for tag in ("EXCEL", "OPT-XLSX", "RESULTS-XLSX", "PARQUET")):
            assert line.split()[-1] == "True", f"missing package hint: {line}"

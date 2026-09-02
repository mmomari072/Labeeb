import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from examples.case_study_reactor_uncertainty import run_reactor_case_study
from labeeb.bundle import load_analysis_bundle


def test_reactor_case_study_execution(tmp_path):
    # Run case study in temporary workspace
    summary = run_reactor_case_study(
        workspace_dir=tmp_path,
        n_samples=5,
        include_failure_test=True,
    )

    # 1. Total and successful cases count
    assert summary["total_cases"] == 6
    assert summary["successful_cases"] == 5
    assert summary["failed_cases"] == 1

    # 2. Failure visibility in results
    failed_result = [r for r in summary["results"] if r.status != "SUCCESS"][0]
    assert failed_result.status == "FAILED"
    assert failed_result.failure is not None
    assert "Physics Error" in failed_result.failure or "code 2" in failed_result.failure or failed_result.exit_code == 2

    # 3. Output Harvesting
    assert len(summary["harvested_keffs"]) == 5
    for val in summary["harvested_keffs"]:
        assert 0.95 < val < 1.05

    # 4. Sensitivity correlations calculated
    corr = summary["correlations"]
    assert "ENRICH" in corr.index
    assert "FLOW" in corr.index
    assert "POWER" in corr.index
    # Positive enrichment feedback on keff
    assert corr.loc["ENRICH", "pearson"] > 0.5

    # 5. Shared memory online summary
    mem_summary = summary["memory_summary"]
    assert "ENRICH" in mem_summary
    assert mem_summary["ENRICH"]["count"] == 6

    # 6. Analysis bundle integrity
    bundle_path = Path(summary["bundle_path"])
    assert bundle_path.is_file()

    loaded_bundle = load_analysis_bundle(bundle_path)
    assert loaded_bundle.manifest["name"] == "jrtr_reactor_case_study"
    assert len(loaded_bundle.results) == 6
    assert "results_csv" in loaded_bundle.artifacts
    assert "events_log" in loaded_bundle.artifacts


def test_reactor_case_study_without_failure_injection(tmp_path):
    summary = run_reactor_case_study(
        workspace_dir=tmp_path,
        n_samples=4,
        include_failure_test=False,
    )

    assert summary["total_cases"] == 4
    assert summary["successful_cases"] == 4
    assert summary["failed_cases"] == 0

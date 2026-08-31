import numpy as np

from labeeb.analysis import correlation_analysis, morris_screening, sobol_indices, wilks_sample_size
from labeeb.report import write_html_report
from labeeb.results import CaseResult


def test_correlation_analysis_supports_pearson_and_spearman():
    inputs = {"x": [1, 2, 3, 4], "z": [4, 3, 2, 1]}
    result = correlation_analysis(inputs, [2, 4, 6, 8])
    assert result.loc["x", "pearson"] == 1.0
    assert result.loc["z", "spearman"] == -1.0


def test_morris_screening_identifies_linear_parameter_effect():
    samples = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
    result = morris_screening(samples, [0, 2, 5, 3])
    assert result.loc["x0", "mean_absolute_effect"] == 2.0
    assert result.loc["x1", "mean_absolute_effect"] == 3.0


def test_sobol_indices_and_wilks_reference_values():
    first, total = sobol_indices([1, 2, 3, 4], [1, 2, 3, 4], [[1], [2], [5], [8]])
    assert first[0] > 0.9
    assert total[0] > 0.9
    assert wilks_sample_size(0.95, 0.95, sides=1) == 59
    assert wilks_sample_size(0.95, 0.95, sides=2) == 93


def test_html_report_is_self_contained(tmp_path):
    report = write_html_report([CaseResult(0, {"x": 1}, "SUCCESS", 0, 0.1)], tmp_path / "report.html")
    content = report.read_text(encoding="utf-8")
    assert "Labeeb Campaign" in content
    assert "SUCCESS" in content

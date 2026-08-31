import json

import pytest

from labeeb.exceptions import LabeebError
from labeeb.extractors import extract_csv, extract_json, extract_regex, run_extractor


def test_output_extractors_support_csv_json_regex_and_callable(tmp_path):
    csv_path = tmp_path / "results.csv"
    csv_path.write_text("keff,temp\n1.001,300\n", encoding="utf-8")
    json_path = tmp_path / "results.json"
    json_path.write_text(json.dumps({"metrics": {"keff": 1.002}}), encoding="utf-8")
    text_path = tmp_path / "solver.log"
    text_path.write_text("final residual = 2.5e-4\n", encoding="utf-8")

    assert extract_csv(csv_path, "keff") == [1.001]
    assert extract_json(json_path, "metrics.keff") == 1.002
    assert extract_regex(text_path, r"residual = ([0-9.e-]+)") == "2.5e-4"
    assert run_extractor(text_path, lambda path: path.read_text().strip()) == "final residual = 2.5e-4"


def test_output_extractors_raise_domain_error_for_missing_fields(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("keff\n", encoding="utf-8")

    with pytest.raises(LabeebError):
        extract_csv(path, "missing")

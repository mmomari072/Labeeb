"""Focused tests: OutputCatalog integrated into Campaign.run() as opt-in
(LAB-OUTPUT-CATALOG-INTEGRATION-01), preserving disabled/default behavior."""

from labeeb import Campaign, CampaignManifest, OutputCatalog


def _manifest(tmp_path, name="cat-study", command='printf out; printf err >&2', values=None, **execution):
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    payload = {
        "name": name,
        "parameters": {"VALUE": values or [1, 2]},
        "templates": [str(template)],
        "commands": [command],
        "execution": {"run_dir": str(tmp_path / "runs"), **execution},
    }
    return CampaignManifest.from_dict(payload)


def test_disabled_by_default_no_catalog_file_created(tmp_path):
    manifest = _manifest(tmp_path, capture_output=True)
    results = Campaign(manifest).run()

    assert [r.status for r in results] == ["SUCCESS", "SUCCESS"]
    catalog_files = list(tmp_path.rglob("*.sqlite"))
    assert catalog_files == []  # no catalog (and no state) was created implicitly


def test_constructor_opt_in_records_every_attempt(tmp_path):
    manifest = _manifest(tmp_path, capture_output=True)
    catalog_path = tmp_path / "catalog.sqlite"

    results = Campaign(manifest, output_catalog=catalog_path).run()

    assert [r.status for r in results] == ["SUCCESS", "SUCCESS"]
    with OutputCatalog(catalog_path) as catalog:
        assert catalog.case_ids() == [0, 1]
        for case_id in (0, 1):
            rows = catalog.get(case_id)
            assert len(rows) == 1
            row = rows[0]
            assert row["attempt"] == 0
            assert row["status"] == "SUCCESS"
            assert row["unit"] == "cat-study"
            assert row["exit_code"] == 0
            assert row["duration_seconds"] is not None and row["duration_seconds"] >= 0
            assert row["stdout_path"] is not None and row["stdout_path"].endswith("stdout.log")
            assert row["stderr_path"] is not None and row["stderr_path"].endswith("stderr.log")
            assert row["started_at"] and row["ended_at"]


def test_manifest_execution_config_enables_catalog(tmp_path):
    manifest = _manifest(tmp_path, output_catalog=str(tmp_path / "cfg_catalog.sqlite"))

    results = Campaign(manifest).run()

    assert len(results) == 2
    with OutputCatalog(tmp_path / "cfg_catalog.sqlite") as catalog:
        assert len(catalog.all_records()) == 2


def test_failed_and_retried_attempts_are_recorded_separately(tmp_path):
    failing = _manifest(tmp_path, name="retry-study", command="python -c \"import sys; sys.exit(2)\"", values=[1])
    state_path = tmp_path / "state.sqlite"
    catalog_path = tmp_path / "catalog.sqlite"

    first = Campaign(failing, state_path=state_path, output_catalog=catalog_path).run(max_retries=2)
    assert first[0].status == "FAILED"

    # Same parameters/template but a now-working command: hash changes, retry runs.
    ok_manifest = _manifest(tmp_path, name="retry-study", command="printf ok", values=[1])
    second = Campaign(ok_manifest, state_path=state_path, output_catalog=catalog_path).run(max_retries=2)
    assert second[0].status == "SUCCESS"

    with OutputCatalog(catalog_path) as catalog:
        rows = catalog.attempts(0)
        assert len(rows) == 2
        assert [(row.attempt, row.status) for row in rows] == [(0, "FAILED"), (1, "SUCCESS")]
        assert rows[0].message is not None and "exited with code 2" in rows[0].message
        assert rows[1].exit_code == 0
        assert rows[1].unit == "retry-study"


def test_catalog_records_metrics_from_case_outputs_delta(tmp_path):
    from labeeb import CsvHarvester

    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    # Command writes results.csv with one keff row (commands are NOT templated;
    # parameters only reach files, so the metric is constant per case here).
    command = 'python -c "open(\'results.csv\',\'w\').write(\'keff\\n1.0001\\n\')"'
    manifest = CampaignManifest.from_dict(
        {
            "name": "metric-study",
            "parameters": {"VALUE": [1.0, 2.0]},
            "templates": [str(template)],
            "commands": [command],
            "execution": {"run_dir": str(tmp_path / "runs")},
        }
    )
    campaign = Campaign(manifest, output_catalog=tmp_path / "catalog.sqlite")
    harvester = CsvHarvester(name="keff", file_target="results.csv", column="keff")

    # Inject the harvester into the case the campaign builds for its run loop.
    original_build = campaign.build_case

    def instrumented_build():
        instrumented = original_build()
        instrumented.add_harvester(harvester)
        return instrumented

    campaign.build_case = instrumented_build  # type: ignore[method-assign]
    campaign.run()

    with OutputCatalog(tmp_path / "catalog.sqlite") as catalog:
        for case_id in (0, 1):
            row = catalog.latest(case_id)
            assert row is not None
            assert row.metrics["keff"] == [1.0001]  # this attempt's harvested slice


def test_existing_campaign_behavior_unchanged_without_catalog(tmp_path):
    """Regression: no catalog, no state -> same results/run dirs as before."""
    manifest = _manifest(tmp_path)
    results = Campaign(manifest).run()
    assert [r.status for r in results] == ["SUCCESS", "SUCCESS"]
    assert (tmp_path / "runs" / "case_0" / "input.deck").read_text(encoding="utf-8") == "value=1.0\n"
    assert (tmp_path / "runs" / "case_1" / "input.deck").read_text(encoding="utf-8") == "value=2.0\n"

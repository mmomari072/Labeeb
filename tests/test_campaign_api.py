from pathlib import Path

from labeeb.campaign import Campaign, CampaignManifest


def test_campaign_python_api_runs_case_study_and_returns_results(tmp_path: Path) -> None:
    template = tmp_path / "input.deck"
    template.write_text("density=#DENSITY#\n", encoding="utf-8")
    manifest = CampaignManifest.from_dict(
        {
            "name": "api-study",
            "parameters": {"DENSITY": [1.0, 2.0]},
            "templates": [str(template)],
            "commands": ["python -c \"from pathlib import Path; Path('done').write_text('ok')\""],
            "execution": {"run_dir": str(tmp_path / "runs")},
        }
    )

    results = Campaign(manifest).run()

    assert [result.status for result in results] == ["SUCCESS", "SUCCESS"]
    assert (tmp_path / "runs" / "case_0" / "input.deck").read_text() == "density=1.0\n"
    assert (tmp_path / "runs" / "case_1" / "done").read_text() == "ok"


def test_campaign_state_reuses_successful_cases(tmp_path: Path) -> None:
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    manifest = CampaignManifest.from_dict(
        {
            "name": "resume-study",
            "parameters": {"VALUE": [3]},
            "templates": [str(template)],
            "commands": ["python -c \"from pathlib import Path; Path('marker').touch()\""],
            "execution": {"run_dir": str(tmp_path / "runs")},
        }
    )
    state_path = tmp_path / "state.sqlite"

    first = Campaign(manifest, state_path=state_path).run()
    marker = tmp_path / "runs" / "case_0" / "marker"
    marker.unlink()
    second = Campaign(manifest, state_path=state_path).run()

    assert first[0].status == second[0].status == "SUCCESS"
    assert not marker.exists()


def test_campaign_persists_execution_events_incrementally(tmp_path: Path) -> None:
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    events_path = tmp_path / "runs" / "events.jsonl"
    manifest = CampaignManifest.from_dict(
        {
            "name": "event-study",
            "parameters": {"VALUE": [1, 2]},
            "templates": [str(template)],
            "commands": ["true"],
            "execution": {"run_dir": str(tmp_path / "runs"), "events_file": str(events_path)},
        }
    )

    results = Campaign(manifest).run()

    assert len(results) == 2
    assert len(events_path.read_text(encoding="utf-8").splitlines()) == 2

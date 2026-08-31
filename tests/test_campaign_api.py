from pathlib import Path
import json

from labeeb.campaign import Campaign, CampaignManifest
from labeeb.results import CampaignStateStore, CaseResult


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
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 8
    assert sum(event["event_type"] == "command" for event in events) == 2


def test_campaign_logs_lifecycle_and_captures_output_artifacts(tmp_path: Path) -> None:
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    events_path = tmp_path / "events.jsonl"
    manifest = CampaignManifest.from_dict(
        {
            "name": "lifecycle-study",
            "parameters": {"VALUE": [1]},
            "templates": [str(template)],
            "commands": ["printf out; printf err >&2"],
            "execution": {
                "run_dir": str(tmp_path / "runs"),
                "events_file": str(events_path),
                "capture_output": True,
            },
        }
    )

    Campaign(manifest).run()

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event_type"] for event in events] == [
        "campaign_start", "case_start", "command", "case_complete", "campaign_complete"
    ]
    assert events[2]["case_id"] == 0
    assert (tmp_path / "runs" / "case_0" / "stdout.log").read_text() == "out"
    assert (tmp_path / "runs" / "case_0" / "stderr.log").read_text() == "err"


def test_campaign_retry_records_attempt_and_uses_distinct_directory(tmp_path: Path) -> None:
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    state_path = tmp_path / "state.sqlite"
    events_path = tmp_path / "events.jsonl"
    manifest = CampaignManifest.from_dict(
        {
            "name": "retry-study",
            "parameters": {"VALUE": [1]},
            "templates": [str(template)],
            "commands": ["true"],
            "execution": {"run_dir": str(tmp_path / "runs"), "events_file": str(events_path)},
        }
    )
    with CampaignStateStore(state_path) as state:
        state.save(CaseResult(0, {"VALUE": 1}, "FAILED", 1, 0.1, failure="transient"), "old-hash")

    Campaign(manifest, state_path=state_path).run(max_retries=3)

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events[1]["attempt"] == 1
    assert (tmp_path / "runs" / "case_0_iter1" / "input.deck").exists()


def test_campaign_marks_completion_failed_when_a_case_fails(tmp_path: Path) -> None:
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    events_path = tmp_path / "events.jsonl"
    manifest = CampaignManifest.from_dict(
        {
            "name": "failure-study",
            "parameters": {"VALUE": [1]},
            "templates": [str(template)],
            "commands": ["false"],
            "execution": {"run_dir": str(tmp_path / "runs"), "events_file": str(events_path)},
        }
    )

    results = Campaign(manifest).run()

    assert results[0].status == "FAILED"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events[-2]["event_type"] == "case_failure"
    assert events[-1]["event_type"] == "campaign_complete"
    assert events[-1]["status"] == "FAILED"

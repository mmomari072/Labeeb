import json

from labeeb.cli import main
from labeeb.results import CampaignStateStore, CaseResult


def test_cli_validate_accepts_manifest(tmp_path, capsys):
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps({
        "name": "cli_campaign",
        "parameters": {"RHO": [19.0]},
        "templates": ["input.i"],
        "commands": ["echo run"],
    }), encoding="utf-8")

    assert main(["validate", str(path)]) == 0
    assert "valid" in capsys.readouterr().out


def test_cli_run_executes_local_campaign(tmp_path, capsys):
    template = tmp_path / "input.i"
    template.write_text("RHO=#RHO#\n", encoding="utf-8")
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps({
        "name": "cli_run",
        "parameters": {"RHO": [19.0]},
        "templates": [str(template)],
        "commands": ["echo run"],
        "execution": {"run_dir": str(tmp_path / "runs")},
    }), encoding="utf-8")

    assert main(["run", str(path)]) == 0
    assert "completed" in capsys.readouterr().out


def test_cli_status_and_resume_report_persisted_state(tmp_path, capsys):
    state_path = tmp_path / "state.sqlite"
    with CampaignStateStore(state_path) as state:
        state.save(CaseResult(0, {}, "FAILED", 1, 0.1, failure="retry"), "hash")

    assert main(["status", str(state_path)]) == 0
    assert "failed" in capsys.readouterr().out
    assert main(["resume", str(state_path)]) == 0
    assert "0" in capsys.readouterr().out

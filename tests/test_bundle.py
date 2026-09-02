import json
import zipfile
from pathlib import Path
import pytest

from labeeb.campaign import Campaign, CampaignManifest
from labeeb.publisher import JsonlEventPublisher
from labeeb.shared_memory import CampaignMemory
from labeeb.bundle import AnalysisBundle, BundleError, export_analysis_bundle, load_analysis_bundle


def test_analysis_bundle_json_export_and_import(tmp_path: Path):
    template = tmp_path / "deck.template"
    template.write_text("PARAM = #PARAM#\n")

    manifest = CampaignManifest(
        name="test_bundle_campaign",
        parameters={"PARAM": [1, 2]},
        templates=[str(template)],
        commands=["python -c 'print(\"done\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    event_file = tmp_path / "events.jsonl"
    pub = JsonlEventPublisher(event_file)
    mem = CampaignMemory()

    campaign = Campaign(manifest, memory=mem, publisher=pub)
    results = campaign.run()
    pub.flush()

    # Create bundle
    bundle = AnalysisBundle.from_campaign(campaign, results=results, publisher=pub)
    assert bundle.manifest["name"] == "test_bundle_campaign"
    assert len(bundle.results) == 2
    assert len(bundle.events) > 0

    json_path = tmp_path / "bundle.json"
    bundle.to_json(json_path)
    assert json_path.exists()

    # Load and validate
    loaded = AnalysisBundle.load(json_path)
    assert loaded.manifest["name"] == "test_bundle_campaign"
    assert len(loaded.results) == 2
    assert len(loaded.events) == len(bundle.events)


def test_analysis_bundle_zip_export_with_artifacts(tmp_path: Path):
    template = tmp_path / "deck.template"
    template.write_text("PARAM = #PARAM#\n")

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "summary.csv").write_text("val1,val2\n10,20\n")

    manifest = CampaignManifest(
        name="zip_campaign",
        parameters={"PARAM": [100]},
        templates=[str(template)],
        commands=["python -c 'print(\"done\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    campaign = Campaign(manifest)
    results = campaign.run()

    zip_path = tmp_path / "bundle.zip"
    bundle = AnalysisBundle.from_campaign(
        campaign,
        results=results,
        artifacts={"summary_csv": str(artifact_dir / "summary.csv")}
    )
    bundle.to_zip(zip_path)
    assert zip_path.exists()

    # Inspect zip contents
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "bundle.json" in namelist
        assert "artifacts/summary.csv" in namelist

    # Load from zip
    loaded = AnalysisBundle.load(zip_path)
    assert loaded.manifest["name"] == "zip_campaign"
    assert len(loaded.results) == 1
    assert "summary_csv" in loaded.artifacts


def test_analysis_bundle_redaction(tmp_path: Path):
    bundle = AnalysisBundle(
        manifest={"name": "secret_camp", "password": "pass", "token": "abc"},
        provenance={"hash": "1234"},
        results=[{"case_id": 0, "api_key": "xyz-123"}],
        events=[{"event_type": "auth", "secret": "forbidden"}],
        redact_keys=["password", "token", "api_key", "secret"]
    )

    json_path = tmp_path / "redacted_bundle.json"
    bundle.to_json(json_path)

    raw_data = json.loads(json_path.read_text())
    assert raw_data["manifest"]["password"] == "[REDACTED]"
    assert raw_data["manifest"]["token"] == "[REDACTED]"
    assert raw_data["results"][0]["api_key"] == "[REDACTED]"
    assert raw_data["events"][0]["secret"] == "[REDACTED]"


def test_analysis_bundle_replay(tmp_path: Path):
    bundle = AnalysisBundle(
        manifest={"name": "replay_camp"},
        provenance={},
        results=[
            {"case_id": 0, "parameters": {"x": 1.0}, "status": "SUCCESS", "metrics": {"temp": 300.0}},
            {"case_id": 1, "parameters": {"x": 2.0}, "status": "SUCCESS", "metrics": {"temp": 350.0}},
        ],
        events=[
            {"event_type": "case_start", "case_id": 0},
            {"event_type": "case_complete", "case_id": 0},
            {"event_type": "case_start", "case_id": 1},
            {"event_type": "case_complete", "case_id": 1},
        ]
    )

    # Replay into fresh CampaignMemory
    fresh_memory = CampaignMemory()
    bundle.replay_memory(fresh_memory)
    assert len(fresh_memory.get_all_cases()) == 2
    assert fresh_memory.get_case(0)["parameters"]["x"] == 1.0

    # Replay events to callback
    replayed_events = []
    bundle.replay_events(lambda e: replayed_events.append(e["event_type"]))
    assert len(replayed_events) == 4
    assert replayed_events[0] == "case_start"


def test_analysis_bundle_invalid_load(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt.txt"
    corrupt_file.write_text("not a valid bundle json or zip")

    with pytest.raises(BundleError):
        AnalysisBundle.load(corrupt_file)


def test_campaign_export_bundle_convenience_method(tmp_path: Path):
    template = tmp_path / "deck.template"
    template.write_text("PARAM = #PARAM#\n")

    manifest = CampaignManifest(
        name="convenience_campaign",
        parameters={"PARAM": [10]},
        templates=[str(template)],
        commands=["python -c 'print(\"done\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    campaign = Campaign(manifest)
    results = campaign.run()

    zip_out = tmp_path / "campaign_export.zip"
    exported_bundle = campaign.export_bundle(zip_out, results=results)
    assert zip_out.exists()
    assert exported_bundle.manifest["name"] == "convenience_campaign"

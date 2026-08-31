import json

import pytest

from labeeb.campaign import CampaignManifest, load_manifest
from labeeb.exceptions import LabeebError


def test_campaign_manifest_loads_json_and_validates_core_fields(tmp_path):
    source = {
        "name": "shield_sweep",
        "parameters": {"RHO": [18.0, 19.0]},
        "templates": ["input.i"],
        "commands": ["mcnp6 input.i"],
        "seed": 17,
        "execution": {"parallel": True, "n_workers": 2, "timeout": 60.0},
    }
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    manifest = load_manifest(path)

    assert manifest.name == "shield_sweep"
    assert manifest.parameters == source["parameters"]
    assert manifest.execution["n_workers"] == 2
    assert manifest.to_dict() == source


def test_campaign_manifest_supports_yaml(tmp_path):
    path = tmp_path / "campaign.yml"
    path.write_text(
        "name: yaml_campaign\nparameters:\n  TEMP: [300, 350]\ntemplates: [input.i]\ncommands: ['echo run']\n",
        encoding="utf-8",
    )

    manifest = load_manifest(path)

    assert manifest.name == "yaml_campaign"
    assert manifest.parameters["TEMP"] == [300, 350]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "x", "parameters": {}, "templates": [], "commands": []},
        {"name": "x", "parameters": {"RHO": []}, "templates": ["i"], "commands": ["run"]},
        {"name": "x", "parameters": {"RHO": [1]}, "templates": ["i"], "commands": []},
    ],
)
def test_campaign_manifest_rejects_invalid_payloads(payload):
    with pytest.raises(LabeebError):
        CampaignManifest.from_dict(payload)


def test_campaign_manifest_provenance_is_deterministic(tmp_path):
    template = tmp_path / "input.i"
    template.write_text("RHO={{ RHO }}\n", encoding="utf-8")
    manifest = CampaignManifest.from_dict(
        {"name": "hashes", "parameters": {"RHO": [19.0]}, "templates": [str(template)], "commands": ["echo run"]}
    )

    provenance = manifest.provenance()

    assert len(provenance["manifest_sha256"]) == 64
    assert provenance["templates"][str(template)]["sha256"]

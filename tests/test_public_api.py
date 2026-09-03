import pytest

import labeeb
from labeeb.campaign import Campaign, CampaignError, CampaignManifest


def test_public_api_is_explicit_and_versioned():
    assert labeeb.__version__ == "1.20.7"
    assert "Campaign" in labeeb.__all__
    assert all(hasattr(labeeb, name) for name in labeeb.__all__)
    assert labeeb.StatusRegistry is labeeb.ExecutionStatusRegistry


def test_campaign_rejects_misaligned_parameter_rows():
    manifest = CampaignManifest.from_dict(
        {"name": "bad", "parameters": {"x": [1, 2], "y": [3]}, "templates": ["input"], "commands": ["run"]}
    )
    with pytest.raises(CampaignError, match="same number of values"):
        Campaign(manifest)

import json
import os
import tempfile
import pytest

from labeeb import Campaign, CampaignManifest, Constraint, Optimizer
from labeeb.campaign import CampaignError
from labeeb.exceptions import OptimizationError
from labeeb.utils.file_io import File


def test_campaign_optimize_basic(tmp_path):
    # Setup deck template
    deck = tmp_path / "model.inp"
    deck.write_text("POWER = #POWER#\n", encoding="utf-8")

    manifest = CampaignManifest(
        name="opt_campaign",
        parameters={"POWER": [10.0, 50.0]},
        templates=[str(deck)],
        commands=["echo peak_temp > data.csv", "echo 500.0 >> data.csv"],
        execution={"run_dir": str(tmp_path / "runs"), "shell": True},
    )

    campaign = Campaign(manifest)
    # Target objective function: minimize peak_temp (which is fixed at 500.0)
    result = campaign.optimize(
        objective_metric="peak_temp",
        variables={"POWER": (10.0, 50.0)},
        method="grid",
        grid_points=3,
        budget=5,
    )

    assert result.evaluations == 3
    assert result.best_objective == 500.0
    assert "POWER" in result.best_candidate


def test_campaign_optimize_inferred_bounds(tmp_path):
    deck = tmp_path / "model.inp"
    deck.write_text("TEMP = #TEMP#\n", encoding="utf-8")

    manifest = CampaignManifest(
        name="inferred_opt",
        parameters={"TEMP": [300.0, 400.0, 500.0]},
        templates=[str(deck)],
        commands=["echo temp > data.csv", "echo 350.0 >> data.csv"],
        execution={"run_dir": str(tmp_path / "runs"), "shell": True},
    )

    campaign = Campaign(manifest)
    result = campaign.optimize(
        objective_metric="temp",
        method="grid",
        grid_points=3,
        budget=3,
    )

    assert result.evaluations == 3
    assert result.best_candidate["TEMP"] in (300.0, 400.0, 500.0)


def test_campaign_optimize_constraints_and_checkpoint(tmp_path):
    deck = tmp_path / "model.inp"
    deck.write_text("PARAM = #PARAM#\n", encoding="utf-8")

    manifest = CampaignManifest(
        name="constrained_opt",
        parameters={"PARAM": [1.0, 10.0]},
        templates=[str(deck)],
        commands=["echo val > data.csv", "echo 100.0 >> data.csv"],
        execution={"run_dir": str(tmp_path / "runs"), "shell": True},
    )

    chk_path = tmp_path / "opt_chk.json"
    constraint = Constraint(name="param_gt_5", predicate=lambda c: c["PARAM"] > 5.0)

    campaign = Campaign(manifest)
    result = campaign.optimize(
        objective_metric="val",
        variables={"PARAM": (1.0, 10.0)},
        constraints=[constraint],
        method="grid",
        grid_points=5,
        budget=10,
        checkpoint_path=chk_path,
    )

    assert os.path.exists(chk_path)
    assert result.evaluations > 0
    # Infeasible candidates skipped simulation
    assert any(rec.status == "infeasible" for rec in result.history)


def test_campaign_optimize_error_non_numeric_params():
    manifest = CampaignManifest(
        name="string_params",
        parameters={"TYPE": ["A", "B"]},
        templates=["dummy.inp"],
        commands=["echo 1"],
    )

    campaign = Campaign(manifest)
    with pytest.raises(CampaignError, match="Cannot infer numeric variable bounds"):
        campaign.optimize(objective_metric="out")

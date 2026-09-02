"""Focused tests: Campaign-native LivePlot/PlotObserver with safe attach/detach
and exception cleanup (LAB-CAMPAIGN-LIVE-PLOT-01)."""

import pytest

from labeeb import (
    Campaign,
    CampaignError,
    CampaignManifest,
    JsonlEventPublisher,
)
from labeeb.plot import LivePlot, PlotObserver
from labeeb.publisher import LiveObserver


def _manifest(tmp_path, values=None, command='printf out', **execution):
    template = tmp_path / "input.deck"
    template.write_text("value=#VALUE#\n", encoding="utf-8")
    payload = {
        "name": "plot-campaign",
        "parameters": {"VALUE": [float(v) for v in (values or [1.0, 2.0, 3.0])]},
        "templates": [str(template)],
        "commands": [command],
        "execution": {"run_dir": str(tmp_path / "runs"), **execution},
    }
    return CampaignManifest.from_dict(payload)


def test_campaign_attaches_plot_records_metrics_and_detaches(tmp_path):
    publisher = JsonlEventPublisher(tmp_path / "events.jsonl")
    plot = PlotObserver(metrics=["VALUE"], output_path=tmp_path / "live.png", enabled=True)
    campaign = Campaign(_manifest(tmp_path), publisher=publisher, live_plot=plot)

    results = campaign.run()

    assert len(results) == 3
    assert plot.get_history()["VALUE"] == [1.0, 2.0, 3.0]
    # Safe detach: observer no longer receives events after the run
    assert plot not in publisher._observers
    publisher.publish({"VALUE": 99.0})
    assert plot.get_history()["VALUE"] == [1.0, 2.0, 3.0]
    # Final image written by close/flush on exit
    assert (tmp_path / "live.png").exists()


def test_campaign_mapping_config_and_manifest_config(tmp_path):
    publisher = JsonlEventPublisher(tmp_path / "events.jsonl")
    # Mapping form on the constructor
    campaign = Campaign(
        _manifest(tmp_path, values=[5.0]),
        publisher=publisher,
        live_plot={"metrics": ["VALUE"], "output_path": str(tmp_path / "a.png"), "enabled": True},
    )
    campaign.run()
    assert (tmp_path / "a.png").exists()

    # Manifest execution.live_plot mapping form
    publisher2 = JsonlEventPublisher(tmp_path / "events2.jsonl")
    manifest = _manifest(tmp_path, values=[7.0], live_plot={"metrics": ["VALUE"]})
    campaign2 = Campaign(manifest, publisher=publisher2)
    campaign2.run()
    # Constructor-less, manifest-built observer is attached for the run then closed;
    # a history-only observer has no output image but the run must succeed.
    assert campaign2.live_plot is None  # resolved per-run from the manifest
    assert campaign2.publisher is not None


def test_campaign_cleans_up_plot_when_run_raises(tmp_path, monkeypatch):
    publisher = JsonlEventPublisher(tmp_path / "events.jsonl")
    plot = PlotObserver(metrics=["VALUE"], output_path=tmp_path / "boom.png")
    campaign = Campaign(_manifest(tmp_path), publisher=publisher, live_plot=plot)

    def explode(case_id, data):
        raise RuntimeError("simulated mid-run failure")

    monkeypatch.setattr(campaign.memory, "record_case", explode)
    with pytest.raises(RuntimeError, match="simulated mid-run failure"):
        campaign.run()

    # Exception cleanup: detached and closed even though run() raised
    assert plot not in publisher._observers
    assert plot._closed is True
    # publisher itself remains functional
    publisher.publish({"x": 1})


def test_live_plot_context_instance_works_through_campaign(tmp_path):
    publisher = JsonlEventPublisher(tmp_path / "events.jsonl")
    with LivePlot(metrics=["VALUE"], output_path=tmp_path / "ctx.png") as plot:
        campaign = Campaign(_manifest(tmp_path, values=[4.0]), publisher=publisher, live_plot=plot)
        campaign.run()
    assert plot.get_history()["VALUE"] == [4.0]
    assert (tmp_path / "ctx.png").exists()


def test_no_publisher_skips_attach_but_run_succeeds(tmp_path):
    plot = PlotObserver(metrics=["VALUE"], output_path=tmp_path / "p.png")
    campaign = Campaign(_manifest(tmp_path), live_plot=plot)  # no publisher
    results = campaign.run()
    assert len(results) == 3
    assert plot.get_history() == {}  # no events reached it
    assert plot._closed is True  # still closed cleanly


def test_invalid_live_plot_config_rejected():
    manifest = CampaignManifest.from_dict(
        {
            "name": "bad-plot",
            "parameters": {"VALUE": [1.0]},
            "templates": ["/nonexistent/template"],
            "commands": ["true"],
        }
    )
    with pytest.raises(CampaignError, match="PlotObserver/LivePlot instance or a configuration mapping"):
        Campaign(manifest, live_plot=12345)


def test_publisher_remove_observer_is_idempotent_and_selective(tmp_path):
    publisher = JsonlEventPublisher(tmp_path / "events.jsonl")
    first = LiveObserver(lambda event: None)
    second = PlotObserver(metrics=["x"])
    publisher.add_observer(first).add_observer(second)
    publisher.remove_observer(first)
    publisher.remove_observer(first)  # idempotent
    assert second in publisher._observers
    assert first not in publisher._observers
    publisher.publish({"x": 1.0})
    assert second.get_history()["x"] == [1.0]

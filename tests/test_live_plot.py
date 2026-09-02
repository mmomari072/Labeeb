from pathlib import Path

from labeeb.publisher import JsonlEventPublisher
from labeeb.plot import LivePlot, PlotObserver
from labeeb.campaign import Campaign, CampaignManifest


def test_plot_observer_disabled_mode(tmp_path: Path):
    out_img = tmp_path / "plot.png"
    observer = PlotObserver(metrics=["temp"], output_path=out_img, enabled=False)
    assert not observer.enabled

    # Should not accumulate or write file
    observer.notify({"event_type": "case_complete", "temp": 300.0})
    observer.flush()

    assert not out_img.exists()
    assert len(observer.get_history().get("temp", [])) == 0


def test_plot_observer_history_tracking():
    observer = PlotObserver(metrics=["temp", "pressure"], enabled=True)
    observer.notify({"event_type": "case_complete", "temp": 300.0, "pressure": 1.5})
    observer.notify({"event_type": "case_complete", "temp": 310.0, "pressure": 1.6})

    hist = observer.get_history()
    assert hist["temp"] == [300.0, 310.0]
    assert hist["pressure"] == [1.5, 1.6]


def test_plot_observer_throttling(tmp_path: Path):
    out_img = tmp_path / "plot.png"
    # High update interval to test throttling
    observer = PlotObserver(
        metrics=["temp"],
        output_path=out_img,
        enabled=True,
        update_interval_seconds=10.0
    )

    # First event triggers a render request
    observer.notify({"event_type": "case_complete", "temp": 300.0})

    # Immediate second event within interval should be throttled (not redrawn)
    observer.notify({"event_type": "case_complete", "temp": 320.0})
    
    # History is updated even if redraw is throttled
    assert observer.get_history()["temp"] == [300.0, 320.0]

    # Explicit flush forces redraw/save
    observer.flush()
    assert out_img.exists()


def test_plot_observer_failure_isolation():
    # Observer with faulty extraction/render settings
    def broken_metric_extract(evt):
        raise ValueError("Invalid metric math")

    observer = PlotObserver(
        extract_fn=broken_metric_extract,
        enabled=True
    )

    # Must never raise exception to caller or interrupt simulation
    observer.notify({"event_type": "case_complete", "val": 100})
    assert len(observer.get_history()) == 0


def test_live_plot_context_and_api(tmp_path: Path):
    out_img = tmp_path / "live.png"
    with LivePlot(metrics=["power"], output_path=out_img, title="Reactor Power") as lp:
        lp.update({"power": 10.0})
        lp.update({"power": 20.0})
        assert lp.get_history()["power"] == [10.0, 20.0]

    assert out_img.exists()


def test_plot_observer_integration_with_event_publisher(tmp_path: Path):
    event_file = tmp_path / "events.jsonl"
    plot_file = tmp_path / "progress.png"
    
    publisher = JsonlEventPublisher(event_file)
    observer = PlotObserver(metrics=["RHO", "duration"], output_path=plot_file, enabled=True)
    publisher.add_observer(observer)

    template = tmp_path / "deck.template"
    deck_text = "RHO = #RHO#\n"
    template.write_text(deck_text)

    manifest = CampaignManifest(
        name="plot_campaign",
        parameters={"RHO": [18.5, 19.0, 19.5]},
        templates=[str(template)],
        commands=["python -c 'print(\"done\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    campaign = Campaign(manifest, publisher=publisher)
    results = campaign.run()
    assert len(results) == 3

    publisher.flush()
    observer.flush()

    assert plot_file.exists()
    assert len(observer.get_history().get("RHO", [])) == 3

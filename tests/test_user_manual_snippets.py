import os
import tempfile
from pathlib import Path
import pytest
import pandas as pd
import labeeb
from labeeb.database import Attribute, Database
from labeeb.sampler import FOATConstructor
from labeeb import halton_sample, latin_hypercube_sample
from labeeb.case import Flag, FlagsMap, Case
from labeeb.utils.file_io import File
from labeeb.extractors import (
    CsvHarvester,
    JsonHarvester,
    RegexHarvester,
    CallableHarvester,
)
from labeeb.campaign import CampaignManifest, Campaign
from labeeb.coupler import Coupler
from labeeb.publisher import (
    JsonlEventPublisher,
    WebSocketEventPublisher,
    RedisStreamEventPublisher,
    CompositeEventPublisher,
    NullEventPublisher,
)
from labeeb.plot import LivePlot, PlotObserver
from labeeb.bundle import AnalysisBundle, export_analysis_bundle, load_analysis_bundle
from labeeb.shared_memory import CampaignMemory, InMemorySharedBackend
from labeeb.analysis import (
    correlation_analysis,
    morris_screening,
    sobol_indices,
    wilks_sample_size,
)


def test_section_3_database_and_attributes(tmp_path):
    density = Attribute(name="RHO", data=[18.5, 19.0, 19.5], unit="g/cm3")
    enrichment = Attribute(name="WF", data=[0.1975, 0.1975, 0.1975], unit="wt_frac")
    scaled_density = density * 1000.0
    offset = density + 0.1
    high_density = density > 19.0

    db = Database(name="core_sampling")
    db.add_attribute(
        Attribute(name="POWER", data=[10.0, 15.0, 20.0], unit="MW"),
        Attribute(name="FLOW", data=[1200.0, 1350.0, 1500.0], unit="m3/h"),
    )
    row_0 = db.get_row(0)
    assert row_0 == {"POWER": 10.0, "FLOW": 1200.0}

    db.add_derived_attribute("POWER_KW", "POWER * 1000.0", unit="kW")
    db.add_derived_attribute(
        "SPECIFIC_FLOW",
        lambda row: row["FLOW"] / row["POWER"],
        dependencies=["FLOW", "POWER"],
        unit="m3/(h*MW)",
    )
    assert list(db["POWER_KW"]) == [10000.0, 15000.0, 20000.0]
    assert list(db["SPECIFIC_FLOW"]) == [120.0, 90.0, 75.0]

    db.update_row(row_id=1, data={"POWER": 16.5})
    assert db["POWER_KW"][1] == 16500.0
    assert db["SPECIFIC_FLOW"][1] == pytest.approx(1350.0 / 16.5)

    csv_path = tmp_path / "core_sampling.csv"
    db.export_to_file(str(csv_path))

    db_new = Database(name="imported")
    db_new.import_from_file(str(csv_path))
    assert len(db_new) == 3
    assert "POWER_KW" in db_new



def test_section_4_sampling():
    sweeper = FOATConstructor()
    sweeper.add_case({
        "INLET_TEMP": [25.0, 30.0, 35.0],
        "CORE_FLOW": [1200.0, 1400.0],
    })
    grid_dict = sweeper.construct()
    grid_db = Database(data=grid_dict)
    assert len(grid_db) == 6

    bounds = [(18.0, 20.0), (0.01, 0.05)]
    lhs_samples = latin_hypercube_sample(bounds, size=100, seed=42)
    assert lhs_samples.shape == (100, 2)

    halton_points = halton_sample(size=100, dimensions=3)
    assert halton_points.shape == (100, 3)


def test_section_5_templating(tmp_path):
    flags = FlagsMap()
    flags.add_flag(Flag(name="#RHO#", attribute_name="RHO", fmt="%6.2f"))
    flags.add_flag(Flag(name="#WF#", attribute_name="WF", fmt="%8.4f"))

    template_file = tmp_path / "relap_deck.jinja2"
    template_file.write_text("Power = {{ power }}\n{% for ch in channels %}Channel {{ ch.id }} flow={{ ch.flow }}\n{% endfor %}")
    
    template = File(file_path=str(template_file))
    template.render_jinja({
        "power": 20.0,
        "channels": [{"id": 1, "flow": 500.0}, {"id": 2, "flow": 600.0}]
    })

    model_inp = tmp_path / "model.inp"
    model_inp.write_text("flux = 1.0e-04, temp = 293.0 $ initial state\n")
    model_tmpl = File(file_path=str(model_inp)).read()
    model_tmpl.replace_assignments(
        {"flux": 2.5e-04, "temp": 300.0},
        fmt={"flux": "{:.2e}", "temp": "%.1f"},
        strict=True,
    )
    assert model_tmpl[0] == "flux = 2.50e-04, temp = 300.0 $ initial state"

    core_inp = tmp_path / "core.inp"
    core_inp.write_text("power = ${power_mw * 1e6 : {:.2e}}\nradius = ${radius * 2.0 : %6.2f}\n")
    core_tmpl = File(file_path=str(core_inp)).read()
    core_tmpl.replace_expressions({
        "power_mw": 15.0,
        "radius": 10.0,
    })
    assert core_tmpl[0] == "power = 1.50e+07"
    assert core_tmpl[1] == "radius =  20.00"



def test_section_6_case_and_harvesters(tmp_path):
    deck = tmp_path / "model.template"
    deck.write_text("POWER = #POWER#\nFLOW = #FLOW#\n")

    case = Case(name="thermal_case", output_files={})
    case.database = Database(data={"POWER": [10.0, 20.0], "FLOW": [1000.0, 1500.0]})
    case.FlagsMap = {"#POWER#": "POWER", "#FLOW#": "FLOW"}
    case.add_file(File(file_path=str(deck)))
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.exe_cmd = ["python", "-c", "print('Executed')"]
    case.timeout = 120.0
    case.capture_output = True
    case.launch()

    # Harvesters
    outp = tmp_path / "outp"
    outp.write_text("final keff estimate = 1.0023\n")
    regex_harvester = RegexHarvester(
        name="keff",
        file_target=str(outp),
        pattern=r"final keff estimate\s+=\s+([0-9\.]+)",
        transform=float
    )
    assert regex_harvester.harvest() == 1.0023

    res_csv = tmp_path / "results.csv"
    res_csv.write_text("Max_Clad_Temp,Pressure\n580.5,15.5\n")
    csv_harvester = CsvHarvester(
        name="clad_temp",
        file_target=str(res_csv),
        column="Max_Clad_Temp",
        transform=lambda col: float(col[0])
    )
    assert csv_harvester.harvest() == 580.5

    sum_json = tmp_path / "summary.json"
    sum_json.write_text('{"results": {"peak_flux": 2.5e14}}')
    json_harvester = JsonHarvester(
        name="peak_flux",
        file_target=str(sum_json),
        key="results.peak_flux"
    )
    assert json_harvester.harvest() == 2.5e14

    sum_txt = tmp_path / "summary.txt"
    sum_txt.write_text("mdnbr=1.85\n")
    callable_harvester = CallableHarvester(
        name="mdnbr",
        file_target=str(sum_txt),
        extractor=lambda path: float(path.read_text().split("=")[1])
    )
    assert callable_harvester.harvest() == 1.85


def test_section_7_campaign_status(tmp_path):
    deck = tmp_path / "deck.template"
    deck.write_text("RHO = #RHO#\nWF = #WF#\n")

    manifest = CampaignManifest(
        name="su_study",
        parameters={
            "RHO": [18.5, 19.0, 19.5],
            "WF": [0.01, 0.02, 0.03],
        },
        templates=[str(deck)],
        commands=["python -c 'print(\"Simulation completed.\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )
    campaign = Campaign(manifest)
    results = campaign.run()
    assert len(results) == 3

    status_summary = campaign.status()
    assert status_summary.get("success") == 3


def test_section_8_coupler():
    mcnp = Case(name="mcnp", output_files={})
    mcnp.database = Database(data={"RHO": [1.0]})

    relap = Case(name="relap", output_files={})
    relap.database = Database(data={"POWER": [20.0], "FLOW": [1200.0]})

    coupler = Coupler(name="neutronics_th_loop")
    coupler.database = Database(data={"RHO": [1.0], "POWER": [20.0], "FLOW": [1200.0]})
    coupler.add_case(mcnp, attributes=["RHO"])
    coupler.add_case(relap, attributes=["POWER", "FLOW"])

    coupler.set_under_relaxation("POWER", factor=0.5)
    relaxed = coupler.relax("POWER", 22.5, old_value=20.0)
    assert relaxed == 21.25

    coupler.set_divergence_threshold("POWER", max_allowed=50.0)
    coupler.add_divergence_detector(lambda c: c.get_under_relaxation("POWER") <= 0)

    result = coupler.run_to_convergence(
        max_exec=20,
        check_fn=lambda c: True,
        error_on_max_exec=True
    )
    assert result.converged is True


def test_section_9_publisher_and_live_plot(tmp_path):
    events_file = tmp_path / "campaign_events.jsonl"
    jsonl_pub = JsonlEventPublisher(str(events_file), max_buffer_size=1000)
    ws_pub = WebSocketEventPublisher(
        "ws://localhost:8000/events",
        reconnect_interval_seconds=2.0,
        timeout=2.0,
        enabled=False
    )
    redis_pub = RedisStreamEventPublisher(
        stream_key="labeeb:events",
        url="redis://localhost:6379/0",
        maxlen=10000,
        socket_timeout=1.0,
        enabled=False
    )
    pub = CompositeEventPublisher([jsonl_pub, ws_pub, redis_pub], redact_keys=["password"])

    pub.publish({"event_type": "metric", "temperature": 340.5, "password": "secret_value"})
    buffered = pub.get_buffered_events()
    assert len(buffered) > 0
    assert buffered[0]["password"] == "[REDACTED]"

    replayed = []
    pub.replay(lambda evt: replayed.append(evt))
    assert len(replayed) == 1

    # LivePlot context
    plot_out = tmp_path / "progress.png"
    with LivePlot(metrics=["RHO", "WF"], output_path=str(plot_out)) as lp:
        lp.observe({"RHO": 19.2, "WF": 0.02})

    pub.flush()
    pub.close()


def test_section_10_analysis_bundle(tmp_path):
    deck = tmp_path / "deck.template"
    deck.write_text("PARAM = #PARAM#\n")

    manifest = CampaignManifest(
        name="bundle_campaign",
        parameters={"PARAM": [1, 2]},
        templates=[str(deck)],
        commands=["python -c 'print(\"done\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )
    campaign = Campaign(manifest)
    results = campaign.run()

    summary_file = tmp_path / "summary.csv"
    summary_file.write_text("col1,col2\n10,20\n")

    bundle = AnalysisBundle.from_campaign(
        campaign=campaign,
        results=results,
        artifacts={"summary": str(summary_file)},
        redact_keys=["api_token", "secret"]
    )

    json_path = tmp_path / "bundle.json"
    zip_path = tmp_path / "bundle.zip"
    bundle.to_json(str(json_path))
    bundle.to_zip(str(zip_path))
    assert json_path.exists()
    assert zip_path.exists()

    loaded = AnalysisBundle.load(str(zip_path))
    assert loaded.manifest["name"] == "bundle_campaign"
    assert len(loaded.results) == 2

    restored_mem = CampaignMemory()
    loaded.replay_memory(restored_mem)
    assert len(restored_mem.get_all_cases()) == 2


def test_section_11_shared_memory():
    memory = CampaignMemory(backend=InMemorySharedBackend())
    received = []
    memory.add_listener(lambda case_id, data: received.append(data.get("status")))

    memory.record_case(0, {"TEMP": 320.0, "PRESSURE": 2.1, "status": "SUCCESS"})
    memory.record_case(1, {"TEMP": 340.0, "PRESSURE": 2.2, "status": "SUCCESS"})

    assert received == ["SUCCESS", "SUCCESS"]
    df = memory.to_dataframe()
    assert len(df) == 2

    stats = memory.online_summary(metrics=["TEMP", "PRESSURE"])
    assert stats["TEMP"]["mean"] == 330.0


def test_section_12_analysis():
    correlations = correlation_analysis(
        inputs={"RHO": [18.0, 19.0, 20.0], "TEMP": [300.0, 320.0, 340.0]},
        output=[1.002, 1.015, 1.028]
    )
    assert "pearson" in correlations.columns

    n_samples = wilks_sample_size(coverage=0.95, confidence=0.95, sides=1)
    assert n_samples == 59


def test_section_13_case_study():
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        deck = root / "simulation.template"
        deck.write_text("FUEL_DENSITY = #RHO#\nENRICHMENT = #WF#\n")

        samples = latin_hypercube_sample([(18.5, 19.5), (0.015, 0.025)], size=10, seed=123)
        rhos = [float(s[0]) for s in samples]
        wfs = [float(s[1]) for s in samples]

        manifest = CampaignManifest(
            name="jrtr_fuel_uncertainty",
            parameters={"RHO": rhos, "WF": wfs},
            templates=[str(deck)],
            commands=["python -c 'print(\"Simulation completed.\")'"],
            execution={"main_dir": str(root), "run_dir": "runs"}
        )

        event_path = root / "events.jsonl"
        publisher = JsonlEventPublisher(event_path)
        memory = CampaignMemory()

        campaign = Campaign(manifest, memory=memory, publisher=publisher)
        results = campaign.run()
        publisher.flush()

        assert len(results) == 10
        summary = memory.online_summary(metrics=["RHO", "WF"])
        assert "RHO" in summary
        assert "WF" in summary

        bundle_path = root / "jrtr_fuel_uncertainty.zip"
        bundle = campaign.export_bundle(bundle_path, results=results)
        assert bundle_path.exists()
        assert bundle.manifest["name"] == "jrtr_fuel_uncertainty"

        dummy_keff = [1.0 + 0.01 * r - 0.05 * w for r, w in zip(rhos, wfs)]
        corr = correlation_analysis(inputs={"RHO": rhos, "WF": wfs}, output=dummy_keff)
        assert len(corr) == 2
        publisher.close()

import csv
import os
import sys
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

    db.add_derived_attribute(
        "CUMULATIVE_ENERGY",
        lambda database, index: sum(database["POWER"][: index + 1]),
        context="database",
        unit="MWh",
    )
    db.add_derived_attribute(
        "GLOBAL_MEAN_POWER",
        lambda database: sum(database["POWER"]) / len(database["POWER"]),
        context="database",
        vectorized=True,
        unit="MW",
    )
    assert list(db["CUMULATIVE_ENERGY"]) == [10.0, 25.0, 45.0]

    db.update_row(row_id=1, data={"POWER": 16.5})
    assert db["POWER_KW"][1] == 16500.0
    assert db["SPECIFIC_FLOW"][1] == pytest.approx(1350.0 / 16.5)
    assert list(db["CUMULATIVE_ENERGY"]) == [10.0, 26.5, 46.5]
    assert db["GLOBAL_MEAN_POWER"][0] == pytest.approx((10.0 + 16.5 + 20.0) / 3.0)

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


def test_section_6_post_output_feedback_adaptive_loop(tmp_path):
    deck_template = tmp_path / "model.template"
    deck_template.write_text("POWER = #POWER#\n", encoding="utf-8")

    case = Case(name="adaptive_sim", output_files={"data.csv": ["peak_temp"]})
    case.database = Database(data={"POWER": [100.0, 100.0, 100.0]})
    case.FlagsMap = {"#POWER#": "POWER"}
    case.add_file(File(file_path=str(deck_template)))
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = ["echo peak_temp > data.csv", "echo 600.0 >> data.csv"]

    def adaptive_feedback_hook(outputs, case_obj):
        peak_temp = outputs["peak_temp"][-1][0] if isinstance(outputs["peak_temp"][-1], list) else outputs["peak_temp"][-1]
        next_idx = case_obj.case_id + 1
        if next_idx < len(case_obj.database):
            if peak_temp > 500.0:
                current_power = case_obj.database["POWER"][next_idx]
                case_obj.database.set_row(next_idx, {"POWER": current_power * 0.9})
        return {"is_overheating": float(peak_temp > 500.0)}

    case.add_post_output_hook("adaptive_feedback", adaptive_feedback_hook)
    case.launch(parallel=False)

    assert case.outputs["is_overheating"] == [1.0, 1.0, 1.0]
    assert list(case.database["POWER"]) == [100.0, 90.0, 90.0]


def test_section_6_failure_handling_policies(tmp_path):
    # 1. Case with command_failure_policy="retry" and max_attempts=3
    case_retry = Case(name="retry_case", output_files={})
    case_retry.command_failure_policy = "retry"
    case_retry.max_attempts = 3
    assert case_retry.command_failure_policy == "retry"
    assert case_retry.max_attempts == 3

    # 2. Sequential campaign with continue policies & OutputCatalog
    deck = tmp_path / "deck.template"
    deck.write_text("RHO = #RHO#\n", encoding="utf-8")

    fail_cmd = (
        f"{sys.executable} -c \"import pathlib, sys; "
        f"sys.exit(1 if '19.0' in pathlib.Path('deck.template').read_text() else 0)\""
    )

    manifest = CampaignManifest.from_dict({
        "name": "seq_failure_sweep",
        "parameters": {"RHO": [18.5, 19.0, 19.5]},
        "templates": [str(deck)],
        "commands": [fail_cmd],
        "execution": {
            "main_dir": str(tmp_path),
            "run_dir": "runs_seq",
            "command_failure_policy": "continue",
            "harvest_failure_policy": "continue",
            "output_catalog": str(tmp_path / "catalog_seq.sqlite"),
        }
    })

    campaign = Campaign(manifest, state_path=str(tmp_path / "state_seq.sqlite"))
    results = campaign.run()

    assert len(results) == 3
    assert results[0].status == "SUCCESS"
    assert results[1].status == "FAILED"
    assert results[2].status == "SUCCESS"

    # 3. Parallel campaign with continue policies
    manifest_parallel = CampaignManifest.from_dict({
        "name": "parallel_failure_sweep",
        "parameters": {"RHO": [18.0, 18.5, 19.0, 19.5]},
        "templates": [str(deck)],
        "commands": [fail_cmd],
        "execution": {
            "main_dir": str(tmp_path),
            "run_dir": "runs_parallel",
            "parallel": True,
            "n_workers": 2,
            "command_failure_policy": "continue",
            "harvest_failure_policy": "continue",
        }
    })

    campaign_parallel = Campaign(manifest_parallel)
    results_par = campaign_parallel.run()

    assert len(results_par) == 4
    successes = [r for r in results_par if r.status == "SUCCESS"]
    failures = [r for r in results_par if r.status == "FAILED"]
    assert len(successes) == 3
    assert len(failures) == 1


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
        work_root = Path(workspace)

        # 1. Parameter Generation & Database Setup
        bounds = [(0.190, 0.205), (1100.0, 1300.0), (10.0, 15.0)]
        samples = latin_hypercube_sample(bounds, size=6, seed=42)
        enrich_vals = [round(float(s[0]), 5) for s in samples]
        flow_vals = [round(float(s[1]), 2) for s in samples]
        power_vals = [round(float(s[2]), 2) for s in samples]

        db = Database(name="reactor_parameters")
        db.add_attribute(
            Attribute("ENRICH", data=enrich_vals, unit="fraction"),
            Attribute("FLOW", data=flow_vals, unit="kg/s"),
            Attribute("POWER", data=power_vals, unit="MWth"),
        )
        db.add_derived_attribute("POWER_KW", "POWER * 1000.0", unit="kW")
        db.add_derived_attribute(
            "SPECIFIC_FLOW",
            lambda row: row["FLOW"] / max(row["POWER"], 1e-3),
            dependencies=["FLOW", "POWER"],
            unit="kg/(s*MW)",
        )

        # 2. Template Deck Setup
        template_file = work_root / "reactor.template"
        template_file.write_text(
            "TITLE JRTR Core Sensitivity Model\n"
            "PARAM ENRICHMENT = #ENRICH#\n"
            "PARAM FLOW_RATE = #FLOW#\n"
            "PARAM POWER_MW = #POWER#\n"
            "PARAM POWER_WATTS = ${POWER * 1e6 : {:.2e}}\n"
        )

        # 3. Deterministic Local Physics Stub
        stub_file = work_root / "physics_stub.py"
        stub_file.write_text(
            "import re, sys, pathlib\n"
            "content = pathlib.Path('reactor.template').read_text()\n"
            "enrich = float(re.search(r'ENRICHMENT = ([0-9.e+-]+)', content).group(1))\n"
            "flow = float(re.search(r'FLOW_RATE = ([0-9.e+-]+)', content).group(1))\n"
            "power = float(re.search(r'POWER_MW = ([0-9.e+-]+)', content).group(1))\n"
            "keff = 1.0000 + 1.25 * (enrich - 0.1975) - 0.00005 * (flow - 1200.0)\n"
            "peak_temp = 293.15 + (power * 1e6) / (flow * 4184.0) * 15.0\n"
            "with open('physics.log', 'w') as f:\n"
            "    f.write(f'JRTR Simulation Converged: final keff = {keff:.5f}\\n')\n"
            "    f.write(f'Maximum Fuel Temperature: {peak_temp:.2f} K\\n')\n"
        )
        stub_cmd = f"{sys.executable} {stub_file.resolve()}"

        # 4. Campaign Orchestration with Event Publishing and Shared Memory
        manifest = CampaignManifest(
            name="jrtr_reactor_case_study",
            parameters={
                "ENRICH": db["ENRICH"].tolist(),
                "FLOW": db["FLOW"].tolist(),
                "POWER": db["POWER"].tolist(),
            },
            templates=[str(template_file)],
            commands=[stub_cmd],
            execution={"main_dir": str(work_root), "run_dir": "runs", "capture_output": True},
        )

        events_log = work_root / "campaign_events.jsonl"
        publisher = JsonlEventPublisher(events_log)
        memory = CampaignMemory()
        campaign = Campaign(manifest, memory=memory, publisher=publisher)

        # 5. Execute Simulation Campaign
        results = campaign.run()
        publisher.flush()

        # 6. Output Harvesting Verification
        harvested_keffs = []
        for r in [res for res in results if res.status == "SUCCESS"]:
            case_dir = work_root / "runs" / f"case_{r.case_id}"
            harvester = RegexHarvester(
                name="keff",
                file_target=str(case_dir / "physics.log"),
                pattern=r"final keff = ([0-9\.]+)",
                transform=float,
            )
            val = harvester.harvest(str(case_dir))
            harvested_keffs.append(val)
            r.metrics["keff"] = val

        assert len(harvested_keffs) == 6

        # 7. Post-Run Sensitivity Analysis & Bundle Export
        correlations = correlation_analysis(
            inputs={
                "ENRICH": [r.parameters["ENRICH"] for r in results if r.status == "SUCCESS"],
                "FLOW": [r.parameters["FLOW"] for r in results if r.status == "SUCCESS"],
                "POWER": [r.parameters["POWER"] for r in results if r.status == "SUCCESS"],
            },
            output=harvested_keffs,
        )
        assert len(correlations) == 3

        bundle_path = work_root / "jrtr_reactor_case_study.zip"
        bundle = campaign.export_bundle(bundle_path, results=results)
        assert bundle_path.exists()
        assert bundle.manifest["name"] == "jrtr_reactor_case_study"
        publisher.close()


def test_section_7b_campaign_native_live_plot_example_runs_verbatim():
    """Execute the USER_MANUAL 'Campaign-Native Live Plotting' example code
    verbatim so the documented snippet is guaranteed runnable."""
    manual = Path(__file__).resolve().parent.parent / "docs" / "USER_MANUAL.md"
    text = manual.read_text(encoding="utf-8")

    marker = "### Campaign-Native Live Plotting (opt-in)"
    start = text.index(marker)
    fence = text.index("```python", start) + len("```python")
    end = text.index("```", fence)
    example = text[fence:end].strip()

    # The example is self-contained (imports + TemporaryDirectory); run it
    # verbatim inside the labeeb package context.
    namespace = {"__name__": "__test_manual_example__"}
    exec(compile(example, "<USER_MANUAL campaign live-plot example>", "exec"), namespace)


def test_section_14_optimization_runs_verbatim():
    """Execute the USER_MANUAL section-14 optimizer code block verbatim so the
    documented optimization/resume example cannot drift from reality."""
    manual = Path(__file__).resolve().parent.parent / "docs" / "USER_MANUAL.md"
    text = manual.read_text(encoding="utf-8")

    start = text.index("## 14. Simulation-Based Optimization")
    end = text.index("## 15. Exception Hierarchy")
    section = text[start:end]
    fence = section.index("```python") + len("```python")
    close = section.index("```", fence)
    example = section[fence:close].strip()

    namespace = {"__name__": "__test_manual_optimizer_example__"}
    exec(compile(example, "<USER_MANUAL section 14 optimizer example>", "exec"), namespace)

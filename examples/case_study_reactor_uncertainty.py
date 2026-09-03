"""
API-First Reactor Uncertainty & Sensitivity Case Study
=====================================================

This executable case study demonstrates an end-to-end simulation campaign using
Labeeb's Python API without relying on external simulation solvers or CLI commands.

Highlights:
1. Declarative parameter database with derived attributes.
2. Dual templating with flag replacement and inline mathematical expressions.
3. Subprocess execution against a deterministic local physics stub.
4. Declarative output harvesting (CSV tables and Regex log extraction).
5. Robust failure handling and error visibility.
6. Shared-memory recording and online statistical summarization.
7. Post-run sensitivity correlation analysis and reproducible bundle export.
"""

import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from labeeb.analysis import correlation_analysis
from labeeb.bundle import export_analysis_bundle
from labeeb.campaign import Campaign, CampaignManifest
from labeeb.database import Attribute, Database
from labeeb.extractors import RegexHarvester
from labeeb.publisher import JsonlEventPublisher
from labeeb.results import CaseResult, export_case_results
from labeeb.sampler import latin_hypercube_sample
from labeeb.shared_memory import CampaignMemory


def create_reactor_template(template_path: Path) -> Path:
    """Create a parameterized reactor input deck template."""
    content = (
        "TITLE Generic Core Sensitivity Model\n"
        "PARAM ENRICHMENT = #ENRICH#\n"
        "PARAM FLOW_RATE = #FLOW#\n"
        "PARAM POWER_MW = #POWER#\n"
        "PARAM POWER_WATTS = ${POWER * 1e6 : {:.2e}}\n"
        "CONTROL TARGET_KEFF = 1.00000\n"
    )
    template_path.write_text(content, encoding="utf-8")
    return template_path


def create_physics_stub(stub_path: Path) -> Path:
    """Create a deterministic local physics solver stub."""
    script = (
        "import math\n"
        "import pathlib\n"
        "import re\n"
        "import sys\n\n"
        "deck_path = pathlib.Path('reactor.template')\n"
        "if not deck_path.exists():\n"
        "    sys.stderr.write('Physics Error: Missing input deck.\\n')\n"
        "    sys.exit(1)\n\n"
        "content = deck_path.read_text(encoding='utf-8')\n"
        "m_enrich = re.search(r'ENRICHMENT = ([0-9.e+-]+)', content)\n"
        "m_flow = re.search(r'FLOW_RATE = ([0-9.e+-]+)', content)\n"
        "m_power = re.search(r'POWER_MW = ([0-9.e+-]+)', content)\n\n"
        "if not (m_enrich and m_flow and m_power):\n"
        "    sys.stderr.write('Physics Error: Failed to parse input parameters.\\n')\n"
        "    sys.exit(1)\n\n"
        "enrich = float(m_enrich.group(1))\n"
        "flow = float(m_flow.group(1))\n"
        "power = float(m_power.group(1))\n\n"
        "if enrich <= 0.0 or flow <= 0.0 or power > 100.0:\n"
        "    sys.stderr.write('Physics Error: Non-physical parameters detected.\\n')\n"
        "    sys.exit(2)\n\n"
        "keff = 1.0000 + 1.25 * (enrich - 0.1975) - 0.00005 * (flow - 1200.0)\n"
        "peak_temp = 293.15 + (power * 1e6) / (flow * 4184.0) * 15.0\n"
        "peak_flux = 1.5e14 * (power / 10.0)\n\n"
        "with open('results.csv', 'w', encoding='utf-8') as f:\n"
        "    f.write('keff,peak_temp,peak_flux\\n')\n"
        "    f.write(f'{keff:.5f},{peak_temp:.2f},{peak_flux:.4e}\\n')\n\n"
        "with open('physics.log', 'w', encoding='utf-8') as f:\n"
        "    f.write(f'Simulation Converged: final keff = {keff:.5f}\\n')\n"
        "    f.write(f'Maximum Fuel Temperature: {peak_temp:.2f} K\\n')\n"
    )
    stub_path.write_text(script, encoding="utf-8")
    return stub_path


def run_reactor_case_study(
    workspace_dir: Optional[Union[str, Path]] = None,
    n_samples: int = 8,
    include_failure_test: bool = True,
) -> Dict[str, Any]:
    """Execute the complete reactor uncertainty and sensitivity case study.

    Args:
        workspace_dir: Optional directory to store simulation runs and artifacts.
            If None, a temporary directory is created and cleaned up.
        n_samples: Number of sample cases to generate.
        include_failure_test: Whether to append an intentional failure row to verify
            failure recording and error isolation.

    Returns:
        Dictionary containing campaign results, sensitivity correlations,
        memory summary, and artifact paths.
    """
    temp_dir_obj = None
    if workspace_dir is None:
        temp_dir_obj = tempfile.TemporaryDirectory()
        work_root = Path(temp_dir_obj.name)
    else:
        work_root = Path(workspace_dir)
        work_root.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Parameter Generation & Database Setup
        bounds = [
            (0.190, 0.205),   # ENRICH: 19.0% to 20.5% U-235
            (1100.0, 1300.0), # FLOW: 1100 to 1300 kg/s
            (10.0, 15.0),     # POWER: 10 to 15 MWth
        ]
        samples = latin_hypercube_sample(bounds, size=n_samples, seed=42)
        enrich_vals = [round(float(s[0]), 5) for s in samples]
        flow_vals = [round(float(s[1]), 2) for s in samples]
        power_vals = [round(float(s[2]), 2) for s in samples]

        if include_failure_test:
            # Append an out-of-bounds parameter row that triggers stub solver failure
            enrich_vals.append(-1.0)
            flow_vals.append(0.0)
            power_vals.append(999.0)

        db = Database(name="reactor_parameters")
        db.add_attribute(
            Attribute("ENRICH", data=enrich_vals, unit="fraction"),
            Attribute("FLOW", data=flow_vals, unit="kg/s"),
            Attribute("POWER", data=power_vals, unit="MWth"),
        )

        # Declarative derived attributes (demonstrating topological recomputation)
        db.add_derived_attribute(
            "POWER_KW",
            "POWER * 1000.0",
            unit="kW",
            description="Total core power in kilowatts",
        )
        db.add_derived_attribute(
            "SPECIFIC_FLOW",
            lambda row: row["FLOW"] / max(row["POWER"], 1e-3),
            dependencies=["FLOW", "POWER"],
            unit="kg/(s*MW)",
        )

        # 2. Template Deck & Solver Setup
        template_file = work_root / "reactor.template"
        create_reactor_template(template_file)

        stub_file = work_root / "physics_stub.py"
        create_physics_stub(stub_file)
        stub_cmd = f"{sys.executable} {stub_file.resolve()}"

        # 3. Campaign Orchestration with Event Publishing and Shared Memory
        manifest = CampaignManifest(
            name="reactor_case_study",
            parameters={
                "ENRICH": db["ENRICH"].tolist(),
                "FLOW": db["FLOW"].tolist(),
                "POWER": db["POWER"].tolist(),
            },
            templates=[str(template_file)],
            commands=[stub_cmd],
            execution={
                "main_dir": str(work_root),
                "run_dir": "runs",
                "capture_output": True,
                "timeout": 30.0,
            },
        )

        events_log = work_root / "campaign_events.jsonl"
        publisher = JsonlEventPublisher(events_log)
        memory = CampaignMemory()

        campaign = Campaign(manifest, memory=memory, publisher=publisher)

        # 4. Execute Simulation Campaign
        results: List[CaseResult] = campaign.run()
        publisher.flush()

        successful_cases = [r for r in results if r.status == "SUCCESS"]
        failed_cases = [r for r in results if r.status != "SUCCESS"]

        # 5. Output Harvesting Verification
        harvested_keffs: List[float] = []
        for r in successful_cases:
            case_dir = work_root / "runs" / f"case_{r.case_id}"
            log_target = case_dir / "physics.log"
            harvester = RegexHarvester(
                name="keff",
                file_target=str(log_target),
                pattern=r"final keff = ([0-9\.]+)",
                transform=float,
            )
            val = harvester.harvest(str(case_dir))
            harvested_keffs.append(val)
            r.metrics["keff"] = val

        # 6. Shared Memory Online Summary
        memory_summary = memory.online_summary(metrics=["ENRICH", "FLOW", "POWER"])

        # 7. Sensitivity Correlation Analysis
        if len(successful_cases) >= 3:
            enrich_success = [r.parameters["ENRICH"] for r in successful_cases]
            flow_success = [r.parameters["FLOW"] for r in successful_cases]
            power_success = [r.parameters["POWER"] for r in successful_cases]
            correlations = correlation_analysis(
                inputs={
                    "ENRICH": enrich_success,
                    "FLOW": flow_success,
                    "POWER": power_success,
                },
                output=harvested_keffs,
            )
        else:
            correlations = {}

        # 8. Results Export & Analysis Bundle
        csv_export = work_root / "campaign_results.csv"
        export_case_results(results, csv_export)

        bundle_path = work_root / "reactor_case_study.zip"
        bundle = campaign.export_bundle(
            bundle_path,
            results=results,
            artifacts={"results_csv": csv_export, "events_log": events_log},
        )

        return {
            "total_cases": len(results),
            "successful_cases": len(successful_cases),
            "failed_cases": len(failed_cases),
            "results": results,
            "harvested_keffs": harvested_keffs,
            "correlations": correlations,
            "memory_summary": memory_summary,
            "bundle_path": str(bundle_path),
            "events_log": str(events_log),
        }
    finally:
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()


if __name__ == "__main__":
    output_dir = Path.cwd() / "case_study_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = run_reactor_case_study(workspace_dir=output_dir, n_samples=6, include_failure_test=True)
    print(f"Case Study Completed Successfully:")
    print(f"  - Total Cases Executed: {summary['total_cases']}")
    print(f"  - Successes: {summary['successful_cases']}")
    print(f"  - Expected Failure Captured: {summary['failed_cases']}")
    print(f"  - Sensitivity Correlations: {summary['correlations']}")
    print(f"  - Bundle Exported: {summary['bundle_path']}")

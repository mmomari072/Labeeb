# Labeeb (لبيب) v1.6.0 User Manual & API Guide

> **Sensitivity & Uncertainty Analysis, Simulation Coupling, and Online State Analysis API**  
> **Author**: Eng. Mohammad Omari  
> **Institution**: Jordan Research and Training Reactor (JRTR)  
> **Version**: 1.6.0  

---

## 1. Introduction & Design Philosophy

**Labeeb** is an API-first Python framework engineered for nuclear engineering, thermal-hydraulics, and general scientific computing workflows. It orchestrates the full lifecycle of numerical simulation experiments:

1. **Deterministic & Stochastic Sampling**: Generate parameter matrices via grid sweeps, Latin Hypercube Sampling (LHS), Halton low-discrepancy sequences, and probability mass functions.
2. **Template Processing**: Inject sampled parameters into text-based input decks via delimited token replacement (`FlagsMap`) or dynamic Jinja2 templates (`File.render_jinja()`).
3. **Execution & Declarative Harvesters**: Launch simulation executables in isolated directories with automatic timeout enforcement, execution event recording, and typed output harvesting (CSV, JSON, Regex, Callable).
4. **Stateful Campaigns & Reproducibility**: Execute campaigns from validated Python objects or YAML/JSON manifests with input hashing, automatic resume/retry caching, and status tracking.
5. **Coupling Kernel & Stability Controls**: Coordinate multi-code iterative feedback loops (e.g. neutronics $\leftrightarrow$ thermal-hydraulics) with typed under-relaxation, divergence detection, and iteration failure controls.
6. **Non-Blocking Shared Campaign Memory**: Stream live simulation results to in-memory shared state for real-time online analysis and statistical summaries.

---

## 2. Installation & Quickstart

Install Labeeb with all optional components (Jinja2 templating, plotting, and dev tools):

```bash
# Editable installation with dev tools
pip install -e .[dev]

# Or with uv:
uv pip install -e .[dev]
```

Verify the installation:
```python
import labeeb
print(labeeb.__version__)  # Output: 1.6.0
```

---

## 3. Data Representation: `Attribute` & `Database`

### `Attribute`
An `Attribute` represents a typed 1D column sequence with optional physical units and vectorized mathematical operations.

```python
from labeeb.database import Attribute

# Instantiate columns with unit metadata
density = Attribute(name="RHO", data=[18.5, 19.0, 19.5], unit="g/cm3")
enrichment = Attribute(name="WF", data=[0.1975, 0.1975, 0.1975], unit="wt_frac")

# Vectorized arithmetic returns a new Attribute instance preserving properties
scaled_density = density * 1000.0   # Attribute([18500.0, 19000.0, 19500.0])
offset = density + 0.1

# Rich comparisons return a new boolean Attribute instance
high_density = density > 19.0        # Attribute([False, False, True])
```

### `Database`
A `Database` manages an aligned collection of `Attribute` instances with tabular import/export capabilities.

```python
from labeeb.database import Attribute, Database

db = Database(name="core_sampling")
db.add_attribute(
    Attribute(name="POWER", data=[10.0, 15.0, 20.0], unit="MW"),
    Attribute(name="FLOW", data=[1200.0, 1350.0, 1500.0], unit="m3/h"),
)

# Access rows as standard dictionaries
row_0 = db.get_row(0)  # {"POWER": 10.0, "FLOW": 1200.0}

# Update rows in-place
db.update_row(row_id=1, data={"POWER": 16.5})

# Export tabular data (.csv, .xlsx, .parquet, .json)
db.export_to_file("core_sampling.csv")

# Import data into a fresh Database instance
db_new = Database(name="imported")
db_new.import_from_file("core_sampling.csv")
```

---

## 4. Parameter Sampling & Design Matrices

### Full Factorial & One-At-A-Time Sweeps (`FOATConstructor`)
Construct Cartesian product grids across parameter ranges:

```python
from labeeb.sampler import FOATConstructor
from labeeb.database import Database

sweeper = FOATConstructor()
sweeper.add_case({
    "INLET_TEMP": [25.0, 30.0, 35.0],
    "CORE_FLOW": [1200.0, 1400.0],
})

# Returns a dictionary containing mapped parameter value lists and indices
grid_dict = sweeper.construct()
# Wrap directly into a Database
grid_db = Database(data=grid_dict)
print(f"Generated {len(grid_db)} parameter rows.")  # 6 rows
```

### Advanced Sampling: Latin Hypercube & Halton Sequences
Generate space-filling low-discrepancy sequences for uncertainty quantification using the `size` parameter:

```python
from labeeb import halton_sample, latin_hypercube_sample

# Latin Hypercube Sampling with bounding intervals
bounds = [(18.0, 20.0), (0.01, 0.05)]  # (RHO range, WF range)
lhs_samples = latin_hypercube_sample(bounds, size=100, seed=42)

# Multi-dimensional Halton sequence
halton_points = halton_sample(size=100, dimensions=3)
```

---

## 5. Text Templating & Input Decks

Labeeb supports delimited placeholder substitution via `Flag` / `FlagsMap` and dynamic Jinja2 templating.

### Token Replacement (`FlagsMap`)
```python
from labeeb.case import Flag, FlagsMap

# Associate token with database column and formatting
flags = FlagsMap()
flags.add_flag(Flag(name="#RHO#", attribute_name="RHO", fmt="%6.2f"))
flags.add_flag(Flag(name="#WF#", attribute_name="WF", fmt="%8.4f"))
```

### Jinja2 Templating
For dynamic loops, conditionals, and expressions, pass context dictionaries to `render_jinja`:
```python
from labeeb.utils.file_io import File

template = File("relap_deck.jinja2")
template.render_jinja({
    "power": 20.0,
    "channels": [{"id": 1, "flow": 500.0}, {"id": 2, "flow": 600.0}]
})
```

---

## 6. Simulation Execution & Declarative Output Harvesters

### `Case` Runner
The `Case` runner orchestrates filesystem layout, template injection, process execution, and log capture.

```python
from labeeb.case import Case
from labeeb.database import Database
from labeeb.utils.file_io import File

case = Case(name="thermal_case", output_files={})
case.database = Database(data={"POWER": [10.0, 20.0], "FLOW": [1000.0, 1500.0]})
case.FlagsMap = {"#POWER#": "POWER", "#FLOW#": "FLOW"}
case.add_file(File(file_path="model.template"))

case.exe_cmd = ["python", "-c", "print('Executed')"]
case.timeout = 120.0  # Execution timeout in seconds
case.capture_output = True

# Launch all parameter rows
case.launch()
```

### Declarative Output Harvesters (`labeeb.extractors`)
Extract typed scalar and vector responses from simulation outputs:

```python
from pathlib import Path
from labeeb.extractors import (
    CsvHarvester,
    JsonHarvester,
    RegexHarvester,
    CallableHarvester,
)

# Extract keff and std dev via Regex
regex_harvester = RegexHarvester(
    name="keff",
    file_target="outp",
    pattern=r"final keff estimate\s+=\s+([0-9\.]+)",
    transform=float
)

# Extract specific column from CSV output
csv_harvester = CsvHarvester(
    name="clad_temp",
    file_target="results.csv",
    column="Max_Clad_Temp",
    transform=float
)

# Extract dotted path from JSON output
json_harvester = JsonHarvester(
    name="peak_flux",
    file_target="summary.json",
    key="results.peak_flux"
)

# Custom programmatic harvester receiving target Path
callable_harvester = CallableHarvester(
    name="mdnbr",
    file_target="summary.txt",
    extractor=lambda path: float(path.read_text().split("=")[1])
)
```

---

## 7. Stateful Campaigns & Status Registry

### `CampaignManifest`
Define execution-agnostic, reproducible study manifests in Python, JSON, or YAML:

```python
from labeeb.campaign import CampaignManifest, Campaign

manifest = CampaignManifest(
    name="su_study",
    parameters={
        "RHO": [18.5, 19.0, 19.5],
        "WF": [0.01, 0.02, 0.03],
    },
    templates=["deck.template"],
    commands=["python -c 'print(\"done\")'"],
    execution={
        "main_dir": "./study_workspace",
        "run_dir": "runs",
        "timeout": 300,
        "events_file": "events.jsonl",
    }
)
```

### Running with Automatic Resume & Status Registry
```python
# Initialize campaign with SQLite state store for safe resume/retry
campaign = Campaign(manifest, state_path="campaign_state.sqlite")

# Run campaign (automatically reuses valid cached runs if input hash matches)
results = campaign.run(resume=True, max_retries=2)

# Inspect execution status counts (returns lowercase keys)
print(campaign.status())  # {'success': 3}

# Export structured status registry
campaign.export_status("execution_summary.csv")
```

---

## 8. Multi-Physics Coupling & Stability Controls (`labeeb.coupler`)

`Coupler` coordinates iterative workflows between multiple simulation codes (e.g. Neutronics $\leftrightarrow$ Thermal-Hydraulics) with stability controls.

```python
from labeeb.coupler import Coupler
from labeeb.case import Case
from labeeb.database import Database

mcnp = Case(name="mcnp", output_files={})
mcnp.database = Database(data={"RHO": [1.0]})

relap = Case(name="relap", output_files={})
relap.database = Database(data={"POWER": [20.0], "FLOW": [1200.0]})

coupler = Coupler(name="coupled_feedback")
coupler.database = Database(data={"RHO": [1.0], "POWER": [20.0], "FLOW": [1200.0]})
coupler.add_case(mcnp, attributes=["RHO"])
coupler.add_case(relap, attributes=["POWER", "FLOW"])

# 1. Typed Under-Relaxation (prevents spatial power oscillations)
coupler.set_under_relaxation("POWER", factor=0.5)

# In coupling callback:
def feedback_step(unit, **kwargs):
    # Retrieve raw computed power
    raw_power = 22.5
    # Relax against prior iteration: relaxed = 0.5 * 22.5 + 0.5 * old_power
    relaxed_power = unit.relax("POWER", raw_power)

coupler.add_coupling_functions(feedback_step)

# 2. Divergence Detection
coupler.set_divergence_threshold("POWER", max_allowed=50.0)
coupler.add_divergence_detector(lambda c: c.get_under_relaxation("POWER") <= 0)

# 3. Max-Iteration Enforcement
result = coupler.run_to_convergence(
    max_exec=20,
    check_fn=lambda c: True,
    error_on_max_exec=True  # Raises CouplingError if not converged within max_exec
)
```

---

## 9. Non-Blocking Shared Campaign Memory (`labeeb.shared_memory`)

Stream results and parameter outputs to thread-safe shared memory for online monitoring and statistics without blocking execution:

```python
from labeeb.shared_memory import CampaignMemory, InMemorySharedBackend

memory = CampaignMemory(backend=InMemorySharedBackend())

# Register real-time progress listener
memory.add_listener(lambda case_id, data: print(f"Case {case_id} finished: {data.get('status')}"))

# Ingest outputs as cases resolve
memory.record_case(0, {"TEMP": 320.0, "PRESSURE": 2.1, "status": "SUCCESS"})
memory.record_case(1, {"TEMP": 340.0, "PRESSURE": 2.2, "status": "SUCCESS"})

# Point-in-time snapshot & tabular conversion
df = memory.to_dataframe()

# Real-time online running statistics
stats = memory.online_summary(metrics=["TEMP", "PRESSURE"])
print(f"Running mean temperature: {stats['TEMP']['mean']:.1f} K")
```

---

## 10. Sensitivity & Uncertainty Analysis (`labeeb.analysis`)

Perform fast post-processing and sensitivity screening:

```python
from labeeb.analysis import (
    correlation_analysis,
    morris_screening,
    sobol_indices,
    wilks_sample_size,
)

# 1. Pearson and Spearman rank correlation
correlations = correlation_analysis(
    inputs={"RHO": [18.0, 19.0, 20.0], "TEMP": [300.0, 320.0, 340.0]},
    output=[1.002, 1.015, 1.028]
)

# 2. Wilks order-statistics sample size
n_samples = wilks_sample_size(coverage=0.95, confidence=0.95, sides=1)
print(f"Minimum runs for 95/95 one-sided limit: {n_samples}")
```

---

## 11. Complete Runnable Case Study Example

Here is an end-to-end, fully runnable Python script illustrating a complete uncertainty study using Labeeb:

```python
import tempfile
from pathlib import Path
from labeeb import (
    Campaign,
    CampaignManifest,
    CampaignMemory,
    latin_hypercube_sample,
    correlation_analysis,
)

def run_case_study():
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        
        # 1. Create simulation template deck
        deck = root / "simulation.template"
        deck.write_text("FUEL_DENSITY = #RHO#\nENRICHMENT = #WF#\n")

        # 2. Generate Latin Hypercube parameter design (using size=10)
        samples = latin_hypercube_sample([(18.5, 19.5), (0.015, 0.025)], size=10, seed=123)
        rhos = [float(s[0]) for s in samples]
        wfs = [float(s[1]) for s in samples]

        # 3. Configure campaign manifest
        manifest = CampaignManifest(
            name="jrtr_fuel_uncertainty",
            parameters={"RHO": rhos, "WF": wfs},
            templates=[str(deck)],
            commands=["python -c 'print(\"Simulation completed.\")'"],
            execution={"main_dir": str(root), "run_dir": "runs"}
        )

        # 4. Attach shared memory and run
        memory = CampaignMemory()
        campaign = Campaign(manifest, memory=memory)
        results = campaign.run()

        print(f"Campaign execution complete: {len(results)} cases resolved.")
        summary = memory.online_summary(metrics=["RHO", "WF"])
        print("Online summary:", summary)

        # 5. Sensitivity correlation against simulated dummy output
        dummy_keff = [1.0 + 0.01 * r - 0.05 * w for r, w in zip(rhos, wfs)]
        corr = correlation_analysis(inputs={"RHO": rhos, "WF": wfs}, output=dummy_keff)
        print("Sensitivity Correlations:\n", corr)

if __name__ == "__main__":
    run_case_study()
```

---

## 12. Exception Hierarchy

All domain exceptions inherit from `LabeebError`:

| Exception Class | Module | Trigger Condition |
| :--- | :--- | :--- |
| **`CampaignError`** | `labeeb.campaign` | Invalid manifest structure, mismatched parameter lengths |
| **`CaseExecutionError`** | `labeeb.exceptions` | Executable launch failure, non-zero return code, or timeout |
| **`CouplingError`** | `labeeb.exceptions` | Divergence detected, unmapped cases, or max iterations exceeded |
| **`ExtractionError`** | `labeeb.extractors` | Missing output files, unparseable regex, or schema mismatches |
| **`DatabaseError`** | `labeeb.exceptions` | Mismatched attribute lengths or invalid column indexing |
| **`SamplingError`** | `labeeb.exceptions` | Invalid distribution bounds or probability weights |
| **`SharedMemoryError`**| `labeeb.shared_memory`| Invalid case ID or uncopyable shared state |

# Labeeb API-First Training Curriculum (v1.23.0)

> **Goal**: Master sensitivity analysis (SA) and uncertainty analysis (UA) workflows using the Labeeb Python API.  
> **Audience**: Python developers, simulation engineers, researchers  
> **Prerequisites**: Python ≥3.8, basic NumPy/Pandas familiarity, text-file manipulation  

---

## Learning Outcomes

By completing this curriculum, you will:
- ✓ Design parameter sweeps (full-factorial, one-at-a-time, statistical)
- ✓ Execute simulation campaigns with automatic templating and output extraction
- ✓ Analyze sensitivity (correlations, Morris screening, Sobol indices)
- ✓ Quantify uncertainty (LHS, Halton sampling, tolerance limits)
- ✓ Couple multi-physics codes with convergence controls
- ✓ Build reproducible analysis bundles with provenance tracking

---

## Curriculum Structure

| Module | Topic | Duration | Prerequisites | Key Concepts |
|--------|-------|----------|---|---|
| **0** | Getting Started | 30 min | None | Installation, first script, verification |
| **1** | Data Representation | 1 h | Python basics | Attribute, Database, derived attributes, import/export |
| **2** | Parameter Sampling | 1.5 h | Module 1 | FOAT, OAT, LHS, Halton, per-attribute sampling |
| **3** | Case Execution | 2 h | Modules 1–2 | Case, File, FlagsMap, harvesters (CSV/JSON/Regex) |
| **4** | Campaign Orchestration | 1.5 h | Module 3 | Campaign, CampaignManifest, resume/retry, state |
| **5** | Sensitivity Analysis | 2 h | Module 4 | Correlation, Morris, Sobol indices, factor ranking |
| **6** | Uncertainty Analysis | 1.5 h | Modules 2, 4 | Wilks' method, tolerance limits, LHS propagation |
| **7** | Multi-Physics Coupling | 2 h | Module 3 | Coupler, convergence contract, under-relaxation |
| **8** | Analysis Bundles | 1 h | Module 4 | Export/load, redaction, reproducibility, provenance |
| **9** | Live Plotting | 1 h | Module 4 | LivePlot, EventPublisher, non-blocking observers |
| **10** | Advanced Topics | Variable | All | Optimization, custom backends, failure policies |
| **Capstone** | End-to-end study | 4 h | All | Multi-parameter campaign, SA/UA, bundle export |
| | **Total** | **~20 hours** | | |

---

## Module 0: Getting Started (30 min)

**Learning Objectives**:
- Install Labeeb and verify functionality
- Understand package structure and public API
- Run a minimal working example

**Install & Verify**

```bash
# Install from PyPI
python -m pip install labeeb

# Or editable from a checkout
cd /path/to/Labeeb
python -m pip install -e .[dev]

# Verify installation
python -c "import labeeb; print(labeeb.__version__)"  # v1.23.0
```

**Exercise 0.1**: First Script

```python
from labeeb.database import Attribute, Database

# Create attributes
density = Attribute(name="RHO", data=[18.5, 19.0], unit="g/cm3")
enrichment = Attribute(name="WF", data=[0.01, 0.02], unit="wt_frac")

# Build database
db = Database(name="demo")
db.add_attribute(density, enrichment)

# Print to verify
print(f"Database: {db.name}")
print(f"Rows: {len(db)}")
print(f"Row 0: {db.get_row(0)}")
```

**Reference**: [Installation Guide](../README.md#installation)

---

## Module 1: Data Representation (1 hour)

**Learning Objectives**:
- Create and manipulate `Attribute` objects with units
- Build `Database` collections with row/column operations
- Add derived attributes with dependency tracking
- Import/export data (CSV, Excel, Parquet, JSON)

**Key Concepts**:
- `Attribute`: typed 1D column with units and vectorized operations
- `Database`: aligned collection of attributes (like a DataFrame)
- Derived attributes: computed columns with auto-dependency tracking
- Database-context callbacks: cumulative, global, or lagged calculations

**Exercise 1.1**: Attribute Operations

```python
from labeeb.database import Attribute

# Create attributes
power = Attribute(name="POWER", data=[10.0, 15.0, 20.0], unit="MW")
flow = Attribute(name="FLOW", data=[1200.0, 1350.0, 1500.0], unit="m3/h")

# Vectorized math
power_kw = power * 1000.0
print(power_kw.data)  # [10000.0, 15000.0, 20000.0]

# Comparisons
high_power = power > 12.0
print(high_power.data)  # [False, True, True]
```

**Exercise 1.2**: Database with Derived Attributes

```python
from labeeb.database import Attribute, Database

db = Database(name="reactor_core")
db.add_attribute(
    Attribute(name="POWER", data=[10.0, 15.0, 20.0], unit="MW"),
    Attribute(name="FLOW", data=[1200.0, 1350.0, 1500.0], unit="m3/h"),
)

# Add derived attribute (expression)
db.add_derived_attribute("POWER_KW", "POWER * 1000.0", unit="kW")

# Add derived attribute (lambda)
db.add_derived_attribute(
    "SPECIFIC_FLOW",
    lambda row: row["FLOW"] / row["POWER"],
    dependencies=["FLOW", "POWER"],
    unit="m3/(h*MW)"
)

# Update a row (cascades recomputation)
db.update_row(row_id=1, data={"POWER": 16.5})

# Export
db.export_to_file("reactor_core.csv")

# Re-import
db_new = Database(name="imported")
db_new.import_from_file("reactor_core.csv")
```

**Reference**: [USER_MANUAL § 3: Data Representation](./USER_MANUAL.md#3-data-representation-attribute--database)

---

## Module 2: Parameter Sampling & Design Matrices (1.5 hours)

**Learning Objectives**:
- Understand sampling strategies (FOAT, OAT, statistical)
- Choose appropriate design for sensitivity vs. uncertainty studies
- Generate parameter matrices with independent per-attribute sampling

**Key Concepts**:

| Method | Design | Efficiency | Best For |
|--------|--------|-----------|----------|
| **FOAT** | N^d combinations | Space-filling but expensive | Complete interaction analysis |
| **OAT** | (N-1)×M+1 cases | Fast screening | Factor prioritization, sensitivity ranking |
| **LHS** | User-defined size N | Efficient space-filling | Uncertainty propagation, small N |
| **Halton** | Deterministic, N | Reproducible | Monte Carlo with seed control |

**Exercise 2.1**: Full Factorial (FOAT)

```python
from labeeb.sampler import FOATConstructor
from labeeb.database import Database

foat = FOATConstructor()
foat.add_case({
    "INLET_TEMP": [25.0, 30.0, 35.0],    # 3 values
    "CORE_FLOW": [1200.0, 1400.0],       # 2 values
    "ENRICHMENT": [0.01, 0.02],          # 2 values
})

grid = foat.construct()
db = Database(data=grid)
print(f"Generated {len(db)} cases")  # 3 × 2 × 2 = 12
```

**Exercise 2.2**: One-At-A-Time (OAT)

```python
from labeeb.sampler import OATConstructor

oat = OATConstructor()
oat.add_case({
    "INLET_TEMP": [25.0, 30.0, 35.0],
    "CORE_FLOW": [1200.0, 1400.0],
    "ENRICHMENT": [0.01, 0.02],
})

grid = oat.construct()
db = Database(data=grid)
print(f"Generated {len(db)} cases")  # 1 + (3-1) + (2-1) + (2-1) = 5
# Rows: (25, 1200, 0.01), (30, 1200, 0.01), (35, 1200, 0.01), 
#       (25, 1400, 0.01), (25, 0.02, 0.01)
```

**Exercise 2.3**: Per-Attribute Sampling (Independent Distributions)

```python
from labeeb.database import Database
from labeeb.sampler import uniform_sample, normal_sample

db = Database(name="uncertainty_quantification")
db.add_sampled_attribute(
    "INLET_TEMP",
    lambda size: uniform_sample(25.0, 35.0, size),
    size=100,
    unit="°C"
)
db.add_sampled_attribute(
    "CORE_FLOW",
    lambda size: normal_sample(1300.0, 50.0, size),
    size=100,
    unit="m3/h"
)

print(f"Generated {len(db)} cases with independent distributions")
```

**Exercise 2.4**: Low-Discrepancy Sequences

```python
from labeeb.sampler import latin_hypercube_sample, halton_sample

# Latin Hypercube Sampling
bounds = [(25.0, 35.0), (1200.0, 1400.0), (0.01, 0.02)]
lhs_points = latin_hypercube_sample(bounds, size=50, seed=42)

# Halton sequence (deterministic, reproducible)
halton_points = halton_sample(size=50, dimensions=3, skip=0)
```

**Reference**: [USER_MANUAL § 4: Parameter Sampling](./USER_MANUAL.md#4-parameter-sampling--design-matrices)

---

## Module 3: Case Execution & Output Harvesting (2 hours)

**Learning Objectives**:
- Execute individual simulations with templating and timeout control
- Extract structured output using declarative harvesters
- Handle execution events and failure modes
- Understand execution backend contract

**Key Concepts**:
- `Case`: orchestrates single run with templating, execution, harvest
- `File` / `FlagsMap`: template processing (delimited or Jinja2)
- Harvesters: CSV, JSON, Regex, Excel, Callable extraction
- Execution events: structured logging of start, completion, status, duration

**Exercise 3.1**: Basic Case Execution

```python
from labeeb.case import Case

# Minimal case
case = Case(
    name="reactor_case_1",
    commands=["python simulate.py --input=deck.txt --output=results.csv"],
    run_dir="/tmp/cases"
)

# Execute with 5-minute timeout
result = case.run(timeout=300)

print(f"Status: {result.status}")  # SUCCESS, FAILED, TIMEOUT
print(f"Exit code: {result.exit_code}")
print(f"Duration: {result.duration_seconds}s")
```

**Exercise 3.2**: Templating with FlagsMap

```python
from labeeb.case import Case, Flag, FlagsMap

case = Case(
    name="templated_case",
    commands=["python simulate.py --input=deck.txt --output=results.csv"],
    run_dir="/tmp/cases"
)

# Define parameters to inject into template
flags = FlagsMap({
    "POWER": Flag(name="POWER", value=15.0),
    "FLOW": Flag(name="FLOW", value=1300.0),
    "ENRICHMENT": Flag(name="ENRICHMENT", value=0.02),
})

# Map template file + flags
case.template_inputs = {
    "deck.txt": ("deck.template.txt", flags),  # (source_template, FlagsMap)
}

# Template syntax: #POWER#, #FLOW#, #ENRICHMENT# in deck.template.txt
# Execution will create deck.txt with values substituted

result = case.run(timeout=300)
```

**Exercise 3.3**: Declarative Output Harvesting

```python
from labeeb.case import Case
from labeeb.extractors import CsvHarvester, JsonHarvester, RegexHarvester

case = Case(
    name="harvesting_case",
    commands=["python simulate.py --input=deck.txt --output=results.csv"],
    run_dir="/tmp/cases"
)

# Add harvesters (what to extract from outputs)
case.add_harvester(
    CsvHarvester(
        name="OUTLET_TEMP",
        file="results.csv",
        column="outlet_temperature",
        transform=lambda x: float(x)
    )
)

case.add_harvester(
    RegexHarvester(
        name="CONVERGENCE_ITER",
        file="debug.log",
        pattern=r"Final Iteration: (\d+)",
        transform=lambda x: int(x)
    )
)

case.add_harvester(
    JsonHarvester(
        name="POWER_DENSITY",
        file="results.json",
        key="core.power_density",  # Dot-separated path
        transform=lambda x: float(x)
    )
)

result = case.run(timeout=300)

# Access harvested outputs
print(f"Outlet temp: {result.metrics['OUTLET_TEMP']} °C")
print(f"Iterations: {result.metrics['CONVERGENCE_ITER']}")
print(f"Power density: {result.metrics['POWER_DENSITY']} MW/L")
```

**Reference**: [USER_MANUAL § 5: Case Execution](./USER_MANUAL.md#5-case-execution--declarative-output-harvesting)

---

## Module 4: Campaign Orchestration (1.5 hours)

**Learning Objectives**:
- Design and run campaigns (batch executions across parameter space)
- Use manifests for reproducible configuration
- Understand resume/retry with hash-aware caching
- Export campaign results in multiple formats

**Key Concepts**:
- `Campaign`: orchestrates all cases with automated result collection
- `CampaignManifest`: validated YAML/JSON configuration as source of truth
- Resume & retry: automatically re-uses matching cached results, retries failures
- State persistence: SQLite-backed resume/retry tracking

**Exercise 4.1**: Python API Campaign

```python
from labeeb.campaign import Campaign, CampaignManifest
from labeeb.case import Case
from labeeb.sampler import FOATConstructor
from labeeb.database import Database
from labeeb.extractors import CsvHarvester

# Build parameter matrix
foat = FOATConstructor()
foat.add_case({
    "POWER": [10.0, 15.0, 20.0],
    "FLOW": [1200.0, 1400.0],
})
params_db = Database(data=foat.construct())

# Create case template
case = Case(
    name="reactor_sim",
    commands=["python simulate.py --input=deck.txt --output=results.csv"],
    run_dir="/tmp/campaign_run"
)
case.add_harvester(CsvHarvester(name="OUTLET_TEMP", file="results.csv", column="T_out"))

# Build manifest
manifest = CampaignManifest(
    name="sensitivity_study",
    parameters_db=params_db,
    case_template=case,
    seed=42
)

# Run campaign
campaign = Campaign(manifest=manifest)
results = campaign.run()

# Access results
for case_id, result in results.items():
    print(f"Case {case_id}: {result.status}, metrics={result.metrics}")

# Export
campaign.export_results(format="csv", output_file="results.csv")
campaign.export_results(format="parquet", output_file="results.parquet")
```

**Exercise 4.2**: Manifest-Based Campaign

Create `campaign.yaml`:
```yaml
name: "reactor_sensitivity"
parameters:
  POWER: [10.0, 15.0, 20.0]
  FLOW: [1200.0, 1400.0]
  ENRICHMENT: [0.01, 0.02]
templates:
  deck.txt: ["deck.template.txt", "FlagsMap"]
commands:
  - "python simulate.py --input=deck.txt --output=results.csv"
harvesters:
  OUTLET_TEMP:
    type: "csv"
    file: "results.csv"
    column: "outlet_temperature"
  POWER_DENSITY:
    type: "json"
    file: "results.json"
    key: "core.power_density"
seed: 42
resume: true
```

Run:
```python
from labeeb.campaign import Campaign, load_manifest

manifest = load_manifest("campaign.yaml")
campaign = Campaign(manifest=manifest)
results = campaign.run()
```

**Reference**: [USER_MANUAL § 6: Campaign Orchestration](./USER_MANUAL.md#6-campaign-orchestration)

---

## Module 5: Sensitivity Analysis (2 hours)

**Learning Objectives**:
- Compute correlation-based sensitivity (Pearson, Spearman)
- Perform Morris screening for factor prioritization
- Calculate global Sobol indices (variance-based sensitivity)
- Interpret sensitivity results and rank parameters

**Key Concepts**:
- **Pearson/Spearman**: linear/monotonic relationships (quick, assumes correlation)
- **Morris**: one-at-a-time sampling → main effects + interactions (screening tool)
- **Sobol**: variance decomposition → first-order + total-order indices (comprehensive)

**Exercise 5.1**: Correlation Analysis

```python
from labeeb.analysis import correlation_analysis
import numpy as np

# Assume campaign results available
parameters = np.array([
    [10.0, 1200.0, 0.01],
    [15.0, 1200.0, 0.01],
    [20.0, 1200.0, 0.01],
    [10.0, 1400.0, 0.01],
    # ... more cases
])

outputs = np.array([305.2, 310.5, 315.8, 307.1, ...])  # OUTLET_TEMP

# Compute correlations
pearson_r, spearman_r = correlation_analysis(parameters, outputs)
print(f"Pearson r: {pearson_r}")
print(f"Spearman ρ: {spearman_r}")

# Interpretation: values close to ±1 = strong relationship
# Positive = larger param → larger output
# Negative = larger param → smaller output
```

**Exercise 5.2**: Morris Screening

```python
from labeeb.analysis import morris_screening

# OAT design with perturbations
morris_mu, morris_sigma = morris_screening(parameters, outputs)

print(f"Morris μ (main effect): {morris_mu}")  # Sensitivity magnitude
print(f"Morris σ (interaction): {morris_sigma}")  # Parameter interaction strength

# Interpretation:
# High μ, low σ  = important, linear effect
# High μ, high σ = important, but interacts strongly
# Low μ         = not important (can fix at baseline)
```

**Exercise 5.3**: Sobol Global Sensitivity

```python
from labeeb.analysis import sobol_indices

# Requires ~2N×d function evals for d parameters
s1, st = sobol_indices(parameters, outputs)

print(f"Sobol S1 (first-order): {s1}")  # Direct variance contribution
print(f"Sobol ST (total-order): {st}")  # Including interactions

# Interpretation:
# S1[i] = fraction of output variance from parameter i alone
# ST[i] = fraction of output variance involving parameter i
# ST[i] - S1[i] = interaction effects
# Sum(S1) ≤ 1.0 (residual = interactions + non-linearity)
```

**Reference**: [USER_MANUAL § 7: Sensitivity Analysis](./USER_MANUAL.md#7-sensitivity-analysis-and-global-indices)

---

## Module 6: Uncertainty Analysis & Tolerance Limits (1.5 hours)

**Learning Objectives**:
- Understand uncertainty propagation via forward Monte Carlo
- Compute non-parametric tolerance limits
- Apply Wilks' method to determine sample sizes
- Interpret confidence/coverage tradeoffs

**Key Concepts**:
- **Uncertainty propagation**: run many cases with sampled inputs → output distribution
- **Wilks' method**: non-parametric N for k-of-m ordering statistics
- **Tolerance limit**: interval guaranteed to contain population fraction with confidence C

**Exercise 6.1**: Wilks Sample Size

```python
from labeeb.analysis import wilks_sample_size

# Compute sample size for 95/95 (95% coverage, 95% confidence)
n_95_95 = wilks_sample_size(confidence=0.95, coverage=0.95)
print(f"N for 95/95: {n_95_95}")  # 59

# Other common targets
n_90_90 = wilks_sample_size(confidence=0.90, coverage=0.90)
print(f"N for 90/90: {n_90_90}")  # 38

n_99_95 = wilks_sample_size(confidence=0.99, coverage=0.95)
print(f"N for 99/95: {n_99_95}")  # 93

# Higher confidence/coverage → larger N
```

**Exercise 6.2**: LHS Uncertainty Campaign

```python
from labeeb.sampler import latin_hypercube_sample
from labeeb.campaign import Campaign
from labeeb.analysis import wilks_sample_size
import numpy as np

# 1. Compute sample size
n = wilks_sample_size(confidence=0.95, coverage=0.95)  # 59

# 2. Generate LHS design
bounds = [(10.0, 20.0), (1200.0, 1400.0), (0.01, 0.02)]
design = latin_hypercube_sample(bounds, size=n, seed=42)

# 3. Run campaign with design
# (parameters in design populate campaign parameter matrix)

# 4. Extract outputs and compute tolerance interval
results = campaign.run()
outputs = np.array([r.metrics["OUTLET_TEMP"] for r in results])

# Non-parametric tolerance interval (min, max)
lower = np.min(outputs)
upper = np.max(outputs)
print(f"95/95 tolerance interval: [{lower:.2f}, {upper:.2f}] °C")

# All outputs within [lower, upper] with 95% confidence
# that 95% of population is covered
```

**Reference**: [USER_MANUAL § 8: Uncertainty Analysis](./USER_MANUAL.md#8-uncertainty-analysis-and-tolerance-limits)

---

## Module 7: Multi-Physics Coupling (2 hours)

**Learning Objectives**:
- Understand iterative coupling between multiple codes
- Implement convergence contracts with under-relaxation
- Control iteration budgets and divergence detection
- Design nested coupling topologies

**Key Concepts**:
- `Coupler`: coordinates two or more units (Case or nested Coupler) in feedback loop
- Under-relaxation: blend new solution with old for stability (αₖ ∈ [0, 1])
- Convergence tolerance: criterion to stop iterations (e.g., norm of change < ε)
- Divergence detection: abort if no progress after N iterations

**Exercise 7.1**: Simple Two-Code Coupling

```python
from labeeb.coupler import Coupler
from labeeb.case import Case

# Define units
neutronics = Case(
    name="neutron_sim",
    commands=["python neutronics.py --power_density=power.txt --output=flux.txt"],
    run_dir="/tmp/coupling"
)

thermal = Case(
    name="thermal_sim",
    commands=["python thermal.py --flux=flux.txt --output=temp.txt"],
    run_dir="/tmp/coupling"
)

# Build coupler
coupler = Coupler(
    units=[neutronics, thermal],
    feedback_key="power_density",
    relaxation_factor=0.5,      # Under-relaxation: 50/50 blend
    max_iterations=20,
    convergence_tolerance=0.001  # Stop when change < 0.1%
)

# Run until convergence
result = coupler.run_to_convergence()

print(f"Converged: {result.converged}")
print(f"Iterations: {result.iteration_count}")
print(f"Final residual: {result.final_residual}")
```

**Exercise 7.2**: Nested Coupling

```python
# Multi-level coupling: (neutronics ↔ thermal) ↔ structural

inner_coupler = Coupler(
    units=[neutronics, thermal],
    feedback_key="power_density",
    relaxation_factor=0.5,
    max_iterations=10,
    convergence_tolerance=0.01
)

structural = Case(
    name="structural_sim",
    commands=["python structural.py --temp=temp.txt --output=stress.txt"],
    run_dir="/tmp/coupling"
)

outer_coupler = Coupler(
    units=[inner_coupler, structural],
    feedback_key="temperature",
    relaxation_factor=0.3,      # Tighter control at outer loop
    max_iterations=5,
    convergence_tolerance=0.001
)

result = outer_coupler.run_to_convergence()
```

**Reference**: [ARCHITECTURE.md § Multi-Physics Coupling](../ARCHITECTURE.md#multi-physics-coupling)

---

## Module 8: Analysis Bundles & Reproducibility (1 hour)

**Learning Objectives**:
- Export campaigns as reproducible, self-contained bundles
- Implement redaction for safe data sharing
- Verify bundle integrity via provenance hashes
- Reuse bundles in downstream analysis

**Key Concepts**:
- `AnalysisBundle`: archive with manifest, parameters, results, provenance hashes
- Redaction: automatic masking of secrets (API keys, passwords, tokens)
- Provenance: SHA-256 of inputs + git commit info for reproducibility

**Exercise 8.1**: Export Bundle

```python
from labeeb.bundle import export_analysis_bundle

# Export campaign as bundle (ZIP + metadata)
export_analysis_bundle(
    campaign=campaign,
    output_path="analysis_v1.0.zip",
    include_logs=True,
    include_artifacts=True,
    redact_secrets=True  # Automatic masking
)

# Bundle structure:
# analysis_v1.0.zip
#   ├── manifest.json         (parameters, commands, seed)
#   ├── results.parquet       (all case results)
#   ├── provenance.json       (SHA-256 hashes, commit info)
#   ├── execution_log.jsonl   (structured events)
#   └── metadata/
#       ├── environment.json  (Python version, deps)
#       └── logs/             (optional case logs)
```

**Exercise 8.2**: Load and Reuse Bundle

```python
from labeeb.bundle import load_analysis_bundle

# Load bundle (read-only)
bundle = load_analysis_bundle("analysis_v1.0.zip")

print(f"Name: {bundle.manifest.name}")
print(f"Seed: {bundle.manifest.seed}")
print(f"Provenance: {bundle.provenance}")  # Reproducibility proof
print(f"Results shape: {bundle.results.shape}")

# Reuse results in new analysis
from labeeb.analysis import sobol_indices

params = np.array([r.parameters.values() for r in bundle.results])
outputs = np.array([r.metrics["OUTPUT"] for r in bundle.results])

s1, st = sobol_indices(params, outputs)
```

**Reference**: [USER_MANUAL § 9: Analysis Bundles](./USER_MANUAL.md#9-analysis-bundles-and-reproducibility)

---

## Module 9: Live Plotting & Online Analysis (1 hour)

**Learning Objectives**:
- Attach non-blocking observers to campaigns
- Stream execution events (JSONL, WebSocket, Redis)
- Generate live plots during campaign execution
- Isolate analysis from simulation workflow

**Key Concepts**:
- `LivePlot`: worker-thread background rendering (never blocks simulation)
- `EventPublisher`: pluggable event streaming (JSONL, WebSocket, Redis, custom)
- Failure isolation: slow analysis never pauses execution

**Exercise 9.1**: Live Plotting

```python
from labeeb.plot import LivePlot
from labeeb.campaign import Campaign

# Create live plot observer
live_plot = LivePlot(
    metrics=["OUTLET_TEMP", "POWER_DENSITY", "CONVERGENCE_ITER"],
    update_interval=1.0,  # seconds
    output_file="~/labeeb_live_plot.png"  # Final figure location
)

# Attach to campaign
campaign.add_observer(live_plot)

# Run campaign (live plot updates in background)
results = campaign.run()

# Final figure saved at ~/labeeb_live_plot.png
```

**Exercise 9.2**: Event Publisher (JSONL Logging)

```python
from labeeb.publisher import JsonlEventPublisher
from labeeb.campaign import Campaign

# Log all execution events to JSONL
publisher = JsonlEventPublisher(output_file="execution_log.jsonl")

campaign.add_observer(publisher)
results = campaign.run()

# execution_log.jsonl contains:
# {"timestamp": "...", "case_id": "case_0", "event": "start", ...}
# {"timestamp": "...", "case_id": "case_0", "event": "complete", "status": "SUCCESS", ...}
# ...
```

**Reference**: [USER_MANUAL § 10: Live Plotting](./USER_MANUAL.md#10-live-plotting--online-analysis)

---

## Module 10: Advanced Topics (Optional, Variable Time)

### 10a. Optimization & Surrogate Models
- `Optimizer`: simulation-based optimization with checkpoint/resume
- `SurrogateModel`: GP, neural network, or Gaussian process surrogates
- `rank_candidates()`: find next points using acquisition functions (EI, LCB)
- Reference: [USER_MANUAL § 11: Optimization](./USER_MANUAL.md#11-simulation-based-optimization)

### 10b. Custom Execution Backends
- Implement `ExecutionBackend` interface for HPC, cloud, or custom schedulers
- Inject via `case.execution_backend = MyBackend()`
- Reference: [DEVELOPER_GUIDE § 3.1: Execution Backends](./DEVELOPER_GUIDE.md#31-execution-backends)

### 10c. Failure Policies
- Configurable stop/continue/retry on case failure
- Partial result alignment: one row per case, no silent truncation
- Reference: [USER_MANUAL § 5.4: Failure Handling](./USER_MANUAL.md#54-failure-policies)

### 10d. Advanced Logging & Redaction
- `configure_logging()`: application-owned setup, rotating file handlers
- Automatic redaction of secrets (passwords, API keys, tokens)
- Reference: [DEVELOPER_GUIDE § 2.2.1: Logging](./DEVELOPER_GUIDE.md#221-logging-configuration-api)

---

## Capstone Project: End-to-End Study

**Objective**: Design and execute a multi-parameter sensitivity/uncertainty analysis from scratch.

**Steps**:

1. **Define parameter space** (3–5 parameters, mix of ranges and distributions)
   ```python
   # Example: reactor core with 4 parameters
   params = {
       "INLET_TEMP": [25.0, 30.0, 35.0],        # 3 values (FOAT)
       "CORE_FLOW": [1200.0, 1350.0, 1500.0],   # 3 values
       "ENRICHMENT": [0.01, 0.02],              # 2 values
       "CLAD_THICK": [0.5, 0.7, 0.9],           # 3 values
   }
   # Total: 3 × 3 × 2 × 3 = 54 cases (FOAT)
   ```

2. **Run FOAT design** (identify important parameters)
   ```python
   from labeeb.sampler import FOATConstructor
   foat = FOATConstructor()
   foat.add_case(params)
   # Execute 54 cases
   ```

3. **Compute Pearson/Spearman** (quick correlation check)
   ```python
   from labeeb.analysis import correlation_analysis
   pearson_r, spearman_r = correlation_analysis(params, outputs)
   # Rank by |r| to identify top 2–3 parameters
   ```

4. **Run OAT screening** (confirm sensitivity with fewer cases)
   ```python
   from labeeb.sampler import OATConstructor
   oat = OATConstructor()
   oat.add_case(params)
   # Execute ~13 cases
   ```

5. **Run LHS uncertainty campaign** (Wilks-size sample)
   ```python
   from labeeb.analysis import wilks_sample_size
   from labeeb.sampler import latin_hypercube_sample
   
   n = wilks_sample_size(confidence=0.95, coverage=0.95)
   bounds = [(25, 35), (1200, 1500), (0.01, 0.02), (0.5, 0.9)]
   design = latin_hypercube_sample(bounds, size=n, seed=42)
   # Execute 59 cases
   ```

6. **Compute Sobol indices** (global sensitivity)
   ```python
   from labeeb.analysis import sobol_indices
   s1, st = sobol_indices(params, outputs)
   print(f"Parameter importance: {s1}")
   ```

7. **Extract tolerance interval** (uncertainty quantification)
   ```python
   import numpy as np
   lower, upper = np.min(outputs), np.max(outputs)
   print(f"95/95 tolerance: [{lower}, {upper}]")
   ```

8. **Export analysis bundle** (reproducible, shareable)
   ```python
   from labeeb.bundle import export_analysis_bundle
   export_analysis_bundle(campaign, "analysis_final.zip", redact_secrets=True)
   ```

9. **Document findings** (summary report)
   - Which parameters are sensitive (S1 > 0.1)?
   - Which interactions matter (ST - S1 > 0.05)?
   - What is the output range (tolerance interval)?
   - Can any parameters be fixed to reduce future runs?

---

## Troubleshooting & Tips

| Issue | Solution |
|-------|----------|
| Templating fails | Check token names match exactly (`#POWER#` in template); verify FlagsMap keys |
| Harvester misses data | Verify file paths are relative to `run_dir/case_i/`; check regex patterns |
| Campaign hangs | Look for infinite loops in coupler; set reasonable timeouts; enable verbose logging |
| Redaction too aggressive | Customize patterns in `logging_config.py` (not recommended unless necessary) |
| Out-of-memory on LHS | Use `size` parameter to chunk; switch to Halton for memory-efficient space-filling |
| Slow convergence in coupler | Increase `relaxation_factor` (faster, riskier); tighten `convergence_tolerance` |

---

## Assessment (Self-Check)

Can you (without reference):

- [ ] Create and manipulate `Attribute` and `Database` objects with derived attributes?
- [ ] Design a FOAT, OAT, or LHS sampling plan for your own problem?
- [ ] Execute a templated case with harvesting and timeout control?
- [ ] Run a full campaign, export results, and resume on failure?
- [ ] Compute Pearson, Morris, and Sobol sensitivity metrics?
- [ ] Estimate Wilks sample size and build a tolerance limit?
- [ ] Set up and run a coupled simulation with convergence controls?
- [ ] Export an analysis bundle and verify reproducibility (provenance)?
- [ ] Implement a custom execution backend for your scheduler?

If yes to 7+ of 9: **You've mastered the Labeeb API!** 🎓

---

## Resources

- **API Reference**: [USER_MANUAL.md](./USER_MANUAL.md)
- **Developer Contracts**: [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)
- **Architecture**: [ARCHITECTURE.md](../ARCHITECTURE.md)
- **Runnable Examples**: [examples/](../examples/)
- **Contributing**: [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Source Code**: [GitHub](https://github.com/mmomari072/Labeeb)

---

**Total Curriculum Time**: ~20 hours of guided study + capstone project  
**Estimated Hands-On Practice**: 30+ hours of case studies and variations

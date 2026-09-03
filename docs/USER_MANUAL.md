# Labeeb (لبيب) v2.0.0 User Manual & API Guide

> **Sensitivity & Uncertainty Analysis, Simulation Coupling, and Online State Analysis API**  
> **Author**: Eng. Mohammad Omari  
> **Version**: 2.0.0

---

## 1. Introduction & Design Philosophy

**Labeeb** is an API-first Python framework for scientific computing workflows. It orchestrates the full lifecycle of numerical simulation experiments:

1. **Deterministic & Stochastic Sampling**: Generate parameter matrices via grid sweeps, Latin Hypercube Sampling (LHS), Halton low-discrepancy sequences, and probability mass functions.
2. **Template Processing**: Inject sampled parameters into text-based input decks via delimited token replacement (`FlagsMap`) or dynamic Jinja2 templates (`File.render_jinja()`).
3. **Execution & Declarative Harvesters**: Launch simulation executables in isolated directories with automatic timeout enforcement, execution event recording, and typed output harvesting (CSV, JSON, Regex, Callable).
4. **Stateful Campaigns & Reproducibility**: Execute campaigns from validated Python objects or YAML/JSON manifests with input hashing, automatic resume/retry caching, and status tracking.
5. **Coupling Kernel & Stability Controls**: Coordinate iterative feedback loops between simulation models with typed under-relaxation, divergence detection, and iteration failure controls.
6. **Non-Blocking Shared Campaign Memory**: Stream live simulation results to in-memory shared state for real-time online analysis and statistical summaries.

---

## 2. Installation & Quickstart

Install the runtime package with pip:

```bash
python -m pip install labeeb
```

For local development, install the checkout in editable mode:

```bash
python -m pip install -e .
```

Install development tools and optional documentation/example dependencies:

```bash
python -m pip install -e ".[dev]"
# Or use the repository requirements file:
python -m pip install -r requirements-dev.txt
```

The project is configured through `pyproject.toml` and also provides a
`setup.py` compatibility shim for legacy packaging tools. Runtime dependencies
are listed in `requirements.txt`.

Verify the installation:
```python
import labeeb
print(labeeb.__version__)  # Output: 2.0.0
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

# Declarative Derived Attributes with auto-tracked dependencies & topological updates
db.add_derived_attribute("POWER_KW", "POWER * 1000.0", unit="kW")
db.add_derived_attribute("SPECIFIC_FLOW", lambda row: row["FLOW"] / row["POWER"], dependencies=["FLOW", "POWER"], unit="m3/(h*MW)")

# Database-Context Callbacks: Function receives (database, index=None) for lagged, cumulative, or global calculations
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

# Update rows in-place (automatically triggers cascading topological recomputations)
db.update_row(row_id=1, data={"POWER": 16.5})

# Export tabular data (.csv, .xlsx, .parquet, .json)
db.export_to_file("core_sampling.csv")

# Import data into a fresh Database instance
db_new = Database(name="imported")
db_new.import_from_file("core_sampling.csv")
```

---

## 4. Parameter Sampling & Design Matrices

### Full Factorial and One-At-A-Time Sweeps
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

For an OAT design, use `OATConstructor`. The first value for each attribute is
the baseline; each following row changes one attribute while the others remain
at baseline:

```python
from labeeb.sampler import OATConstructor

oat = OATConstructor()
oat.add_case({"INLET_TEMP": [25.0, 30.0, 35.0], "CORE_FLOW": [1200.0, 1400.0]})
oat_dict = oat.construct()
# Rows: (25, 1200), (30, 1200), (35, 1200), (25, 1400)
```

Choose the design based on the question you are answering:

| Design | Changes per run | Typical use |
| --- | --- | --- |
| `FOATConstructor` | Every combination of every parameter | Complete interaction study when the grid is small |
| `OATConstructor` | One parameter at a time from a shared baseline | Screening, ranking sensitivities, and quick optimization setup |
| Per-attribute samplers | Each attribute follows its own distribution | Uncertainty quantification and randomized campaigns |

Use FOAT when parameter interactions are important and the Cartesian product is
tractable. Use OAT when you need an interpretable baseline comparison and want
to limit the number of runs. Use independent attribute samplers when values
should represent distributions rather than a fixed design grid. These approaches
can also be combined: generate a design with a constructor, then derive or
sample additional database attributes before launching the campaign.

Attributes can use different sampling strategies when building a `Database`:

```python
db.add_sampled_attribute("INLET_TEMP", lambda size: uniform_sample(25.0, 35.0, size), size=8)
db.add_sampled_attribute("CORE_FLOW", lambda size: normal_sample(1300.0, 50.0, size), size=8)
```

### Correlated & Truncated Sampling (V2-UQ)
Joint draws with correlation and physically bounded marginals:

```python
from labeeb import correlated_normal_sample, truncated_normal_sample

# 1) Correlated joint draws (rows stay correlated across attributes)
joint = correlated_normal_sample(
    [300.0, 15.0], [[900.0, 30.0], [30.0, 1.0]], size=200, seed=1
)
db = Database(data={
    "TEMP": joint[:, 0].tolist(),   # mean 300, variance 900 (rho = 30/30 = 1.0)
    "FLUX": joint[:, 1].tolist(),
})

# 2) Truncated/bounded normal marginal (e.g. cladding limits 5..15 mm)
db2 = Database(data={"case": list(range(8))})
db2.add_sampled_attribute(
    "CLAD",
    lambda size: truncated_normal_sample(10.0, 2.0, low=5.0, high=15.0, size=size, seed=2),
    size=8,
)
```

`correlated_normal_sample` validates the covariance (symmetric, positive
semi-definite, `|rho| <= 1`) and `truncated_normal_sample` supports one-sided
bounds via `low=`/`high=` alone; both accept `seed=` for reproducibility.

### Cancelling Runs & Versioned Records (V2-EXEC)
Cooperative cancellation and schema-stamped results/events:

```python
# 1) Cancel a case between commands (sticky; the running command is not killed)
runner.cancel()          # remaining commands/retries are skipped (FAILED,
                         # reason "cancelled (user interruption)")

# 2) Versioned records: readers accept legacy exports and stamp writes
from labeeb.results import RESULT_SCHEMA_VERSION, CaseResult
from labeeb.execution import EVENT_SCHEMA_VERSION, ExecutionEvent
result = CaseResult(case_id=0, parameters={}, status="OK", exit_code=0, duration_seconds=0.1)
record = result.to_record()              # {"schema_version": "1", ...}
result = CaseResult.from_record(record)  # tolerant of version-less records
legacy_event = {"command": "true", "cwd": ".", "status": "completed",
                "returncode": 0, "duration_seconds": 0.1,
                "started_at": "t", "ended_at": "t"}
ev = ExecutionEvent.from_dict(legacy_event)  # defaults schema_version "1"
assert RESULT_SCHEMA_VERSION == EVENT_SCHEMA_VERSION == "1"
```

Unsupported schema versions raise `ValueError` on read; mid-command process
kill is reserved for the future scheduler/container adapters.

### Advanced Sampling: Latin Hypercube & Halton Sequences
Generate space-filling low-discrepancy sequences for uncertainty quantification using the `size` parameter:

```python
from labeeb import halton_sample, latin_hypercube_sample, normal_sample, uniform_sample

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

template = File("simulation_deck.jinja2")
template.render_jinja({
    "power": 20.0,
    "channels": [{"id": 1, "flow": 500.0}, {"id": 2, "flow": 600.0}]
})
```

### Assignment-Style Replacement (`File.replace_assignments`)
Replaces numerical or string values in simulation input decks while preserving whitespace, comments, and delimiters:
```python
from labeeb.utils.file_io import File

template = File("model.inp").read()
template.replace_assignments(
    {"flux": 2.5e-04, "temp": 300.0},
    fmt={"flux": "{:.2e}", "temp": "%.1f"},
    strict=True,
)
```

### Inline Expression Replacement (`File.replace_expressions`)
Safely evaluates mathematical expressions embedded in input decks using `${expr : fmt}` tags:
```python
from labeeb.utils.file_io import File

template = File("core.inp").read()
template.replace_expressions({
    "power_mw": 15.0,
    "radius": 10.0,
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

#### Copy & Render Semantics
For every database row, `Case.launch()` creates an isolated run directory
`<main_dir>/<run_case_main_dir>/case_<id>` (repeated convergence passes of the
same case use `case_<id>_iter<attempt>`). Input templates are then *copied into
the run directory and rendered there*: flag replacement
(`#RHO#` -> value), assignment-style replacement, and inline `${expr}`
evaluation are applied in order to the in-memory copy, and the rendered file is
written into the case directory. The original template file is never modified.
`objects_to_be_copied` files are copied verbatim (unrendered) into the same
directory, and simulation outputs are discovered and harvested from that same
run directory.

#### Output Declaration & Discovery Contract
Outputs are declared explicitly — never guessed from the filesystem:

* `output_files={"out.csv": ["keff", ...]}` declares *required* CSV columns;
  a missing file or column fails the case.
* Harvesters declare named, typed extractions from a specific file:
  `CsvHarvester`, `JsonHarvester`, `RegexHarvester`, `ExcelHarvester`, or
  `CallableHarvester`. By default the target file is *required* (missing file ->
  `ExtractionError`, failing the case). Set `optional=True` (on the harvester or
  via `Case.add_harvester(..., optional=True)`) to declare an *optional* output:
  when the file was not produced, the run records `None` for that metric instead
  of failing — useful for codes that emit auxiliary files conditionally.

#### Failure-Handling Policies
Command and output-harvesting failures are configurable per `Case` and in `Campaign` manifests — the defaults preserve classic fail-fast behavior exactly:

```python
from labeeb import Case, Campaign, CampaignManifest

# Defaults (unchanged semantics): stop on the first failure.
case = Case(name="sim", output_files={}, command_failure_policy="stop", harvest_failure_policy="stop")

# continue: record the failure (FAILED history entry + case.failure), skip remaining
# commands/harvesters for that case, and let campaign/launch record FAILED without raising.
case.command_failure_policy = "continue"
case.harvest_failure_policy = "continue"

# retry: rerun a failed command up to max_attempts (each failed attempt is recorded
# in execution_history and OutputCatalog); exhaustion falls back to stop semantics.
case.command_failure_policy = "retry"
case.max_attempts = 3
```

##### Policy Options & Defaults

* `command_failure_policy`:
  * `"stop"` (**default**): Raises `CaseExecutionError` on the first failing command — preserving classic fail-fast semantics.
  * `"continue"`: Records the failure (`status="FAILED"`, exit code, redacted command, message), skips remaining commands for that case, and surfaces the failure through `case._case_failed` / `case.failure`. `Case.launch()` aggregates it, and `Campaign.run()` records a `FAILED` result (which can be retried on a later run).
  * `"retry"`: Re-runs a failed command up to `max_attempts` times, recording each failed attempt in `execution_history` and `OutputCatalog`. If all retries fail, it stops and surfaces the final failure.
* `harvest_failure_policy`:
  * `"stop"` (**default**): Raises `CaseExecutionError` when a required output file is missing/unreadable or a harvester fails.
  * `"continue"`: Appends `None` for affected metrics, logs a warning, records `_case_failed`, and allows the case run to complete cleanly without raising.
* `max_attempts`: Retry budget integer used when `command_failure_policy="retry"` (must be $\ge 2$).

##### Sequential and Parallel Campaign Execution Examples

Campaigns accept failure policies via the manifest `execution` mapping:

```yaml
execution:
  run_dir: runs
  parallel: true
  n_workers: 4
  command_failure_policy: continue   # options: stop (default), continue, retry
  harvest_failure_policy: continue   # options: stop (default), continue
  max_attempts: 3                    # used when command_failure_policy is retry
```

```python
# Programmatic Python Manifest with Parallel Worker Execution and Continue Policy
manifest = CampaignManifest.from_dict({
    "name": "parallel_fuel_sweep",
    "parameters": {"RHO": [18.0, 18.5, 19.0, 19.5]},
    "templates": ["deck.inp"],
    "commands": ["simulation-code --input deck.inp"],
    "execution": {
        "run_dir": "runs",
        "parallel": True,
        "n_workers": 4,
        "command_failure_policy": "continue",
        "harvest_failure_policy": "continue",
        "output_catalog": "catalog.sqlite",
    }
})

campaign = Campaign(manifest, state_path="state.sqlite")
results = campaign.run()

# Failed cases are recorded as FAILED results without aborting parallel worker processes
successes = [r for r in results if r.status == "SUCCESS"]
failures = [r for r in results if r.status == "FAILED"]
print(f"Sweep complete: {len(successes)} succeeded, {len(failures)} failed.")
```

##### State Store & Output Catalog Recording Semantics

- **`CampaignStateStore`**: Saves the final result payload per case. If a case fails under `continue` or retry exhaustion, it is stored as `FAILED`. On subsequent `campaign.run(resume=True)`, failed cases can be re-attempted.
- **`OutputCatalog`**: Appends **one row per attempt** (attempt 0, 1, 2, ...). When `command_failure_policy="retry"`, every failed attempt is recorded as a distinct catalog row with its command, exit code, stdout/stderr path, and duration — providing a complete append-only audit trail.
- **All Recorded Failures**: Always remain visible in `case.execution_history` (status, exit code, message), `Campaign` results (`status="FAILED"`, `failure=...`), `OutputCatalog` rows, and `case_failure` lifecycle events.

#### Post-Output Hooks
Hooks run *after* output files/harvesters are read and *before* results are
finalized (between `_read_outputs()` and `post_functions`), in registration
order:

```python
def ratio_hook(outputs, case):
    # CSV column rows hold [row_value]; harvester/derived metrics are scalars
    return {"ratio": outputs["x"][-1][0] / outputs["y"][-1][0]}

case.add_post_output_hook("ratio", ratio_hook)   # or: add_post_output_hook(fn)

def clamp_keff_hook(outputs, case):
    outputs["keff"][-1] = min(outputs["keff"][-1][0], 0.99)  # in-place edit

case.add_post_output_hook("clamp_keff", clamp_keff_hook)
```

Contract:

* Signature `hook(outputs, case)`: `outputs` is the live `case.outputs`
  mapping (in-place edits honored); `case` carries `case_id`,
  `current_case_dir`, `execution_history`, and the database row.
* **Return semantics**: `None` = no additions (mutations only); a dict
  `{metric: value}` appends one row entry per key (new columns are created).
  Returned metrics flow into `Campaign` results and — via per-key output
  deltas — into `OutputCatalog` rows automatically.
* **Validation**: hooks must be callable, names unique, and returns must be
  `None` or a dict; violations raise `CaseExecutionError`.
* **Failure policy**: exceptions raised *inside* a hook follow
  `harvest_failure_policy` — `stop` (default) fails the case with
  `CaseExecutionError`; `continue` records the failure on
  `case.post_output_hook_failures` (per attempt, readable after the run),
  keeps the harvested outputs, and runs the remaining hooks without failing
  the case.
* **Parallel safety**: each parallel worker runs its own hook invocation on
  its own row (hooks must not share mutable state across calls); hook-created
  columns merge back in `case_id` order like regular outputs.

##### Secure Command Execution
Commands are executed WITHOUT a shell by default (argv-style, the safe
default):

```python
# Safe default: argv lists run with no shell at all.
case.exe_cmd = [["python", "deck_solver.py", "--mode", "steady"],
                ["mcnp", "input.i"]]

# Plain strings are parsed argv-safe too (shlex): quotes are honored, but
# shell metacharacters (>, |, &&, ;) are NOT interpreted.
case.exe_cmd = ["python -c \"print(1)\""]   # works, argv-style
```

Legacy shell command strings (redirections, pipes, chaining) are preserved
via an explicit opt-in — per `Case`, per backend, or per manifest:

```python
case.exe_cmd = ["echo 600.0 >> data.csv"]   # needs shell semantics
case.shell = True                           # explicit opt-in
```

Campaign manifests accept `execution.shell: true`; the backend equivalent is
`LocalExecutionBackend(default_shell=True)` or the per-call `shell=True`
argument. Timeout (`-999`, `timed_out=True`), launch failure (`-1`, e.g.
missing executable — recorded FAILED, never raised from the backend), logging
and redaction semantics are unchanged for both forms.

##### Post-Output Feedback & Sequential Adaptive Optimization

Post-output hooks can perform **adaptive feedback loops** — deriving output metrics from current harvested results and updating parameter values in `case.database` for subsequent rows before those future cases execute.

```python
def adaptive_feedback_hook(outputs, case):
    # 1. Harvest or derive metric for the current row (case.case_id)
    peak_temp = outputs["peak_temp"][-1]
    
    # 2. Derive output metric returned to case.outputs & OutputCatalog
    derived_metrics = {"is_overheating": float(peak_temp > 500.0)}

    # 3. Feedback update: adjust input parameters for the NEXT database row (case_id + 1)
    next_idx = case.case_id + 1
    if next_idx < len(case.database):
        if peak_temp > 500.0:
            # Overheating detected: reduce next row POWER parameter by 10%
            current_power = case.database["POWER"][next_idx]
            case.database.set_row(next_idx, {"POWER": current_power * 0.9})
            
    return derived_metrics

case.add_post_output_hook("adaptive_feedback", adaptive_feedback_hook)
```

Key Semantics & Operational Rules:

* **Current vs. Future Input Timing**:
  - Modifying row $i$'s inputs inside row $i$'s post-output hook does *not* re-render or re-run row $i$, because command execution and output harvesting for row $i$ have already completed.
  - Modifying future rows in `case.database` (e.g. `case.database.set_row(i + 1, ...)` or `case.database["PARAM"][i + 1] = new_val`) updates input parameters *before* `launch_case(i + 1)` runs. When row $i + 1$ launches, its templates are rendered from the updated `case.database` parameters.
* **`outputs` vs `case.database`**:
  - `outputs` (`case.outputs`): dictionary of harvested simulation metrics (`{metric: [val_0, val_1, ...]}`). Returning `{metric: value}` appends a synthesized metric to `case.outputs`.
  - `case.database`: tabular parameter store containing input parameters and derived attributes. Post-output hooks update `case.database` to feed back adjustments into future case executions.
* **State / Catalog / Failure Behavior & Row Alignment**:
  - `CampaignStateStore` records the final result payload for each case.
  - `OutputCatalog` records the executed parameters, exit code, duration, harvested outputs, and hook-synthesized metrics per attempt row.
  - Hook exceptions follow `harvest_failure_policy`: `stop` (default) fails the case with `CaseExecutionError`; `continue` records the failure on `case.post_output_hook_failures` without aborting remaining cases.
  - Row alignment: Each case execution appends exactly one value per metric in `case.outputs`, guaranteeing exact row index alignment matching `case_id`.
* **Parallel-Safety Limits**:
  - **Sequential Execution (`parallel=False`, default)**: Adaptive feedback works deterministically because row $i$ completes its post-output hook before row $i + 1$ prepares and launches.
  - **Parallel Execution (`parallel=True`, `n_workers > 1`)**: Workers run concurrently in isolated process copies of `case`. Modifications to `case.database` inside a parallel worker process modify only that worker's local process memory and **cannot affect other concurrent or future parallel workers**. Therefore, **adaptive post-output feedback updating `case.database` for future rows requires sequential execution (`parallel=False`)**.

### Structured Execution Logging & Redaction
Every shell command executed through `Case.launch()` or `LocalExecutionBackend` produces an auditable `ExecutionEvent` record and, when JSON logging is enabled, a structured log line. Events are also recorded per case in `case.execution_history` and can be exported:

```python
from labeeb.execution import LocalExecutionBackend, export_execution_events

backend = LocalExecutionBackend()
result = backend.run("simulation-code --input deck", cwd=".", timeout=300.0)

event = result.event  # ExecutionEvent
event.command          # redacted command string
event.cwd              # working directory
event.status           # "SUCCESS" | "FAILED" | "TIMEOUT"
event.returncode       # exit code (-999 on timeout, -1 if launch failed)
event.duration_seconds # wall-clock timing
event.started_at / event.ended_at
event.stdout_bytes / event.stderr_bytes  # sizes, not contents
event.message          # failure/timeout context (reason + redacted stderr tail)
event.timed_out        # True when the command hit the timeout budget
export_execution_events([event], "execution_events.json")
```

Structured JSON logs (one record per execution) are emitted through the `labeeb` logger when configured with `json_format=True`; the full event is embedded under the record's `payload` key together with `case_id`/`unit`/`attempt` context:

```python
from labeeb.logging_config import configure_logging
configure_logging(log_file="run/labeeb_structured.jsonl", json_format=True, stream=False)
# -> {"timestamp": ..., "level": "INFO", "logger": "labeeb", "message": "execution SUCCESS: printf done",
#     "payload": {"command": ..., "cwd": ..., "status": "SUCCESS", "returncode": 0,
#                 "duration_seconds": ..., "stdout_bytes": 4, "stderr_bytes": 0, "timed_out": false, ...}}
```

Redaction is applied defensively at every sink: key/value secrets (`password=...`, `token=...`, `api_key=...`) and CLI-flag values (`--api-key sk-123`, `-password hunter2`) are replaced with `[REDACTED]` in log lines, JSON payloads, execution events, and `execution_history` entries. When Labeeb logging is left unconfigured (no handlers), execution proceeds unchanged and only default Python logging behavior applies — structured emission never alters command execution or its results.

### Declarative Output Harvesters (`labeeb.extractors`)
Extract typed scalar and vector responses from simulation outputs:

```python
from pathlib import Path
from labeeb.extractors import (
    CsvHarvester,
    ExcelHarvester,
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

# Extract a column from an Excel output workbook (optional file: None when absent)
excel_harvester = ExcelHarvester(
    name="rod_burnup",
    file_target="burnup.xlsx",
    column="BU_peak",
    sheet=0,
    optional=True,
)

# Custom programmatic harvester receiving target Path
callable_harvester = CallableHarvester(
    name="mdnbr",
    file_target="summary.txt",
    extractor=lambda path: float(path.read_text().split("=")[1])
)
```

### Durable Output Catalog (`labeeb.outputs`)
`OutputCatalog` persists an append-only SQLite ledger linking every (case, attempt)
execution to its harvested metrics, artifacts, stdout/stderr files, and status —
surviving process restarts and retries. Unlike `CampaignStateStore` (which keeps
only the latest result per case), the catalog never overwrites: each attempt is a
new row. It can share a SQLite file with `CampaignStateStore` without conflict.

```python
from labeeb import OutputCatalog
from labeeb.case import Case

catalog = OutputCatalog("campaign.sqlite")   # coexists with CampaignStateStore
case = Case("thermal_case", output_files={})
# ... configure database, templates, exe_cmd ...
case.launch()                                # run case_0, case_1, ...

# Catalog the most recent attempt of a launched case, linking metrics/artifacts
catalog.record_from_case(
    case,
    metrics={"rho": 18.5},                   # harvested outputs for this run
    artifacts={"deck": "runs/case_0/deck.inp"},
)
# Or record an arbitrary attempt directly:
from labeeb.outputs import OutputRecord
catalog.record(OutputRecord(case_id=0, attempt=1, status="SUCCESS", exit_code=0))

rows = catalog.get(0)          # all attempts for case 0, oldest first
latest = catalog.latest(0)     # most recent attempt record
catalog.summary()              # {"success": 2, "failed": 1, ...}
catalog.export("catalog.csv")  # CSV / JSON / Parquet export
```

Each record stores `case_id`, `attempt`, `unit`, `status`, redacted `command`,
`exit_code`, `duration_seconds`, `metrics`, `artifacts`, `stdout_path` /
`stderr_path` (when `capture_output` wrote them), `stdout_bytes`/`stderr_bytes`,
failure `message`, and `started_at`/`ended_at` timing. Command and message
strings are redacted before persistence.

### Campaign Integration (opt-in)
`Campaign.run()` records **every executed attempt** (successes, failures, and
retries) into an `OutputCatalog` when one is configured — two equivalent ways:

```python
from labeeb import Campaign

campaign = Campaign(manifest, state_path="state.sqlite", output_catalog="catalog.sqlite")
campaign.run()
```

or, declaratively in the manifest:

```python
execution:
  run_dir: runs
  output_catalog: catalog.sqlite   # per-attempt ledger next to campaign state
```

Per attempt the catalog row links the case/attempt to its status, exit code,
command, duration, harvested metrics, and stdout/stderr log paths (when
`capture_output` is enabled). Retries accumulate as separate attempt rows
(`attempt` 0, 1, ...), matching the retry numbering of `CampaignStateStore`.
When no catalog is configured — the default — campaign behavior is completely
unchanged and no file is created.

### Campaign-Native Live Plotting (opt-in)
Pass a `PlotObserver`/`LivePlot` instance (or a configuration mapping) to
`Campaign(..., live_plot=...)` — or declare `execution.live_plot` in the
manifest — to plot campaign parameters/metrics online while `run()` executes:

```python
from labeeb import Campaign, PlotObserver, JsonlEventPublisher
from labeeb.campaign import CampaignManifest

# Standalone, runnable example (manifest defines RHO over 3 rows)
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmp:
    template = Path(tmp) / "deck.inp"
    template.write_text("RHO = #RHO#\n", encoding="utf-8")
    manifest = CampaignManifest.from_dict({
        "name": "plot-demo",
        "parameters": {"RHO": [18.5, 19.0, 19.5]},
        "templates": [str(template)],
        "commands": ["python -c 'print(\"done\")'"],
        "execution": {"run_dir": str(Path(tmp) / "runs")},
    })

    publisher = JsonlEventPublisher(str(Path(tmp) / "events.jsonl"))
    plot = PlotObserver(metrics=["RHO"], output_path=str(Path(tmp) / "live.png"))

    campaign = Campaign(manifest, publisher=publisher, live_plot=plot)
    campaign.run()          # plot is attached for the run, detached + closed after
    assert plot.get_history()["RHO"] == [18.5, 19.0, 19.5]
    # or: live_plot={"metrics": ["RHO"], "output_path": "runs/live.png"}
```

The campaign attaches the observer to its publisher before the first event and
**safely detaches and closes it afterwards — including when `run()` raises** —
so plotting can never leak errors into execution (attach/detach/close failures
are logged and ignored). The observer receives every lifecycle event (case
start/complete/failure, campaign start/complete), so numeric metrics named in
`metrics=` accumulate from event payloads. Publisher behavior is unchanged;
`EventPublisher` additionally gains an idempotent `remove_observer()` for
detachment. Without a publisher, a configured plot is closed cleanly and the run
proceeds headless.

### Backup & Restore (`labeeb.backup`)
Campaign state databases and run artifacts can be snapshotted as one validated,
atomic backup directory:

```python
from labeeb import create_backup, restore_backup, validate_backup

backup_dir = create_backup(
    "backups/study_01",
    state_path="campaign_state.sqlite",        # CampaignStateStore database
    artifacts=["runs/"],                       # run artifact tree(s)
    memory_snapshot=campaign.memory.snapshot(),  # explicit opt-in (never implicit)
)
manifest = validate_backup(backup_dir)         # raises BackupError on any mismatch
restore_backup(backup_dir, state_path="restored.sqlite", artifacts_root="restored_runs/")
```

Semantics:

* SQLite state files are captured with the sqlite3 *online-backup API* from a
  read-only connection — a consistent snapshot even while another process is
  writing — never by copying the live file.
* Each backup contains `manifest.json` with `format`/`version` metadata,
  creation time, and per-file SHA-256 checksums; `validate_backup()` re-checksums
  every file and runs `PRAGMA quick_check` on the contained database.
* Destinations are staged next to the target and published atomically
  (`os.replace`); an existing non-empty destination is never overwritten.
* Restore validates the entire backup first, then restores the database through
  a sibling temp file + atomic replace (close live handles first) and artifacts
  via atomic per-file replacement into `artifacts_root`.
* Shared memory follows an **explicit snapshot export policy**: memory is
  derived/volatile and is only included when `memory_snapshot=` is passed
  (stored as `shared_memory.json`); otherwise the manifest records the
  deliberate exclusion.
* Errors raise the domain exception `labeeb.BackupError`.

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

solver_a = Case(name="solver_a", output_files={})
solver_a.database = Database(data={"RHO": [1.0]})

solver_b = Case(name="solver_b", output_files={})
solver_b.database = Database(data={"POWER": [20.0], "FLOW": [1200.0]})

coupler = Coupler(name="coupled_feedback")
coupler.database = Database(data={"RHO": [1.0], "POWER": [20.0], "FLOW": [1200.0]})
coupler.add_case(solver_a, attributes=["RHO"])
coupler.add_case(solver_b, attributes=["POWER", "FLOW"])

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

### Typed Relaxation, Aitken Acceleration & Restart

Under-relaxation accepts scalar *or* vector values (lists, tuples, numpy
arrays are mixed elementwise) and Aitken delta-squared acceleration can be
enabled per attribute with a deterministic default (off; extrapolation starts
after `min_iterations` raw iterates, guarded against zero denominators):

```python
# Vector/typed relaxation: elementwise omega mixing
coupler.set_under_relaxation("POWER_MAP", 0.4)
coupler.relax("POWER_MAP", [1.2, 3.0], old_value=[1.0, 2.0])  # -> [1.08, 2.4]

# Aitken acceleration on the shared iterate sequence (deterministic)
coupler.enable_aitken("POWER", min_iterations=3)   # accelerate from 3rd raw iterate
coupler.disable_aitken("POWER")                    # deterministic identity afterwards
```

Divergence and exhaustion semantics preserve the **last complete state**: a
pass is atomic — if `CouplingError` is raised mid-pass (divergence detector or
threshold), the shared row is restored to the pre-pass snapshot before the
error propagates; exhausted `run_to_convergence(error_on_max_exec=True)` keeps
the final completed pass (recorded on `last_convergence`) and then raises.
Coupling state can be checkpointed and resumed:

```python
coupler.save_state("coupling_step_2.json")     # row, step, relaxation/Aitken controls
# ... later, in a fresh process (re-register callables first) ...
coupler.load_state("coupling_step_2.json")
coupler.launch_case(2)                          # continue from the saved step
```

Observational progress callbacks fire once per COMPLETE pass with a
deep-copied read-only snapshot (`name`, `c_step`, `attempt`, `status`,
`case_names`, `database_row`, `last_convergence`); they cannot mutate the
coupler and exceptions inside them are swallowed:

```python
coupler.add_progress_callback(lambda snap: log_step(snap["c_step"], snap["status"]))
```

Nested `Coupler` children report their own completed passes before the parent
reports its completed pass (deterministic ordering).

---

## 9. Streaming Events, Transports, & Live Observers (`labeeb.publisher`, `labeeb.plot`)

Labeeb provides an API-first, strictly non-blocking event publishing and monitoring subsystem designed to stream lifecycle events and metric telemetry during execution without risking simulation crashes or performance degradation.

### Built-in Event Publishers

```python
from labeeb.publisher import (
    JsonlEventPublisher,
    WebSocketEventPublisher,
    RedisStreamEventPublisher,
    CompositeEventPublisher,
    NullEventPublisher,
)

# 1. Append-only JSONL streaming
jsonl_pub = JsonlEventPublisher("campaign_events.jsonl", max_buffer_size=1000)

# 2. Asynchronous WebSocket transport with reconnect backoff and non-blocking queue
ws_pub = WebSocketEventPublisher(
    "ws://localhost:8000/events",
    reconnect_interval_seconds=2.0,
    timeout=2.0,
)

# 3. Asynchronous Redis Streams XADD transport with configurable socket timeouts
redis_pub = RedisStreamEventPublisher(
    stream_key="labeeb:events",
    url="redis://localhost:6379/0",
    maxlen=10000,
    socket_timeout=1.0,
)

# 4. Composite multiplexer with failure isolation
pub = CompositeEventPublisher([jsonl_pub, ws_pub, redis_pub])
```

### Ring Buffering, Replay, & Redaction

All publishers inherit from `EventPublisher` and include in-memory ring buffering and sensitive data redaction:

```python
# Publish arbitrary structured event
pub.publish({"event_type": "metric", "temperature": 340.5, "password": "secret_value"})

# In-memory buffer inspection
buffered = pub.get_buffered_events()
assert len(buffered) > 0

# Replay buffered events to custom listener
replayed = []
pub.replay(lambda evt: replayed.append(evt))

# Clean lifecycle shutdown
pub.flush()
pub.close()
```

### Live Visualization with `LivePlot` & `PlotObserver`

Visualize simulation metrics in real-time with bounded update cadences and headless support:

```python
from labeeb.plot import LivePlot, PlotObserver

# 1. Attach PlotObserver directly to publisher
observer = PlotObserver(
    output_path="runs/live_plot.png",
    metrics=["RHO", "duration"],
    update_interval_seconds=0.5,
    enabled=True
)
pub.add_observer(observer)
# ... later: pub.remove_observer(observer)  # idempotent detach

# 2. Context manager for automated flushes and plot rendering
with LivePlot(metrics=["RHO", "WF"], output_path="runs/progress.png") as lp:
    lp.observe({"RHO": 19.2, "WF": 0.02})
```

Rendering is **non-blocking**: `observe()`/`notify()` only records metric history
on the calling thread and wakes an isolated background worker, so plotting never
delays simulation execution. The worker re-renders the plot image at the
`update_interval_seconds` cadence, draws through the headless `Agg` backend, and
is failure-isolated (render/import errors are logged and skipped; a broken
observer can never raise into the simulation or kill the worker). When the
observer is `enabled=False`, or no `output_path` is set (history-only mode), no
worker thread is started at all. `flush()` forces a final frame and waits
(bounded, max 5 s) for the worker; `close()` flushes the final frame, stops the
worker, and joins it with the same bounded wait — so `with LivePlot(...)`
guarantees the finished image exists when the block exits, while `notify()`
never blocks on the image writer.

---

## 10. Reproducible Analysis Bundles (`labeeb.bundle`)

Package simulation campaign runs into self-contained, reproducible, and shareable JSON or ZIP archives containing manifests, cryptographic provenance hashes, results, execution event timelines, and opt-in artifact files:

```python
from labeeb.bundle import AnalysisBundle, export_analysis_bundle, load_analysis_bundle

# Export bundle from executed Campaign
bundle = AnalysisBundle.from_campaign(
    campaign=campaign,
    results=results,
    artifacts={"summary": "runs/summary.csv"},
    redact_keys=["api_token", "secret"]
)

# 1. Export to formatted JSON
bundle.to_json("bundle.json")

# 2. Export to compressed ZIP archive with artifact files included
bundle.to_zip("bundle.zip")

# 3. Load, validate schema & provenance integrity
loaded = AnalysisBundle.load("bundle.zip")
print(f"Loaded campaign '{loaded.manifest['name']}' with {len(loaded.results)} results.")

# 4. Replay state directly into fresh CampaignMemory or event listener
from labeeb.shared_memory import CampaignMemory

restored_mem = CampaignMemory()
loaded.replay_memory(restored_mem)
```

---

## 11. Non-Blocking Shared Campaign Memory (`labeeb.shared_memory`)

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

## 12. Sensitivity & Uncertainty Analysis (`labeeb.analysis`)

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

## 13. Complete Runnable Case Study Example

Here is an end-to-end, fully runnable Python script (`examples/case_study_reactor_uncertainty.py`) illustrating a complete nuclear reactor sensitivity & uncertainty study using Labeeb's Python API, with parameter database derived attributes, dual templating, local deterministic physics stub, declarative output harvesting, shared memory, failure visibility, and analysis bundle export:

```python
import math
import sys
import tempfile
from pathlib import Path
from labeeb import (
    Campaign,
    CampaignManifest,
    CampaignMemory,
    Database,
    Attribute,
    RegexHarvester,
    JsonlEventPublisher,
    export_case_results,
    latin_hypercube_sample,
    correlation_analysis,
)

def run_reactor_case_study(workspace_dir=None, n_samples=8, include_failure_test=True):
    with tempfile.TemporaryDirectory() if workspace_dir is None else tempfile.NullContext() as tmp:
        work_root = Path(tmp if workspace_dir is None else workspace_dir)
        work_root.mkdir(parents=True, exist_ok=True)

        # 1. Parameter Generation & Database Setup
        bounds = [(0.190, 0.205), (1100.0, 1300.0), (10.0, 15.0)]
        samples = latin_hypercube_sample(bounds, size=n_samples, seed=42)
        enrich_vals = [round(float(s[0]), 5) for s in samples]
        flow_vals = [round(float(s[1]), 2) for s in samples]
        power_vals = [round(float(s[2]), 2) for s in samples]

        if include_failure_test:
            # Append non-physical boundary row to verify failure visibility
            enrich_vals.append(-1.0)
            flow_vals.append(0.0)
            power_vals.append(999.0)

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
            "TITLE Generic Core Sensitivity Model\n"
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
            "if enrich <= 0 or flow <= 0:\n"
            "    sys.stderr.write('Physics Error: Non-physical parameters.\\n')\n"
            "    sys.exit(2)\n"
            "keff = 1.0000 + 1.25 * (enrich - 0.1975) - 0.00005 * (flow - 1200.0)\n"
            "peak_temp = 293.15 + (power * 1e6) / (flow * 4184.0) * 15.0\n"
            "with open('physics.log', 'w') as f:\n"
            "    f.write(f'Simulation Converged: final keff = {keff:.5f}\\n')\n"
            "    f.write(f'Maximum Fuel Temperature: {peak_temp:.2f} K\\n')\n"
        )
        stub_cmd = f"{sys.executable} {stub_file.resolve()}"

        # 4. Campaign Orchestration with Event Publishing and Shared Memory
        manifest = CampaignManifest(
            name="reactor_case_study",
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

        # 7. Post-Run Sensitivity Analysis & Bundle Export
        correlations = correlation_analysis(
            inputs={
                "ENRICH": [r.parameters["ENRICH"] for r in results if r.status == "SUCCESS"],
                "FLOW": [r.parameters["FLOW"] for r in results if r.status == "SUCCESS"],
                "POWER": [r.parameters["POWER"] for r in results if r.status == "SUCCESS"],
            },
            output=harvested_keffs,
        )

        bundle_path = work_root / "reactor_case_study.zip"
        campaign.export_bundle(bundle_path, results=results)
        print("Sensitivity Correlations:\n", correlations)
        return {"results": results, "correlations": correlations, "bundle": bundle_path}

if __name__ == "__main__":
    run_reactor_case_study()
```

---

## 14. Simulation-Based Optimization & Optional AI Integrations

### Optimization Controller (`labeeb.optimizer`)
The `Optimizer` proposes candidates inside declared bounds (full-factorial
`grid` or seeded per-index `random`), evaluates each through your objective
function — typically one `Case`/`Campaign` simulation — and records every
candidate (simulated, failed, or constraint-infeasible) into a durable,
exportable history:

```python
from tempfile import TemporaryDirectory
from labeeb import Constraint, Optimizer, export_optimization_history

def run_simulation(candidate):
    # normally: render a deck, launch a Case, harvest a metric; here a toy:
    return (candidate["T"] - 550.0) ** 2 + (candidate["flow"] - 8.0) ** 2

with TemporaryDirectory() as tmp:
    checkpoint = f"{tmp}/opt.json"
    opt = Optimizer(
        {"T": (400.0, 700.0), "flow": (0.0, 16.0)},   # search domain
        run_simulation,                               # one simulation per call
        direction="minimize",
        method="grid",                                # or "random" (seed=...)
        grid_points=5, budget=25,
        constraints=[Constraint("flow>=1", lambda c: c["flow"] >= 1.0)],
        checkpoint_path=checkpoint,                   # atomic JSON after each eval
        patience=9, tolerance=1e-6,                   # optional early stopping
    )
    result = opt.run()
    assert result.best_objective < 1e-6
    export_optimization_history(result, f"{tmp}/history.csv")

    # resume: skips the already-evaluated candidates and continues
    resumed = Optimizer(
        {"T": (400.0, 700.0), "flow": (0.0, 16.0)}, run_simulation,
        direction="minimize", method="grid", grid_points=5, budget=25,
        checkpoint_path=checkpoint, resume=True,
    )
    res_2 = resumed.run()
    assert res_2.cached > 0
```

### First-Class Campaign Optimization (`Campaign.optimize`)
A `Campaign` can directly optimize simulation parameters over manifest ranges or variable bounds by building and launching single-row cases, harvesting the target objective metric, applying feasibility constraints, and saving checkpoints:

```python
from labeeb import Campaign, CampaignManifest

manifest = CampaignManifest(
    name="reactor_opt",
    parameters={"POWER": [10.0, 50.0]},
    templates=["model.inp"],
    commands=["echo peak_temp > data.csv", "echo 450.0 >> data.csv"],
    execution={"shell": True},
)
campaign = Campaign(manifest)
res = campaign.optimize(
    objective_metric="peak_temp",
    direction="minimize",
    method="grid",
    grid_points=3,
    budget=5,
)
print("Best candidate:", res.best_candidate)
```

Semantics: `budget` counts *simulated* evaluations (successes + failures);
infeasible proposals and resume cache hits are free; `None`/exceptions/NaN
objectives are recorded as failures and never become the best; maximize via
`direction="maximize"`.

### Optional AI/ML integrations (`labeeb.ai`)
`labeeb.ai` layers external engines *without importing them at module load*
— the core stays lightweight, and missing engines raise
`OptimizationError` with an install hint:

* `SurrogateModel(["T", "flow"]).fit_from_history(result.history)` — a
  scikit-learn RandomForest regressor (or `"linear"`, or your own factory)
  fitted on optimizer history; `predict(candidate)` ranks candidates and
  `save()`/`SurrogateModel.load()` persists the model (versioned envelope).
  Requires: `pip install scikit-learn`.
* `optimize_scipy(objective, variables, method="Nelder-Mead", maxiter=...)`
  returns the same `OptimizeResult` shape as the core optimizer
  (direction-aware, failures recorded). Requires: `pip install scipy`.
* `optimize_optuna(objective, variables, n_trials=50, seed=42)` — seeded TPE
  study adapter with the same result shape. Requires: `pip install optuna`.
* `NeuralMLPSurrogate(var_names)` — optional PyTorch MLP surrogate
  (seeded, `fit_from_history`/`predict`/`save`/`load`).
  Requires: `pip install torch`.
* `BoTorchGPSurrogate(var_names)` — optional BoTorch single-task GP
  surrogate. Requires: `pip install botorch`.
* `rank_candidates(predictor, variables, n=100, method="random", seed=42,
  direction="minimize")` — pure-stdlib acquisition helper: samples candidates
  in the domain (seeded per-index random, or a grid), scores them with any
  fitted surrogate (`.predict`) or plain callable, and returns
  `[(prediction, candidate), ...]` sorted best-first and deterministic per
  seed — ready to plug into the next `Optimizer` round for surrogate-guided
  search. No engine required.

Runnable end-to-end example (core only, no engines needed):

```bash
python examples/optimize_ai_case_study.py   # Case per candidate, 7 runs
```

With `scikit-learn` installed the example additionally fits a RandomForest
surrogate on the history and prints `rank_candidates` top picks.

```python
# scikit-learn only: fit a surrogate on a finished optimization, then predict
from labeeb import Optimizer, SurrogateModel
toy = Optimizer({"T": (400.0, 700.0), "flow": (0.0, 15.0)},
                lambda c: 0.0, budget=2).run()
model = SurrogateModel(["T", "flow"], backend="rf", seed=1)
model.fit_from_history(toy.history)
model.save("/tmp/my_surrogate.pkl")
assert model.predict({"T": 550.0, "flow": 8.0}) < 1.0
```

Reproducibility is explicit: every stochastic engine accepts a `seed`, RF
uses `random_state=seed`/`n_jobs=1`, and Optuna's sampler is seeded.

## 15. Exception Hierarchy

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
| **`PublisherError`** | `labeeb.publisher` | Unrecoverable event publisher failure |
| **`BundleError`** | `labeeb.bundle` | Corrupt analysis bundle archive or missing bundle schema |

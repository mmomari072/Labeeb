# Labeeb v2.0.0 Migration & API Contract Guide

This guide details the **Labeeb v2.0.0 public API contract**, breaking changes, migration steps from v1.x, deprecations, and compatibility guarantees.

---

## 1. Migration Overview & Compatibility Guarantees

Labeeb v2.0.0 introduces a refined, Python-first public API centered around `Campaign`, `Case`, `Coupler`, `Database`, `Optimizer`, and `File`.

### Key Migration Principles
* **v1.x Compatibility**: Documented v1.x signatures remain fully supported during the v1.25 transition release. Deprecation warnings are emitted where signatures or behaviors will change in v2.0.0.
* **Additive Enhancements**: New features (such as database-aware derived attributes, safe assignment replacement, and correlated sampling) are additive and opt-in.
* **Domain Exceptions**: All error handling raises specific subclasses of `LabeebError` (`DatabaseError`, `SamplingError`, `CaseExecutionError`, `CouplingError`, `TemplateError`).

---

## 2. Core v2 Component Contracts

### 2.1 Campaign & Case
`Campaign` is the primary Python-first orchestration boundary. `Case` handles individual execution directories, template substitution, command launching, and output harvesting.

```python
from labeeb import Campaign, Case, Database

# API-first campaign creation
db = Database(name="study_db", data={"TEMP": [300.0, 350.0], "POWER": [10.0, 15.0]})
case = Case(name="thermal_sim", output_files={"out.csv": ["peak_temp"]})
case.database = db

campaign = Campaign(case=case, state_path="campaign_state.sqlite")
results = campaign.run()
```

### 2.2 Database & Derived Attributes
`Database` manages aligned `Attribute` columns. In v2, `add_derived_attribute` supports database-aware callbacks `(database, index)` for lag/prior-row or global calculations, along with automatic dependency tracking and cycle detection.

```python
from labeeb import Database

db = Database(data={"POWER": [10.0, 15.0, 20.0]})

# Row-level derived attribute
db.add_derived_attribute("POWER_KW", "POWER * 1000.0", unit="kW")

# Database-aware derived attribute reading prior row
def _power_delta(database, idx):
    if idx == 0:
        return 0.0
    return database["POWER"][idx] - database["POWER"][idx - 1]

db.add_derived_attribute("POWER_DELTA", _power_delta, context="database", dependencies=["POWER"])
```

### 2.3 File & Template Replacements
`File` provides safe line-structured assignment replacements (`replace_assignment`) and inline expression replacements (`replace_expressions`), preserving comments and formatting without arbitrary code execution.

```python
from labeeb import File

template = File(file_path="model.inp")
# Safe assignment replacement for x = value
template.replace_assignment("POWER", 50.0, preserve_format=True)
```

### 2.4 Coupler & CoupledUnit
`Coupler` coordinates multi-physics iterative loops between `Case` instances or nested `Coupler` instances, supporting typed under-relaxation, Aitken acceleration, divergence handling, and state serialization (`save_state` / `load_state`).

```python
from labeeb import Coupler

coupler = Coupler(name="neutronics_th")
# Add child units and set convergence controls
```

### 2.5 Optimizer & Sampling
`Optimizer` provides simulation-based optimization with grid or random sampling, constraint evaluation, and atomic checkpointing (`save_checkpoint` / `load_checkpoint`). Correlated (`correlated_normal_sample`) and truncated (`truncated_normal_sample`) normal sampling are available out of the box.

---

## 3. Breaking Changes & Deprecations (v1.x -> v2.0.0)

| Feature / API | v1.x Behavior | v2.0.0 Behavior | Migration Advice |
|---|---|---|---|
| `replace_assignment` | Single keyword replace | Assignment-aware (`x=val`) line replacement preserving comments | Use `file_obj.replace_assignment(key, val)` |
| Derived Attributes | Row-dict only (`row["ATTR"]`) | Context-aware (`context="row"` or `context="database"`) | Set `context="database"` when reading prior rows |
| Subprocess Commands | Defaulted to shell strings | `argv`/list `shell=False` default; explicit `shell=True` opt-in | Pass commands as list `["cmd", "arg"]` or set `shell=True` |
| Optional Dependencies | Hard imports in some modules | Lazy imports with clear installation hints | Install required extras e.g. `pip install labeeb[excel]` |

---

## 4. Result Schemas & Artifact Exports

* **`CaseResult`**: Sealed dataclass recording `case_id`, `status` (`SUCCESS`/`FAILED`), `exit_code`, `duration`, `parameters`, `outputs`, and `artifacts`.
* **`OutputCatalog`**: Append-only per-attempt ledger for audit trails.
* **`AnalysisBundle`**: Exportable JSON/ZIP bundle containing provenance hashes, manifest config, execution events, and results.

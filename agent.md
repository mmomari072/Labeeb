# AGENT.MD - AI Agent Operating Manual for Labeeb

> **Project**: Labeeb (لبيب)  
> **Purpose**: General-purpose Sensitivity & Uncertainty (S&U) analysis and simulation coupling API  
> **Domain**: Nuclear engineering (MCNP, RELAP5), thermo-hydraulics, neutronics, and general scientific computing relying on text-based input decks  
> **Author**: Eng. Mohammad Omari  

---

## 1. Project Overview & Philosophy

**Labeeb** is a Python API designed to orchestrate parameter sampling, input deck templating, automated execution of numerical simulation codes, output harvesting, and multi-physics iterative coupling.

### Key Architectural Pillars
1. **Lightweight Data Representation**: `Attribute` (typed 1D column with vectorized math and metadata) and `Database` (multi-column tabular data store with import/export capabilities).
2. **Flexible Parameter Sampling**: Grid sweeps via `FOATConstructor` (Full Factorial / One-At-A-Time) and statistical sampling via `DiscreteSampling`, `uniform_sample`, and `normal_sample`.
3. **Robust Template Processing**: Dual-mode text templating supporting:
   - Delimited placeholder replacement via `Flag` and `FlagsMap` (e.g. `#RHO#` $\rightarrow$ `19.25`).
   - Dynamic Jinja2 templating via `File.render_jinja()`.
4. **Execution & Directory Orchestration**: `Case` manages filesystem trees, input deck generation, executable launching, and output extraction.
5. **Coupling Kernel**: `Coupler` coordinates multi-code iterative runs (e.g., neutronics $\leftrightarrow$ thermal-hydraulics feedback loops) with user-defined convergence or step callbacks.

---

## 2. Repository Structure

```
Labeeb/
├── pyproject.toml              # Modern PEP 517/621 build configuration
├── README.md                   # User-facing overview, diagrams & examples
├── agent.md                    # Agent guidelines, architecture rules & instructions (this file)
├── ARCHITECTURE.md             # Detailed architectural deep-dive & dataflow specs
├── CONTRIBUTING.md             # Developer setup, coding standards & PR guidelines
├── src/
│   └── labeeb/
│       ├── __init__.py         # Package exports, versioning & startup banner
│       ├── database.py         # Attribute and Database core data models
│       ├── sampler.py          # Parametric and stochastic sampling utilities
│       ├── case.py             # Case, Flag, FlagsMap for execution orchestration
│       ├── coupler.py          # Coupler for multi-case iterative workflows
│       ├── coupled_unit.py     # CoupledUnit base + ConvergenceResult (shared by Case/Coupler)
│       ├── exceptions.py       # Domain-specific hierarchy of exceptions
│       └── utils/
│           ├── __init__.py     # Utility exports
│           ├── file_io.py      # File object, text parsing, Jinja rendering
│           ├── os_ops.py       # File system management, subdirectories, path safety
│           └── progress.py     # Progress indicators and status loggers
├── tests/
│   ├── test_case.py            # Unit tests for Case and Flags
│   ├── test_coupler.py         # Unit tests for Coupler workflows
│   ├── test_coupled_unit.py    # Unit tests for run_to_convergence, hooks, nesting
│   ├── test_database.py        # Unit tests for Attribute and Database
│   └── test_sampler.py         # Unit tests for sampling constructors
└── archive/                    # Archived legacy scripts, data, and reference materials
```

---

## 3. Core Module Specifications

### A. `labeeb.database`
* **`Attribute`**:
  * Wraps a 1D Python list/numpy array.
  * Encapsulates `name` (str) and `unit` (Optional[str]).
  * Implements rich comparison (`==`, `!=`, `<`, `<=`, `>`, `>=`) and arithmetic (`+`, `-`, `*`, `/`, `**`, `%`, `//`) operations yielding new `Attribute` instances.
* **`Database`**:
  * Dictionary-backed column store: `{attr_name: Attribute}`.
  * Ensures all columns maintain consistent row lengths.
  * Methods: `add_attribute()`, `get_row(index)`, `set_row(index, values)`, `to_dataframe()`, `export_to_file()`, `import_from_file()`.
  * Formats supported: `.csv`, `.xlsx`, `.parquet`, `.json`, `.pkl`.

### B. `labeeb.sampler`
* **`FOATConstructor`**:
  * Constructs parametric matrices / grid sweeps.
  * `add_case(dict_of_param_lists)` computes Cartesian product sweeps across parameter variants.
* **`DiscreteSampling`**:
  * Manages probability mass functions (PMF) and cumulative distribution functions (CDF).
  * Methods: `define_sample(values, probs)`, `get_random_sample(n)`, `stat(m)`.
* **Distribution Helpers**:
  * `uniform_sample(low, high, n)`
  * `normal_sample(loc, scale, n)`
  * `sample(dist_type, **params)`

### C. `labeeb.case`
* **`Flag`**:
  * Represents a placeholder token in input templates (e.g. name=`"#RHO#"`, attribute_name=`"RHO"`, fmt=`"%6.2f"`).
* **`FlagsMap`**:
  * Dictionary-like collection for mapping tokens to flags and setting values per iteration.
* **`Case`**:
  * Primary runner unit.
  * Properties: `database`, `FlagsMap`, `exe_cmd`, `run_case_main_dir`, `files`.
  * Lifecycle:
    1. Prepares target execution directories (`case_0`, `case_1`, ...).
    2. Injects formatted parameter values into template files.
    3. Executes CLI commands (`exe_cmd`) via subprocess.
    4. Gathers stdout/logs and records run states.

### D. `labeeb.coupler`
* **`Coupler`**:
  * Coordinates iterative coupling between multiple units -- `Case` instances, or nested `Coupler` instances for sub-coupling. `add_case()`/`add_cases()` accept either uniformly.
  * Allows registering coupling step callback functions via `add_coupling_functions()`; these fire exactly once per coupling pass, after every unit has reached its own convergence -- never per-unit mid-loop.
  * Per-unit convergence budget (`max_exec`/`check_fn`) is stored on the parent, keyed by child name (`set_unit_convergence()`), set at `add_case()` time and mutable between steps.
  * Manages iteration directories (`coupling_iteration_0`, `coupling_iteration_1`, ...; suffixed `_iterN` for repeated convergence passes over the same step).
  * Updates shared parameters across case boundaries.

### E. `labeeb.coupled_unit`
* **`CoupledUnit`**: shared base inherited by both `Case` and `Coupler`.
  * `run_to_convergence(max_exec, check_fn) -> ConvergenceResult`: repeats a single pass until `check_fn` returns `True` or `max_exec` is exhausted. Deliberately never reads `len(database)` -- row/scenario looping is owned exclusively by each subclass's own `launch()`.
  * `pre_functions`/`post_functions`: ordered lists, run around every pass.
  * Invariant: a parent's `check_fn` must only see a nested-`Coupler` child after that child's own `run_to_convergence` has fully resolved -- never mid-iteration.
* **`ConvergenceResult`**: dataclass (`unit`, `converged`, `executions`, `residual`) with `to_dict()`.

### F. `labeeb.exceptions`
* Base: `LabeebError`
* Subclasses: `DatabaseError`, `SamplingError`, `CaseExecutionError`, `CouplingError`.
* **Rule**: Always raise specific subclasses from `labeeb.exceptions` rather than generic `ValueError` or `RuntimeError` when handling domain logic errors.

---

## 4. Development & Testing Workflow

### Environment & Tools
* **Python**: $\ge 3.8$ compatible (tested up to Python 3.14).
* **Package Manager / Runner**: Standard pip or `uv`.

### Commands
```bash
# Run complete test suite
pytest

# Run tests with verbose output
pytest -v

# Run a specific test file
pytest tests/test_database.py

# Format & Lint
black src tests
isort src tests
flake8 src tests
```

---

## 5. Agent Implementation Guidelines & Rules

When modifying or expanding the Labeeb codebase, AI agents must adhere to the following principles:

1. **Preserve Clean Type Annotations**:
   * All public methods and functions must have type hints (`typing.List`, `typing.Dict`, `typing.Optional`, `typing.Union`, `typing.Any`).
2. **Error Handling**:
   * Use custom exceptions from `labeeb.exceptions`.
   * Include helpful error context in exception messages.
3. **File I/O Safety**:
   * Use `pathlib.Path` or `os.path` safely across OS platforms (Linux / macOS / Windows).
   * Ensure directory creation uses `exist_ok=True`.
   * Avoid unclosed file handles; use context managers or `labeeb.utils.file_io.File`.
4. **Subprocess & Simulation Safety**:
   * Ensure `Case` and `Coupler` handle missing executables gracefully with clear `CaseExecutionError` messages.
   * Provide timeout and logging options for long-running simulation codes.
5. **No Breaking Changes to Core API**:
   * Existing syntax documented in `README.md` must remain backward compatible.
   * Database indexing (`db.get_row()`, `db["ATTR"]`), Case execution (`runner.launch()`), and Coupler flows must maintain signature stability.
6. **Documentation & Tests**:
   * Every new feature or bug fix must be accompanied by corresponding unit tests under `tests/`.
   * Update `README.md`, `agent.md`, and `ARCHITECTURE.md` when extending public interfaces.

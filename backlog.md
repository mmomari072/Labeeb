# Labeeb Development Backlog & Roadmap

This document tracks the ongoing development roadmap, completed features, and upcoming tasks for **Labeeb**.

---

## 0. Release-Blocking Reliability Work

These items were identified during the August 2026 API review. They must be completed and covered by regression tests before using Labeeb to produce sensitivity or uncertainty results.

- [ ] **BL-001 — Restore declared Python compatibility**
  - Import `Tuple` in `labeeb.case` (or postpone annotation evaluation) so package import works on every supported Python version.
  - Replace or guard `ProcessPoolExecutor.shutdown(cancel_futures=...)` for Python 3.8 support, or raise the documented minimum Python version.
  - Add CI/import smoke tests for the minimum supported Python version.
- [ ] **BL-002 — Fail runs deterministically and preserve result alignment**
  - Raise `CaseExecutionError`, or return an explicit failed case result, when a simulator command returns non-zero or times out.
  - Treat declared-but-missing output files/columns as a failed case, or append a case-ID-indexed missing result with its failure status.
  - Guarantee one status/result record per input row; never silently shorten output vectors.
- [ ] **BL-003 — Prevent stale template substitutions**
  - Reset all `FlagsMap` values before each row, then validate that every required template flag has a value.
  - Raise a clear `CaseExecutionError` for missing mapped attributes rather than reusing a prior row's value.
- [ ] **BL-004 — Make coupling campaign coverage explicit**
  - Remove the hard-coded `i > 20` skip in `Coupler.launch`, or replace it with an explicit configurable limit that fails rather than omits work.
  - Add a regression test proving that a 22-row coupling database launches all 22 rows.
- [ ] **BL-005 — Validate uncertainty distributions**
  - Reject empty value sets, unequal lengths, non-finite or negative probabilities, and probability totals less than or equal to zero with `SamplingError`.
  - Normalize only valid weights and add deterministic seeding/injected RNG support for reproducible studies.

---

## 1. Practical Campaign Workflow

Implement these after the release blockers to make Labeeb suitable for repeatable local and HPC simulation studies.

- [ ] **PF-001 — Campaign manifests and provenance**
  - Define campaigns in validated YAML or JSON, including parameter space, templates, commands, random seed, and execution settings.
  - Record input-deck hashes, executable/environment metadata, package version, and timestamps for every case.
- [ ] **PF-002 — Structured, case-indexed results**
  - Introduce a `CaseResult` model containing parameters, status, exit code, duration, artifact paths, parsed metrics, and failure details.
  - Export a single case-indexed result table; retain failure records alongside successful results.
- [ ] **PF-003 — Resume, retry, and result caching**
  - Persist campaign state in SQLite or Parquet.
  - Resume incomplete campaigns, retry configured transient failures, and reuse cases with unchanged input hashes.
- [ ] **PF-004 — Pluggable execution backends**
  - Separate execution from `Case` behind a backend interface.
  - Support local processes first, then SLURM/PBS job submission and containerized execution.
- [ ] **PF-005 — Extensible output extractors**
  - Support CSV, JSON, regex/text, and user-supplied extractor functions.
  - Validate expected fields and units before admitting metrics into campaign results.
- [ ] **PF-006 — Configuration-first CLI**
  - Provide commands such as `labeeb validate`, `labeeb run campaign.yml`, `labeeb status`, and `labeeb resume`.

---

## 2. Advanced Sampling & Uncertainty Quantification (UQ)

- [ ] **PF-007 — Design-of-experiments & stochastic sampling**
  - Seeded Latin Hypercube Sampling (LHS) and Sobol/Halton low-discrepancy sequences.
  - Joint distributions and Gaussian copulas for correlated physical parameters (e.g. coolant density and temperature).
  - Bounded and truncated distributions (e.g. truncated normal, Weibull, log-normal).
- [ ] **PF-008 — Sensitivity & statistical analysis**
  - Global Sensitivity Analysis (GSA): Pearson/Spearman correlation coefficients, Morris screening method, and Sobol sensitivity indices ($S_i$, $S_{Ti}$).
  - Non-parametric tolerance limit calculator (**Wilks' formula**) for nuclear safety margins (e.g. 95/95 one-sided and two-sided criteria).
- [ ] **PF-009 — Automated scientific reports & visualization**
  - Interactive tornado charts, correlation heatmaps, and scatter matrices.
  - Automated HTML/PDF executive summary reports with convergence diagnostics and artifact links.

---

## 3. Database & Tabular Layer (`labeeb.database`)

- [x] **Lightweight Column Store**: `Attribute` class with typed 1D arrays and vectorized arithmetic/comparison operations.
- [x] **Multi-format Import/Export**: Support for `.csv`, `.xlsx`, `.parquet`, `.json`, and `.pkl`.
- [ ] **Legacy Method Porting (`labeeb.old2`)**:
  - Direct plotting capabilities (`db.plot(x_attr, y_attr)` with automatic unit labels and grid formatting).
  - Advanced Excel multi-sheet importing and exporting.
- [ ] **Deeper Pandas Integration**: Enhanced pandas DataFrame accessor utilities and column type coercion.

---

## 4. Templating & File Processing (`labeeb.utils.file_io`)

- [x] **Dual Templating Engine**:
  - **Delimited Placeholder Replacement**: Fast token substitution via `Flag` and `FlagsMap` (e.g., `#RHO#` $\rightarrow$ `19.25`).
  - **Jinja2 Rendering**: Dynamic templates with conditional logic and control flow via `File.render_jinja()`.
- [ ] **Custom Jinja2 Filters & Math Functions**:
  - Number formatters (e.g., `{{ RHO | fmt("%6.4f") }}`, scientific notation `5e`).
  - Built-in math functions (`cos()`, `sin()`, `exp()`, arithmetic combinations) accessible within templates.
- [ ] **Fixed-Width & Fortran Card Formatters**:
  - Strict column-aligned text formatting (e.g., 5-character / 10-character cards for legacy codes like MCNP and RELAP5) to prevent overflow errors.

---

## 5. Execution & Output Harvesting Engine (`labeeb.case`)

- [x] **Case Runner**: Directory tree generator (`case_0`, `case_1`, ...), input deck deployment, and subprocess execution.
- [ ] **Execution Failure Semantics**: Timeout handling, log capture, `CaseExecutionError`, and a reliable per-case success/failure contract. See BL-002.
- [ ] **Execution Status Registry**: Detailed tracking and database recording of exit codes, execution wall-clock time, and stdout/stderr status per case.
- [ ] **Declarative Output Harvesters**:
  - Declarative pattern extractors (`runner.add_harvester(name, pattern, file_target)`) that parse stdout/output files and append columns back into `Database`.
  - Built-in parsers for standard domain outputs (e.g. MCNP tallies / $k_{eff}$, RELAP5/TRACE strip charts, Serpent detector files, OpenMC HDF5 outputs).

---

## 6. Multi-Physics Coupling Kernel (`labeeb.coupler`)

- [ ] **Complete Iterative Coupling Loop**: Step-wise orchestration that executes every requested database row without silent limits. See BL-004.
- [x] **Step Callbacks & Shared Databases**: Parameter mapping and cross-case state propagation.
- [ ] **Coupling Stability & Relaxation Controls**:
  - Under-relaxation algorithms and Aitken $\Delta^2$ acceleration to dampen feedback oscillations between physics codes (e.g. neutronics $\leftrightarrow$ thermal-hydraulics).
  - Divergence detection and maximum-iteration failure semantics.
- [ ] **Hierarchical / Nested Progress Bars**: Subprogress indicators dedicated to coupling iteration steps and inner case runs.
- [ ] **Coupling State Serialization & Restart**: Checkpoint intermediate state snapshot tables (`coupling_state.parquet`) for resume and post-mortem analysis.

---

## 7. Project Governance & Artifacts

- [x] **Packaging**: Modern `pyproject.toml` (PEP 517/621) with `src/` layout.
- [x] **Unit Testing Suite**: `pytest` suite across database, sampling, case, and coupler modules.
- [x] **Documentation & Agent Manual**:
  - `agent.md` & `AGENTS.md` (Agent Operating Manual)
  - `ARCHITECTURE.md` (System Architecture & Dataflow)
  - `CONTRIBUTING.md` (Development Guidelines & Standards)
  - `backlog.md` (Feature Roadmap & Backlog)

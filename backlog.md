# Labeeb Development Backlog & Roadmap

This document tracks the ongoing development roadmap, completed features, and upcoming tasks for **Labeeb**.

## Release Milestones

| Release | Milestone scope | Release gate | Status |
|---|---|---|---|
| **v0.2.2** | Reliability: BL-001 through BL-005 | Full suite green, compatibility CI, no silent failures/skips, committed and pushed | Released |
| **v0.3.0** | Campaign foundation: PF-001 through PF-006 | Manifest-to-results end-to-end campaign, resume/retry evidence, local backend and CLI documented | Released |
| **v0.4.0** | API-first case studies and DOE foundation: PF-007 | Python Campaign runner, resumable case studies, seeded LHS and Halton designs | Released |
| **v0.5.0** | UQ and reporting: PF-008 through PF-009 | Sensitivity validation, tolerance limits, reproducible HTML report API | Released |
| **v1.0.0** | Stable production API | Compatibility freeze, migration policy, local workflow acceptance, tagged release | Released |

Release status is evidence-based: an item is **implemented**, **tested**, **verified**, and **committed/pushed** separately. A release is not complete until all four states are recorded.

v1.0 compatibility policy: names in `labeeb.__all__` and documented method
signatures are stable for the 1.x series. Additions are backward compatible;
removals or signature changes require a deprecation notice and a future major
release.

Logging API progress: v1.1 adds application-owned configuration, rotating file
handlers, and contextual command records; CLI verbosity flags remain secondary
follow-up work.

v1.3 adds typed `ExecutionEvent` records and JSON event export for API-driven
case-study auditing. v1.4 unifies the legacy execution helper and adds
incremental JSONL event persistence.

v1.5 completes the API-first observability milestone: campaign lifecycle and
failure events, retry-attempt correlation, optional stdout/stderr artifacts,
secret redaction, JSON logging, and concurrent-safe JSONL appends.

| **v1.5.0** | Comprehensive API observability and execution audit trail | Full suite green, redaction/lifecycle/retry/artifact/concurrency coverage, committed and pushed | Released |
| **v1.22.0** | Shareable campaign memory and live online analysis | Redacted bundle export, provider-neutral sharing, opt-in consent, non-blocking live figures, integrity and privacy tests | Released |
| **v1.24.0** | Optional integration dependencies | Excel/Parquet/plot extras, clear missing-engine guidance, focused and full suite green, committed and pushed | Release candidate |
| **v1.23.0** | Coupling reliability, nested progress, and secure execution | Coupling restart tests, progress-style compatibility tests, safe argv execution, full suite green, committed and pushed | Released |
| **v2.0.0** | Stable Python-first campaign, data, execution, and optimization contract | Derived attributes, expression templating, versioned result schemas, production backends, complete sampling/optimization APIs, migration guide, clean-install/Python matrix, independent QA, tagged release | Planned |

### v2.0.0 execution roadmap

The v2 plan and specification are maintained in
`docs/superpowers/plans/2026-09-03-v2-api-foundation.md` and
`docs/superpowers/specs/2026-09-03-v2-roadmap.md`.

- [ ] **V2-DB-01** — Database-aware derived attributes; owner: Hermes; dependency: none.
- [ ] **V2-TPL-01** — Safe expression-aware assignment templating; owner: AGY; dependency: none.
- [ ] **V2-DOC-01** — v2 API contract and migration guide; owner: Claude; dependency: none.
- [ ] **V2-EXEC-01** — Versioned execution/result contracts and production backends; dependency: V2-DOC-01.
- [ ] **V2-UQ-01** — Complete OAT/correlated/bounded sampling and benchmark validation; dependency: V2-DB-01.
- [ ] **V2-OPT-01** — First-class Campaign optimization integration and optional AI backends; dependency: V2-EXEC-01 and V2-UQ-01.
- [ ] **V2-REL-01** — Python matrix, clean install, API snapshots, case studies, independent QA, and v2 release; dependency: all prior tasks.

### PF-010 — Shareable campaign memory for online analysis

- [x] Add an API-first `MemoryShare`/campaign bundle export containing the
  manifest, provenance, parameters, case results, execution events, and opted-in
  logs/artifacts.
- [x] Redact secrets by default and require explicit opt-in before any network
  operation; preserve a local JSON/ZIP export that needs no provider.
- [x] Define a provider-neutral `share()` interface so online analysis services
  can be added without coupling the core package to one vendor.
- [x] Add integrity metadata, privacy tests, and a case-study example showing
  how an exported bundle can be consumed by an online analysis workflow.

### PF-011 — Non-blocking live variable plots

- [x] Provide an API-first observer/stream for selected variables and derived
  metrics while a campaign is executing.
- [x] Update online figures incrementally as results arrive without changing
  simulation inputs, convergence decisions, scheduling, or failure handling.
- [x] Isolate plotting and network work from the execution path so a slow or
  unavailable analysis client cannot pause or fail the campaign.
- [x] Support headless execution, bounded buffering, redacted data sharing, and
  tests proving execution results are identical with plotting enabled or off.
- [x] Define a provider-neutral `EventPublisher` API: implement durable JSONL
  publishing first, then optional WebSocket delivery for browser dashboards and
  Redis Streams for distributed/replayable consumers.
- [x] Treat raw sockets as an internal transport only if needed; do not use
  Memcached as the event channel because it is volatile and not replayable.

Acceptance evidence: focused online-analysis tests pass (52), the full suite
passes (358 passed, 11 skipped), and execution invariance was checked with
memory, JSONL publishing, and disabled live plotting.

---

## 0. Release-Blocking Reliability Work

These items were identified during the August 2026 API review. They must be completed and covered by regression tests before using Labeeb to produce sensitivity or uncertainty results.

- [x] **BL-001 — Restore declared Python compatibility**
  - Import `Tuple` in `labeeb.case` (or postpone annotation evaluation) so package import works on every supported Python version.
  - Replace or guard `ProcessPoolExecutor.shutdown(cancel_futures=...)` for Python 3.8 support, or raise the documented minimum Python version.
  - Add CI/import smoke tests for the minimum supported Python version.
  - Completed: imported `Tuple`, added a Python 3.8-compatible executor shutdown helper, added compatibility regression tests, and added a Python 3.8/3.14 CI matrix with import smoke coverage.
- [x] **BL-002 — Fail runs deterministically and preserve result alignment**
  - Raise `CaseExecutionError`, or return an explicit failed case result, when a simulator command returns non-zero or times out.
  - Treat declared-but-missing output files/columns as a failed case, or append a case-ID-indexed missing result with its failure status.
  - Guarantee one status/result record per input row; never silently shorten output vectors.
  - Completed: non-zero exits/timeouts and missing outputs raise `CaseExecutionError`; failed rows receive aligned `None` results and failure history records in serial and parallel launches.
- [x] **BL-003 — Prevent stale template substitutions**
  - Reset all `FlagsMap` values before each row, then validate that every required template flag has a value.
  - Raise a clear `CaseExecutionError` for missing mapped attributes rather than reusing a prior row's value.
  - Completed: typed and dictionary flag maps now reset and validate values; coupler partial mappings pass only active flags to child cases.
- [x] **BL-004 — Make coupling campaign coverage explicit**
  - Remove the hard-coded `i > 20` skip in `Coupler.launch`, or replace it with an explicit configurable limit that fails rather than omits work.
  - Add a regression test proving that a 22-row coupling database launches all 22 rows.
  - Completed: default launches cover every database row; `max_steps` now raises `CouplingError` when it would omit rows.
- [x] **BL-005 — Validate uncertainty distributions**
  - Reject empty value sets, unequal lengths, non-finite or negative probabilities, and probability totals less than or equal to zero with `SamplingError`.
  - Normalize only valid weights and add deterministic seeding/injected RNG support for reproducible studies.
  - Completed: validated weighted distributions and added injectable RNG support with regression coverage.

---

## 1. Practical Campaign Workflow

Implement these after the release blockers to make Labeeb suitable for repeatable local and HPC simulation studies.

- [x] **PF-001 — Campaign manifests and provenance**
  - Define campaigns in validated YAML or JSON, including parameter space, templates, commands, random seed, and execution settings.
  - Record input-deck hashes, executable/environment metadata, package version, and timestamps for every case.
  - Completed: added validated JSON/YAML `CampaignManifest`, deterministic manifest/template hashes, executable discovery metadata, and regression tests.
- [x] **PF-002 — Structured, case-indexed results**
  - Introduce a `CaseResult` model containing parameters, status, exit code, duration, artifact paths, parsed metrics, and failure details.
  - Export a single case-indexed result table; retain failure records alongside successful results.
  - Completed: added `CaseResult` and CSV/JSON/Parquet export while retaining failed cases in the result table.
- [x] **PF-003 — Resume, retry, and result caching**
  - Persist campaign state in SQLite or Parquet.
  - Resume incomplete campaigns, retry configured transient failures, and reuse cases with unchanged input hashes.
  - Completed: added SQLite-backed `CampaignStateStore` with durable attempts, pending-case discovery, retry budgets, and input-hash cache reuse.
- [x] **PF-004 — Pluggable execution backends**
  - Separate execution from `Case` behind a backend interface.
  - Support local processes first, then SLURM/PBS job submission and containerized execution.
  - Completed local foundation: added injectable `ExecutionBackend` and `LocalExecutionBackend`; scheduler/container backends remain follow-up extensions.
- [x] **PF-005 — Extensible output extractors**
  - Support CSV, JSON, regex/text, and user-supplied extractor functions.
  - Validate expected fields and units before admitting metrics into campaign results.
  - Completed: added built-in CSV/JSON/regex extractors, callable support, named Case harvesters, and missing-field errors.
- [x] **PF-006 — Configuration-first CLI**
  - Provide commands such as `labeeb validate`, `labeeb run campaign.yml`, `labeeb status`, and `labeeb resume`.
  - Completed: added the `labeeb` console entry point and validated local run/status/resume commands.

---

## 2. Advanced Sampling & Uncertainty Quantification (UQ)

- [x] **PF-007 — Design-of-experiments & stochastic sampling**
  - Seeded Latin Hypercube Sampling (LHS) and Halton low-discrepancy sequences.
  - Joint distributions and Gaussian copulas for correlated physical parameters (e.g. coolant density and temperature).
  - Bounded and truncated distributions (e.g. truncated normal, Weibull, log-normal).
  - Completed foundation: added the Python `Campaign` runner plus reproducible LHS and Halton APIs; correlated and specialized distributions remain v0.5 work.
- [x] **PF-008 — Sensitivity & statistical analysis**
  - Global Sensitivity Analysis (GSA): Pearson/Spearman correlation coefficients, Morris screening method, and Sobol sensitivity indices ($S_i$, $S_{Ti}$).
  - Non-parametric tolerance limit calculator (**Wilks' formula**) for nuclear safety margins (e.g. 95/95 one-sided and two-sided criteria).
  - Completed: added dependency-light Pearson/Spearman correlation, Morris screening, Saltelli Sobol estimates, and Wilks sample-size APIs.
- [x] **PF-009 — Automated scientific reports & visualization**
  - Interactive tornado charts, correlation heatmaps, and scatter matrices.
  - Automated HTML/PDF executive summary reports with convergence diagnostics and artifact links.
  - Completed foundation: added a self-contained HTML report writer; interactive charts and PDF generation remain future extensions.

---

## 3. Database & Tabular Layer (`labeeb.database`)

- [x] **Lightweight Column Store**: `Attribute` class with typed 1D arrays and vectorized arithmetic/comparison operations.
- [x] **Multi-format Import/Export**: Support for `.csv`, `.xlsx`, `.parquet`, `.json`, and `.pkl`.
- [ ] **Legacy Method Porting (`labeeb.old2`)**:
  - Direct plotting capabilities (`db.plot(x_attr, y_attr)` with automatic unit labels and grid formatting).
  - Advanced Excel multi-sheet importing and exporting.
- [ ] **Deeper Pandas Integration**: Enhanced pandas DataFrame accessor utilities and column type coercion.
- [ ] **Derived Function Attributes**:
  - Add an API such as `db.add_derived_attribute("x", lambda row: row["y"] + 1, dependencies=["y"])`.
  - Track dependencies and metadata, support vectorized evaluation, and
    recompute derived columns when source attributes change.
  - Validate missing dependencies and reject circular derived-attribute graphs.

---

## 4. Templating & File Processing (`labeeb.utils.file_io`)

- [x] **Dual Templating Engine**:
  - **Delimited Placeholder Replacement**: Fast token substitution via `Flag` and `FlagsMap` (e.g., `#RHO#` $\rightarrow$ `19.25`).
  - **Jinja2 Rendering**: Dynamic templates with conditional logic and control flow via `File.render_jinja()`.
- [ ] **Custom Jinja2 Filters & Math Functions**:
  - Number formatters (e.g., `{{ RHO | fmt("%6.4f") }}`, scientific notation `5e`).
  - Built-in math functions (`cos()`, `sin()`, `exp()`, arithmetic combinations) accessible within templates.
- [ ] **Expression-Aware Text Replacement**:
  - Search assignment-style records such as `x=1` (including configured
    whitespace/format variants) and replace only the value, e.g. `x=42`.
  - Support values computed from the case/database API while preserving the
    original key, separators, comments, and line structure.
  - Add safe matching, formatting controls, and regression tests for repeated
    keys, scientific notation, and missing assignments.
- [ ] **Fixed-Width & Fortran Card Formatters**:
  - Strict column-aligned text formatting for legacy fixed-width input cards to prevent overflow errors.

---

## 5. Execution & Output Harvesting Engine (`labeeb.case`)

- [x] **Case Runner**: Directory tree generator (`case_0`, `case_1`, ...), input deck deployment, and subprocess execution.
- [x] **Execution Failure Semantics**: Timeout handling, log capture, `CaseExecutionError`, and a reliable per-case success/failure contract. See BL-002; completed in the reliability milestone.
- [ ] **Execution Status Registry**: Detailed tracking and database recording of exit codes, execution wall-clock time, and stdout/stderr status per case.
- [ ] **Declarative Output Harvesters**:
  - Declarative pattern extractors (`runner.add_harvester(name, pattern, file_target)`) that parse stdout/output files and append columns back into `Database`.
  - Built-in parsers for common domain outputs such as tally files, strip charts, detector files, and HDF5 outputs.

---

## 6. Multi-Physics Coupling Kernel (`labeeb.coupler`)

- [x] **Complete Iterative Coupling Loop**: Step-wise orchestration that executes every requested database row without silent limits. See BL-004; completed in the reliability milestone.
- [x] **Step Callbacks & Shared Databases**: Parameter mapping and cross-case state propagation.
- [ ] **Coupling Stability & Relaxation Controls**:
  - Under-relaxation algorithms and Aitken $\Delta^2$ acceleration to dampen feedback oscillations between physics codes (e.g. neutronics $\leftrightarrow$ thermal-hydraulics).
  - Divergence detection and maximum-iteration failure semantics.
- [x] **Hierarchical / Nested Progress Bars**: Subprogress indicators dedicated to coupling iteration steps and inner case runs.
- [x] **Coupling State Serialization & Restart**: Checkpoint intermediate state snapshot tables (`coupling_state.parquet`) for resume and post-mortem analysis.

---

## 7. Project Governance & Artifacts

- [x] **Packaging**: Modern `pyproject.toml` (PEP 517/621) with `src/` layout.
- [x] **Unit Testing Suite**: `pytest` suite across database, sampling, case, and coupler modules.
- [x] **Documentation & Agent Manual**:
  - `agent.md` & `AGENTS.md` (Agent Operating Manual)
  - `ARCHITECTURE.md` (System Architecture & Dataflow)
  - `CONTRIBUTING.md` (Development Guidelines & Standards)
  - `backlog.md` (Feature Roadmap & Backlog)

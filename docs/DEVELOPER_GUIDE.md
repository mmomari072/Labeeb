# Labeeb Developer Guide

Companion to `README.md` (user-facing overview), `docs/USER_MANUAL.md` (API
manual with executable examples), `docs/V2_MIGRATION_GUIDE.md` (v2 API contracts & deprecations),
`ARCHITECTURE.md` (design specs), and `CONTRIBUTING.md` (setup/PR workflow). This guide is
written for developers extending Labeeb: it pins down the contracts, extension points, runtime
lifecycles, persistence and failure semantics, test conventions, compatibility rules, and
debugging recipes that are easy to get wrong.

Version scope: v1.24.0 feature surface, including the current LAB-* release gates.

---

## 1. Module Map & Architecture in One Page

```
labeeb/
  __init__.py      package exports + __all__ (public API surface)
  database.py      Attribute (typed 1D column) + Database (dict-backed tabular store)
  sampler.py       FOATConstructor, OATConstructor, DiscreteSampling, uniform/normal/halton/LHS samples
  case.py          Flag/FlagsMap, Case (runner), failure policies, harvesters wiring
  coupled_unit.py  CoupledUnit base + ConvergenceResult (Case & Coupler share it)
  coupler.py       Coupler: multi-code iterative coupling (units = Case or Coupler)
  campaign.py      CampaignManifest (validated config) + Campaign.run() orchestration
  execution.py     ExecutionBackend interface, LocalExecutionBackend, ExecutionEvent/Result,
                   export/append helpers (structured execution logging)
  logging_config.py  configure_logging, Json/Redacting formatters, CaseLoggerAdapter, redaction
  extractors.py    Harvester families (CSV/JSON/Regex/Excel/Callable), extract_* parse fns
  exceptions.py    LabeebError hierarchy (see ARCHITECTURE.md section 3)
  results.py       CaseResult, CampaignStateStore (SQLite resume/retry state),
                   export_case_results (CSV/JSON/Parquet/XLSX)
  outputs.py       OutputRecord + OutputCatalog (append-only per-attempt ledger)
  backup.py        create_backup/validate_backup/restore_backup (+ BackupManifest)
  bundle.py        AnalysisBundle export/load (JSON/ZIP, provenance hashes)
  analysis.py      analysis workflows over databases/results
  publisher.py     EventPublisher base + JSONL/WebSocket/Redis/Composite/Null adapters
  plot.py          PlotObserver + LivePlot (background-worker rendering)
  shared_memory.py SharedMemoryBackend, InMemorySharedBackend, CampaignMemory
  report.py        StatusRegistry + status symbols
  cli.py           thin CLI adapter over Campaign
  utils/progress.py Timer + ProgressBar: hierarchical indent rendering with
                   styles default/apt/powershell and a headless (non-TTY)
                   plain-line fallback; constructor signature preserved
tests/             pytest suite (see section 7)
docs/              USER_MANUAL.md (public), this guide, ARCHITECTURE.md
examples/          runnable case study (case_study_reactor_uncertainty.py)
```

Layering rule: `campaign` orchestrates; `case` runs one row and owns the
filesystem tree, templating, execution and harvest; `execution`/`publisher`/
`plot`/`logging_config` are the observable side effects (all opt-in, all
failure-isolated); `results`/`outputs`/`backup` are the persistence layer.
Modules import downward, never upward (`campaign` imports `case`; neither
`case` nor `outputs` import `campaign`). Public exports are centralized in
`__init__.py` and enumerated in `__all__`.

---

## 2. API Contracts & Stability Rules

Public API = everything imported in `src/labeeb/__init__.py` and listed in
`__all__` (importable as `from labeeb import X`), plus documented module-level
helpers (`labeeb.case.Case`, `labeeb.execution.*`, `labeeb.plot.*`,
`labeeb.extractors.*`, ...).

Hard rules (enforced by convention + tests):

1. **Never break a documented signature.** New behavior is additive:
   trailing keyword arguments with defaults (e.g. `Case(..., output_catalog=)`,
   `Campaign(..., live_plot=)`, `add_derived_attribute(..., context="row")`).
   Positional order of existing parameters is frozen.
2. **Every new public symbol needs**: import + `__all__` entry in
   `__init__.py`, a focused test importing it through `labeeb`, and a doc
   mention (README or USER_MANUAL). The `tests/test_public_api.py` suite checks
   export integrity.
3. **Domain errors, not generic ones.** Raise from `labeeb.exceptions`:
   `DatabaseError`, `SamplingError`, `CaseExecutionError` (with
   `TemplateError`), `CouplingError`, `ExtractionError`, `PublisherError`,
   `BackupError`, `SharedMemoryError` — all under `LabeebError`. Error messages
   carry the offending value and the remedy ("install with: pip install ...").
4. **Optional dependencies are optional.** Import pandas/matplotlib/openpyxl
   defensively at the point of use with a clear message or a documented
   `enabled=False` path (publisher adapters, plotting, Excel I/O). Never import
   an optional dep at module import time unless the package hard-depends on it.
5. **Persisted records stay round-trippable.** `OutputRecord.to_record()` /
   `from_record()` and `BackupManifest.to_dict()` / `from_dict()` are the
   canonical serializers for their stores; state rows are versioned with
   defaults so older records still load. When adding fields to a persisted
   record, give them defaults — old files must keep parsing.
6. **Type annotations** on every public method (Python >= 3.8 compatible
   typing, `Optional`/`Union` style used throughout).

---

## 3. Extension Points

### 3.1 Execution backends (`labeeb.execution`)

Contract to implement a scheduler/remote backend:

```python
class ExecutionBackend:                      # interface
    def run(self, command, cwd, timeout=None, log_file=None, shell=None) -> ExecutionResult: ...

class ExecutionResult:  returncode, stdout, stderr, duration_seconds,
                        timed_out: bool, event: ExecutionEvent | None
```

`command` is a string OR an argv sequence. The local backend is
secure-by-default: argv sequences run with `shell=False`; plain strings are
`shlex.split` into argv unless `shell=True` is explicit (per call, via
`LocalExecutionBackend(default_shell=True)`, `Case.shell`, or the manifest key
`execution.shell`). Injected/custom backends keep their own contract (Case
only forwards `shell=` to the local backend).

`LocalExecutionBackend` also honors `set_logger(command_logger)` so case
context (`case_id`/`unit`/`attempt`) flows into every `ExecutionEvent` and log
record. Inject your backend with `case.execution_backend = mine`; it must:

* return `returncode < 0` sentinel semantics: `-999` = timeout (with
  `timed_out=True`), `-1` = launch failure (OSError), anything else nonzero =
  command failure. `Case._execute` derives `TIMEOUT`/`FAILED`/`SUCCESS` from
  these.
* populate `result.event` (an `ExecutionEvent` with redacted `command`, cwd,
  status, byte counts, timing, `message`, `timed_out`) — the structured
  execution log depends on it.
* never raise on command failures (return results instead); structured
  emission `_emit_structured` is level-gated and failure-isolated.

### 3.2 Harvesters & output parsers (`labeeb.extractors`)

Every harvester subclasses `Harvester`:

| Harvester            | Constructor extras          | Parses            |
|----------------------|-----------------------------|-------------------|
| `CsvHarvester`       | `column`, `transform`, `optional` | CSV column list |
| `JsonHarvester`      | `key` (dotted), `transform`, `optional` | JSON path |
| `RegexHarvester`     | `pattern`, `transform`, `optional` | first capture group |
| `ExcelHarvester`     | `column`, `sheet`, `transform`, `optional` | XLSX/XLS column |
| `CallableHarvester`  | `extractor: Path -> Any`, `transform`, `optional` | arbitrary |

Rules:

* `harvest(base_dir="")` resolves `file_target` relative to `base_dir` (the
  case run directory) and raises `ExtractionError` for a missing file UNLESS
  `optional=True`, which returns `None`.
* `optional=True` is the explicit "discovery may fail" contract; a missing
  required output fails the case through `Case._read_outputs`.
* New parsers: add `extract_<fmt>(path, ...)` raising `ExtractionError`, an
  `XxxHarvester`, export both from `__init__.py`. Only `run_extractor`'s
  suffix dispatch needs touching if the tuple-spec path should auto-detect.

### 3.3 Publishers & observers (`labeeb.publisher`, `labeeb.plot`)

* `EventPublisher` base: `publish(event)` normalizes, buffers, dispatches to
  observers, then `_publish_impl`; bounded failure isolation (never raises).
  `add_observer` accepts `LiveObserver`, any object with `notify`, or a raw
  callable (wrapped); `remove_observer` is idempotent (identity/equality).
* `PlotObserver`/`LivePlot` are observer-style: `notify(event)` records
  numeric `metrics` (or `extract_fn` output) into history and wakes the render
  worker; rendering runs on a daemon thread (Agg/headless), throttled by
  `update_interval_seconds`, failure-isolated. Implement your own observer by
  exposing `notify(dict)`.
* `Campaign(..., live_plot=...)` or manifest `execution.live_plot` auto-attach
  to the campaign publisher and detach+close in `finally` (exception-safe).

### 3.4 Custom functions inside the sandbox (`utils.file_io`)

`evaluate_expression(expr, context, allow_custom_functions=True)` evaluates
mathematical expressions with an AST whitelist, no builtins, and redaction of
dunder/private names; `context` can carry your own callables (e.g. for deck
math). See `replace_assignments(evaluate_expressions=...)`,
`replace_expressions(context=...)`, and `Database.add_derived_attribute`
(expression strings, auto-inferred deps, vectorized mode).

### 3.5 Database/derived attributes & callbacks (`labeeb.database`)

`add_derived_attribute(name, function, dependencies=None, *, context="row"|"database",
unit=, description=, Type=, vectorized=)` — see USER_MANUAL. Row callbacks get
`row` dicts; `context="database"` callbacks get `(database, index=None)` and
may be dynamic (no declared deps -> refreshed conservatively). Callbacks
raising `TypeError` *inside* their body are re-invoked by the signature
dispatcher up to 3 times and the surfaced error can be misleading — keep
callback bodies free of data-driven TypeErrors.

### 3.6 Post-output hooks (`Case.add_post_output_hook`)

Hooks run between `_read_outputs()` and `post_functions` (after harvest,
before result finalization), in registration order, with `(outputs, case)` —
mutations honored, dict returns appended as new metric rows (auto-flowing
into catalog metrics via per-key deltas). Validation: callable + unique names
+ dict-or-None return. Hook exceptions follow `harvest_failure_policy`
(stop -> CaseExecutionError; continue -> recorded on
`case.post_output_hook_failures`, outputs kept, remaining hooks run).
Parallel workers each run their own copy; hook-created columns are union-merged
in `case_id` order.

### 3.7 Coupling stability & restart (`Coupler`)

`Coupler.relax()` mixes elementwise for scalar OR vector (list/tuple/numpy)
values via per-attribute omega; `enable_aitken(attr, min_iterations)` applies
Aitken delta-squared to the raw iterate sequence once enough history exists
(off by default; guarded denominator). Each coupling pass is atomic:
`Coupler._run_once` snapshots the shared row and restores it if the pass
raises `CouplingError` (divergence), so the database always holds the last
COMPLETE state; `run_to_convergence(error_on_max_exec=True)` exhaustion keeps
the final completed pass and records `last_convergence` before raising.
`save_state(path)`/`load_state(path)` serialize the shared row, c_step,
relaxation/Aitken controls, thresholds and unit budgets (atomic JSON write;
callables must be re-registered after load). `add_progress_callback(fn)`
registers observational callbacks fired once per complete pass with a
deep-copied snapshot (cannot mutate; exceptions swallowed); nested Couplers
report child-pass before parent-pass.

---

## 4. Lifecycle, Events & Timing

### 4.1 Case single row (`launch_case(case_id, _attempt=N)`)

1. Reset per-run state: `_case_failed=False`, `failure=None` (attempt markers).
2. Compute run dir `main_dir/run_case_main_dir/<run_case_sub_dir>_<id>`
   (append `_iter<attempt>` for repeated convergence passes).
3. Run `pre_functions`; if `new`, create the dir, copy `objects_to_be_copied`
   verbatim, build the flags map from row data, render input files
   (`_write_input`: flag replacement -> assignment replacement -> `${expr}`)
   into the case dir, then execute (`_execute`).
4. `_read_outputs()`: parse `output_files` CSV columns (required) and harvest
   declared harvesters into `case.outputs[<name>]` (one appended element per
   row, aligned with database rows).
5. Run `post_functions`.

Ordering guarantee: outputs discovered in the SAME dir the templates were
rendered into; retries of a case reuse `case_<id>_iter<N>` dirs, and every
attempt resets its failure markers.

### 4.2 Command execution & failure policies (`_execute`)

Per command: run through the injected backend; append an `execution_history`
entry (case_id, redacted command, exit code, status SUCCESS/TIMEOUT/FAILED,
duration, merged ExecutionEvent incl. `message`/`timed_out`). Failure handling:

* `command_failure_policy="stop"` (default): raise `CaseExecutionError`
  immediately.
* `"continue"`: mark `_case_failed` + `failure`, break out of remaining
  commands. `launch_case` returns normally; `Case.launch()` aggregates it;
  `Campaign.run()` records a FAILED `CaseResult`.
* `"retry"`: rerun up to `max_attempts`, appending a FAILED history entry per
  failed attempt; exhaustion behaves like `stop`.

`harvest_failure_policy="continue"` appends `None` outputs and marks the case
instead of raising; `_record_failed_case` is marker-guarded so outputs never get
double-recorded (row alignment invariant).

### 4.3 Campaign run loop (`Campaign.run()`)

For each row: cache-hit check (`state.should_reuse`), retry budget check
(`state.retry_allowed`), then execute the case and record. Lifecycle events
published through the publisher (or JSONL `events_file`):

`campaign_start`, `case_cache_hit`, `case_start`, `command` (from the
execution backend event), `case_complete`/`case_failure`, `campaign_complete`.

Event payloads carry `case_id`, `attempt`, `status`, parameters and duration.
Observers (plots) receive every payload; OutputCatalog gets one row per
executed attempt (see 6.2). Cleanup order on exit (including exceptions):
catalog + state stores close -> `campaign_complete` (success path) -> live plot
detach/close.

### 4.4 Live plot worker timing

`notify()` = history append only (non-blocking). Worker renders when dirty at
cadence; `flush()` forces a frame bypassing the cadence and waits bounded
(5 s) until render completes (`_rendering` in-flight flag); `close()` flushes,
stops and joins bounded, idempotent, ignores post-close events. No worker is
started when `enabled=False` or when no `output_path` is set.

---

## 5. Persistence Semantics

| Store | Shape | Write semantics | Resumability |
|---|---|---|---|
| `CampaignStateStore` (sqlite) | one row per case | UPSERT (latest result; `attempts` counter increments) | resume/retry across `run()` calls; input-hash reuse guard |
| `OutputCatalog` (sqlite) | one row per (case, attempt) | append-only, never overwrites | full attempt history queryable |
| `StatusRegistry` (memory/export) | per-case status | overwrite | export via `export_case_results` |
| backup dir | files + `manifest.json` | atomic staging + rename | validated checksums + sqlite quick_check |

Coexistence: `CampaignStateStore` and `OutputCatalog` can share one SQLite file
(distinct tables). Keep handles short-lived; state/catalog connections are
opened per `run()` and closed in `finally`.

### 5.1 CampaignStateStore details

`save(result, input_hash)`: attempts = previous+1; `get(case_id)` returns
`{case_id, input_hash, status, attempts, result, updated_at}`;
`should_reuse(case_id, hash)` true only for SUCCESS with matching hash;
`retry_allowed(case_id, max_retries)`.

### 5.2 OutputCatalog details

`record(OutputRecord)` inserts; `record_from_case(case, metrics=, artifacts=)`
catalogs the latest history entry and auto-links `stdout.log`/`stderr.log`;
`attempts(case_id)` ascending, `latest(case_id)`, `summary()`, `case_ids()`,
`all_records()`, `to_dataframe()`, `export(path)` (CSV/JSON/Parquet/XLSX).
Commands and messages are redacted at construction.

### 5.3 Backup & restore

`create_backup(dest, state_path=, artifacts=(), memory_snapshot=None,
overwrite=False)`: SQLite captured via the sqlite3 online-backup API from a
read-only connection (consistent snapshot, busy-retried) — never a live-file
copy; artifacts copied byte-for-byte; manifest.json (format `labeeb-backup`,
version 1, per-file SHA-256/size, shared-memory policy record). Destinations are
staged and atomically renamed; non-empty destinations are refused.
`validate_backup` re-checksums and runs `PRAGMA quick_check`;
`restore_backup` validates first, then restores DB via temp file + atomic
replace and artifacts per file. Shared-memory snapshots are explicit opt-in
(`memory_snapshot=` -> `shared_memory.json`), never implicit.

### 5.4 Export formats

`export_case_results(results, path)` and `OutputCatalog.export(path)` accept
`.csv`, `.json`, `.parquet`, `.xlsx` (openpyxl engine); everything else raises
`ValueError` listing the formats. `Database` export/import covers CSV/XLSX/
Parquet/JSON/pickle.

---

## 6. Failure & Observability Semantics

* Command failures: recorded, policy-dependent stop/continue/retry (see 4.2);
  timeouts return `-999` + `timed_out=True`; launch failures `-1`.
* Harvest failures: required files/columns/harvesters raise (default) or
  record `None` (`continue` policy); `optional=True` harvesters never raise for
  a missing file.
* Campaign failures: `run()` returns all results incl. FAILED (never raises
  per case); a campaign whose cases failed reports `campaign_status="FAILED"`
  via the final event. `Case.launch()` raises one aggregate
  `CaseExecutionError` after recording every failed case.
* Observer/publisher/plot/catalog errors are logged and skipped — never raised
  into the simulation.
* Structured logging: `configure_logging(json_format=True)` produces JSONL
  lines; execution records embed the full `ExecutionEvent` under `payload`.
  Redaction covers key/value secrets (`password=...`, `token=`, `api_key=`...)
  and CLI-flag secrets (`--api-key sk-1`, `-password x`); applied at every sink
  (log lines, JSON payloads, events, history, catalog rows). Disabled logging
  leaves execution untouched.

---

## 7. Testing Guide

Run: `python -m pytest` (whole suite) or `python -m pytest tests/test_X.py -q`
(focused). Full-suite time ~7 s; disk headroom check with `df -h /` when disk is
tight (<200 MB free: run focused files only).

Conventions that keep the suite honest:

* **Feature = file**: one focused test file per feature gate
  (`test_template_expressions.py`, `test_outputs_catalog.py`,
  `test_backup.py`, `test_failure_policy.py`, `test_live_plot_async.py`, ...).
* **Default-preservation tests**: when adding a knob, assert the old behavior
  still holds with defaults (e.g. `test_default_stop_raises_and_records`).
* **Executable manual examples**: doc snippets referenced as runnable must be
  executed. `tests/test_user_manual_snippets.py` mirrors USER_MANUAL sections
  3-13 as real tests (including `test_section_6_failure_handling_policies` for
  the policy docs and `test_section_7b_campaign_native_live_plot_example_runs_verbatim`,
  which `exec()`s the code block extracted verbatim from `USER_MANUAL.md`).
* **Fake the world, don't reach out**: commands are real but local
  (`printf`, `python -c ...`, deterministic transient-failure scripts writing a
  counter file); backends/publishers can be injected or monkeypatched
  (`monkeypatch.setattr(subprocess, "run", boom)`); temp dirs via `tmp_path`.
* **Concurrency care**: live-plot tests assert bounded wall-clock behavior and
  run 3x when timing-sensitive; thread-render completion is waited via
  `flush()`/`close()`; never assert on absolute mtimes.
* **Lint hygiene**: `flake8 --select=F,E9` on changed files (repo is not
  fully black/flake8-clean at 79 cols; keep new code clean, don't churn
  unrelated debt). Type-optional noise (pyright) is acceptable in tests when
  guarded by `assert x is not None`.

---

## 8. Compatibility, Contribution & Release

* Contribution workflow: see `CONTRIBUTING.md` (setup, standards, PR steps).
* Every change ships tests + docs (README, USER_MANUAL, ARCHITECTURE when the
  public surface moves) + `__init__` exports for new public names.
* Multi-agent pipeline convention (LAB-*): implementer commits a feature-tagged
  commit message (`feat(<area>): <summary> (LAB-XXXX-01)`), pushes to
  `origin/main`, and reports focused/full test evidence to the QA gate; QA is
  review-only with verbatim-example probes; fixes land as their own
  follow-up tasks. Queued work is acknowledged on the bus before starting.
* Release process: feature work accumulates on `main`; releases are tagged
  (`v1.x.y`) by the orchestrator after the QA gates pass. `__version__` lives
  in `src/labeeb/__init__.py`; bump it with the release.

---

## 9. Debugging Recipes

* Enable structured logs: `configure_logging(level="DEBUG", log_file="run.log",
  json_format=True)`; watch for the `execution <STATUS>` records with payload.
* Inspect stores read-only:
  `python -c "import sqlite3;c=sqlite3.connect('file:catalog.sqlite?mode=ro',uri=True);print(c.execute('select * from output_catalog').fetchall())"`.
* A case that "did nothing": check `execution_history` (events carry
  `message`/`timed_out`), run-dir `stdout.log`/`stderr.log` when
  `capture_output=True`, and `_read_outputs` (harvesters resolve relative to
  `current_case_dir`).
* Timeouts report `-999`; OSError launch failures `-1`; nonexistent shell
  binaries via `shell=True` surface as exit 127 FAILED, not OSError.
* Redaction false positives (e.g. `-secretary`): pattern requires whitespace
  after a keyword flag; re-check with `redact_sensitive()` directly.
* Worker-thread plot issues: `flush()`/`close()` are bounded (5 s); if an image
  is missing after `with LivePlot(...)`, a render raised earlier — logs carry
  the warning; a monkeypatched `_render` that raises is caught by the worker
  loop (belt-and-braces) and logged.
* Concurrency misalignment in `case.outputs`: continue-policy failures must not
  double-append Nones (`_record_failed_case` is marker-guarded); row outputs
  align one element per database row.

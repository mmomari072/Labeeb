# Labeeb v2.0.0 API Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define and implement the v2 public API foundations needed for database-aware derived attributes, expression-aware templating, and a controlled migration from v1.x.

**Architecture:** v2 keeps `Campaign` as the Python-first orchestration boundary and makes `Database` and `File` the reusable data/template primitives. New behavior is additive during the v1.25 development cycle, with explicit v2 contract tests and migration documentation before any removals or signature changes.

**Tech Stack:** Python >=3.8, pathlib, pytest, existing `Database`, `Attribute`, `File`, `Campaign`, and custom Labeeb exceptions.

**Spec:** `docs/superpowers/specs/2026-09-03-v2-roadmap.md`

## Global Constraints

- Python >=3.8 compatibility is mandatory.
- Python APIs are primary; CLI changes are secondary adapters.
- Preserve documented v1 behavior until the v2 migration boundary is explicitly approved.
- Every public change requires focused tests and user/developer documentation.
- Use domain-specific exceptions from `labeeb.exceptions`.
- Do not modify `uv.lock`, unrelated untracked files, or another worker's owned paths.
- Each completed task must be committed and pushed with exact test evidence.

### Task 1: Database-aware derived attributes

**Files:**
- Modify: `src/labeeb/database.py`
- Modify: `src/labeeb/exceptions.py` only if a specific validation error is required
- Test: `tests/test_database.py` or a focused `tests/test_derived_attributes.py`
- Update: `README.md`, `docs/USER_MANUAL.md`, `ARCHITECTURE.md`

**Interface:** `Database.add_derived_attribute(name: str, func: Callable[[Database, int], Any], *, dependencies: Optional[Sequence[str]] = None, unit: Optional[str] = None) -> Attribute`. The callback receives the database and current row index, so it can read prior rows. Dependencies are validated and cycles rejected.

- [ ] Write tests for current-row calculation, previous-row access, optional index compatibility, missing dependencies, cycle detection, recomputation after source updates, and metadata.
- [ ] Run the focused tests and confirm the new behavior fails before implementation.
- [ ] Implement dependency validation, deterministic evaluation order, and derived-column recomputation without breaking ordinary attributes.
- [ ] Run focused database tests and the full suite.
- [ ] Update API examples and commit only owned files.

### Task 2: Expression-aware template replacement

**Files:**
- Modify: `src/labeeb/utils/file_io.py`
- Modify: `src/labeeb/case.py` only for the public Case adapter, if needed
- Test: `tests/test_file_io.py` and/or `tests/test_expression_templating.py`
- Update: `README.md`, `docs/USER_MANUAL.md`, `ARCHITECTURE.md`

**Interface:** `File.replace_assignment(key: str, value: Any, *, occurrence: Union[int, str] = "all", preserve_format: bool = True) -> str`, replacing only assignment values such as `x=1`, `x = 1`, or scientific notation while preserving separators, comments, and line structure.

- [ ] Write tests for whitespace variants, repeated keys, comments, scientific notation, missing keys, and formatted numeric values.
- [ ] Run focused tests and confirm the new behavior fails.
- [ ] Implement safe line-based matching with no arbitrary expression execution.
- [ ] Run focused and full tests, then document the API-first usage.
- [ ] Commit and push the owned implementation.

### Task 3: v2 API contract and migration documentation

**Files:**
- Create: `docs/V2_MIGRATION_GUIDE.md`
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `docs/DEVELOPER_GUIDE.md`
- Test: `tests/test_documentation_contract.py`

**Interface:** Document the v2 contract for `Campaign`, `Case`, `Coupler`, `Database`, `Optimizer`, result schemas, errors, optional extras, deprecations, and migration examples. Documentation snippets must be executable where practical.

- [ ] Write documentation tests for required headings, version policy, migration examples, and absence of forbidden project-specific references.
- [ ] Run documentation tests and confirm missing contract sections fail.
- [ ] Add the migration guide and architecture contract with explicit v1 compatibility rules.
- [ ] Run documentation and full tests, then commit and push.

### Task 4: Production execution and result contract

**Files:** `src/labeeb/execution.py`, `src/labeeb/case.py`, `src/labeeb/results.py`, focused tests, and API docs.

- [ ] Define versioned `CaseResult`/execution event schemas and compatibility tests.
- [ ] Add cancellation/interruption and a backend contract for local, scheduler, and container implementations.
- [ ] Verify retry, timeout, failure, resume, and output-catalog invariants.
- [ ] Add scheduler/container adapters only after the interface contract is stable.

### Task 5: Complete scientific sampling and optimization APIs

**Files:** `src/labeeb/sampler.py`, `src/labeeb/optimizer.py`, `src/labeeb/analysis.py`, focused tests, and API docs.

- [ ] Add per-attribute OAT strategies, correlated distributions, and bounded/truncated distributions.
- [ ] Integrate objectives, constraints, checkpoints, and resumable optimization into `Campaign`.
- [ ] Add reproducible benchmark fixtures for sampling, sensitivity, and optimization correctness.

### Task 6: v2 release gates

**Files:** `pyproject.toml`, CI configuration, release notes, all public docs, and release tests.

- [ ] Add Python 3.8 through current CI and clean-install smoke tests.
- [ ] Add `py.typed`, API surface snapshots, dependency-extra tests, and reproducibility benchmarks.
- [ ] Publish v2 migration notes and at least three executable API case studies.
- [ ] Require focused tests, full suite, `git diff --check`, clean-install smoke test, review/QA PASS, a signed release commit, and an annotated `v2.0.0` tag.

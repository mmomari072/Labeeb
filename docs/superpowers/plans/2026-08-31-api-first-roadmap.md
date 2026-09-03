# Labeeb API-First Execution Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the remaining Labeeb backlog as small, independently tested API milestones, with live analysis isolated from simulation execution.

**Architecture:** Keep the Python API as the source of truth. Derived data, execution status, harvesters, coupling controls, and online analysis expose typed interfaces; CLI and network transports remain thin adapters. Persist durable state locally first, then publish optional non-blocking updates to external consumers.

**Tech Stack:** Python >=3.8, pathlib, dataclasses, SQLite/JSONL, pytest, optional pandas/Jinja2, optional WebSocket and Redis integrations.

**Spec:** `backlog.md` and `AGENTS.md`

## Global Constraints

- Preserve documented 1.x public signatures and backward compatibility.
- Every public API addition has type annotations and regression tests.
- Use domain-specific exceptions for invalid database, template, execution, and coupling operations.
- Network and plotting observers must never alter or block simulation execution.
- Redact secrets by default before persistence or sharing.
- Shared-worktree changes use precise staging and leave unrelated edits untouched.

---

## Roadmap and Dependencies

| Phase | Deliverable | Owner | Dependency | Gate |
|---|---|---|---|---|
| A | Derived database attributes and expression templating | Codex | Current `File.replace_assignments()` | Focused + full tests |
| B | Execution status registry and status export | agy `%4` | Existing `ExecutionEvent`/`CaseResult` | API tests + review |
| C | Declarative harvesters and domain parser hooks | Codex | B | Failure-alignment tests |
| D | Coupling relaxation, divergence, progress, restart | Codex + agy review | B/C interfaces | Deterministic convergence tests |
| E | Memory bundles, `EventPublisher`, live plots | Codex | B/C | Offline, redaction, non-blocking tests |
| F | Legacy database/pandas, Jinja filters, Fortran formatters | Follow-up | A/E | Compatibility suite |

## Task 1: Finish derived database attributes

**Files:** `src/labeeb/database.py`, `tests/test_database.py`, `README.md`, `ARCHITECTURE.md`.

- [ ] Add a typed `Database.add_derived_attribute(name, function, dependencies)` API.
- [ ] Write failing tests for row and vector evaluation, metadata, recomputation, missing dependencies, and cycles.
- [ ] Implement dependency validation and deterministic recomputation without changing ordinary attribute behavior.
- [ ] Run `pytest tests/test_database.py -q` and then the full suite.
- [ ] Request code review and commit only owned files.

## Task 2: Finish expression-aware templating

**Files:** `src/labeeb/utils/file_io.py`, `tests/test_case.py`, `README.md`.

- [ ] Add strict/missing-assignment behavior and configurable numeric formatting to `replace_assignments()`.
- [ ] Cover repeated keys, scientific notation, comments, separators, whitespace, and absent assignments.
- [ ] Run focused tests, full tests, and `git diff --check`.

## Task 3: Execution status registry — agy implementation slice

**Files:** `src/labeeb/results.py`, `src/labeeb/campaign.py`, `tests/test_campaign_api.py`, `README.md`.

- [ ] Add a typed status record keyed by `case_id` and `attempt`, retaining status, return code, duration, timestamps, artifact paths, and failure text.
- [ ] Persist status updates transactionally alongside `CampaignStateStore` and expose a read-only API for in-progress analysis.
- [ ] Preserve failed and retried rows; do not change execution control decisions.
- [ ] Add tests for success, timeout, failure, retry, resume, and concurrent read access.
- [ ] Report files changed, focused/full test output, and commit hash before handoff.

## Task 4: Declarative output harvesters

**Files:** `src/labeeb/case.py`, `src/labeeb/results.py`, `tests/test_case.py`, `tests/test_campaign_api.py`.

- [ ] Define a harvester protocol returning named values or a domain exception.
- [ ] Implement regex/text, CSV, and JSON harvesters with declared units and missing-field failures.
- [ ] Attach harvested metrics to aligned `CaseResult` records without shortening failed campaigns.
- [ ] Add extension hooks for external simulation-code adapters without requiring those tools at import time.

## Task 5: Coupling stability and restart

**Files:** `src/labeeb/coupler.py`, `src/labeeb/coupled_unit.py`, `tests/test_coupler.py`, `tests/test_coupled_unit.py`.

- [ ] Add typed under-relaxation and Aitken controls with deterministic defaults.
- [ ] Detect divergence and exhausted iterations using `CouplingError` and preserve the last complete state.
- [ ] Serialize/restore coupling state and expose nested progress callbacks that are observational only.
- [ ] Prove callback ordering, restart equivalence, and no silent row omission.

## Task 6: Shareable memory and live analysis

**Files:** create `src/labeeb/memory.py` and `src/labeeb/publishing.py`; modify `src/labeeb/campaign.py`, `tests/test_memory.py`, `tests/test_publishing.py`, `README.md`.

- [ ] Export a redacted local JSON/ZIP bundle containing manifest, provenance, results, events, and opted-in artifacts.
- [ ] Define `EventPublisher.publish(event) -> None` with bounded, asynchronous failure isolation.
- [ ] Implement JSONL first, then optional WebSocket and Redis Streams adapters; never use Memcached as the event channel.
- [ ] Add live variable observers and figure updates that cannot block or mutate execution.
- [ ] Test disabled/offline publishers, redaction, replay, buffering, and result equivalence with plotting enabled or disabled.

## Review and Release Gates

- [ ] After each task: focused tests, full suite, diff check, API review, and QA/security review.
- [ ] Verify reported, landed, tested, reviewed, committed, and pushed states separately.
- [ ] Release `v1.6.0` only after Tasks 1–6 meet their gates; defer optional integrations if they do not meet the no-blocking requirement.

# Online Campaign Analysis Milestone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and complete Labeeb’s API-first campaign memory and non-blocking live-analysis capabilities for reproducible online study workflows.

**Architecture:** Keep execution authoritative and move observation, persistence, and sharing to opt-in components. `CampaignMemory` and `MemoryShare` provide local, redacted bundles; `EventPublisher` provides durable event delivery; `PlotObserver` consumes events/results asynchronously and must never affect case scheduling or failure decisions.

**Tech Stack:** Python >=3.8, standard library, SQLite/JSONL, pytest, optional matplotlib/pandas integrations.

**Spec:** `backlog.md` sections PF-010 and PF-011.

## Global Constraints

- Python-first APIs are primary; CLI remains a thin adapter.
- Network sharing is opt-in; local export must work without a provider.
- Secrets are redacted by default.
- Plotting/publishing failures cannot fail or pause campaign execution.
- Preserve existing public signatures and simulator-neutral documentation.
- Every change requires focused tests, relevant regression tests, and a commit.

### Task 1: Verify campaign memory and sharing

**Files:**
- Inspect: `src/labeeb/shared_memory.py`, `src/labeeb/backup.py`, `src/labeeb/campaign.py`
- Test: `tests/test_shared_memory.py`, `tests/test_backup.py`
- Docs: `docs/USER_MANUAL.md`, `docs/DEVELOPER_GUIDE.md`

**Interfaces:** Confirm `CampaignMemory.snapshot()` and bundle export include manifest/provenance/results/events plus explicit memory opt-in; confirm redaction, integrity metadata, and local-only operation.

- [ ] Run focused memory/backup tests and inspect persisted bundle contents.
- [ ] Add only missing tests or implementation for redaction, integrity failure, opt-in memory, and provider-neutral export.
- [ ] Update user/developer documentation with one Python example.
- [ ] Run focused tests and commit the verified changes.

### Task 2: Verify non-blocking live analysis

**Files:**
- Inspect: `src/labeeb/plot.py`, `src/labeeb/publisher.py`, `src/labeeb/campaign.py`
- Test: `tests/test_plot.py`, `tests/test_publisher.py`, `tests/test_campaign.py`
- Docs: `docs/USER_MANUAL.md`, `docs/DEVELOPER_GUIDE.md`

**Interfaces:** Confirm `PlotObserver`/`LivePlot` and `EventPublisher` are opt-in, bounded, headless-safe, and isolate rendering/publishing exceptions from execution.

- [ ] Run focused observer/publisher/campaign tests.
- [ ] Add only missing tests for identical campaign results with observers enabled/disabled and slow/failing observers.
- [ ] Document JSONL as the durable baseline and mark WebSocket/Redis as optional future transports.
- [ ] Run focused tests and commit the verified changes.

### Task 3: Independent integration QA

**Files:**
- Inspect all files changed by Tasks 1–2.
- Test: full `tests/` suite and runnable examples.

**Interfaces:** Validate that the public exports, campaign lifecycle, failure policies, state/catalog persistence, memory bundles, event streams, and live plots compose without changing results.

- [ ] Run full pytest and `git diff --check`.
- [ ] Run at least one API-first campaign example with memory/export and one with live plotting.
- [ ] Report PASS/FAIL with exact commands, files, and blockers; make no source edits.

### Task 4: Release gate

- [ ] Update `backlog.md` to reflect verified PF-010/PF-011 status.
- [ ] Align package/docs version metadata.
- [ ] Run the full release test gate.
- [ ] Create and push the next minor release tag only after Tasks 1–3 pass.

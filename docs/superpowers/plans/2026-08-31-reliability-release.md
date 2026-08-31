# Reliability Release Implementation Plan

> **For agentic workers:** Execute this plan inline with test-first verification and preserve unrelated shared-worktree changes.

**Goal:** Finish the release-blocking reliability backlog and define explicit Labeeb milestones and release gates.

**Architecture:** Harden the existing `DiscreteSampling` validation and RNG boundary without changing its public sampling shape. Record milestone scope and release gates in `backlog.md`, then verify the complete package before committing and pushing.

**Tech Stack:** Python 3.8+, NumPy, pytest, GitHub Actions.

**Spec:** `backlog.md` release-blocking reliability work and milestone section.

## Global Constraints

- Preserve the declared `requires-python = ">=3.8"` contract.
- Use `SamplingError` for invalid distribution configuration.
- Preserve existing public API return shapes and compatibility defaults.
- Run focused tests, the full suite, and `git diff --check` before release.

### Task 1: Validate discrete distributions

**Files:** Modify `src/labeeb/sampler.py`; test `tests/test_sampler.py`.

- [ ] Add failing tests for empty values, length mismatch, negative/non-finite probabilities, and non-positive totals.
- [ ] Implement validation and deterministic RNG injection while preserving default behavior.
- [ ] Run focused and full tests.

### Task 2: Record milestones and release gates

**Files:** Modify `backlog.md`.

- [ ] Add v0.2.2, v0.3.0, v0.4.0, and v1.0.0 milestone scopes with explicit acceptance gates.
- [ ] Mark BL-005 complete only after tests pass.

### Task 3: Release verification and delivery

**Files:** All owned changes in the working tree.

- [ ] Run the full suite and `git diff --check`.
- [ ] Commit the reliability release changes.
- [ ] Push the current branch to `origin`.

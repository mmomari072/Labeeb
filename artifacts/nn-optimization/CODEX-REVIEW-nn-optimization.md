# Codex Review: NN/Online Optimization in Labeeb

**Date**: 2026-09-03  
**For**: Codex (architecture decision)  
**Status**: Requires guidance before Phase 2 case study finalization  

---

## Executive Summary

User wants to add **iterative surrogate-based optimization** (online learning) to Labeeb for the production reactor case study. This feature already exists in backlog as **V2-OPT-01** but is vague and deferred to v2.0. Need architectural decision on scope and timing.

---

## What User Is Requesting

**Iterative Online Learning Loop:**

```python
# Batch 1: Initial exploration
labeeb.run_campaign(initial_10_cases) → results_10

# Iteration 1: Train surrogate, predict next case
surrogate.train(results_10)
next_case = optimizer.predict_next()
labeeb.run_campaign(next_case) → results_11

# Iteration 2: Re-train, predict again
surrogate.train(results_11)
next_case = optimizer.predict_next()
labeeb.run_campaign(next_case) → results_12

# Continue until converged or budget exhausted
```

**Key characteristics:**
- Sequential (not parallel)
- Adaptive (next batch depends on previous results)
- Surrogate-based (NN or Gaussian Process)
- Optimization objective (find best parameters)

---

## Why It Matters

**Reactor case study comparison:**

| Approach | Cases | Time | Coverage | Method |
|----------|-------|------|----------|--------|
| Manual (old way) | ~20 hand-picked | 2 weeks | 25% | Ad-hoc |
| FOAT (current plan) | 81 cases | 1 hour | 100% | Full factorial |
| **Online (proposed)** | **~35 cases** | **1 hour** | **100%** | **Adaptive search** |

**Impact story strength:**
- FOAT: "81 cases, 4× more coverage than manual"
- Online: "35 cases finds optimum, 57% fewer evaluations than FOAT"

---

## What's Already in Backlog

**From `backlog.md` line 51:**

```
- [ ] **V2-OPT-01** — First-class Campaign optimization integration 
      and optional AI backends; dependency: V2-EXEC-01 and V2-UQ-01.
```

**Status**: NOT STARTED  
**Scope**: Deliberately vague ("integration", "optional")  
**Dependencies**: Requires v2 execution/UQ contracts first  
**Timeline**: Planned for v2.0.0 (future major release)

---

## The Gap

V2-OPT-01 likely means:
- "Run fixed campaign, optimize offline" (design once, execute once, analyze for optimum)

User is asking for:
- "Run adaptive campaign, optimize online" (design iteratively, learn continuously)

**Architectural conflict:**
- **Labeeb today**: Manifest upfront → parallel execution → offline analysis ✓
- **Online learning**: Batch 1 → analyze → Batch 2 → analyze → Batch 3 → ... ✗

Current Labeeb design is **not optimized** for sequential, adaptive workflows.

---

## Three Architecture Options

### Option A: Built into Labeeb Core (v1.25)

**Pros:**
- Integrated API: `campaign.run_adaptive(initial_cases=10, optimizer=...)`
- Full Labeeb lifecycle support (memory, bundles, events)
- Users don't learn two packages

**Cons:**
- Adds sequential mode alongside parallel mode (complexity)
- Changes core execution model
- Testing burden increases (adaptive + all existing features)
- Non-blocking observers become tricky in sequential mode

### Option B: Separate Layer `labeeb-online` (Recommended)

**Pros:**
- Keeps Labeeb pure (parallel, offline)
- `labeeb-online` orchestrates the loop
- Clear separation of concerns
- Users opt-in, existing workflows unaffected
- Lower risk

**Cons:**
- Two packages to learn
- Integration points must be explicit (bundle export, re-import)
- Slightly higher setup for users

**Architecture:**
```
User code:
  │
  ├─ labeeb (campaigns 1, 2, 3, ...)
  │  - Parallel execution
  │  - Bundle export
  │
  └─ labeeb-online (orchestrator)
     - Train surrogate
     - Predict next batch
     - Call labeeb campaign
     - Re-train on combined results
```

### Option C: External (Users Bring Optimizer)

**Pros:**
- No new Labeeb code
- Users choose optimizer (Optuna, PyMC, custom)

**Cons:**
- No first-party support
- Integration friction
- Poor case study narrative ("DIY" doesn't inspire)

---

## Recommendation

**Option B** (`labeeb-online` separate package) is lowest risk and highest clarity:

1. **Case study Phase 2**: Build NN surrogate + online optimizer as *example* (not built-in)
2. **Document as pattern**: "How to do adaptive optimization with Labeeb"
3. **Propose `labeeb-online`** as v1.25 feature (post v1.20.7)
4. **Clarify V2-OPT-01** in v2 planning docs to distinguish offline vs. online

---

## Proposal for Case Study

**Reactor sensitivity analysis (3 variants):**

1. **Phase 1 (done)**: Define synthetic case, parameter ranges
2. **Phase 2a (current plan)**: Run 81-case FOAT → Sobol indices
3. **Phase 2b (proposed)**: Run adaptive 35-case search → find optimum
4. **Phase 3**: Compare results, discuss tradeoffs

**Blog post sections:**
- Traditional: "81 cases, 14× faster than manual, comprehensive coverage"
- Adaptive: "35 cases, finds optimum in half the evaluations, faster convergence"
- Conclusion: "Choose based on your goal: explore space or optimize"

---

## Decision Questions for Codex

1. **Timing**: Is online learning v1.25 or truly v2.0+?
2. **Scope**: Built-in, separate package, or external?
3. **Case study**: Include adaptive demo or stick with FOAT?
4. **V2-OPT-01**: Should we clarify/split this item in the backlog?

---

## Files to Review

- `backlog.md` (line 51: V2-OPT-01)
- `docs/superpowers/plans/2026-09-03-case-study-implementation.md` (reactor case study, Phase 2)
- `docs/superpowers/plans/2026-09-03-nn-optimization-discovery.md` (initial discovery doc)
- This file: `docs/superpowers/plans/CODEX-REVIEW-nn-optimization.md`

---

## Next Steps

**If Option B (separate package) is approved:**
1. Create `docs/superpowers/plans/2026-09-03-labeeb-online-design.md` (detailed spec)
2. Add Phase 2b to case study (35-case adaptive search example)
3. Scope `labeeb-online` as v1.25 feature
4. Update backlog with clarified V2-OPT-01

**If Option A or C preferred:**
- Codex to provide alternative design doc and timeline

---

**Waiting for decision:** Case study Phase 2 scope depends on this architectural choice.

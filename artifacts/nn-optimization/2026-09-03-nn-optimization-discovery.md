# NN/Online Optimization Discovery for Labeeb

**Date**: 2026-09-03  
**Source**: User request during case study planning  
**Status**: Flagged for architectural decision  

---

## What the User Wants

**Online/Adaptive Learning for Optimization:**

```
Batch 1: Run 10 initial cases → Train surrogate
Batch 2: Predict next promising point → Run 1 case → Re-train
Batch 3: Predict next point → Run 1 case → Re-train
... (iterate until converged or budget exhausted)
```

This is **Bayesian optimization** or **active learning**—not traditional campaign execution.

---

## What's Already in Backlog

From `backlog.md` line 51:

```
- [ ] **V2-OPT-01** — First-class Campaign optimization integration 
      and optional AI backends; dependency: V2-EXEC-01 and V2-UQ-01.
```

**Status**: Planned for v2.0.0, NOT STARTED  
**Dependencies**: Must complete v2 execution/UQ contracts first  
**Scope**: "Integration" and "optional AI backends" (deliberately vague)

---

## The Gap

**V2-OPT-01 says "optimization integration"**  
**User is asking for "iterative surrogate-based optimization"**

These are related but different:
- V2-OPT-01: Likely offline optimization (run fixed campaign, optimize on results)
- User request: Online optimization (design campaign iteratively)

**Architectural conflict:**
- Labeeb today: Upfront manifest → parallel execution → offline analysis
- Online learning: Batch 1 → decide → Batch 2 → decide → Batch 3 → ...

---

## Reactor Case Study Impact

**If added to case study (Phase 2):**

```
Initial FOAT (planned):   81 cases, full factorial
With online learning:     35 cases, adaptive search
Result:                   57% fewer evaluations, same optimum found
```

**Stronger story:** "Found optimum in 35 cases instead of 81"

---

## Recommendations for Codex

1. **Timing**: Is online learning v1.25 feature or truly v2.0+?
2. **Scope**: Should it be:
   - Labeeb core (built-in)?
   - Separate layer `labeeb-online` (recommended)?
   - External (users bring their own optimizer)?
3. **Case study**: Include online learning demo or defer?
4. **V2-OPT-01**: Does this discovery clarify or expand that item?

---

## Related Files to Review

- `backlog.md` (line 51: V2-OPT-01)
- `docs/superpowers/plans/2026-09-03-case-study-implementation.md` (Phase 2 placeholder)
- `docs/TRAINING.md` (Module 6: does it cover optimization?)


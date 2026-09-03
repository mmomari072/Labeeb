# NN/Surrogate-Based Optimization in Labeeb - Claude's Evaluation

**Date**: 2026-09-03  
**Assessment**: Online learning for optimization is worthwhile, but **not core to Labeeb**.

---

## The Real Story

Labeeb's strength is **sampling + execution + SA/UA analysis**.

Online learning (iterative surrogate-based optimization) is a **different problem entirely**—it's not about understanding parameter sensitivity; it's about finding the best parameters as fast as possible.

These are complementary, not merged.

---

## My Honest Assessment

### YES, Do It — But Externally

**Why online learning matters:**
- For expensive simulators (1 hour/case), you can't afford 81 cases
- 35-case adaptive search finds the optimum in half the evaluations
- The story is compelling: "Smart sampling beats brute force"

**Why NOT put it in Labeeb core:**
- Labeeb's design assumes "upfront manifest → parallel execution"
- Online learning needs "analyze → decide → execute → repeat" (sequential)
- Forcing sequential into a parallel architecture = complexity, confusion, bugs
- The non-blocking observer system becomes useless in sequential mode
- Testing burden doubles (everything with/without adaptation)

**Why external is better:**
- Labeeb stays focused: "Run your campaign, analyze the results"
- External layer handles: "Plan next batch, call Labeeb, re-train, repeat"
- Users who need adaptation import it; others never know it exists
- Each layer is testable, understandable, maintainable independently

---

## The Clean Architecture

```
labeeb (core)
├─ Campaign execution (parallel)
├─ Bundle export (results + manifest + provenance)
└─ SA/UA analysis (Sobol, Wilks)

labeeb-online (new layer, opt-in)
├─ Surrogate training (NN, GP, etc.)
├─ Acquisition function (uncertainty, EI, etc.)
└─ Orchestration loop (batch 1 → train → predict → batch 2 → ...)
    (calls labeeb campaigns internally)

User code
├─ Initial design (10 cases via labeeb-online)
├─ Loop iterations (via labeeb-online)
├─ Final analysis (via labeeb)
└─ Report
```

This is **clean, composable, testable**.

---

## For the Reactor Case Study

**Do BOTH, tell different stories:**

1. **Traditional FOAT** (81 cases)
   - Story: "Comprehensive coverage, understand all parameters via Sobol"
   - Use when: You want to explore the full space, publish indices

2. **Adaptive Search** (35 cases via online learning)
   - Story: "Fast optimization, find the best configuration"
   - Use when: You have an objective, budget is tight

**Blog post structure:**
- "Two approaches to sensitivity and optimization"
- FOAT: "When you need to understand the landscape"
- Adaptive: "When you need to find the peak"
- Conclusion: "Labeeb handles both workflows"

This positions Labeeb as the **foundation**, not the solution to everything.

---

## Timeline Recommendation

**v1.20.7 (now):** Publish reactor case study with FOAT only
- 81 cases, Sobol indices
- Strong story, no NN dependency
- Ship it in 2–3 weeks

**v1.25 (next):** Add labeeb-online package
- Separate repository or subdirectory
- Orchestrates adaptive campaigns
- Use reactor case study Phase 2 as demo

**v2.0 (later):** Integrate tighter if users demand it
- By then, you'll know exactly what integration looks like
- Can make informed API choices
- No rushed decisions

---

## Why This Matters

Scope creep kills projects. Labeeb is already strong—parameter sweeps, SA/UA, reproducible bundles, live plotting. Adding online learning now:
- Delays case study (real opportunity cost)
- Doubles testing surface area
- Muddles the message ("Is Labeeb for exploration or optimization?")

Keeping it separate:
- Ship case study in 3 weeks
- Prove Labeeb adoption
- Then build online learning *on top* with clear integration points
- Users with optimization needs can use both; exploratory users ignore labeeb-online

---

## Bottom Line

✅ **YES**: Build online learning. It's valuable.  
❌ **NO**: Don't merge it into Labeeb core.  
✅ **YES**: Create `labeeb-online` as separate layer.  
✅ **YES**: Use reactor case study to demo both workflows.  

**Ship reactor FOAT case study first (v1.20.7).**  
**Then build labeeb-online (v1.25).**  

Don't let perfect be the enemy of good.


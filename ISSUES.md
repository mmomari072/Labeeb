# Known Issues & Pending Tasks

## [OPEN] OATConstructor with Multiple Attributes Produces Baseline+OAT Instead of Factorial Design

**Priority:** Medium  
**Date Reported:** 2026-09-16  
**Status:** Ready for Implementation

### Problem
When using multiple OAT attributes in Database construction, the current `OATConstructor` produces a "baseline + one-at-a-time" design instead of a factorial Cartesian product.

### Example
```python
db = Database(
    attributes=[
        Attribute("z", sampling=OAT([1, 2, 3])),
        Attribute("kk", sampling=OAT([3, 6])),
    ],
    n=1,
    seed=42,
)
```

#### Current Output (4 rows)
```
z:  [1, 2, 3, 1]     ← baseline z=1, vary z, then revert to z=1 for kk variation
kk: [3, 3, 3, 6]     ← baseline kk=3, then vary kk
```

#### Expected Output (6 rows - Factorial)
```
z:  [1, 2, 3, 1, 2, 3]   ← all z values for each kk
kk: [3, 3, 3, 6, 6, 6]   ← repeat for each kk value
```

### Root Cause
`OATConstructor.construct()` (sampler.py:256-285) implements Morris screening design:
- 1 baseline row
- n-1 rows for each parameter's variations from baseline
- Total: 1 + sum(n_i - 1) = 1 + (3-1) + (2-1) = 4 rows

This is correct for sensitivity analysis but wrong for parametric sweeps with multiple discrete factors.

### Expected Behavior
With multiple OAT attributes, produce all combinations (Cartesian product):
- Total rows: product(n_i) = 3 × 2 = 6 rows
- Each parameter cycles through all values at each level of other parameters

### Affected Code
- `src/labeeb/sampler.py`: `OATConstructor.construct()` (lines 256-285)
- `src/labeeb/database.py`: `_construct_from_attributes()` uses OATConstructor result

### Solution
Modify OATConstructor to detect multiple OAT attributes and produce factorial design instead of baseline+OAT design.

### Implementation Notes
- Single OAT attribute: Keep baseline+OAT behavior (1 + (n-1) rows) for Morris screening compatibility
- Multiple OAT attributes: Switch to factorial design (product of all n_i values)
- Update tests and documentation to reflect new behavior

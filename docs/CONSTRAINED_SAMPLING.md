# Constrained Sampling with Row-by-Row Validation Filtering

## Overview

Starting in v2.3.8, Labeeb supports **row-by-row validation filtering** during Database sampling. This enables you to validate constraints after each row is generated and derived, without needing post-hoc filtering.

## Why Row-by-Row Validation?

### Traditional Approach (Before v2.3.8)
```python
# Generate n samples, then filter
db = Database(attributes=[...], n=1000)
valid_rows = [i for i in range(len(db)) if is_valid_constraint(db.get_row(i))]
# Problem: You might end up with fewer than expected rows
# Inefficient: Generate samples you'll throw away
```

### New Approach (v2.3.8+)
```python
# Validate during sampling, get exactly n valid rows
db = Database(
    attributes=[...],
    n=100,
    row_filter=lambda row: is_valid_constraint(row)
)
# Result: Exactly 100 rows, all valid
```

## Usage

### Basic Example

```python
from labeeb import Database, Attribute, Uniform, Derived, Constant

db = Database(
    name="constrained_example",
    attributes=[
        Attribute("thickness_1", sampling=Uniform(1, 20)),
        Attribute("thickness_2", sampling=Uniform(1, 20)),
        Attribute("total", sampling=Derived(
            lambda row: row["thickness_1"] + row["thickness_2"]
        )),
    ],
    n=50,
    seed=42,
    # Constraint: total thickness must be > 15
    row_filter=lambda row: row["total"] > 15,
    max_rejections=5000,
)

print(f"Generated {len(db)} valid rows")
print(f"Acceptance rate: {db.sampling_stats['acceptance_rate']:.1%}")
```

### Complex Multi-Parameter Constraints

```python
MAX_THICKNESS = 50

db = Database(
    name="shield_design",
    attributes=[
        Attribute("material_id", sampling=Constant(1)),
        Attribute("shd_1", sampling=Uniform(1, 20)),
        Attribute("shd_2", sampling=Uniform(1, 20)),
        Attribute("shd_3", sampling=Uniform(1, 20)),
        Attribute("shd_4", sampling=Derived(
            lambda row: MAX_THICKNESS - (row["shd_1"] + row["shd_2"] + row["shd_3"])
        )),
    ],
    n=100,
    seed=123,
    row_filter=lambda row: all([
        # All thicknesses positive
        row["shd_1"] > 0,
        row["shd_2"] > 0,
        row["shd_3"] > 0,
        row["shd_4"] > 0,
        # Total within bounds
        (row["shd_1"] + row["shd_2"] + row["shd_3"] + row["shd_4"]) <= MAX_THICKNESS,
        # Additional physical constraint
        row["shd_1"] + row["shd_4"] >= 15,
    ]),
    max_rejections=10000,
)

print(f"Valid configurations: {len(db)}")
print(f"Acceptance rate: {db.sampling_stats['acceptance_rate']:.1%}")
print(f"Total attempts: {db.sampling_stats['total_attempts']}")
```

## How It Works

### Execution Flow

1. **Sample**: Each non-derived attribute is sampled independently
2. **Derive**: All derived attributes are evaluated using the sampled values
3. **Validate**: The `row_filter` function is called with the complete row
4. **Keep/Reject**: 
   - If filter returns `True`: Row is kept
   - If filter returns `False`: Row is discarded
5. **Repeat**: Continue until exactly `n` valid rows are collected

### Example Trace

```
Attempt 1: Sample t1=5, t2=8 → Derive total=13 → Validate (13 > 15)? ✗ Reject
Attempt 2: Sample t1=9, t2=12 → Derive total=21 → Validate (21 > 15)? ✓ Keep (1/100)
Attempt 3: Sample t1=4, t2=6 → Derive total=10 → Validate (10 > 15)? ✗ Reject
Attempt 4: Sample t1=11, t2=10 → Derive total=21 → Validate (21 > 15)? ✓ Keep (2/100)
...
Attempt 120: Sample t1=8, t2=9 → Derive total=17 → Validate (17 > 15)? ✓ Keep (100/100) ✓ DONE
```

## Sampling Statistics

After construction, access statistics via `db.sampling_stats`:

```python
stats = db.sampling_stats
print(f"Total attempts: {stats['total_attempts']}")      # How many rows were tried
print(f"Total accepted: {stats['total_accepted']}")      # How many passed filter
print(f"Total rejected: {stats['total_rejected']}")      # How many failed filter
print(f"Acceptance rate: {stats['acceptance_rate']:.1%}") # Percentage that passed
```

**Typical Output:**
```
Total attempts: 120
Total accepted: 100
Total rejected: 20
Acceptance rate: 83.3%
```

## Best Practices

### 1. Keep Filters Reasonable

```python
# ✓ Good: Simple, fast to evaluate
row_filter=lambda row: row["total"] > 15

# ✓ Good: Multiple independent checks
row_filter=lambda row: row["x"] > 0 and row["y"] < 100

# ⚠️ Warning: Very restrictive filter (< 1% acceptance)
row_filter=lambda row: row["x"] > 99.9 and row["y"] < 0.01  # Likely to time out
```

### 2. Monitor Acceptance Rate

```python
if db.sampling_stats['acceptance_rate'] < 0.5:
    logger.warning(f"Low acceptance rate: {db.sampling_stats['acceptance_rate']:.1%}")
    # Consider: relax filter, increase n, or adjust sampling bounds
```

### 3. Use Derived Attributes for Constraints

```python
# ✓ Good: Constraint depends on derived attribute
Attribute("total", sampling=Derived(lambda row: row["a"] + row["b"])),
row_filter=lambda row: row["total"] > 100

# Less ideal: Computing constraint in filter every time
row_filter=lambda row: row["a"] + row["b"] > 100
```

### 4. Set Appropriate max_rejections

```python
# Default: n * 100 (e.g., for n=100, max_rejections=10,000)
# If acceptance rate ~80%, expect ~12,500 attempts to get 100 valid samples
# This provides a good safety margin

# Conservative approach
db = Database(
    attributes=[...],
    n=50,
    row_filter=lambda row: ...,
    max_rejections=100000,  # Explicit high limit for tight constraints
)
```

## Error Handling

### Constraint Rejection Limit Exceeded

```python
try:
    db = Database(
        attributes=[...],
        n=100,
        row_filter=lambda row: row["x"] > 99.99,  # Very tight!
        max_rejections=5000,
    )
except DatabaseError as e:
    print(f"Too many rejections: {e}")
    # Solution: Relax filter or increase max_rejections
```

### Filter Function Errors

```python
# If row_filter raises an exception, the row is treated as rejected
# This is safe but you should catch errors in your filter:

def safe_filter(row):
    try:
        return row["a"] / row["b"] > 0.5  # Could divide by zero
    except (ZeroDivisionError, KeyError):
        return False  # Explicit rejection

db = Database(
    attributes=[...],
    n=100,
    row_filter=safe_filter,
)
```

## Performance Considerations

### Acceptance Rate Impact

| Acceptance Rate | Attempts for n=100 | Overhead |
|---|---|---|
| 99% | ~101 | Minimal |
| 90% | ~111 | Low |
| 80% | ~125 | Moderate |
| 50% | ~200 | Significant |
| 10% | ~1,000 | High |
| 1% | ~10,000 | Very High |

### Optimization Tips

1. **Simplify filter logic** - Avoid expensive computations in the filter
2. **Order checks** - Put cheap checks first, expensive ones last
3. **Profile filter** - Use `cProfile` to identify bottlenecks
4. **Consider sampling bounds** - Tighten uniform/normal bounds to increase acceptance

```python
# Instead of:
row_filter=lambda row: row["x"] > 90 and row["x"] < 100  # 10% acceptance

# Do:
Attribute("x", sampling=Uniform(90, 100)),  # Already bounded
row_filter=lambda row: True  # No filter needed or simpler filter
```

## Comparison with Alternatives

### Option 1: Row-by-Row Filtering (Recommended)
```python
db = Database(
    attributes=[...],
    n=100,
    row_filter=lambda row: constraint(row),
)
```
- ✓ Natural fit with Derived attributes
- ✓ No wasted sampling
- ✓ Automatic statistics tracking
- ✓ Clean API

### Option 2: Post-Hoc Filtering (Traditional)
```python
db = Database(attributes=[...], n=150)
valid_indices = [i for i in range(len(db)) if constraint(db.get_row(i))]
# Might have only 100 valid rows instead of 150
```
- ✗ Unpredictable output size
- ✗ Wasted computation
- ✓ Simpler for very tight constraints

### Option 3: Adjust Sampling Bounds
```python
db = Database(
    attributes=[
        Attribute("x", sampling=Uniform(90, 100)),  # Pre-filtered!
    ],
    n=100,
)
```
- ✓ Most efficient if you know bounds
- ✓ No filtering needed
- ✗ Requires domain knowledge

## Examples

### Shield Thickness Design

```python
from labeeb import Database, Attribute, Uniform, Derived, Constant

db = Database(
    name="shielding_constrained",
    attributes=[
        Attribute("materials", sampling=Constant([31, 25, 30, 7])),
        Attribute("shd_1_thk", sampling=Uniform(1, 30)),
        Attribute("shd_2_thk", sampling=Uniform(1, 30)),
        Attribute("shd_3_thk", sampling=Uniform(1, 30)),
        Attribute("shd_4_thk", sampling=Derived(
            lambda row: 100 - (row["shd_1_thk"] + row["shd_2_thk"] + row["shd_3_thk"])
        )),
        Attribute("total_shielding", sampling=Derived(
            lambda row: sum([row[f"shd_{i}_thk"] for i in range(1, 5)])
        )),
    ],
    n=50,
    row_filter=lambda row: all([
        row["shd_1_thk"] > 0,
        row["shd_2_thk"] > 0,
        row["shd_3_thk"] > 0,
        row["shd_4_thk"] > 0,
        row["total_shielding"] <= 100,
    ]),
    max_rejections=5000,
)

print(f"Feasible designs: {len(db)}")
print(f"Efficiency: {db.sampling_stats['acceptance_rate']:.1%}")
```

### Boundary-Layer Reynolds Number

```python
db = Database(
    name="fluid_dynamics",
    attributes=[
        Attribute("velocity", sampling=Uniform(0.5, 10)),      # m/s
        Attribute("length", sampling=Uniform(0.01, 1.0)),      # m
        Attribute("viscosity", sampling=Constant(1e-5)),       # m²/s
        Attribute("reynolds", sampling=Derived(
            lambda row: (row["velocity"] * row["length"]) / row["viscosity"]
        )),
    ],
    n=200,
    row_filter=lambda row: 1e4 <= row["reynolds"] <= 1e6,  # Turbulent range
    max_rejections=2000,
)

print(f"Turbulent cases: {len(db)}")
```

## Troubleshooting

| Issue | Solution |
|---|---|
| "Row filter rejected all rows" | Relax filter constraints or adjust sampling bounds |
| "Too many consecutive rejections" | Increase `max_rejections` or simplify filter |
| Acceptance rate < 50% | Consider alternative constraint formulation |
| Performance degradation | Profile filter function, move expensive checks to Derived attributes |


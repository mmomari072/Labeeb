# Merging and Consolidating Results (v2.3.8+)

## Overview

The new `labeeb.merge` module provides utilities to consolidate results from multiple campaigns, runs, or iterations. This enables cross-run analysis, sensitivity studies, and multi-configuration validation.

## Quick Start

```python
from labeeb import Campaign, export_case_results
from labeeb.merge import merge_case_results, validate_merge, export_merge_report

# Run campaigns
campaigns = [Campaign(manifest1).run(), Campaign(manifest2).run()]

# Export results
df1 = export_case_results(campaigns[0].results, "campaign1.csv")
df2 = export_case_results(campaigns[1].results, "campaign2.csv")

# Merge with campaign tracking
merged = merge_case_results([df1, df2], campaign_ids=["ConfigA", "ConfigB"])

# Validate
assert validate_merge(merged)['valid']

# Export
export_merge_report(merged, "final_results.csv")
```

## Available Functions

### merge_case_results()

Combine results from multiple campaigns into a single DataFrame.

```python
from labeeb.merge import merge_case_results

# Basic usage
merged = merge_case_results([df1, df2, df3])

# With campaign identifiers
merged = merge_case_results(
    results_dfs=[df1, df2, df3],
    campaign_ids=["Baseline", "Optimized_v1", "Optimized_v2"],
    reset_index=True,
)
```

**Parameters:**
- `results_dfs`: List of DataFrames from `export_case_results()`
- `campaign_ids`: Optional list of campaign names (same length as dfs)
- `reset_index`: Reset pandas index after concatenation

**Returns:** Merged DataFrame with all cases and optional campaign_id column

---

### merge_case_info_json()

Extract and consolidate metadata from multiple `case_info.json` files.

```python
from labeeb.merge import merge_case_info_json
from pathlib import Path

# Merge metadata from directories
case_dirs = [
    Path("/runs/case_0"),
    Path("/runs/case_1"),
    Path("/runs/case_2"),
]

merged_metadata = merge_case_info_json(case_dirs)
```

**Extracts:**
- Case ID and name
- Execution status and timing
- Per-command execution details
- Parameter values
- Output values

**Returns:** DataFrame with consolidated case metadata

---

### merge_outputs_with_parameters()

Combine case outputs with input parameters into a single DataFrame.

```python
from labeeb.merge import merge_outputs_with_parameters

# After campaign.run()
output_df = merge_outputs_with_parameters(
    campaign=campaign,
    output_format="flat",  # or "nested"
)
```

**Parameters:**
- `campaign`: Executed Campaign instance
- `output_format`: 
  - `"flat"`: Parameters expanded as individual columns
  - `"nested"`: Parameters kept as dict columns

**Returns:** DataFrame combining inputs, outputs, and execution metadata

---

### aggregate_by_parameters()

Group results by parameter values and apply aggregations.

```python
from labeeb.merge import aggregate_by_parameters

summary = aggregate_by_parameters(
    df=merged_results,
    group_by=["thickness_1", "thickness_2"],
    agg_columns={
        "response": "mean",
        "case_id": "count",
        "duration_seconds": "sum",
        "status": lambda x: (x == "SUCCESS").sum(),
    }
)
```

**Parameters:**
- `df`: Merged DataFrame
- `group_by`: Column names to group by
- `agg_columns`: Dict mapping column name to aggregation function
  - Strings: "mean", "sum", "count", "min", "max"
  - Callable: Custom aggregation function

**Returns:** Aggregated DataFrame grouped by parameters

---

### validate_merge()

Check merged DataFrame for consistency and quality issues.

```python
from labeeb.merge import validate_merge

validation = validate_merge(
    merged_df=merged,
    case_id_column="case_id",
    required_columns=["status", "exit_code"],
)

if not validation['valid']:
    for error in validation['errors']:
        print(f"Error: {error}")
    for warning in validation['warnings']:
        print(f"Warning: {warning}")
```

**Checks:**
- Duplicate case IDs
- Missing values per column
- Required columns present
- Data type consistency

**Returns:** Dict with validation results and statistics

---

### export_merge_report()

Export merged DataFrame in multiple formats.

```python
from labeeb.merge import export_merge_report

# CSV (human-readable)
export_merge_report(merged, "results.csv", format="csv")

# Parquet (efficient binary)
export_merge_report(merged, "results.parquet", format="parquet")

# JSON (preserves nested structures)
export_merge_report(merged, "results.json", format="json")

# Excel (spreadsheet)
export_merge_report(merged, "results.xlsx", format="xlsx")
```

**Parameters:**
- `merged_df`: DataFrame to export
- `output_path`: Output file path
- `format`: Export format ("csv", "parquet", "json", "xlsx")

**Returns:** Path object of exported file

---

## Workflows

### Cross-Campaign Comparison

```python
from labeeb import Campaign, export_case_results
from labeeb.merge import merge_case_results, validate_merge
import json

# Run multiple campaigns with different configurations
configs = [
    {"name": "baseline", "param_A": 1.0},
    {"name": "optimized_v1", "param_A": 1.5},
    {"name": "optimized_v2", "param_A": 2.0},
]

campaigns = []
for config in configs:
    manifest = create_manifest(config)  # Your logic
    c = Campaign(manifest)
    c.run()
    campaigns.append(c)

# Export and merge
results = [export_case_results(c.results, f"temp_{config['name']}.csv") 
           for c, config in zip(campaigns, configs)]
merged = merge_case_results(results, campaign_ids=[c['name'] for c in configs])

# Validate
validation = validate_merge(merged)
assert validation['valid'], f"Merge failed: {validation['errors']}"

# Export
export_merge_report(merged, "comparison_results.csv")

# Summary statistics
print(f"Total cases: {len(merged)}")
print(f"Unique campaigns: {merged['campaign_id'].nunique()}")
print(f"Success rate: {(merged['status'] == 'SUCCESS').sum() / len(merged):.1%}")
```

### Parameter Space Analysis

```python
from labeeb.merge import merge_case_results, aggregate_by_parameters
import json

# Merge all campaign results
merged = merge_case_results([df1, df2, df3])

# Parse JSON columns
merged['parameters'] = merged['parameters'].apply(json.loads)
merged['metrics'] = merged['metrics'].apply(json.loads)

# Extract key parameters
merged['param_A'] = merged['parameters'].apply(lambda x: x.get('A'))
merged['param_B'] = merged['parameters'].apply(lambda x: x.get('B'))
merged['response'] = merged['metrics'].apply(lambda x: x.get('response'))

# Aggregate by parameter combinations
summary = aggregate_by_parameters(
    merged,
    group_by=['param_A', 'param_B'],
    agg_columns={
        'response': ['mean', 'std'],
        'case_id': 'count',
        'duration_seconds': 'mean',
    }
)

# Find best configuration
best = summary.loc[summary['response_mean'].idxmax()]
print(f"Best configuration: A={best['param_A']}, B={best['param_B']}")
print(f"Mean response: {best['response_mean']:.2f}")
```

### Multi-Phase Sensitivity Analysis

```python
from labeeb import Campaign, export_case_results
from labeeb.merge import merge_case_results, aggregate_by_parameters, export_merge_report
import pandas as pd

# Phase 1: Coarse screening
phase1_campaign = Campaign(coarse_manifest)
phase1_campaign.run()
phase1_df = export_case_results(phase1_campaign.results, "phase1.csv")

# Phase 2: Refined analysis on promising candidates
phase2_results = []
for case in phase1_campaign.cases:
    if case.outputs['efficiency'] > 0.8:  # Promising
        refined_manifest = refine_manifest(case)
        c = Campaign(refined_manifest)
        c.run()
        phase2_results.append(export_case_results(c.results, f"phase2_{case.case_id}.csv"))

# Consolidate all results
all_phases = [phase1_df] + phase2_results
merged = merge_case_results(
    all_phases,
    campaign_ids=['Phase1_Screening'] + [f'Phase2_Refinement_{i}' for i in range(len(phase2_results))]
)

# Analyze
summary = aggregate_by_parameters(
    merged,
    group_by=['param_A'],
    agg_columns={'efficiency': 'mean', 'cost': 'mean'}
)

export_merge_report(summary, "sensitivity_summary.csv")
```

---

## Best Practices

### 1. Track Campaign Identity

```python
# Always use campaign_ids to distinguish runs
merged = merge_case_results(
    [df1, df2, df3],
    campaign_ids=["baseline", "variant_a", "variant_b"]  # ✓ Good
)

# Not:
merged = merge_case_results([df1, df2, df3])  # ✗ Can't tell results apart
```

### 2. Validate Before Analysis

```python
validation = validate_merge(merged)
if not validation['valid']:
    print("Cannot proceed - merge has issues:")
    for error in validation['errors']:
        print(f"  - {error}")
    return

if validation['warnings']:
    print("Merge warnings:")
    for warning in validation['warnings']:
        print(f"  - {warning}")
```

### 3. Parse JSON Columns Before Aggregation

```python
import json

# These are stored as JSON strings - parse them first
df['parameters'] = df['parameters'].apply(json.loads)
df['metrics'] = df['metrics'].apply(json.loads)

# Now you can extract individual fields
df['param_A'] = df['parameters'].apply(lambda x: x.get('A'))
df['response'] = df['metrics'].apply(lambda x: x.get('response'))
```

### 4. Handle Missing Values

```python
# Fill missing values appropriately for your domain
merged['status'].fillna('UNKNOWN', inplace=True)
merged['exit_code'].fillna(-1, inplace=True)
merged['duration_seconds'].fillna(0, inplace=True)

# Or remove incomplete rows
merged = merged.dropna(subset=['status', 'exit_code'])
```

### 5. Export in Appropriate Format

| Format | Best For | Pros | Cons |
|---|---|---|---|
| **CSV** | Human review, Excel | Human-readable, universal | Not good for nested data |
| **Parquet** | Large datasets, compression | Efficient, binary | Not human-readable |
| **JSON** | Nested data, APIs | Preserves structure | Verbose |
| **XLSX** | Report distribution | Spreadsheet-familiar | Limited formatting |

---

## Example: Complete Workflow

```python
#!/usr/bin/env python
"""
Multi-campaign analysis workflow demonstrating result merging.
"""
from labeeb import Campaign, export_case_results
from labeeb.merge import (
    merge_case_results,
    aggregate_by_parameters,
    validate_merge,
    export_merge_report
)
from pathlib import Path
import json

def run_configuration(config_name, params):
    """Run campaign with given configuration."""
    manifest = {
        "name": config_name,
        "parameters": params,
        "templates": ["input.txt"],
        "commands": ["./simulator input.txt"],
    }
    campaign = Campaign(manifest)
    return campaign.run()

# Step 1: Run multiple configurations
configs = {
    "baseline": {"threshold": 0.5, "iterations": 100},
    "optimized_strict": {"threshold": 0.7, "iterations": 50},
    "optimized_aggressive": {"threshold": 0.3, "iterations": 200},
}

campaigns = {name: run_configuration(name, params) 
             for name, params in configs.items()}

# Step 2: Export results
results_dfs = {}
for name, campaign in campaigns.items():
    df = export_case_results(campaign.results, f"temp_{name}.csv")
    results_dfs[name] = df

# Step 3: Merge
merged = merge_case_results(
    results_dfs=[results_dfs[name] for name in configs.keys()],
    campaign_ids=list(configs.keys())
)

# Step 4: Validate
validation = validate_merge(merged)
print(f"Validation: {validation}")
assert validation['valid'], "Merge validation failed"

# Step 5: Analyze
merged['parameters'] = merged['parameters'].apply(json.loads)
merged['metrics'] = merged['metrics'].apply(json.loads)

# Extract key columns
merged['threshold'] = merged['parameters'].apply(lambda x: x.get('threshold'))
merged['runtime'] = merged['metrics'].apply(lambda x: x.get('runtime', 0))

# Aggregate by configuration
summary = aggregate_by_parameters(
    merged,
    group_by=['campaign_id'],
    agg_columns={
        'runtime': 'mean',
        'case_id': 'count',
        'status': lambda x: (x == 'SUCCESS').sum(),
    }
)

# Step 6: Export results
export_merge_report(merged, "all_results.csv")
export_merge_report(summary, "summary.csv")

print("\n=== Analysis Complete ===")
print(f"Total cases analyzed: {len(merged)}")
print(f"Configurations: {merged['campaign_id'].nunique()}")
print(f"\nSummary:\n{summary}")
```

---

## Performance Notes

### Dataset Sizes
- **< 100K cases**: All formats acceptable, in-memory processing fine
- **100K - 1M cases**: Parquet recommended for storage efficiency
- **> 1M cases**: Consider chunked processing or database storage

### Memory Usage
```python
# Estimate memory before loading
import pandas as pd

# CSV: ~5x size of file on disk
# Parquet: ~2x size of file on disk
# JSON: ~3x size of file on disk

# Monitor during merge
import tracemalloc
tracemalloc.start()
merged = merge_case_results(dfs)
current, peak = tracemalloc.get_traced_memory()
print(f"Peak memory: {peak / 1024 / 1024:.1f} MB")
```

### Optimization Tips
1. Filter large merges before aggregation
2. Use Parquet for intermediate storage
3. Aggregate before visualization
4. Consider column selection to reduce size

---

## Troubleshooting

| Issue | Solution |
|---|---|
| "Merge validation failed" | Check for duplicate case_ids or missing columns |
| "KeyError: 'parameter'" | Ensure JSON columns are parsed with `json.loads()` |
| "Memory exceeded" | Switch to Parquet format or process in chunks |
| "Different schema between runs" | Use `validate_merge()` to identify discrepancies |


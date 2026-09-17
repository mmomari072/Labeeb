# Harvester Aggregation - Data Summary Options

**Extract summaries and statistics from harvested data without post-processing.**

## The Problem

Previously, harvesters always returned all extracted values, requiring post-processing:

```python
# OLD WAY - Extract all then compute
case.add_harvester(CsvHarvester("temps", "results.csv", "temperature"))
case.launch()
all_temps = case.outputs["temps"][0]  # [300, 350, 400, 425, 450, ...]

# Manual post-processing
final_temp = all_temps[-1]
avg_temp = statistics.mean(all_temps)
max_temp = max(all_temps)
```

## The Solution: Aggregation Parameter

**Compute summaries directly during harvesting:**

```python
# NEW WAY - Aggregation during harvest
case.add_harvester(
    CsvHarvester("final_temp", "results.csv", "temperature", aggregation="last")
)
case.add_harvester(
    CsvHarvester("avg_temp", "results.csv", "temperature", aggregation="mean")
)
case.add_harvester(
    CsvHarvester("peak_temp", "results.csv", "temperature", aggregation="max")
)
case.launch()

final_temp = case.outputs["final_temp"][0]  # Single value: 500
avg_temp = case.outputs["avg_temp"][0]      # Single value: 400.5
peak_temp = case.outputs["peak_temp"][0]    # Single value: 500
```

---

## Supported Aggregation Methods

| Method | Description | Returns | Example |
|--------|-------------|---------|---------|
| **`"all"`** (default) | Return all values unchanged | List | [300, 350, 400] |
| **`"first"`** | First value only | Single | 300 |
| **`"last"`** | Last value only | Single | 400 |
| **`"min"`** | Minimum value | Single | 300 |
| **`"max"`** | Maximum value | Single | 400 |
| **`"mean"` or `"avg"`** | Average of values | Single | 350.0 |
| **`"median"`** | Median value | Single | 350 |
| **`"std"`** | Standard deviation | Single | 50.0 |
| **`"sum"`** | Sum of all values | Single | 1050 |
| **`"integration"`** | Numerical integration (sum) | Single | 1050 |
| **`"count"`** | Total number of values | Single | 3 |

---

## Usage Examples

### CSV Data Extraction

```python
from labeeb import Case, CsvHarvester

case = Case("thermal_analysis")

# Extract all temperatures
case.add_harvester(
    CsvHarvester("all_temps", "results.csv", "temperature")
)

# Extract final temperature
case.add_harvester(
    CsvHarvester("final_temp", "results.csv", "temperature", aggregation="last")
)

# Extract average temperature
case.add_harvester(
    CsvHarvester("avg_temp", "results.csv", "temperature", aggregation="mean")
)

# Extract peak temperature
case.add_harvester(
    CsvHarvester("peak_temp", "results.csv", "temperature", aggregation="max")
)

case.launch()

# Results
print(case.outputs["all_temps"])      # [[300, 350, 400, 425, 450]]
print(case.outputs["final_temp"])     # [450]
print(case.outputs["avg_temp"])       # [405.0]
print(case.outputs["peak_temp"])      # [450]
```

### JSON Data Extraction

```python
from labeeb import JsonHarvester

# Extract all iteration counts
case.add_harvester(
    JsonHarvester("all_iters", "config.json", "solver.iterations")
)

# Extract only the final iteration count
case.add_harvester(
    JsonHarvester("final_iters", "config.json", "solver.iterations", 
                  aggregation="last")
)
```

### Log File Pattern Matching

```python
from labeeb import RegexHarvester

# Extract all residuals
case.add_harvester(
    RegexHarvester("all_residuals", "output.log", 
                   pattern=r"Residual:\s*([\d.eE+-]+)")
)

# Extract minimum residual
case.add_harvester(
    RegexHarvester("min_residual", "output.log",
                   pattern=r"Residual:\s*([\d.eE+-]+)",
                   aggregation="min")
)

# Extract mean residual
case.add_harvester(
    RegexHarvester("mean_residual", "output.log",
                   pattern=r"Residual:\s*([\d.eE+-]+)",
                   aggregation="mean")
)
```

### Excel Data Extraction

```python
from labeeb import ExcelHarvester

# Extract all pressure values
case.add_harvester(
    ExcelHarvester("all_pressure", "results.xlsx", "Pressure", sheet="Results")
)

# Extract only the final pressure
case.add_harvester(
    ExcelHarvester("final_pressure", "results.xlsx", "Pressure", sheet="Results",
                   aggregation="last")
)

# Extract average pressure
case.add_harvester(
    ExcelHarvester("avg_pressure", "results.xlsx", "Pressure", sheet="Results",
                   aggregation="mean")
)
```

### AutoHarvester with Aggregation

```python
from labeeb import AutoHarvester

# Auto-detect file type + aggregate
case.add_harvester(AutoHarvester("peak_energy", "output.csv", 
                                  column="energy", aggregation="max"))
case.add_harvester(AutoHarvester("final_stress", "results.json",
                                  key="analysis.stress", aggregation="last"))
case.add_harvester(AutoHarvester("avg_error", "convergence.log",
                                  pattern=r"error:\s*([\d.eE+-]+)",
                                  aggregation="mean"))
```

---

## Real-World Patterns

### Pattern 1: Convergence Analysis

```python
case = Case("convergence_study")

# Extract convergence metrics
case.add_harvester(RegexHarvester(
    "iterations_needed", "solver.log",
    pattern=r"Total iterations:\s*(\d+)",
    aggregation="first"  # Only the first (and likely only) match
))

case.add_harvester(RegexHarvester(
    "min_error", "solver.log",
    pattern=r"Error:\s*([\d.eE+-]+)",
    aggregation="min"
))

case.add_harvester(RegexHarvester(
    "final_error", "solver.log",
    pattern=r"Error:\s*([\d.eE+-]+)",
    aggregation="last"
))

case.launch()
```

### Pattern 2: Performance Profiling

```python
case = Case("performance_test")

# Extract all timing measurements
case.add_harvester(CsvHarvester(
    "all_times", "profile.csv", "duration_ms"
))

# Extract summary statistics
case.add_harvester(CsvHarvester(
    "min_time", "profile.csv", "duration_ms", aggregation="min"
))
case.add_harvester(CsvHarvester(
    "avg_time", "profile.csv", "duration_ms", aggregation="mean"
))
case.add_harvester(CsvHarvester(
    "max_time", "profile.csv", "duration_ms", aggregation="max"
))
case.add_harvester(CsvHarvester(
    "time_variance", "profile.csv", "duration_ms", aggregation="std"
))

case.launch()

# Analyze performance
if case.outputs["time_variance"][0] < 5:  # Low variance
    print("Consistent performance")
```

### Pattern 3: Data Integration

```python
from labeeb import apply_aggregation

case = Case("integration_study")

# Extract flux values for numerical integration
case.add_harvester(CsvHarvester(
    "total_flux", "field_output.csv", "flux", aggregation="sum"
))

# Or manually aggregate later
case.add_harvester(CsvHarvester(
    "flux_data", "field_output.csv", "flux"
))

case.launch()

total_flux_direct = case.outputs["total_flux"][0]  # Already aggregated
total_flux_manual = apply_aggregation(case.outputs["flux_data"][0], "sum")
```

---

## Advanced: With Transforms

Aggregation is applied **after** transform:

```python
# Transform first, then aggregate
case.add_harvester(
    CsvHarvester(
        "scaled_avg",
        "results.csv",
        "temperature",
        transform=lambda x: [v * 1.8 + 32 for v in x],  # C to F conversion
        aggregation="mean"  # Mean of converted values
    )
)
```

---

## Standalone Usage

Use `apply_aggregation()` function directly:

```python
from labeeb import apply_aggregation

data = [100, 200, 300, 400, 500]

first = apply_aggregation(data, "first")      # 100
last = apply_aggregation(data, "last")        # 500
avg = apply_aggregation(data, "mean")         # 300
total = apply_aggregation(data, "sum")        # 1500
count = apply_aggregation(data, "count")      # 5
```

---

## Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Lines of code** | 10+ lines per metric | 1 line per metric |
| **Post-processing** | Manual (error-prone) | Automatic (reliable) |
| **Clarity** | Implicit computation | Explicit intention |
| **Performance** | Extract all, then compute | Compute during extraction |
| **Output size** | Large (all values) | Small (single summary) |

---

## Error Handling

```python
from labeeb import apply_aggregation, ExtractionError

try:
    # Handles empty data gracefully
    result = apply_aggregation([], "mean")
except ExtractionError as e:
    print(f"Aggregation failed: {e}")

try:
    # Handles invalid aggregation method
    result = apply_aggregation([1, 2, 3], "invalid_method")
except ExtractionError as e:
    print(f"Unknown aggregation: {e}")
```

---

## Migration Guide

### Before
```python
from statistics import mean, median

case.add_harvester(CsvHarvester("temps", "results.csv", "temperature"))
case.launch()

temps = case.outputs["temps"][0]
final = temps[-1]
average = mean(temps)
peak = max(temps)
```

### After
```python
case.add_harvester(CsvHarvester("final_temp", "results.csv", "temperature", 
                                aggregation="last"))
case.add_harvester(CsvHarvester("avg_temp", "results.csv", "temperature",
                                aggregation="mean"))
case.add_harvester(CsvHarvester("peak_temp", "results.csv", "temperature",
                                aggregation="max"))
case.launch()

final = case.outputs["final_temp"][0]
average = case.outputs["avg_temp"][0]
peak = case.outputs["peak_temp"][0]
```

---

## Summary

Aggregation streamlines data extraction by:
- Reducing post-processing code
- Improving clarity of intent
- Handling common statistical operations
- Supporting both immediate use and complex pipelines

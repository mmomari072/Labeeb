# Multi-Column CSV Harvesters

Four new harvester types for flexible extraction of multiple columns from CSV files without repetition.

## Problem

Previously, extracting multiple columns from a CSV required defining a separate `CsvHarvester` for each column:

```python
# OLD WAY - Verbose and repetitive
case.add_harvester(CsvHarvester("temp", "results.csv", "temperature"))
case.add_harvester(CsvHarvester("pres", "results.csv", "pressure"))
case.add_harvester(CsvHarvester("dens", "results.csv", "density"))
case.add_harvester(CsvHarvester("vx", "results.csv", "velocity_x"))
case.add_harvester(CsvHarvester("vy", "results.csv", "velocity_y"))
case.add_harvester(CsvHarvester("vz", "results.csv", "velocity_z"))
# ... 6 harvesters for just 6 columns!
```

## Solution: Four Flexible Harvester Options

### 1. BulkCsvHarvester - All Columns

Harvest **all columns** from a CSV file at once.

```python
from labeeb import BulkCsvHarvester

case.add_harvester(
    BulkCsvHarvester(name="all_results", file_target="results.csv")
)
# Returns: {"column1": [...], "column2": [...], ...}
```

**Best for:**
- Complete output capture for post-processing
- Saving all metrics in single harvester
- When you don't know column names in advance

**Returns:**
```python
{
    "temperature": [300, 350, 400],
    "pressure": [101.3, 102.5, 103.7],
    "density": [1.225, 1.2, 1.18],
    ...all columns
}
```

**Example:**
```python
case.add_harvester(BulkCsvHarvester("thermal_output", "results.csv"))
case.launch()

all_data = case.outputs["thermal_output"][0]  # First (and only) case
print(all_data["temperature"])  # [300, 350, 400]
```

---

### 2. MultiColumnCsvHarvester - Specific Columns

Harvest **specific columns** you know in advance.

```python
from labeeb import MultiColumnCsvHarvester

case.add_harvester(
    MultiColumnCsvHarvester(
        name="thermo_results",
        file_target="results.csv",
        columns=["temperature", "pressure", "density"]
    )
)
# Returns: {"temperature": [...], "pressure": [...], "density": [...]}
```

**Best for:**
- Known set of output columns you need
- Filtering out unnecessary data
- Clear declaration of dependencies

**Returns:**
```python
{
    "temperature": [300, 350, 400],
    "pressure": [101.3, 102.5, 103.7],
    "density": [1.225, 1.2, 1.18]
}
```

**Example:**
```python
case.add_harvester(
    MultiColumnCsvHarvester(
        "thermo",
        "results.csv",
        columns=["temperature", "pressure", "density", "enthalpy"]
    )
)
case.launch()

thermo = case.outputs["thermo"][0]
print(thermo["temperature"])  # [300, 350, 400]
print(thermo["pressure"])     # [101.3, 102.5, 103.7]
```

---

### 3. PatternCsvHarvester - Regex Pattern Matching

Harvest columns **matching a regex pattern**.

```python
from labeeb import PatternCsvHarvester

case.add_harvester(
    PatternCsvHarvester(
        name="velocity_components",
        file_target="results.csv",
        column_pattern=r"velocity_.*"
    )
)
# Returns: {"velocity_x": [...], "velocity_y": [...], "velocity_z": [...]}
```

**Best for:**
- Variable/dynamic column naming patterns
- Component-based outputs (velocity_*, stress_*, etc)
- Robust to output format changes
- Multiple similar columns with consistent naming

**Common Patterns:**
```python
# All velocity components
column_pattern=r"velocity_.*"      # velocity_x, velocity_y, velocity_z
column_pattern=r"v[xyz]"           # vx, vy, vz

# All stress components
column_pattern=r"stress_.*"        # stress_xx, stress_yy, stress_zz, stress_xy, ...
column_pattern=r"sigma.*"          # sigma_11, sigma_22, ...

# Thermal properties
column_pattern=r"temp.*"           # temperature, temp_boundary, temp_interior
column_pattern=r".*_heat"          # convective_heat, conductive_heat, ...

# Time-based outputs
column_pattern=r"t\d+"             # t0, t1, t2, ...
column_pattern=r"time_step_\d+"    # time_step_0, time_step_1, ...

# All columns starting with specific prefix
column_pattern=r"^cell_.*"         # cell_1, cell_2, cell_3, ...
```

**Returns:**
```python
{
    "velocity_x": [0.1, 0.15, 0.2],
    "velocity_y": [0.2, 0.25, 0.3],
    "velocity_z": [0.05, 0.08, 0.1]
}
```

**Example:**
```python
# Extract all velocity and stress components
case.add_harvester(
    PatternCsvHarvester("velocity", "results.csv", column_pattern=r"velocity_.*")
)
case.add_harvester(
    PatternCsvHarvester("stress", "results.csv", column_pattern=r"stress_.*")
)
case.launch()

velocity = case.outputs["velocity"][0]
stress = case.outputs["stress"][0]

print(velocity.keys())  # dict_keys(['velocity_x', 'velocity_y', 'velocity_z'])
print(stress.keys())    # dict_keys(['stress_xx', 'stress_yy', 'stress_zz', 'stress_xy', ...])
```

---

### 4. DataFrameHarvester - Full DataFrame Processing

Return entire **pandas DataFrame** for custom analysis and transformations.

```python
from labeeb import DataFrameHarvester
import pandas as pd

case.add_harvester(
    DataFrameHarvester(
        name="full_data",
        file_target="results.csv",
        transform=lambda df: df[["temperature", "pressure"]].mean()
    )
)
# Returns: Full DataFrame or transformed result
```

**Best for:**
- Advanced statistical analysis
- Complex transformations and filtering
- Pivot tables, groupby operations
- Computing derived metrics
- Custom post-processing logic

**Without Transform:**
```python
case.add_harvester(DataFrameHarvester("raw_data", "results.csv"))
case.launch()

df = case.outputs["raw_data"][0]
print(type(df))       # <class 'pandas.core.frame.DataFrame'>
print(df.shape)       # (100, 12)
print(df.columns)     # Index(['time', 'temperature', ...])
```

**With Transform:**
```python
# Compute statistics
case.add_harvester(
    DataFrameHarvester(
        "statistics",
        "results.csv",
        transform=lambda df: {
            "mean": df.mean().to_dict(),
            "std": df.std().to_dict(),
            "max": df.max().to_dict(),
        }
    )
)

# Select specific columns and subset
case.add_harvester(
    DataFrameHarvester(
        "thermo_subset",
        "results.csv",
        transform=lambda df: df[["temperature", "pressure", "density"]]
    )
)

# Compute correlations
case.add_harvester(
    DataFrameHarvester(
        "correlations",
        "results.csv",
        transform=lambda df: df.corr().to_dict()
    )
)

# Filter rows
case.add_harvester(
    DataFrameHarvester(
        "high_temp_data",
        "results.csv",
        transform=lambda df: df[df["temperature"] > 350].reset_index(drop=True)
    )
)
```

---

## Comparison Table

| Feature | BulkCsv | MultiColumn | Pattern | DataFrame |
|---------|---------|------------|---------|-----------|
| **Extract all columns** | ✅ Yes | ❌ No | ❌ No | ✅ Yes |
| **Select specific columns** | ❌ No | ✅ Yes | ❌ No | ✅ Yes |
| **Pattern matching** | ❌ No | ❌ No | ✅ Yes | ❌ No |
| **Advanced transforms** | ✅ Basic | ✅ Basic | ✅ Basic | ✅ Full |
| **Returns dict** | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No (returns DataFrame) |
| **Best for many columns** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Code simplicity** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |

---

## Real-World Examples

### Example 1: CFD Simulation with Many Outputs

```python
from labeeb import Case, BulkCsvHarvester, PatternCsvHarvester

case = Case(name="cfd_sim")

# Option A: Get everything
case.add_harvester(BulkCsvHarvester("all_outputs", "field_results.csv"))

# Option B: Get velocity and pressure only
case.add_harvester(
    MultiColumnCsvHarvester(
        "primary_vars",
        "field_results.csv",
        columns=["velocity_x", "velocity_y", "velocity_z", "pressure"]
    )
)

# Option C: Get all components using patterns
case.add_harvester(PatternCsvHarvester("velocity", "field_results.csv", r"velocity_.*"))
case.add_harvester(PatternCsvHarvester("stress", "field_results.csv", r"stress_.*"))
case.add_harvester(PatternCsvHarvester("strain", "field_results.csv", r"strain_.*"))
```

### Example 2: Multi-Phase Thermal Analysis

```python
from labeeb import DataFrameHarvester

case = Case(name="thermal_analysis")

# Harvest raw data
case.add_harvester(
    DataFrameHarvester(
        "temperature_field",
        "thermal_output.csv",
        transform=lambda df: df[df.columns[df.columns.str.contains("temp", case=False)]]
    )
)

# Compute thermal statistics
case.add_harvester(
    DataFrameHarvester(
        "thermal_stats",
        "thermal_output.csv",
        transform=lambda df: {
            "max_temp": df["temperature"].max(),
            "avg_temp": df["temperature"].mean(),
            "temp_gradient": (df["temperature"].max() - df["temperature"].min()),
        }
    )
)
```

### Example 3: Structural Analysis with Pattern Matching

```python
from labeeb import PatternCsvHarvester

case = Case(name="structural_fem")

# Extract by component type using patterns
case.add_harvester(PatternCsvHarvester("displacements", "fem.csv", r"u[xyz]"))      # ux, uy, uz
case.add_harvester(PatternCsvHarvester("stresses", "fem.csv", r"sigma_\d+"))        # sigma_11, sigma_22, ...
case.add_harvester(PatternCsvHarvester("strains", "fem.csv", r"epsilon_\d+"))       # epsilon_11, ...
case.add_harvester(PatternCsvHarvester("reactions", "fem.csv", r"rf[xyz]"))         # rfx, rfy, rfz
```

---

## Performance Considerations

- **BulkCsvHarvester**: Minimal overhead, reads file once
- **MultiColumnCsvHarvester**: Slightly better than multiple `CsvHarvester` (single read)
- **PatternCsvHarvester**: Regex matching overhead, but still single file read
- **DataFrameHarvester**: Full DataFrame in memory, appropriate for post-processing

All four options are more efficient than defining one harvester per column.

---

## Migration from Old Style

### Before (6 Harvesters)
```python
case.add_harvester(CsvHarvester("temperature", "results.csv", "temperature"))
case.add_harvester(CsvHarvester("pressure", "results.csv", "pressure"))
case.add_harvester(CsvHarvester("density", "results.csv", "density"))
case.add_harvester(CsvHarvester("vx", "results.csv", "velocity_x"))
case.add_harvester(CsvHarvester("vy", "results.csv", "velocity_y"))
case.add_harvester(CsvHarvester("vz", "results.csv", "velocity_z"))
```

### After (1-2 Harvesters)
```python
# Option 1: One bulk harvester
case.add_harvester(BulkCsvHarvester("all_results", "results.csv"))

# Option 2: Targeted selection
case.add_harvester(MultiColumnCsvHarvester("thermo", "results.csv", 
    columns=["temperature", "pressure", "density"]))
case.add_harvester(PatternCsvHarvester("velocity", "results.csv", r"velocity_.*"))
```

---

## Notes

- All harvesters return dictionaries or DataFrames where keys are column names
- Use `transform` parameter for any post-processing
- Set `optional=True` to handle missing files gracefully
- Works seamlessly with existing single-column harvesters

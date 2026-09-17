# Database Filtering with Save Option - Execution Dataset Preparation

**Create and save filtered database subsets for targeted case execution.**

## Overview

The `Database.filter()` method now supports an optional `save` parameter that automatically exports filtered data to CSV, JSON, or Parquet format. This enables creating **execution-ready datasets** for:

- Running only relevant cases (e.g., only high-temperature scenarios)
- Creating reproducible test datasets
- Sharing filtered data with collaborators
- Downstream analysis with external tools

---

## Two Methods

### Method 1: filter() with save parameter

Filter data and save in one call:

```python
from labeeb import Database

db = Database(name="study", data={
    "temperature": [300, 350, 400, 425, 450],
    "pressure": [100, 102, 105, 108, 110],
    "material": ["steel", "steel", "aluminum", "aluminum", "titanium"]
})

# Filter and save to CSV
filtered = db.filter(
    save="high_temp_cases.csv",
    temperature__gt=350
)
print(f"Filtered {len(filtered)} cases to high_temp_cases.csv")
```

### Method 2: filter_and_save() convenience method

Explicit two-step operation (same result, clearer intent):

```python
# Filter and save - clearer when save is the main goal
filtered = db.filter_and_save(
    "aluminum_cases.csv",
    material="aluminum",
    temperature__gte=350
)
```

---

## Usage Examples

### Basic Filtering and Saving

**Save high-temperature cases:**

```python
# Temperatures above 350K
filtered = db.filter(
    save="high_temp.csv",
    temperature__gt=350
)
```

**Save specific material with pressure range:**

```python
# Aluminum cases with controlled pressure
filtered = db.filter(
    save="aluminum_study.json",
    material="aluminum",
    pressure__gte=100,
    pressure__lte=105
)
```

### Multiple Condition Filters

```python
# Complex filtering with multiple conditions
filtered = db.filter(
    save="execution_subset.csv",
    temperature__gt=350,
    pressure__lte=110,
    material="titanium"
)
print(f"Found {len(filtered)} cases matching criteria")
```

### Using Callable Predicates

```python
# Filter with custom logic
filtered = db.filter(
    save="mid_range_temperatures.json",
    temperature=lambda t: 300 <= t <= 400
)

# Combine with operators
filtered = db.filter(
    save="validation_set.csv",
    temperature=lambda t: 300 <= t <= 400,
    pressure__gte=100
)
```

### Format Auto-Detection

Format is auto-detected from file extension:

```python
db.filter(save="output.csv", temperature__gt=350)     # CSV
db.filter(save="output.json", temperature__gt=350)    # JSON
db.filter(save="output.parquet", temperature__gt=350) # Parquet
db.filter(save="output.pq", temperature__gt=350)      # Parquet
```

### Explicit Format Specification

```python
# Override format if extension doesn't match content
filtered = db.filter_and_save(
    "data.dat",
    format="csv",  # Save as CSV despite .dat extension
    temperature__gt=350
)
```

---

## Real-World Workflow Examples

### Example 1: Create Execution Dataset

Prepare filtered data for case execution:

```python
from labeeb import Database, Case

# Load full database
db = Database(name="full_study")
db.import_from_file("all_cases.csv")

# Filter for execution - only high-temperature scenarios
execution_db = db.filter(
    save="execution_cases.csv",
    temperature__gt=350
)

# Load and run the filtered dataset
case = Case("thermal_study", output_files={})
case.database = Database(name="filtered")
case.database.import_from_file("execution_cases.csv")
case.launch()
```

### Example 2: Create Validation Dataset

Split data for validation:

```python
# Training: low and mid-range temperatures
training = db.filter(
    save="training_set.csv",
    temperature__lte=350
)

# Validation: high temperatures
validation = db.filter(
    save="validation_set.csv",
    temperature__gt=350
)

print(f"Training: {len(training)} cases")
print(f"Validation: {len(validation)} cases")
```

### Example 3: Multi-Stage Filtering

Progressive refinement:

```python
# Stage 1: Filter by material
aluminum_cases = db.filter(save="step1_aluminum.csv", material="aluminum")

# Stage 2: Further filter high-temperature aluminum
high_temp_aluminum = aluminum_cases.filter(
    save="step2_high_temp_aluminum.csv",
    temperature__gt=400
)

# Stage 3: Final filter by pressure
final_cases = high_temp_aluminum.filter(
    save="final_execution_set.csv",
    pressure__lte=108
)

print(f"Original: {len(db)} cases")
print(f"After material filter: {len(aluminum_cases)}")
print(f"After temperature filter: {len(high_temp_aluminum)}")
print(f"Final execution set: {len(final_cases)}")
```

### Example 4: Data Subset Comparison

Create datasets for analysis comparison:

```python
# Create subsets for different analyses
steel_cases = db.filter(
    save="analysis_steel.json",
    material="steel"
)

titanium_cases = db.filter(
    save="analysis_titanium.json",
    material="titanium"
)

aluminum_cases = db.filter(
    save="analysis_aluminum.json",
    material="aluminum"
)

# Now analyze each material separately
print(f"Steel: {len(steel_cases)} cases")
print(f"Titanium: {len(titanium_cases)} cases")
print(f"Aluminum: {len(aluminum_cases)} cases")
```

---

## API Reference

### filter(save=None, **conditions)

Filter database and optionally save filtered data.

**Parameters:**
- `save` (str, optional): File path for saving filtered data. Format auto-detected from extension.
- `**conditions`: Filtering conditions (column_name=value or column__operator=value)

**Returns:**
- New `Database` with filtered rows (saved to file if `save` specified)

**Operators:**
- `__gt` - Greater than
- `__lt` - Less than
- `__gte` - Greater or equal
- `__lte` - Less or equal
- `__eq` - Equal
- `__ne` - Not equal
- `__in` - In list

**Supported Formats:**
- CSV (.csv)
- JSON (.json)
- Parquet (.parquet, .pq)

**Examples:**

```python
# Filter without saving
filtered = db.filter(temperature__gt=350)

# Filter and save
filtered = db.filter(
    save="high_temp.csv",
    temperature__gt=350,
    pressure__lte=110
)

# Filter with callable
filtered = db.filter(
    save="results.json",
    stress=lambda x: 200 <= x <= 500
)
```

### filter_and_save(filepath, format=None, **conditions)

Convenience method combining filter and save operations explicitly.

**Parameters:**
- `filepath` (str): Output file path
- `format` (str, optional): Export format ('csv', 'json', 'parquet'). Auto-detected if not specified.
- `**conditions`: Filtering conditions

**Returns:**
- New `Database` with filtered rows (saved to file)

**Examples:**

```python
# Explicit filtering and saving
filtered = db.filter_and_save(
    "execution_cases.csv",
    temperature__gt=350
)

# With format override
filtered = db.filter_and_save(
    "data.dat",
    format="json",
    velocity__gte=10
)
```

---

## Integration with Case Execution

### Workflow 1: Filter → Load → Execute

```python
# Step 1: Create filtered dataset
execution_set = db.filter(
    save="cases_to_run.csv",
    temperature__gt=350,
    pressure__lte=110
)

# Step 2: Load filtered data for execution
exec_db = Database(name="execution")
exec_db.load("cases_to_run.csv")

# Step 3: Run cases
case = Case("filtered_study")
case.database = exec_db
case.launch()
```

### Workflow 2: One-Shot Execution from Filtered Data

```python
# Combined filter, load, and execute
filtered = db.filter(
    save="temp_execution.csv",
    temperature__gt=350
)

case = Case("study")
case.database = filtered
case.launch()

# Clean up temp file if needed
# os.remove("temp_execution.csv")
```

---

## Benefits

| Use Case | Benefit |
|----------|---------|
| **Performance** | Execute only relevant cases, skip unnecessary scenarios |
| **Reproducibility** | Save exact dataset used for each experiment |
| **Collaboration** | Share filtered subsets with team members |
| **Validation** | Create train/test/validation splits |
| **Analysis** | Prepare subsets for specific analytical studies |
| **Debugging** | Isolate problematic parameter ranges |
| **Documentation** | Keep record of which cases ran (via saved file) |

---

## Comparison: Before vs After

### Before (Manual Save)

```python
# Had to filter then manually construct new database
filtered_df = db.to_dataframe()
filtered_df = filtered_df[filtered_df['temperature'] > 350]
# Then manually recreate database from filtered data
# Or export, reimport separately
```

### After (Built-in Save)

```python
# Direct, one-step operation
filtered = db.filter(
    save="execution_cases.csv",
    temperature__gt=350
)
```

---

## Tips and Best Practices

1. **Use filter_and_save() for clarity** when saving is the primary goal:
   ```python
   # Clear intent: filtering to create execution dataset
   execution_set = db.filter_and_save("cases.csv", temperature__gt=350)
   ```

2. **Chain filters progressively** for complex filtering:
   ```python
   # Stage-by-stage refinement
   step1 = db.filter(material="aluminum")
   step2 = step1.filter(save="final.csv", temperature__gt=350)
   ```

3. **Use descriptive filenames** for reproducibility:
   ```python
   db.filter(save="high_temp_aluminum_cases.csv", ...)
   # vs just
   db.filter(save="data.csv", ...)
   ```

4. **Document filter criteria** in code or filename:
   ```python
   # Good: filename indicates filtering criteria
   db.filter(save="temp_350_500_aluminum.csv", ...)
   
   # Also good: clear conditions in code
   # Filter: temperature 350-500K, aluminum material
   filtered = db.filter(
       save="execution_set.csv",
       material="aluminum",
       temperature__gte=350,
       temperature__lte=500
   )
   ```

---

## See Also

- **Database.filter()** - Filter without saving
- **Database.save()** - Save full database
- **Database.load()** - Load from file
- **Case.launch()** - Execute cases from filtered database


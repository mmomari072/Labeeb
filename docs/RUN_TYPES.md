# Case Execution Modes (run_type)

The `case.run_type` parameter controls how the Case execution handles directories, files, and commands.

## Available Modes

### 1. `"new"` - Fresh Execution
**Default behavior when explicitly set**

- **Directory handling:** Delete all existing case directories, create fresh
- **File copying:** Copy template files to each case directory
- **Execution:** Execute all cases
- **Use case:** Initial fresh simulation run

```python
case = Case(name="my_case")
case.run_type = "new"
case.launch()
```

---

### 2. `"overwrite"` - In-Place Re-execution
**Re-run without deleting (NEW)**

- **Directory handling:** Keep existing directories, don't delete
- **File copying:** Skip copying (preserves existing files and external data)
- **Execution:** Execute all cases
- **Use case:** Re-run simulations after external data collection or analysis

```python
case = Case(name="my_case")
case.run_type = "overwrite"
case.launch()  # Re-executes all cases, preserves external files
```

**Key advantage:** External data collection scripts and analysis files remain in case directories

---

### 3. `"continue"` - Smart Resume
**Resume from previous run with database expansion**

- **Directory handling:** Keep existing directories, create missing ones
- **File copying:** Copy only for new case directories
- **Execution:** Execute only missing cases (those without directories)
- **Use case:** Expand simulation study with additional database rows

```python
# First run
case.database = Database(data={"x": [1, 2, 3]})
case.run_type = "new"
case.launch()

# Later: add more cases
case.database = Database(data={"x": [1, 2, 3, 4, 5]})
case.run_type = "continue"
case.launch()  # Only runs cases 4, 5; cases 1-3 keep existing results
```

---

### 4. `"read_only"` - Analysis Only
**Default (no execution)**

- **Directory handling:** Keep existing directories, don't delete
- **File copying:** Don't copy files
- **Execution:** Skip all execution
- **Use case:** Analyze existing results, harvest outputs

```python
case = Case(name="my_case")
case.run_type = "read_only"  # Default
case.launch()  # Only reads outputs, no execution
```

---

## Comparison Table

| Aspect | `new` | `overwrite` | `continue` | `read_only` |
|--------|-------|-----------|-----------|-----------|
| **Delete dirs** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Copy files** | ✅ Yes | ❌ No | ✅ (new only) | ❌ No |
| **Execute all** | ✅ Yes | ✅ Yes | ❌ No (missing only) | ❌ No |
| **Preserve external data** | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Use for** | Fresh start | Re-run + analysis | Database expansion | Result analysis |

---

## Workflow Examples

### Example 1: Initial Study → Re-analysis Workflow
```python
# Step 1: Initial simulation
case = Case(name="sensitivity_study")
case.database = Database(data={"param": [1, 2, 3]})
case.run_type = "new"
case.launch()

# Step 2: External data collection (manually add files to case_0/, case_1/, case_2/)
# ... collect post-processing data, metrics, plots, etc.

# Step 3: Re-run with latest model changes (keeping external data)
case.run_type = "overwrite"
case.launch()  # Re-executes, preserves external analysis files

# Step 4: Analyze results
case.run_type = "read_only"
case.launch()  # Just reads outputs and harvesters
```

### Example 2: Expanding Parameter Space
```python
# Round 1: Initial sampling
case = Case(name="param_sweep")
case.database = Database(data={"x": [1, 2, 3], "y": [10, 20, 30]})
case.run_type = "new"
case.launch()  # 3 cases executed

# Round 2: Expand with more parameters
case.database = Database(data={"x": [1, 2, 3, 4, 5], "y": [10, 20, 30, 40, 50]})
case.run_type = "continue"
case.launch()  # Cases 1-3 reuse old results, cases 4-5 execute
```

### Example 3: Model Update Workflow
```python
# Initial run with v1.0 model
case = Case(name="model_study")
case.run_type = "new"
case.launch()

# Model improved to v1.1, want to compare
case.run_type = "overwrite"
case.launch()  # Re-executes with v1.1, old results overwritten

# Comparison analysis
old_results = load_previous_backup()  # Backup from before overwrite
new_results = case.outputs
compare(old_results, new_results)
```

---

## Key Distinctions

### `new` vs `overwrite`
- `new`: Complete cleanup, suitable for truly fresh starts
- `overwrite`: Preserve directory structure, suitable for model updates

### `overwrite` vs `continue`
- `overwrite`: Re-execute **all** cases (with potential to redo work)
- `continue`: Execute **only missing** cases (efficient for expansion)

### `continue` vs `read_only`
- `continue`: Execute missing cases, read existing results
- `read_only`: Never execute, only read and analyze existing results

---

## Best Practices

1. **Development & Testing:** Use `"new"` for clean test environments
2. **Production Sweeps:** Use `"new"` for baseline run, then `"continue"` for expansions
3. **Post-processing:** Use `"overwrite"` if you need updated results after external analysis
4. **Multi-stage Analysis:** Use `"read_only"` after execution is complete
5. **Model Comparisons:** Use `"overwrite"` to re-run with different model versions

---

## Implementation Details

### Directory Creation
- `mkdir()` is called for both `new` and `overwrite` modes (safe if exists)
- Only `new` deletes directories before creating

### File Handling
- Files are copied for `new` and `continue` (for new cases only)
- Files are NOT copied for `overwrite` (preserves existing directory contents)

### Execution Decision
```python
should_execute = self.new or self.run_type == "overwrite" or (self.run_type == "continue" and not case_dir_exists)
```

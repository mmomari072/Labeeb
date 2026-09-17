# Supported File Types for Harvesting

Labeeb supports harvesting data from various file formats commonly produced by simulations and analyses.

## Overview

| File Type | Harvester(s) | Data Structure | Use Case |
|-----------|--------------|----------------|----------|
| **CSV** | 5 harvesters | Tabular (rows × columns) | Simulation outputs, data tables |
| **JSON** | JsonHarvester | Key-value hierarchy | Structured metadata, results |
| **Text/Log** | RegexHarvester | Unstructured text | Log files, reports |
| **Excel** | ExcelHarvester | Spreadsheets (sheets × rows × cols) | Formatted reports, multi-sheet data |
| **Custom** | CallableHarvester | Any format | Proprietary, binary, or special formats |

---

## 1. CSV Files (Comma-Separated Values)

**Five specialized harvesters for different extraction patterns:**

### A. CsvHarvester - Single Column
Extract one column from CSV:
```python
from labeeb import CsvHarvester

case.add_harvester(
    CsvHarvester("temperature", "results.csv", column="temperature")
)
```

### B. BulkCsvHarvester - All Columns
Extract all columns at once:
```python
from labeeb import BulkCsvHarvester

case.add_harvester(
    BulkCsvHarvester("all_data", "results.csv")
)
```

### C. MultiColumnCsvHarvester - Specific Columns
Extract selected columns:
```python
from labeeb import MultiColumnCsvHarvester

case.add_harvester(
    MultiColumnCsvHarvester(
        "key_metrics",
        "results.csv",
        columns=["temperature", "pressure", "velocity"]
    )
)
```

### D. PatternCsvHarvester - Pattern-Matched Columns
Extract columns by regex pattern:
```python
from labeeb import PatternCsvHarvester

case.add_harvester(
    PatternCsvHarvester(
        "stress_data",
        "results.csv",
        column_pattern=r"stress_.*"
    )
)
```

### E. DataFrameHarvester - Full DataFrame
Extract full DataFrame with optional transformation:
```python
from labeeb import DataFrameHarvester

case.add_harvester(
    DataFrameHarvester(
        "processed_data",
        "results.csv",
        transform=lambda df: df[df["temperature"] > 300]
    )
)
```

**CSV Example File:**
```csv
time,temperature,pressure,velocity_x,velocity_y
0.0,300,101.3,0.1,0.2
0.5,350,102.5,0.15,0.25
1.0,400,103.7,0.2,0.3
```

**Supported Formats:**
- Standard CSV (comma-delimited)
- TSV (tab-delimited) - via pandas
- Other delimiters via transform
- Large files (pandas backend)

---

## 2. JSON Files (JavaScript Object Notation)

**JsonHarvester - Key-value extraction:**

```python
from labeeb import JsonHarvester

case.add_harvester(
    JsonHarvester(
        "simulation_results",
        "output.json",
        key="results.final_state.temperature"
    )
)
```

**Features:**
- Dotted key path notation for nested access
- Supports arbitrary nesting depth
- Extracts any JSON value type (string, number, array, object)

**JSON Example File:**
```json
{
  "metadata": {
    "version": "2.0",
    "timestamp": "2026-09-17T18:40:00"
  },
  "results": {
    "final_state": {
      "temperature": 450,
      "pressure": 105.2,
      "velocity": [0.25, 0.3, 0.15]
    },
    "convergence": {
      "iterations": 1523,
      "residual": 1.2e-6
    }
  }
}
```

**Access Patterns:**
```python
# Simple value
key="metadata.version"           # → "2.0"

# Nested object
key="results.final_state.temperature"  # → 450

# Arrays
key="results.final_state.velocity"     # → [0.25, 0.3, 0.15]

# Deep nesting
key="results.convergence.residual"     # → 1.2e-6
```

---

## 3. Text/Log Files (Regular Expressions)

**RegexHarvester - Pattern-based text extraction:**

```python
from labeeb import RegexHarvester

case.add_harvester(
    RegexHarvester(
        "final_energy",
        "simulation.log",
        pattern=r"Final Energy\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"
    )
)
```

**Features:**
- Extract values using regex patterns
- Supports capture groups
- Returns first match found
- Useful for unstructured text

**Text Example File:**
```
=== Simulation Start ===
Initial conditions: T=300K, P=101.3kPa
Running CASE_001...

Iteration 1: Energy = 1000.5
Iteration 2: Energy = 1001.2
Iteration 3: Energy = 1002.1

Final Energy = 1050.3
Convergence: CONVERGED
Residual: 1.2e-6
```

**Common Regex Patterns:**
```python
# Extract number with optional sign/exponent
pattern=r"Energy\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"

# Extract quoted string
pattern=r"Status\s*=\s*['\"]([^'\"]+)['\"]"

# Extract from formatted output
pattern=r"Temperature\s*:\s*(\d+\.?\d*)"

# Multiple values (returns first capture group)
pattern=r"Results:\s*X=(\d+)\s+Y=(\d+)"  # Returns X value

# Text match (returns full match if no capture group)
pattern=r"CONVERGED|DIVERGED"
```

**Supported Formats:**
- Log files (.log, .txt)
- Output reports
- Console output capture
- Any text-based format

---

## 4. Excel Files (.xlsx, .xls)

**ExcelHarvester - Multi-sheet spreadsheet extraction:**

```python
from labeeb import ExcelHarvester

# Extract single column from Excel
case.add_harvester(
    ExcelHarvester(
        "thermal_data",
        "results.xlsx",
        column="Temperature",
        sheet=0  # First sheet
    )
)

# Extract from named sheet
case.add_harvester(
    ExcelHarvester(
        "stress_results",
        "results.xlsx",
        column="Stress_XX",
        sheet="Stresses"
    )
)

# Extract full sheet as DataFrame
case.add_harvester(
    ExcelHarvester(
        "full_sheet",
        "results.xlsx",
        column=None,  # None returns full sheet
        sheet="Results"
    )
)
```

**Features:**
- Multiple sheets support
- Access by sheet name or index
- Extract single column or full sheet
- Returns list of values or DataFrame

**Excel Example File:**
```
Sheet 1 "Results":
╔────┬─────────┬──────────┬──────────╗
║ ID │ Temp(K) │ Press(kPa) │ Vel(m/s) ║
╠════╬═════════╬════════════╬══════════╣
║ 1  │  300    │    101.3   │   0.1    ║
║ 2  │  350    │    102.5   │   0.15   ║
║ 3  │  400    │    103.7   │   0.2    ║
╚════╩═════════╩════════════╩══════════╝

Sheet 2 "Stresses":
╔────┬──────────┬──────────┬──────────╗
║ ID │ Stress_XX│ Stress_YY│ Stress_ZZ║
╠════╬──────────╬──────────╬──════════╣
║ 1  │   100    │    50    │    75    ║
║ 2  │   120    │    60    │    85    ║
║ 3  │   150    │    70    │    95    ║
╚════╩──────────╩──────────╩══════════╝
```

**Requirements:**
```bash
# For .xlsx files (modern Excel)
pip install openpyxl

# For .xls files (older Excel)
pip install xlrd

# Both
pip install openpyxl xlrd
```

---

## 5. Custom/Proprietary Formats

**CallableHarvester - User-defined extraction:**

```python
from labeeb import CallableHarvester
from pathlib import Path

# Custom parser function
def parse_binary_output(file_path: Path):
    """Custom parser for proprietary binary format."""
    import struct
    with open(file_path, 'rb') as f:
        data = f.read()
        # Custom binary parsing logic
        values = struct.unpack('f' * 100, data[:400])
        return list(values)

# Use with CallableHarvester
case.add_harvester(
    CallableHarvester(
        "binary_data",
        "output.bin",
        extractor=parse_binary_output
    )
)
```

**Common Custom Formats:**
```python
# HDF5 files (requires h5py)
def parse_hdf5(path):
    import h5py
    with h5py.File(path, 'r') as f:
        return f['temperature'].tolist()

# YAML files (requires pyyaml)
def parse_yaml(path):
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)

# NetCDF files (requires netCDF4)
def parse_netcdf(path):
    from netCDF4 import Dataset
    ds = Dataset(path)
    return ds.variables['temperature'][:].tolist()

# Parquet files (pandas)
def parse_parquet(path):
    import pandas as pd
    return pd.read_parquet(path).to_dict('list')
```

---

## Comparison Matrix

| Feature | CSV | JSON | Text | Excel | Custom |
|---------|-----|------|------|-------|--------|
| **Multiple columns** | ✅ Yes (5 opts) | ❌ No | ❌ No | ✅ (1 sheet) | ✅ Yes |
| **Structured data** | ✅ Tabular | ✅ Hierarchical | ❌ Unstructured | ✅ Sheets | Custom |
| **Multi-select** | ✅ Yes | ❌ Single key | ✅ Regex match | ✅ Yes (1 sheet) | ✅ Custom |
| **Transformation** | ✅ Yes (DataFrame) | ✅ Yes (callable) | ✅ Yes (callable) | ✅ Yes | ✅ Yes |
| **Large files** | ✅ Efficient | ✅ Good | ⚠️ Load all | ✅ Efficient | Custom |
| **Nested access** | ❌ Flat | ✅ Deep nesting | ❌ No | ❌ Flat | ✅ Custom |
| **Multiple sheets** | N/A | ❌ No | N/A | ✅ Multiple | N/A |

---

## Real-World Examples

### Example 1: CFD Simulation Output
```python
from labeeb import Case, PatternCsvHarvester, RegexHarvester

case = Case("cfd_sim")

# Tabular results from CSV
case.add_harvester(PatternCsvHarvester(
    "velocity_field", "field_data.csv", r"velocity_.*"
))

# Convergence metrics from log file
case.add_harvester(RegexHarvester(
    "residual", "simulation.log", 
    r"Final Residual:\s*([\d.eE+-]+)"
))
```

### Example 2: Multi-format Analysis
```python
from labeeb import (
    Case, JsonHarvester, ExcelHarvester, 
    CallableHarvester
)

case = Case("multi_output")

# Metadata from JSON
case.add_harvester(JsonHarvester(
    "metadata", "info.json", "simulation.timestamp"
))

# Results from Excel
case.add_harvester(ExcelHarvester(
    "results", "output.xlsx", "Temperature", sheet="Results"
))

# Custom binary data
case.add_harvester(CallableHarvester(
    "binary_metrics", "metrics.bin", 
    extractor=custom_binary_parser
))
```

### Example 3: Workflow with All Formats
```python
case = Case("comprehensive")

# Primary results
case.add_harvester(BulkCsvHarvester(
    "simulation_output", "final_results.csv"
))

# Configuration/metadata
case.add_harvester(JsonHarvester(
    "config", "simulation_config.json", "parameters"
))

# Convergence info from log
case.add_harvester(RegexHarvester(
    "iterations", "run.log", r"Completed (\d+) iterations"
))

# Formatted report
case.add_harvester(ExcelHarvester(
    "summary", "report.xlsx", sheet="Summary"
))
```

---

## Selecting the Right Format

| Simulation Type | Recommended Format | Reason |
|-----------------|-------------------|--------|
| **CFD/FEM** | CSV + Log files | Tables for fields, logs for convergence |
| **Multi-Physics** | JSON + Excel | Structure for configs, sheets for results |
| **Research Code** | CSV + Regex | Simple outputs, text parsing |
| **Commercial Software** | Excel + Custom | Formatted output, proprietary formats |
| **Data Pipeline** | Parquet/HDF5 | Large datasets, compression |
| **Quick Analysis** | CSV + JSON | Fast reads, simple structure |

---

## Best Practices

1. **CSV for large tabular data** - Efficient pandas backend
2. **JSON for configuration/metadata** - Hierarchical structure
3. **Log files with Regex** - Simple metrics from text output
4. **Excel for formatted reports** - Human-readable sheets
5. **Custom parsers for special formats** - Maximum flexibility

## Combining Harvesters

```python
# Extract from multiple file types in one case
case.add_harvester(BulkCsvHarvester("field_data", "field.csv"))
case.add_harvester(JsonHarvester("config", "config.json", "parameters"))
case.add_harvester(RegexHarvester("status", "log.txt", r"Status: (\w+)"))
case.add_harvester(ExcelHarvester("summary", "report.xlsx", sheet="Summary"))

case.launch()

# Access all extracted data
print(case.outputs["field_data"])      # CSV data
print(case.outputs["config"])          # JSON structure
print(case.outputs["status"])          # Log extraction
print(case.outputs["summary"])         # Excel data
```

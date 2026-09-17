# AutoHarvester - Automatic File Type Detection

**Unified harvester for all file types with automatic format detection.**

## The Problem

Previously, you had to know which harvester to use for each file type:

```python
# OLD WAY - Must choose correct harvester for each file
from labeeb import CsvHarvester, JsonHarvester, RegexHarvester, ExcelHarvester

case.add_harvester(CsvHarvester("temp", "results.csv", "temperature"))
case.add_harvester(JsonHarvester("config", "config.json", "parameters"))
case.add_harvester(RegexHarvester("energy", "sim.log", r"Energy = ([\d.]+)"))
case.add_harvester(ExcelHarvester("sheet", "data.xlsx", "Temperature"))
```

## The Solution: AutoHarvester

**One harvester that detects file type automatically:**

```python
# NEW WAY - AutoHarvester figures it out
from labeeb import AutoHarvester

case.add_harvester(AutoHarvester("temp", "results.csv", column="temperature"))
case.add_harvester(AutoHarvester("config", "config.json", key="parameters"))
case.add_harvester(AutoHarvester("energy", "sim.log", pattern=r"Energy = ([\d.]+)"))
case.add_harvester(AutoHarvester("sheet", "data.xlsx", column="Temperature"))
```

---

## How It Works

### 1. Automatic Detection (No Explicit Type Needed)

```python
from labeeb import AutoHarvester, detect_file_type

# These are detected automatically:
detect_file_type("results.csv")     # → "csv"
detect_file_type("config.json")     # → "json"
detect_file_type("sim.log")         # → "text"
detect_file_type("data.xlsx")       # → "excel"

# So you can just use AutoHarvester:
case.add_harvester(AutoHarvester("data", "results.csv", column="temperature"))
# Automatically detects CSV format ✓
```

### 2. Explicit Type Override (If Needed)

```python
# If file extension doesn't match content:
case.add_harvester(
    AutoHarvester(
        "data", 
        "output.txt",          # Has .txt extension
        column="temperature",
        file_type="csv"        # But it's actually CSV
    )
)
```

---

## Supported File Types & Extensions

| File Type | Extensions | AutoHarvester Use |
|-----------|-----------|-------------------|
| **CSV** | .csv, .tsv, .dat | `column="col_name"` |
| **JSON** | .json | `key="path.to.value"` |
| **Excel** | .xlsx, .xls | `column="col_name"`, `sheet=0` |
| **Text/Log** | .txt, .log, .out | `pattern=r"regex"` |

---

## Usage Examples

### CSV Files

```python
from labeeb import AutoHarvester

# Extract single column
case.add_harvester(
    AutoHarvester(
        "temperature",
        "results.csv",
        column="temperature"  # Auto-detects CSV
    )
)

# Extract all columns (returns DataFrame)
case.add_harvester(
    AutoHarvester(
        "full_data",
        "results.csv"  # No column specified → all data
    )
)
```

### JSON Files

```python
# Access nested values with dot notation
case.add_harvester(
    AutoHarvester(
        "final_temp",
        "config.json",
        key="results.final_state.temperature"  # Auto-detects JSON
    )
)

case.add_harvester(
    AutoHarvester(
        "sim_params",
        "config.json",
        key="simulation.parameters"
    )
)
```

### Text/Log Files

```python
# Extract with regex patterns
case.add_harvester(
    AutoHarvester(
        "final_energy",
        "simulation.log",
        pattern=r"Final Energy\s*=\s*([\d.eE+-]+)"  # Auto-detects text
    )
)

case.add_harvester(
    AutoHarvester(
        "convergence_status",
        "output.txt",
        pattern=r"Status:\s*(\w+)"
    )
)
```

### Excel Files

```python
# Extract column from first sheet
case.add_harvester(
    AutoHarvester(
        "temperature",
        "results.xlsx",
        column="Temperature",
        sheet=0  # Auto-detects Excel
    )
)

# Extract from named sheet
case.add_harvester(
    AutoHarvester(
        "stress_data",
        "results.xlsx",
        column="Stress_XX",
        sheet="Stresses"
    )
)

# Get full sheet as DataFrame
case.add_harvester(
    AutoHarvester(
        "full_sheet",
        "results.xlsx",
        sheet="Results"
        # No column specified → returns full DataFrame
    )
)
```

---

## AutoHarvester vs Specific Harvesters

| Aspect | AutoHarvester | CsvHarvester | JsonHarvester | etc. |
|--------|---------------|--------------|---------------|------|
| **File type detection** | ✅ Automatic | ❌ No | ❌ No | ❌ No |
| **Override capability** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Code simplicity** | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ |
| **Flexibility** | ✅ High | Limited | Limited | Limited |
| **Learning curve** | ⭐⭐ (One class) | ⭐⭐⭐ (Multiple) | ⭐⭐⭐ | ⭐⭐⭐ |

---

## Common Patterns

### Pattern: Mixed File Types in Single Case

```python
case = Case("analysis")

# Extract from multiple file types using single AutoHarvester
case.add_harvester(
    AutoHarvester("thermal_data", "thermal.csv", column="temperature")
)
case.add_harvester(
    AutoHarvester("config", "setup.json", key="parameters.initial_temp")
)
case.add_harvester(
    AutoHarvester("convergence", "output.log", pattern=r"Residual:\s*([\d.eE+-]+)")
)
case.add_harvester(
    AutoHarvester("results", "summary.xlsx", column="Final_Values")
)

case.launch()

# Access all extracted data with simple names
print(case.outputs["thermal_data"])
print(case.outputs["config"])
print(case.outputs["convergence"])
print(case.outputs["results"])
```

### Pattern: Explicit Type When Extension Misleads

```python
# Sometimes file extensions don't match content
# Solution: Use file_type parameter

# File saved as .txt but contains CSV data
case.add_harvester(
    AutoHarvester(
        "data",
        "output.txt",
        column="temperature",
        file_type="csv"  # Override extension
    )
)

# File saved as generic extension but is JSON
case.add_harvester(
    AutoHarvester(
        "config",
        "data.dat",
        key="settings.temp",
        file_type="json"  # Override extension
    )
)
```

### Pattern: With Transforms

```python
# AutoHarvester accepts optional transform parameter
case.add_harvester(
    AutoHarvester(
        "processed",
        "results.csv",
        column="temperature",
        transform=lambda data: [round(x, 2) for x in data]
    )
)

case.add_harvester(
    AutoHarvester(
        "config_dict",
        "config.json",
        key="parameters",
        transform=lambda obj: {k: v for k, v in obj.items() if v is not None}
    )
)
```

---

## File Type Detection Algorithm

```python
from pathlib import Path

def detect_file_type(file_path):
    """Auto-detect based on extension"""
    extension_map = {
        # CSV variants
        '.csv': 'csv',
        '.tsv': 'csv',
        '.dat': 'csv',
        # JSON
        '.json': 'json',
        # Excel
        '.xlsx': 'excel',
        '.xls': 'excel',
        # Text/Log
        '.txt': 'text',
        '.log': 'text',
        '.out': 'text',
    }
    
    ext = Path(file_path).suffix.lower()
    return extension_map.get(ext, 'unknown')
```

---

## Error Handling

```python
# Missing required parameter for file type
try:
    case.add_harvester(
        AutoHarvester("bad", "config.json")  # Missing 'key' parameter
    )
    case.launch()
except ExtractionError as e:
    # "JSON harvester requires 'key' parameter"
    print(e)

# Unknown file type
try:
    case.add_harvester(
        AutoHarvester("unknown", "data.xyz")  # .xyz not recognized
    )
    case.launch()
except ExtractionError as e:
    # "Unknown file type for 'data.xyz'. Explicitly set file_type..."
    print(e)

# Explicit type override for unknown extension
case.add_harvester(
    AutoHarvester(
        "data",
        "data.xyz",
        column="temperature",
        file_type="csv"  # Explicitly tell it what format to use
    )
)
```

---

## Best Practices

1. **Use AutoHarvester by default** - No need for specific harvester classes
2. **Rely on auto-detection** - Works for standard file extensions
3. **Use file_type override sparingly** - Only when extension doesn't match content
4. **Document non-standard formats** - Add comments explaining explicit file_type
5. **Combine with transforms** - Use transform parameter for post-processing

---

## Migration Path

### Before (4 Different Harvesters)
```python
from labeeb import (
    CsvHarvester, JsonHarvester, RegexHarvester, ExcelHarvester
)

case.add_harvester(CsvHarvester("temp", "results.csv", "temperature"))
case.add_harvester(JsonHarvester("config", "config.json", "parameters"))
case.add_harvester(RegexHarvester("status", "output.log", r"Status: (\w+)"))
case.add_harvester(ExcelHarvester("sheet", "data.xlsx", "Temperature"))
```

### After (1 AutoHarvester)
```python
from labeeb import AutoHarvester

case.add_harvester(AutoHarvester("temp", "results.csv", column="temperature"))
case.add_harvester(AutoHarvester("config", "config.json", key="parameters"))
case.add_harvester(AutoHarvester("status", "output.log", pattern=r"Status: (\w+)"))
case.add_harvester(AutoHarvester("sheet", "data.xlsx", column="Temperature"))
```

---

## API Reference

### detect_file_type(file_path)

Detect file type by extension.

```python
from labeeb import detect_file_type

file_type = detect_file_type("results.csv")  # → "csv"
file_type = detect_file_type("config.json")  # → "json"
```

**Returns:** `str` - One of: "csv", "json", "excel", "text", "unknown"

---

### AutoHarvester.__init__()

```python
AutoHarvester(
    name: str,                    # Harvester name
    file_target: Union[str, Path],  # Output file path
    column: Optional[str] = None,   # Column name (CSV/Excel)
    key: Optional[str] = None,      # JSON key with dot notation
    pattern: Optional[str] = None,  # Regex pattern (text)
    sheet: Union[str, int] = 0,     # Sheet name/index (Excel)
    file_type: Optional[str] = None,  # Override: 'csv'|'json'|'excel'|'text'
    transform: Optional[Callable] = None,  # Post-processing function
    optional: bool = False          # If True, missing file → None
)
```

---

## Summary

| Feature | AutoHarvester | Benefit |
|---------|---|---|
| **Auto-detection** | ✓ | No need to specify harvester type |
| **Single class** | ✓ | Simpler, fewer imports |
| **Override option** | ✓ | Handles edge cases |
| **All formats** | ✓ | CSV, JSON, Excel, Text |
| **Backward compatible** | ✓ | Specific harvesters still work |

**Use AutoHarvester for new code. Keep specific harvesters for special cases.**

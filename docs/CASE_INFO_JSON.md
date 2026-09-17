# Case Info JSON - Execution Metadata with Timestamped Commands

**Automatic case metadata file generation with complete execution history.**

## Overview

`case_info.json` is automatically generated in each case directory during `case.launch_case()` execution. It contains:

- **Case identification:** Case ID, name, and timestamp
- **Database attributes:** All database column values for this case
- **Dynamic attribute values:** Computed dynamic attributes at execution time
- **Timestamped execution commands:** Full list of commands executed with timestamps and results
- **Execution status:** Overall status, timing, and exit codes
- **Outputs:** All harvested outputs
- **Metadata:** Directory path, user, run type, version

This enables **case mode workflows** to:
1. Validate case state consistency
2. Detect when commands have changed
3. Conditionally execute tasks based on command differences
4. Support smart case re-execution strategies

---

## File Location

Each case directory contains a `case_info.json` file:

```
output/
├── case_0/
│   ├── case_info.json       ← Generated automatically
│   ├── input.txt
│   ├── output.h5
│   └── ...
├── case_1/
│   ├── case_info.json
│   ├── input.txt
│   ├── output.h5
│   └── ...
```

---

## File Structure

### Complete Example

```json
{
  "case_id": 0,
  "case_name": "thermal_analysis",
  "timestamp": "2026-09-17T19:05:30.123456",
  "database_attributes": {
    "temperature": 350,
    "pressure": 102.5,
    "material": "aluminum",
    "mesh_size": 0.1
  },
  "dynamic_attributes_values": {
    "reynolds_number": 45000,
    "mach_number": 0.85
  },
  "execution": {
    "status": "success",
    "start_time": "2026-09-17T19:05:30",
    "end_time": "2026-09-17T19:05:40",
    "commands_executed": [
      {
        "command": "/usr/bin/simulator --input input.txt --output output.h5",
        "timestamp": "2026-09-17T19:05:30",
        "duration_seconds": 8.5,
        "exit_code": 0,
        "status": "SUCCESS"
      },
      {
        "command": "/usr/bin/postprocessor output.h5 results.csv",
        "timestamp": "2026-09-17T19:05:38",
        "duration_seconds": 1.2,
        "exit_code": 0,
        "status": "SUCCESS"
      }
    ],
    "exit_codes": [0, 0]
  },
  "outputs": {
    "final_temperature": [425.5],
    "max_stress": [250.3],
    "computation_time": [9.7]
  },
  "metadata": {
    "case_directory": "/home/user/work/output/case_0",
    "user": "omari",
    "run_type": "new",
    "version": "2.2.0"
  }
}
```

### Field Descriptions

#### Top Level
- **case_id** (int): Unique case identifier
- **case_name** (str): Name of the case/simulation
- **timestamp** (str): ISO format timestamp when case_info.json was generated

#### database_attributes (object)
- Database column names mapped to their values for this case
- Enables validation: compare with stored case_info to detect database changes

#### dynamic_attributes_values (object)
- Computed dynamic attribute values at execution time
- Shows derived quantities used during case execution

#### execution (object)
- **status** (str): "success" or "failed"
- **start_time** (str): When first command started
- **end_time** (str): When last command finished
- **commands_executed** (array): Timestamped command list
  - **command** (str): Full command executed
  - **timestamp** (str): When this specific command started (ISO format)
  - **duration_seconds** (float): How long this command took
  - **exit_code** (int): Return code (0 = success)
  - **status** (str): "SUCCESS", "FAILED", or "TIMEOUT"
- **exit_codes** (array): All exit codes in order

#### outputs (object)
- Same as `case.outputs` - all harvested metrics and results
- Enables output validation and comparison

#### metadata (object)
- **case_directory** (str): Full path to case directory
- **user** (str): Username that executed the case
- **run_type** (str): "new", "overwrite", "continue", or "read_only"
- **version** (str): Labeeb version used

---

## Use Cases

### 1. Case Mode Validation

Detect if a case can be safely reused:

```python
import json
from pathlib import Path

case_dir = Path("output/case_0")
info_file = case_dir / "case_info.json"

if not info_file.exists():
    print("Case not executed yet")
    case.launch_case(case_id=0)
else:
    with open(info_file) as f:
        case_info = json.load(f)
    
    # Check if database attributes match current database
    current_db_row = database.get_row(0)
    stored_db_attrs = case_info["database_attributes"]
    
    if current_db_row.to_dict() == stored_db_attrs:
        print("✓ Case state matches database - can reuse outputs")
    else:
        print("✗ Database changed - need to re-execute")
        case.launch_case(case_id=0, run_type="overwrite")
```

### 2. Command Change Detection

Execute tasks only if commands changed:

```python
def run_postprocessing(case_info):
    """Run post-processing only if simulation command changed."""
    current_cmd = "/usr/bin/simulator --input input.txt --output output.h5"
    
    commands = case_info["execution"]["commands_executed"]
    sim_cmd = commands[0]["command"]  # First command is simulation
    
    if sim_cmd != current_cmd:
        print("Simulation command changed - re-running post-processing")
        # Rerun post-processing step
    else:
        print("Simulation command unchanged - skipping post-processing")

with open("case_0/case_info.json") as f:
    info = json.load(f)
    run_postprocessing(info)
```

### 3. Execution History

Track all commands executed in a case:

```python
with open("case_0/case_info.json") as f:
    case_info = json.load(f)

print(f"Case {case_info['case_id']} executed on {case_info['timestamp']}")
print(f"Status: {case_info['execution']['status']}")
print(f"Total duration: {case_info['execution']['end_time']}")
print("\nCommands executed:")

for i, cmd in enumerate(case_info["execution"]["commands_executed"], 1):
    print(f"  {i}. {cmd['command']}")
    print(f"     Time: {cmd['timestamp']}")
    print(f"     Duration: {cmd['duration_seconds']:.2f}s")
    print(f"     Exit code: {cmd['exit_code']}")
```

### 4. Case Comparison

Compare two cases:

```python
import json

def compare_cases(case_a_dir, case_b_dir):
    """Compare execution history and results of two cases."""
    with open(f"{case_a_dir}/case_info.json") as f:
        info_a = json.load(f)
    with open(f"{case_b_dir}/case_info.json") as f:
        info_b = json.load(f)
    
    # Compare commands
    cmds_a = info_a["execution"]["commands_executed"]
    cmds_b = info_b["execution"]["commands_executed"]
    
    if cmds_a == cmds_b:
        print("✓ Same commands executed")
    else:
        print("✗ Commands differ")
    
    # Compare outputs
    if info_a["outputs"] == info_b["outputs"]:
        print("✓ Same outputs")
    else:
        print("✗ Outputs differ")
        
    # Compare timing
    time_a = float(info_a["execution"]["end_time"].split("T")[1].split(".")[0].replace(":", ""))
    time_b = float(info_b["execution"]["end_time"].split("T")[1].split(".")[0].replace(":", ""))
    print(f"Case A duration: {info_a['execution']['duration_seconds']:.1f}s")
    print(f"Case B duration: {info_b['execution']['duration_seconds']:.1f}s")

compare_cases("output/case_0", "output/case_1")
```

### 5. Workflow Orchestration

Implement smart case re-execution logic:

```python
def should_reexecute(case_id, case_dir, database, command_list):
    """Determine if case should be re-executed."""
    info_file = Path(case_dir) / "case_info.json"
    
    # Case hasn't run yet
    if not info_file.exists():
        return True
    
    with open(info_file) as f:
        case_info = json.load(f)
    
    # Database attributes changed
    db_row = database.get_row(case_id)
    if dict(db_row) != case_info["database_attributes"]:
        print(f"Case {case_id}: Database changed - re-execute")
        return True
    
    # Commands changed
    stored_cmds = [c["command"] for c in case_info["execution"]["commands_executed"]]
    if stored_cmds != command_list:
        print(f"Case {case_id}: Commands changed - re-execute")
        return True
    
    # Case previously failed
    if case_info["execution"]["status"] != "success":
        print(f"Case {case_id}: Previous execution failed - retry")
        return True
    
    print(f"Case {case_id}: No changes detected - skip")
    return False

# Usage
for case_id in range(num_cases):
    if should_reexecute(case_id, "output", database, exe_cmd):
        case.launch_case(case_id=case_id, run_type="overwrite")
```

---

## Automatic Generation

The `case_info.json` file is generated automatically at the end of `Case.launch_case()`:

```python
case = Case("thermal")
case.database = Database(...)
case.launch_case(case_id=0)
# → output/case_0/case_info.json created automatically
```

No manual intervention required. The file is always created for:
- "new" mode executions
- "overwrite" mode executions  
- "continue" mode executions (only if case directory didn't exist)
- "read_only" mode (outputs already parsed)

---

## Reading case_info.json

### Python

```python
import json

with open("case_0/case_info.json") as f:
    case_info = json.load(f)

# Access data
case_id = case_info["case_id"]
commands = case_info["execution"]["commands_executed"]
status = case_info["execution"]["status"]
```

### Command Line (jq)

```bash
# View case status
jq '.execution.status' case_0/case_info.json

# List all commands
jq '.execution.commands_executed[].command' case_0/case_info.json

# Get execution duration
jq '.execution | {start: .start_time, end: .end_time}' case_0/case_info.json

# Check database attributes
jq '.database_attributes' case_0/case_info.json
```

### Pandas

```python
import pandas as pd
import json

# Load metadata
with open("case_0/case_info.json") as f:
    case_info = json.load(f)

# Convert commands to DataFrame
df_commands = pd.DataFrame(case_info["execution"]["commands_executed"])
print(df_commands[["command", "timestamp", "duration_seconds", "exit_code", "status"]])
```

---

## Case Mode Workflow Example

Complete example of using case_info.json in a case mode workflow:

```python
from pathlib import Path
import json
from labeeb import Case, Database

def smart_case_execution(database, exe_cmd, case_ids, output_dir):
    """Execute cases with smart re-execution based on case_info.json."""
    
    for case_id in case_ids:
        case_dir = Path(output_dir) / f"case_{case_id}"
        info_file = case_dir / "case_info.json"
        
        # Check if case needs execution
        if info_file.exists():
            with open(info_file) as f:
                case_info = json.load(f)
            
            # Validate database state
            db_row = dict(database.get_row(case_id))
            if db_row == case_info["database_attributes"]:
                # Validate commands
                stored_cmds = [c["command"] for c in case_info["execution"]["commands_executed"]]
                if stored_cmds == exe_cmd and case_info["execution"]["status"] == "success":
                    print(f"✓ Case {case_id}: Valid cache, skipping execution")
                    continue
        
        # Execute case
        print(f"→ Case {case_id}: Executing...")
        case = Case(f"case_{case_id}", output_files={})
        case.database = database
        case.exe_cmd = exe_cmd
        case.launch_case(case_id=case_id)
        print(f"✓ Case {case_id}: Complete")

# Usage
db = Database(data={"temp": [300, 350, 400], "pressure": [100, 105, 110]})
cmd = ["/usr/bin/simulator input.txt"]
smart_case_execution(db, cmd, [0, 1, 2], "output")
```

---

## Benefits

| Feature | Benefit |
|---------|---------|
| **Timestamped commands** | Know exactly when each command ran, detect timing regressions |
| **Exit codes** | Identify which commands failed in multi-command cases |
| **Duration tracking** | Monitor performance changes across re-executions |
| **Database snapshot** | Validate case state consistency |
| **Dynamic attributes** | Track computed quantities at execution time |
| **Complete metadata** | Understand case context: user, version, run type |
| **Case validation** | Safely determine if case can be reused or must be re-executed |
| **Workflow automation** | Enable smart, data-driven case orchestration |

---

## Migration Guide

### Before (Manual Tracking)

```python
# Had to manually record execution details
case_executed = False
if os.path.exists("case_0/output.h5"):
    case_executed = True
```

### After (Automatic via case_info.json)

```python
# Automatic metadata available
with open("case_0/case_info.json") as f:
    case_info = json.load(f)
    status = case_info["execution"]["status"]
    commands = case_info["execution"]["commands_executed"]
    # Full execution history automatically tracked
```

---

## See Also

- **Case Mode Documentation:** Guide for smart case re-execution workflows
- **Database Filtering:** `db.filter()` for advanced case state queries
- **Execution History:** `case.execution_history` for in-memory command tracking


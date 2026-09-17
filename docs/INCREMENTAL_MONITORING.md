# Incremental case_info.json Monitoring (v2.3.8+)

## Overview

Starting in v2.3.8, `case_info.json` is written incrementally after each command completes, enabling real-time execution monitoring without polling delays. Each command includes precise ISO 8601 timestamps for exact start and end times.

## Key Features

- **Incremental Writes**: JSON saved after every command, not just at the end
- **Granular Timing**: Separate start_time and end_time for each command (microsecond precision)
- **Real-Time Monitoring**: External tools can poll for live progress
- **Low Overhead**: Minimal JSON I/O impact on execution

## Structure

### Before v2.3.8
```json
{
  "execution": {
    "commands_executed": [
      {
        "command": "echo 'Step 1'",
        "timestamp": "2026-09-17 23:33:52",
        "duration_seconds": 0.003,
        "status": "SUCCESS"
      }
    ]
  }
}
```

### v2.3.8+
```json
{
  "case_id": 0,
  "case_name": "demo",
  "execution": {
    "status": "success",
    "start_time": "2026-09-17T23:33:52.103996",
    "end_time": "2026-09-17T23:33:52.111723",
    "commands_executed": [
      {
        "command": "echo 'Step 1: Initialization'",
        "start_time": "2026-09-17T23:33:52.103996",
        "end_time": "2026-09-17T23:33:52.107028",
        "duration_seconds": 0.003032,
        "exit_code": 0,
        "status": "SUCCESS"
      },
      {
        "command": "echo 'Step 2: Processing'",
        "start_time": "2026-09-17T23:33:52.107215",
        "end_time": "2026-09-17T23:33:52.109427",
        "duration_seconds": 0.002212,
        "exit_code": 0,
        "status": "SUCCESS"
      }
    ]
  }
}
```

## Usage Examples

### Real-Time Progress Monitoring

```python
from labeeb import Case, Database
import json
import time
from pathlib import Path

case = Case(name="long_running", output_files={})
case.database = Database(data={"param": [1.0]})
case.exe_cmd = [
    "sleep 1 && echo 'Phase 1 complete'",
    "sleep 2 && echo 'Phase 2 complete'",
    "sleep 1 && echo 'Phase 3 complete'",
]
case.run_case_main_dir = "runs"
case.run_type = "new"

# Start execution in background (or just launch)
case.launch()

# case_info.json is now available and updated after each command
case_info_path = Path("runs/case_0/case_info.json")
with open(case_info_path) as f:
    info = json.load(f)

print(f"Case: {info['case_name']}")
print(f"Status: {info['execution']['status']}")
print(f"Commands executed: {len(info['execution']['commands_executed'])}")
print(f"Timing:")
for cmd in info['execution']['commands_executed']:
    print(f"  {cmd['command']}: {cmd['duration_seconds']:.3f}s")
```

### Live Execution Dashboard (Polling)

```python
import json
import time
from pathlib import Path

case_dir = Path("runs/case_0")
case_info_file = case_dir / "case_info.json"

def get_progress():
    """Get current execution progress."""
    try:
        with open(case_info_file) as f:
            info = json.load(f)
        return {
            'status': info['execution']['status'],
            'total_commands': len(info['execution']['commands_executed']),
            'total_duration': sum(
                cmd.get('duration_seconds', 0) 
                for cmd in info['execution']['commands_executed']
            ),
        }
    except FileNotFoundError:
        return None

# Monitor execution
while True:
    progress = get_progress()
    if progress is None:
        print("Waiting for execution...")
    else:
        print(f"Status: {progress['status']:8} | "
              f"Commands: {progress['total_commands']} | "
              f"Elapsed: {progress['total_duration']:.1f}s")
        
        if progress['status'] in ('success', 'failed'):
            break
    
    time.sleep(1)
```

### Performance Analysis

```python
import json
from pathlib import Path
from typing import Dict, List

def analyze_performance(case_dir: Path) -> Dict:
    """Analyze command execution performance."""
    case_info_file = case_dir / "case_info.json"
    
    with open(case_info_file) as f:
        info = json.load(f)
    
    commands = info['execution']['commands_executed']
    
    return {
        'total_time': info['execution']['end_time'] - info['execution']['start_time'],  # Requires parsing
        'num_commands': len(commands),
        'per_command_times': [cmd['duration_seconds'] for cmd in commands],
        'slowest_command': max(commands, key=lambda c: c['duration_seconds']),
        'fastest_command': min(commands, key=lambda c: c['duration_seconds']),
        'average_time': sum(c['duration_seconds'] for c in commands) / len(commands),
    }

# Analyze case
from datetime import datetime

case_dir = Path("runs/case_0")
with open(case_dir / "case_info.json") as f:
    info = json.load(f)

cmds = info['execution']['commands_executed']
start = datetime.fromisoformat(info['execution']['start_time'])
end = datetime.fromisoformat(info['execution']['end_time'])
total = (end - start).total_seconds()

print(f"Total execution time: {total:.2f}s")
print(f"Number of commands: {len(cmds)}")
print(f"Average per command: {total / len(cmds):.3f}s")
print(f"\nPer-command breakdown:")
for i, cmd in enumerate(cmds, 1):
    print(f"  {i}. {cmd['command'][:50]:50} {cmd['duration_seconds']:.3f}s")
```

## Integration with External Tools

### Kubernetes Monitoring

```yaml
# Deployment monitoring case_info.json
apiVersion: batch/v1
kind: Job
metadata:
  name: labeeb-case
spec:
  template:
    spec:
      containers:
      - name: simulator
        image: myapp:latest
        command:
        - python
        - -c
        - |
          from labeeb import Campaign
          c = Campaign.from_manifest("manifest.yaml")
          c.run()
          # case_info.json automatically created
      volumeMounts:
      - name: results
        mountPath: /results
```

### CI/CD Pipeline

```yaml
# GitHub Actions monitoring case execution
name: Monitor Case Execution
on: [push]
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run simulation
        run: python -m labeeb run manifest.yaml
      - name: Check execution status
        run: |
          python -c "
          import json
          with open('case_0/case_info.json') as f:
              info = json.load(f)
          if info['execution']['status'] != 'success':
              exit(1)
          "
```

## Real-Time Logging

```python
import json
import time
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

def monitor_case_with_logging(case_dir: Path, poll_interval: float = 0.5):
    """Monitor case execution and log updates."""
    case_info_file = case_dir / "case_info.json"
    last_command_count = 0
    
    while True:
        try:
            with open(case_info_file) as f:
                info = json.load(f)
        except FileNotFoundError:
            logger.debug("Waiting for case_info.json...")
            time.sleep(poll_interval)
            continue
        
        commands = info['execution']['commands_executed']
        current_count = len(commands)
        
        # Log new commands
        if current_count > last_command_count:
            for cmd in commands[last_command_count:]:
                cmd_start = datetime.fromisoformat(cmd['start_time'])
                cmd_end = datetime.fromisoformat(cmd['end_time'])
                duration = (cmd_end - cmd_start).total_seconds()
                
                logger.info(
                    f"Command completed: {cmd['command'][:60]} "
                    f"Status={cmd['status']} Duration={duration:.3f}s"
                )
            
            last_command_count = current_count
        
        # Check if execution finished
        if info['execution']['status'] in ('success', 'failed'):
            logger.info(f"Case execution finished: {info['execution']['status']}")
            break
        
        time.sleep(poll_interval)

# Usage
from pathlib import Path
monitor_case_with_logging(Path("runs/case_0"))
```

## Timing Format

### ISO 8601 Format
All timestamps use ISO 8601 format with microsecond precision:
```
2026-09-17T23:33:52.103996
```

### Parsing in Python
```python
from datetime import datetime

timestamp_str = "2026-09-17T23:33:52.103996"
dt = datetime.fromisoformat(timestamp_str)

# Calculate duration between two timestamps
start = datetime.fromisoformat(cmd['start_time'])
end = datetime.fromisoformat(cmd['end_time'])
duration_seconds = (end - start).total_seconds()
```

## Performance Impact

### Storage Overhead
- Minimal: ~1-2 KB per command record
- Typical case with 10 commands: ~20 KB JSON file
- No compression needed for most use cases

### I/O Overhead
- One JSON write per command execution
- Negligible compared to simulation runtime
- Asynchronous options available (future enhancement)

### Monitoring Overhead
- Polling adds minimal CPU cost
- Typical poll interval: 0.5-1.0 seconds
- Does not interfere with case execution

## Best Practices

### 1. Poll Responsibly
```python
# ✓ Good: reasonable poll interval
time.sleep(1)

# ✗ Bad: too aggressive, wastes CPU
time.sleep(0.001)
```

### 2. Handle Missing Files Gracefully
```python
def safe_read_case_info(case_dir):
    try:
        with open(case_dir / "case_info.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return None  # Execution not started yet
    except json.JSONDecodeError:
        return None  # File being written
```

### 3. Cache Results
```python
last_update = None

def get_progress():
    global last_update
    
    current = read_case_info()
    if current == last_update:
        return  # No change, skip processing
    
    last_update = current
    # Process update
```

## Troubleshooting

| Issue | Solution |
|---|---|
| case_info.json not created | Check case_dir exists and is writable |
| Timestamps are UTC | Convert to local timezone if needed |
| JSON parsing errors | Use try/except for concurrent writes |
| Missing commands | File updated incrementally, wait for completion |


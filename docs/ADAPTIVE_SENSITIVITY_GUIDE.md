# Adaptive Sensitivity Analysis Workflow Guide

**Labeeb v2.1.0+** includes a comprehensive three-phase adaptive sensitivity analysis framework for parameter optimization and iterative design refinement.

## Overview

The adaptive workflow coordinates three distinct phases:

1. **SCREENING**: Sensitivity identification using OAT design and Morris analysis
2. **TARGETING**: Feedback-driven refinement toward target values using sensitivities
3. **REFINEMENT**: Adaptive sampling to converge on optimal region

## Architecture

### Core Classes

#### `Phase` (Enum)
Identifies workflow phases:
- `Phase.SCREENING` - Sensitivity screening phase
- `Phase.TARGETING` - Feedback refinement phase
- `Phase.REFINEMENT` - Adaptive refinement phase

#### `DesignPoint` (Dataclass)
Represents a single design point with execution results:
```python
@dataclass
class DesignPoint:
    parameters: Dict[str, float]  # Input parameters
    outputs: Dict[str, float]     # Simulation outputs (KEFF, power, etc.)
    iteration: int                # Iteration number within phase
    phase: Phase                  # Workflow phase
    case_id: Optional[int]        # Case identifier
    metadata: Dict[str, Any]      # Additional metadata
```

#### `ResultsPool`
Collection manager for design points across all phases:
```python
pool = ResultsPool(target_output="KEFF")

# Add design points
pool.add(design_point)
pool.extend([point1, point2, point3])

# Analysis
sensitivities = pool.estimate_sensitivities()
morris_effects = pool.estimate_morris_effects(phase=Phase.SCREENING)

# Export
df = pool.to_dataframe()
pool.export_to_csv("results.csv")
```

#### `AdaptiveSensitivityAnalysis`
Master coordinator for the three-phase workflow:
```python
workflow = AdaptiveSensitivityAnalysis(
    case_runner=case,
    base_database=db,
    target_output="KEFF",
    target_value=1.2,
    tolerance=0.0002,
)

# Run full workflow
results = workflow.run_full_workflow(
    parameter_ranges={"RHO": [17, 19, 21], "WF": [0.015, 0.020, 0.025]},
    param_bounds={"RHO": (17, 21), "WF": (0.015, 0.025)},
    initial_params={"RHO": 18.0, "WF": 0.02},
)
```

## Phase Details

### Phase 1: SCREENING

Identifies which parameters have the most influence on outputs using Morris one-at-a-time design.

**Method**: `workflow.phase1_screening(parameter_ranges, seed=42)`

```python
parameter_ranges = {
    "RHO": [17.0, 19.0, 21.0],      # 3 density values
    "WF": [0.015, 0.020, 0.025],    # 3 weight fraction values
    "BURNUP": [0, 5, 10],           # 3 burnup values
}

sensitivities = workflow.phase1_screening(parameter_ranges)
print(sensitivities)
#           mean_effect  mean_absolute_effect  std_effect
# RHO             -0.025              0.025      0.001
# WF               0.500              0.500      0.002
# BURNUP          -0.010              0.010      0.001
```

**Output**: DataFrame with Morris elementary effects:
- `mean_effect`: Average directional effect (can be negative)
- `mean_absolute_effect`: Average magnitude of effect (always positive)
- `std_effect`: Variability in effect estimates

**Interpretation**:
- Higher `mean_absolute_effect` → parameter is more sensitive
- Higher `std_effect` → effect is interaction-dependent

### Phase 2: TARGETING

Uses Phase 1 sensitivities to drive feedback-controlled refinement toward target values.

**Method**: `workflow.phase2_targeting(initial_params, feedback_fn=None, max_iterations=10)`

```python
# Use default sensitivity-scaled feedback control
converged_params = workflow.phase2_targeting(
    initial_params={"RHO": 18.0, "WF": 0.02},
    max_iterations=10,
    damping_factor=0.5,
)

# Or provide custom feedback function
def my_feedback(state):
    """Custom feedback control logic."""
    params = state["parameters"]
    error = state["error"]
    sensitivities = state["sensitivities"]
    
    adjustments = {}
    for param_name, sensitivity in sensitivities.items():
        # Custom formula: adjustment = f(error, sensitivity, ...)
        adjustments[param_name] = (error / sensitivity) * 0.3
    
    return adjustments

converged_params = workflow.phase2_targeting(
    initial_params={"RHO": 18.0, "WF": 0.02},
    feedback_fn=my_feedback,
    max_iterations=10,
)
```

**Default Feedback Control**:
```
For each parameter i:
    adjustment[i] = (target - current) / sensitivity[i] * damping_factor
    new_param[i] = current_param[i] + adjustment[i]
```

**State Dictionary** (passed to feedback_fn):
```python
{
    "parameters": {...},              # Current parameter values
    "outputs": {...},                 # Latest simulation outputs
    "error": float,                   # target_value - current_output
    "sensitivities": pd.DataFrame,    # Morris effects from Phase 1
}
```

### Phase 3: REFINEMENT

Adaptive sampling around convergence region to map local response surface.

**Method**: `workflow.phase3_refinement(converged_params, param_bounds, n_points=10, strategy="grid")`

```python
workflow.phase3_refinement(
    converged_params={"RHO": 19.2, "WF": 0.0198},
    param_bounds={"RHO": (17, 21), "WF": (0.015, 0.025)},
    n_points=15,
    strategy="grid",  # or "random" or "latin_hypercube"
)
```

**Strategies**:
- `"grid"`: Uniform grid sampling
- `"random"`: Random uniform sampling
- `"latin_hypercube"`: Latin Hypercube sampling (better coverage)

## Complete Workflow Example

```python
from labeeb import (
    AdaptiveSensitivityAnalysis, Database, Attribute, Case, Flag, FlagsMap, File, CsvHarvester
)

# 1. Setup Case Runner
flags = FlagsMap()
flags.add_flag(Flag("#RHO#", "RHO", "%5.2f"))
flags.add_flag(Flag("#WF#", "WF", "%6.4f"))

case_runner = Case(name="adaptive_solver")
case_runner.add_file(File("template.inp"))
case_runner.exe_cmd = [["python3", "mock_sim.py", "template.inp", "output.csv"]]
case_runner.add_harvester(CsvHarvester("KEFF", "output.csv", "KEFF"))

# 2. Create base database
db = Database(name="workflow_db")
db.add_attribute(
    Attribute("RHO", data=[19.0], unit="g/cm3"),
    Attribute("WF", data=[0.02], unit="fraction"),
)

# 3. Initialize workflow
workflow = AdaptiveSensitivityAnalysis(
    case_runner=case_runner,
    base_database=db,
    target_output="KEFF",
    target_value=1.2,
    tolerance=0.0002,
)

# 4. Run full three-phase workflow
results_pool = workflow.run_full_workflow(
    parameter_ranges={
        "RHO": [17.0, 19.0, 21.0],
        "WF": [0.015, 0.020, 0.025],
    },
    param_bounds={
        "RHO": (17.0, 21.0),
        "WF": (0.015, 0.025),
    },
    initial_params={
        "RHO": 18.0,
        "WF": 0.02,
    },
    phase2_max_iter=10,
    phase3_n_points=15,
    phase3_strategy="latin_hypercube",
)

# 5. Analyze results
results_df = results_pool.to_dataframe()
print(results_df)
results_pool.export_to_csv("adaptive_results.csv")

# Find best result
best_idx = results_df['KEFF'].sub(1.2).abs().idxmin()
print(f"Best: {results_df.loc[best_idx]}")
```

## Results Analysis

### DataFrame Format

```
   phase  iteration  case_id   RHO    WF  KEFF  error converged
0  screening        0        0  17.0  0.015  0.990  +0.210     False
1  screening        1        1  19.0  0.020  1.200  +0.000     True
2  screening        2        2  21.0  0.025  1.410  -0.210     False
3  targeting        0        0  18.0  0.020  1.090  +0.110     False
4  targeting        1        1  19.1  0.020  1.199  +0.001     True
5  refinement       0        0  18.9  0.018  1.180  +0.020     False
...
```

### Common Analysis Tasks

```python
# Filter by phase
screening_points = results_df[results_df['phase'] == 'screening']
targeting_points = results_df[results_df['phase'] == 'targeting']
refinement_points = results_df[results_df['phase'] == 'refinement']

# Get best result
best_keff_idx = results_df['KEFF'].sub(target_value).abs().idxmin()
best_point = results_df.loc[best_keff_idx]

# Convergence analysis
convergence_points = results_df[results_df['phase'] == 'targeting']
print(convergence_points[['iteration', 'RHO', 'WF', 'KEFF', 'error']])

# Sensitivity correlation with outputs
correlation = results_df[['RHO', 'WF', 'KEFF']].corr()
print(correlation)

# Export for further analysis
results_pool.export_to_csv("results.csv")
df = results_pool.to_dataframe()
df.to_excel("results.xlsx")
```

## Integration with Feedback Hooks

The adaptive workflow integrates with Labeeb's post-execution hooks:

```python
def adaptive_feedback_hook(case_obj, **kwargs):
    """Post-execution hook for adaptive refinement."""
    keff = case_obj.outputs.get("KEFF", None)
    if keff is not None:
        # Can update database attributes here for next iteration
        case_obj.database["RHO"][0] = new_value
        # Or trigger adaptive sampling
        # ...

case_runner.add_post_output_hook("adaptive_control", adaptive_feedback_hook)
```

## Advanced Customization

### Custom Feedback Functions

```python
def proportional_integral_feedback(state):
    """PI control with sensitivity-scaled gains."""
    params = state["parameters"]
    error = state["error"]
    sensitivities = state["sensitivities"]
    
    # Get integral of errors (requires additional state tracking)
    error_integral = getattr(proportional_integral_feedback, 'error_sum', 0)
    proportional_integral_feedback.error_sum = error_integral + error
    
    adjustments = {}
    for param_name in params.keys():
        sensitivity = sensitivities.loc[param_name, "mean_absolute_effect"]
        kp = 0.5 / sensitivity  # Proportional gain
        ki = 0.1 / sensitivity  # Integral gain
        
        adjustment = (kp * error) + (ki * error_integral)
        adjustments[param_name] = adjustment
    
    return adjustments

workflow.phase2_targeting(
    initial_params={"RHO": 18.0, "WF": 0.02},
    feedback_fn=proportional_integral_feedback,
)
```

### Multi-Objective Targeting

```python
def multi_output_feedback(state):
    """Feedback based on multiple outputs (KEFF and power)."""
    params = state["parameters"]
    outputs = state["outputs"]
    sensitivities = state["sensitivities"]
    
    # Weighted combination of errors
    keff_error = 1.2 - outputs["KEFF"]  # Target KEFF = 1.2
    power_error = 1000 - outputs["POWER"]  # Target power = 1000 MW
    
    total_error = 0.8 * keff_error + 0.2 * power_error
    
    adjustments = {}
    for param_name in params.keys():
        sensitivity = sensitivities.loc[param_name, "mean_absolute_effect"]
        adjustments[param_name] = (total_error / sensitivity) * 0.3
    
    return adjustments
```

## Performance Considerations

- **Phase 1**: n(1 + m) runs where n = avg values per parameter, m = num parameters
  - Example: 3 parameters with 3 values each → 3 × (1 + 3) = 12 design points
- **Phase 2**: max_iterations runs (typically 5-20)
- **Phase 3**: n_points runs (typically 10-50)

Total typical budget: 30-80 design evaluations

## See Also

- `labeeb.analysis` - Morris screening, correlation analysis, Sobol indices
- `labeeb.database` - Database and Attribute classes
- `labeeb.case` - Case runner and post-execution hooks
- `labeeb.sampler` - OAT, FOAT, LHS, Halton sampling

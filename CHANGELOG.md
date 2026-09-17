# Changelog

## 2.3.8 (Current)

### New Features
- **Incremental case_info.json Updates**: Write case_info.json after each command completes with granular timing (start_time/end_time in ISO format) for real-time execution monitoring
- **Database Merging Utilities**: New `labeeb.merge` module with functions to merge results from multiple campaigns:
  - `merge_case_results()` - Combine results with campaign tracking
  - `merge_case_info_json()` - Consolidate case metadata
  - `merge_outputs_with_parameters()` - Enrich outputs with input parameters
  - `aggregate_by_parameters()` - Group and summarize by parameter values
  - `validate_merge()` - Check merged data consistency
  - `export_merge_report()` - Export in CSV/Parquet/JSON/XLSX formats
- **Row-by-Row Validation Filtering**: New `row_filter` parameter for Database sampling
  - Validate constraints after each row is generated and derived
  - Track acceptance statistics (rate, attempts, rejections)
  - Get exactly n valid rows that pass filter criteria

### Bug Fixes
- Progress bar case counter and remaining time calculations

## 2.3.7

- case_info.json feature with timestamped execution commands
- Progress bar health metrics (success/warning/error tracking)

## 2.1.0

- Construct mixed normal, uniform, OAT, constant, and derived columns together.
- Choose Monte Carlo or Latin hypercube sampling independently of distributions.
- Reuse random draws across OAT rows or generate independent draws per row.
- Resolve derived expression chains in dependency order and recompute them after
  database source updates; support explicit dependencies for row callbacks.
- Support seeded custom `draw(size, rng)` samplers and custom LHS inverse CDFs.
- Validate distribution parameters, sampling options, and design column names.

Existing data constructors and default independent Monte Carlo sampling remain
supported. Legacy custom callables manage their own RNG state. Plan serialization,
correlated mixed designs, and additional built-in distributions are future work.

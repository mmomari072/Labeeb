# Labeeb Development Backlog

**Last Updated:** 2026-09-16

## Completed (v2.1.0+)

### ✅ ProgressBar Health Metrics Enhancement
**Commits:** `8f59a60`, `7052ee8`  
**Date:** 2026-09-17

- Implemented health metrics tracking (error_count, warning_count, success_count)
- Added report_case_status(status, error_msg) method for execution status reporting
- Implemented compact inline display format for all styles (default, apt, powershell)
- Added automatic ANSI color support detection for rich format option
- Implemented format fallback logic: rich → detailed → compact → headless
- Fixed positioning by using only carriage returns, no newlines breaking placement
- All display formats work correctly: headless shows counts, TTY shows inline metrics
- Works seamlessly with all progress bar styles (default, apt, powershell)
- 469/469 tests passing with health metrics fully integrated

**Display Examples:**
- Headless: `CASE:test_case: 1/2 [1/2][E:0% W:0%]`
- Default: `[CASE:test_case](50.00%)[===========] [1/2][E:0% W:0%] [Et:00:00:10][Rt:00:00:10]`
- Apt: `apt_test: 50.0% [====================] [1/2][E:0% W:0%]`
- PowerShell: `>> ps_test >> 50.00% [====================] [1/2][E:0% W:0%]`

---

### ✅ Database Display & Tabulation Support
**Commit:** `551c99a`  
**Date:** 2026-09-16

- Implemented missing `db.rows` attribute (was in `__dir__()` but not `__getattr__()`)
- Added comprehensive display/tabulation documentation to README.md
- Added detailed display examples to docs/USER_MANUAL.md
- Documented all display methods: `to_dataframe()`, `rows`, `get_row()`, `plot()`, export
- Users can now easily view database data in tabular format

### ✅ OATConstructor Factorial Design Fix
**Commits:** `d105b94`, `bdd2079`  
**Date:** 2026-09-16

- **Issue:** Multiple OAT attributes produced baseline+OAT instead of factorial design
  - Was producing 4 rows: z=[1,2,3,1], kk=[3,3,3,6]
  - Expected 6 rows: z=[1,1,2,2,3,3], kk=[3,6,3,6,3,6]
- **Solution:** Refactored OATConstructor with dual-mode behavior:
  - Single OAT attribute → baseline + one-at-a-time (Morris screening)
  - Multiple OAT attributes → full factorial Cartesian product
- **Feature:** Declaration order now matches variation speed
  - First-declared parameter varies slowest
  - Last-declared parameter varies fastest
- Created ISSUES.md to track design decisions
- Added comprehensive tests for both modes

### ✅ Database Save/Load Data Export
**Commit:** `a536f7e`  
**Date:** 2026-09-16

- **Issue:** `db.save()` failed with PicklingError on databases with lambda functions
  - Databases with Derived attributes using lambdas couldn't be pickled
- **Solution:** Changed `save()` to export data instead of pickling objects
  - Supports CSV, JSON, and Parquet formats
  - Auto-detects format from file extension
  - No more function serialization issues
- **Features:**
  - `db.save("file.csv")` → CSV export
  - `db.save("file.json", format="json")` → JSON export
  - `db.save("file.parquet")` → Parquet export
  - `load()` auto-detects and loads any format
- Derived attributes materialized as data (computed values preserved)
- Much more robust and portable than pickle

---

## Known Issues & Design Decisions

### 1. OATConstructor Behavior (RESOLVED)
**File:** `src/labeeb/sampler.py`  
**Status:** ✅ Fixed in v2.1.0+

Single vs multiple OAT attributes now handled consistently:
- Single OAT: baseline + variations (for Morris screening)
- Multiple OAT: full factorial product (for parametric sweeps)

### 2. Database Pickling Limitation (RESOLVED)
**File:** `src/labeeb/database.py`  
**Status:** ✅ Fixed - switched to data export

Lambda functions and other unpicklable objects are no longer a blocker for saving.

---

### ✅ Critical Data Destruction Bug Fix
**Commit:** `694c589`  
**Date:** 2026-09-16

- **Issue:** Database attributes all showed as None after adding configurable index parameters
  - Root cause: Line 769-774 called `self.clear()` before rebuilding dictionary
  - This destroyed all previously added data columns (z, kk, kkk, k)
- **Solution:** Add `__id__` first using direct assignment `self['__id__'] = ...`, then add other attributes
  - Leverages Python 3.7+ dict insertion order preservation
  - No clearing or rebuilding needed
  - Data integrity preserved throughout construction
- All configurable parameters (id_start, index_placement, include_indices) now working correctly

---

## Pending Tasks

### 📋 High Priority (Next Release v2.2.0)

#### ExecutionSettings Pattern (Architectural)
**Priority:** HIGH  
**Complexity:** MEDIUM  
**Scope:** Case, Coupler, Campaign  

**Motivation:**
- Separate execution configuration from case study data
- Reduce attribute clutter on Case/Coupler objects
- Enable settings reusability and serialization
- Improve discoverability (IDE autocomplete)
- Consistent defaults and validation

**Design:**
- Create `ExecutionSettings` class with grouped parameters
- Current scattered attributes: timeout, run_case_main_dir, capture_output, command_failure_policy, harvest_failure_policy, max_attempts, parallel, n_workers, execution_backend, verbose, log_file, event_capture
- Move to: `case.settings.timeout`, `case.settings.run_dir`, etc.
- Implement backward-compatible properties for v2.2-2.3 transition
- Deprecate old direct attributes in v2.3, remove in v3.0

**Tasks:**
- [ ] Design ExecutionSettings class with validation
- [ ] Implement for Case class (with backward compatibility)
- [ ] Implement for Coupler class
- [ ] Implement for Campaign class
- [ ] Add settings.copy(), settings.to_dict(), settings.load() methods
- [ ] Update documentation with settings examples
- [ ] Add tests for validation and inheritance
- [ ] Migration guide for users (v2.1 → v2.2)

---

### 📋 Lower Priority (Future Releases)

- [ ] Add performance benchmarks for large databases (>100k rows)
- [ ] Support correlated sampling across OAT attributes (future enhancement)
- [ ] Add database versioning/schema tracking
- [ ] Implement database merging utilities
- [ ] Add data validation rules and constraints
- [ ] Support custom samplers with seeded RNG across OAT groups

---

## Testing Summary (v2.1.0+)

✅ Database display methods (4 tests)
✅ OAT single attribute (baseline + variations)
✅ OAT multiple attributes (factorial product)
✅ OAT iteration order (declaration order matching)
✅ Save/load CSV/JSON/Parquet
✅ Save with lambda functions
✅ Derived column computation
✅ Random sampling independence

---

## Session Summary: 2026-09-16

**User:** Mohammad OMARI  
**Session Focus:** Bug fixes, feature configuration, and data integrity

### Commits (Latest Session)
1. `551c99a` - Fix db.rows attribute + documentation
2. `d105b94` - OAT factorial design implementation
3. `bdd2079` - Correct OAT iteration order
4. `a536f7e` - Save/load data export fix
5. `7eebf01` - Add configurable index parameters (id_start, index_placement, include_indices)
6. `694c589` - Fix critical data destruction bug in index parameter handling

### Features Added (v2.1.0+)
- ✅ Configurable row ID start value (id_start parameter)
- ✅ Configurable index placement (end vs interleaved)
- ✅ Toggle index inclusion (include_indices boolean)
- ✅ All parameters tested and verified working

### Issues Created
- ISSUES.md: OATConstructor design decision documentation

### Documentation Added
- README.md: Display & tabulation section
- USER_MANUAL.md: Detailed display examples
- ISSUES.md: Known issues tracker
- backlog.md: Development progress tracking

### Code Quality
- 4 major bug fixes
- 100% backward compatible
- Comprehensive parameter validation
- Full test coverage for new features
- Clear documentation and examples

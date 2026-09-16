# Labeeb Development Backlog

**Last Updated:** 2026-09-16

## Completed (v2.1.0+)

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

## Pending Tasks

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
**Session Focus:** Bug fixes and documentation improvements

### Commits
1. `551c99a` - Fix db.rows attribute + documentation
2. `d105b94` - OAT factorial design implementation
3. `bdd2079` - Correct OAT iteration order
4. `a536f7e` - Save/load data export fix

### Issues Created
- ISSUES.md: OATConstructor design decision documentation

### Documentation Added
- README.md: Display & tabulation section
- USER_MANUAL.md: Detailed display examples
- ISSUES.md: Known issues tracker

### Code Quality
- 3 major bug fixes
- 100% backward compatible
- Comprehensive error handling
- Clear documentation and examples

"""
Coupler module for iterative coupling of multiple simulation cases using
database parameters and user-defined coupling functions.
"""

import copy
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Union

from .case import Case
from .coupled_unit import CoupledUnit, ConvergenceResult
from .database import Database
from .exceptions import CouplingError
from .utils import os_ops, progress

logger = logging.getLogger(__name__)


class Coupler(CoupledUnit, dict):
    """
    Coordinates and launches multiple simulation cases in a coupled workflow.

    A `Coupler` is itself a `CoupledUnit`, so it can be nested as a child
    unit inside another `Coupler` (sub-coupling), alongside plain `Case`
    children -- both are composed uniformly via `add_case`/`add_cases`.
    """

    class CaseAccessor:
        """Helper to expose active case contexts to coupling scripts."""

        def __init__(self, coupler_instance: "Coupler"):
            self._coupler = coupler_instance

        @property
        def list(self) -> List[str]:
            """Return names of all coupled cases."""
            return [c.name for c in self._coupler.cases]

        @property
        def working_case(self) -> Optional[str]:
            """Return name of the currently executing case."""
            return self._coupler.case_name

        @property
        def current_step(self) -> Optional[int]:
            """Return index of the current coupling iteration step."""
            return self._coupler.c_step

        def __getitem__(self, name: str) -> Case:
            for case in self._coupler.cases:
                if case.name == name:
                    return case
            raise KeyError(f"Coupled Case '{name}' not found")

        def __getattr__(self, name: str) -> Any:
            if name in ["list", "working_case", "current_step"]:
                return getattr(self, name)
            try:
                return self[name]
            except KeyError as e:
                raise AttributeError(f"CaseAccessor has no attribute '{name}'") from e

        def __dir__(self) -> List[str]:
            return ["working_case", "current_step", "list"] + self.list

    def __init__(self, name: str, **kwargs: Any):
        """
        Initialize Coupler.

        Args:
            name: Coupler run identifier.
        """
        dict.__init__(self)
        CoupledUnit.__init__(self)
        self.name: str = name
        self.description: Optional[str] = None
        self.database: Optional[Database] = None

        self.cases: List[Any] = []
        self.case_mappings: Dict[str, List[str]] = {}
        self._coupling_functions: List[Callable[..., Any]] = []
        self._unit_max_exec: Dict[str, int] = {}
        self._unit_check_fn: Dict[str, Callable[..., bool]] = {}

        self._relaxation_factors: Dict[str, float] = {}
        self._previous_values: Dict[str, Any] = {}
        self._divergence_detectors: List[Callable[..., bool]] = []
        self._divergence_thresholds: Dict[str, float] = {}

        # Aitken delta-squared controls (deterministic; disabled by default so
        # behavior is unchanged until enable_aitken() is called).
        self._aitken_attributes: set = set()
        self._aitken_all: bool = False
        self._aitken_min_iterations: int = 3
        self._aitken_history: Dict[str, List[Any]] = {}

        # Observational progress callbacks (deep-copied snapshots only).
        self._progress_callbacks: List[Callable[..., Any]] = []

        self.main_dir: str = os.getcwd()
        self.run_case_main_dir: str = "coupling_omari_test"
        self.run_case_sub_dir: str = "coupling_iteration"

        self.objects_to_be_copied: List[str] = []
        self.current_case_dir: Optional[str] = None

        self.new: bool = True
        self.run_type: str = "new"

        self.c_step: Optional[int] = None
        self.case_name: Optional[str] = None
        self.max_steps: Optional[int] = None

        self._accessor = self.CaseAccessor(self)
        self._parse_kwargs(**kwargs)

    @property
    def case(self) -> CaseAccessor:
        """Accessor property to fetch cases by name."""
        return self._accessor

    def _parse_kwargs(self, **kwargs: Any) -> None:
        for key, val in kwargs.items():
            if key in self.__dict__:
                setattr(self, key, val)
            elif key.lower() in ["root_dir", "main_dir"]:
                self.main_dir = val
            else:
                logger.warning(f"Coupler parameter '{key}' is not supported")

    # ------------------------------------------------------------------ typed relaxation helpers

    @staticmethod
    def _vector_like(value: Any) -> bool:
        """True for sequence/array values needing elementwise treatment."""
        return isinstance(value, (list, tuple)) or hasattr(value, "tolist")

    @staticmethod
    def _as_flat_list(value: Any) -> List[Any]:
        if isinstance(value, (list, tuple)):
            return list(value)
        if hasattr(value, "tolist"):
            return list(value.tolist())
        return [value]

    @staticmethod
    def _rebuild(template: Any, values: List[Any]) -> Any:
        """Rebuild the caller's container type from elementwise results."""
        if isinstance(template, tuple):
            return tuple(values)
        if isinstance(template, list):
            return values
        if hasattr(template, "dtype"):  # numpy-like arrays need asarray
            try:
                import numpy as _np

                return _np.asarray(values, dtype=getattr(template, "dtype", None))
            except Exception:  # noqa: BLE001
                pass
        try:
            return template.__class__(values)
        except Exception:  # noqa: BLE001 - fall back to a plain list
            return values

    @staticmethod
    def _jsonify(value: Any) -> Any:
        """Recursively convert values (incl. numpy) into JSON-safe primitives."""
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value
        if Coupler._vector_like(value):
            return [Coupler._jsonify(v) for v in Coupler._as_flat_list(value)]
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value)

    def set_under_relaxation(self, attribute: str, factor: float) -> "Coupler":
        """
        Set an under-relaxation factor omega in (0, 1] for a specific attribute.
        """
        if factor <= 0.0 or factor > 1.0:
            raise ValueError(
                f"Under-relaxation factor for '{attribute}' must be in (0, 1], got {factor}"
            )
        self._relaxation_factors[attribute] = float(factor)
        return self

    def get_under_relaxation(self, attribute: str) -> float:
        """Get the configured under-relaxation factor for an attribute (default: 1.0)."""
        return self._relaxation_factors.get(attribute, 1.0)

    # ------------------------------------------------------------------ Aitken controls

    def enable_aitken(self, attribute: Optional[str] = None, min_iterations: int = 3) -> "Coupler":
        """Enable Aitken delta-squared acceleration for one attribute, or for
        every attribute when ``attribute`` is None.

        Deterministic default: disabled until called; ``min_iterations`` (>= 3)
        is the number of raw iterates required before extrapolation is applied
        (the current iterate counts toward it). The extrapolation guards
        against a (near-)zero denominator by falling back to the raw iterate.
        """
        if not isinstance(min_iterations, int) or min_iterations < 3:
            raise ValueError("Aitken min_iterations must be an integer >= 3")
        if attribute is None:
            self._aitken_all = True
        else:
            self._aitken_attributes.add(attribute)
        self._aitken_min_iterations = min_iterations
        return self

    def disable_aitken(self, attribute: Optional[str] = None) -> "Coupler":
        """Disable Aitken acceleration (attribute-scoped or all)."""
        if attribute is None:
            self._aitken_all = False
            self._aitken_attributes.clear()
        else:
            self._aitken_attributes.discard(attribute)
        self._aitken_history.clear()
        return self

    def _aitken_active(self, attribute: str) -> bool:
        return self._aitken_all or attribute in self._aitken_attributes

    def _aitken_extrapolate(self, x0: Any, x1: Any, x2: Any) -> Optional[Any]:
        """Aitken delta-squared on three successive iterates: x* = x2 - (dx)^2/d2x.

        Scalar or elementwise; returns None when the denominator is (near) zero.
        """
        x0l, x1l, x2l = self._as_flat_list(x0), self._as_flat_list(x1), self._as_flat_list(x2)
        results: List[Any] = []
        guard = 1e-12
        for a, b, c in zip(x0l, x1l, x2l):
            denominator = c - 2.0 * b + a
            try:
                if abs(denominator) <= guard * (1.0 + abs(c) + abs(b) + abs(a)):
                    return None
                results.append(c - (c - b) ** 2 / denominator)
            except (TypeError, ValueError):
                return None
        if not Coupler._vector_like(x2):
            return float(results[0])
        return self._rebuild(x2, results)

    def _aitken_candidate(self, attribute: str, raw_value: Any) -> Any:
        """Record the raw iterate (only while Aitken is enabled); return the
        accelerated value once enough history exists, else the raw value."""
        if not self._aitken_active(attribute):
            return raw_value
        history = self._aitken_history.setdefault(attribute, [])
        history.append(self._jsonify(raw_value))
        if len(history) < self._aitken_min_iterations:
            return raw_value
        accelerated = self._aitken_extrapolate(history[-3], history[-2], history[-1])
        return accelerated if accelerated is not None else raw_value

    # ------------------------------------------------------------------ typed relaxation

    def relax(self, attribute: str, new_value: Any, old_value: Optional[Any] = None) -> Any:
        """Apply under-relaxation (and optional Aitken acceleration) to a value.

        Scalar values follow:  relaxed = omega * new + (1 - omega) * old.
        List/tuple/numpy values are mixed elementwise (``typed`` relaxation).
        When Aitken is enabled for ``attribute`` the raw iterate is first
        extrapolated (once enough history exists), then mixed with ``omega``.
        """
        omega = self.get_under_relaxation(attribute)
        if old_value is None:
            if attribute in self._previous_values:
                old_value = self._previous_values[attribute]
            else:
                self._aitken_candidate(attribute, new_value)  # keep history aligned
                self._previous_values[attribute] = self._jsonify(new_value)
                return new_value

        if not self._vector_like(new_value):
            old_val = float(old_value)
            candidate = self._aitken_candidate(attribute, new_value)
            new_val = float(candidate)
            relaxed = omega * new_val + (1.0 - omega) * old_val
            self._previous_values[attribute] = relaxed
            return relaxed

        # vector/typed path: elementwise mixing of the (possibly accelerated) iterate
        base = self._aitken_candidate(attribute, new_value)
        base_list = self._as_flat_list(base)
        old_list = self._as_flat_list(old_value)
        mixed = [
            omega * float(nv) + (1.0 - omega) * float(ov)
            for nv, ov in zip(base_list, old_list)
        ]
        result = self._rebuild(new_value, mixed)
        self._previous_values[attribute] = self._jsonify(result)
        return result

    def add_divergence_detector(self, *funcs: Callable[..., bool]) -> "Coupler":
        """Add custom callback(s) that return True if coupling divergence is detected."""
        for f in funcs:
            if f not in self._divergence_detectors:
                self._divergence_detectors.append(f)
        return self

    def set_divergence_threshold(self, attribute: str, max_allowed: float) -> "Coupler":
        """Set a maximum allowable numerical threshold for an attribute before aborting due to divergence."""
        self._divergence_thresholds[attribute] = float(max_allowed)
        return self

    def check_divergence(self) -> None:
        """
        Evaluate configured divergence detectors and thresholds.
        Raises CouplingError immediately if divergence is detected.
        """
        for detector in self._divergence_detectors:
            try:
                if detector(self):
                    detector_name = getattr(detector, "__name__", "custom_detector")
                    raise CouplingError(
                        f"Coupling divergence detected by detector '{detector_name}' "
                        f"in Coupler '{self.name}' at step {self.c_step}"
                    )
            except CouplingError:
                raise
            except Exception as e:
                raise CouplingError(
                    f"Coupling divergence check failed in Coupler '{self.name}': {e}"
                ) from e

        if self.database and self.c_step is not None:
            row = self.database.get_row(self.c_step)
            for att, limit in self._divergence_thresholds.items():
                val = row.get(att)
                if val is not None and isinstance(val, (int, float)):
                    if abs(val) > limit:
                        raise CouplingError(
                            f"Coupling divergence detected in Coupler '{self.name}' at step {self.c_step}: "
                            f"attribute '{att}' value {val} exceeds threshold {limit}"
                        )

    def run_to_convergence(
        self,
        max_exec: Optional[int] = None,
        check_fn: Optional[Callable[..., bool]] = None,
        error_on_max_exec: bool = False,
        **kwargs: Any,
    ) -> ConvergenceResult:
        """
        Repeatedly call `_run_once` until `check_fn(self, **kwargs)` returns
        True or `max_exec` attempts are used. If `error_on_max_exec` is True and
        convergence is not achieved within `max_exec` passes, raises CouplingError.
        """
        n = max_exec if max_exec is not None else self.default_max_exec
        unit_name = getattr(self, "name", self.__class__.__name__)

        for i in range(n):
            self._run_once(_attempt=i, **kwargs)

            converged = True if check_fn is None else bool(check_fn(self, **kwargs))
            if converged:
                result = ConvergenceResult(unit=unit_name, converged=True, executions=i + 1)
                self.last_convergence = result
                return result

        logger.warning(f"'{unit_name}' did not converge within max_exec={n} executions.")
        result = ConvergenceResult(unit=unit_name, converged=False, executions=n)
        self.last_convergence = result
        if error_on_max_exec:
            # Every pass completed; the last complete state is preserved on
            # the shared row and recorded for restart.
            raise CouplingError(
                f"Coupler '{unit_name}' failed to converge within max_exec={n} executions."
            )
        return result

    def add_case(
        self,
        case: "Union[Case, Coupler]",
        attributes: Optional[List[str]] = None,
        max_exec: Optional[int] = None,
        check_fn: Optional[Callable[..., bool]] = None,
    ) -> "Coupler":
        """
        Register a single unit (a `Case`, or another `Coupler` for
        sub-coupling), optionally specifying which attributes to copy.

        `max_exec`/`check_fn` set this unit's own convergence budget
        (how many times it may re-execute before moving to the next unit
        in a coupling step) and can be changed later via
        `set_unit_convergence()` between coupling steps.
        """
        if case not in self.cases:
            if case.name in [c.name for c in self.cases]:
                logger.warning(f"Duplicate case name '{case.name}' detected.")
            self.cases.append(case)
        if attributes is not None:
            self.case_mappings[case.name] = attributes
            # Ensure the child's own database has every mapped column, so
            # update_row(add_new=False) never KeyErrors -- this matters
            # when the same Case is shared across multiple parent
            # Couplers with different attribute mappings.
            case_db = getattr(case, "database", None)
            if case_db is not None:
                missing = [a for a in attributes if a not in case_db]
                if missing:
                    case_db.create_attribute(*missing)
        if max_exec is not None or check_fn is not None:
            self.set_unit_convergence(case.name, max_exec=max_exec, check_fn=check_fn)
        return self

    def add_cases(self, *args: Any, **kwargs: Any) -> "Coupler":
        """
        Register multiple units.
        Supports either:
          - Multiple Case/Coupler instances: add_cases(case1, case2)
          - A single dictionary mapping unit -> attribute list: add_cases({case1: ['RHO'], case2: []})
        """
        if len(args) == 1 and isinstance(args[0], dict):
            for case, attributes in args[0].items():
                self.add_case(case, attributes)
        else:
            for c in args:
                if isinstance(c, CoupledUnit):
                    self.add_case(c)
        return self

    def set_unit_convergence(
        self,
        name: str,
        max_exec: Optional[int] = None,
        check_fn: Optional[Callable[..., bool]] = None,
    ) -> "Coupler":
        """Set or update a registered unit's convergence budget/check, keyed by name."""
        if max_exec is not None:
            self._unit_max_exec[name] = max_exec
        if check_fn is not None:
            self._unit_check_fn[name] = check_fn
        return self

    def add_coupling_functions(self, *funcs: Callable[..., Any]) -> "Coupler":
        """Add user-defined coupling callback functions."""
        for f in funcs:
            if f not in self._coupling_functions:
                self._coupling_functions.append(f)
        return self

    def _execute_coupling_functions(self, **kwargs: Any) -> List[Any]:
        return [f(self, **kwargs) for f in self._coupling_functions]

    def launch(self, **kwargs: Any) -> "Coupler":
        """
        Launch the entire coupled loop sequence.
        """
        self.initialization()
        if not self.database:
            raise CouplingError("No database assigned to Coupler")

        prog_bar = progress.ProgressBar(name=self.name, start=0, end=len(self.database))
        for i in prog_bar:
            if self._shall_stop():
                logger.info("Coupler launcher stopped by user request")
                break

            self.c_step = i
            if self.max_steps is not None and i >= self.max_steps:
                raise CouplingError(
                    f"Coupler '{self.name}' max_steps={self.max_steps} would omit "
                    f"database rows (total: {len(self.database)})"
                )

            self.launch_case(**kwargs)
        return self

    def create_case_main_dir(self) -> "Coupler":
        """Helper to call initialization."""
        return self.initialization()

    def initialization(self) -> "Coupler":
        """Clean and create main case folder."""
        cases_root_path = os_ops.set_fullpath(self.main_dir, self.run_case_main_dir)
        if self.run_type != "new":
            self.new = False
        else:
            self.new = True
            os_ops.rmdir(cases_root_path)

        os_ops.mkdir(cases_root_path)
        return self

    def launch_case(self, c_step: Optional[int] = None, **kwargs: Any) -> "Coupler":
        """
        Launch a single coupled step run.
        """
        if c_step is not None:
            self.c_step = c_step

        if self.c_step is None:
            self.c_step = 0

        self._run_once(**kwargs)
        return self

    def _run_once(self, **kwargs: Any) -> None:
        """Run one complete coupling pass with last-complete-state protection.

        The shared row is snapshotted before the pass; if the pass raises
        ``CouplingError`` (e.g. divergence), the snapshot is restored so the
        database always retains the last COMPLETE state. Observational
        progress callbacks fire after a successful pass.
        """
        if self.c_step is None:
            self.c_step = 0
        snapshot = self._snapshot_step_row()
        try:
            self._run_once_body(**kwargs)
        except CouplingError:
            self._restore_step_row(snapshot)
            raise
        self._notify_progress(**kwargs)

    def _run_once_body(self, **kwargs: Any) -> None:
        """
        One pass of a coupling step: run every registered unit to its own
        convergence (in order), then run coupling functions ONCE after all
        units have resolved -- not per-unit -- so feedback (e.g. updating
        shared parameters) always sees every unit's final state for this
        step. Used both directly and as the repeated pass inside
        `run_to_convergence()` for overall coupling convergence.
        """
        if self.c_step is None:
            self.c_step = 0
        idx = self.c_step
        # `_attempt` (set by run_to_convergence's repeated passes) keeps
        # repeated overall-coupling-convergence passes over the same
        # c_step from overwriting each other's run directory on disk.
        attempt = kwargs.pop("_attempt", 0) or 0
        dir_name = (
            f"{self.run_case_sub_dir}_{idx}"
            if not attempt
            else f"{self.run_case_sub_dir}_{idx}_iter{attempt}"
        )
        self.current_case_dir = os_ops.set_fullpath(self.main_dir, self.run_case_main_dir, dir_name)

        for case in self.cases:
            self.case_name = case.name
            case.set_vars(root_dir=self.current_case_dir)
            mapped_atts = self.case_mappings.get(case.name)

            # Update the unit's database row with the coupler's current database row parameters
            if self.database and case.database:
                row_data = self.database.get_row(self.c_step)
                if mapped_atts is not None:
                    row_data = {k: v for k, v in row_data.items() if k in mapped_atts}
                # Belt-and-suspenders: a Case's database can be (re)assigned
                # after add_case(), or the same Case instance can be shared
                # under multiple parent Couplers with different attribute
                # mappings -- provision any still-missing mapped columns
                # here rather than letting update_row KeyError.
                missing = [k for k in row_data if k not in case.database]
                if missing:
                    case.database.create_attribute(*missing)
                case.database.update_row(row_id=0, data=row_data, add_new=False)

            case.run_to_convergence(
                max_exec=self._unit_max_exec.get(case.name),
                check_fn=self._unit_check_fn.get(case.name),
                indent=1,
                _active_flag_attributes=mapped_atts,
                **kwargs,
            )

        # Coupling functions run once per pass, after every unit has
        # reached its own convergence (or exhausted its max_exec) --
        # see CoupledUnit's parent/child convergence invariant.
        self._execute_coupling_functions(**kwargs)
        self.check_divergence()

    def _shall_stop(self) -> bool:
        return False

    # ------------------------------------------------------------------ last-complete-state protection

    def _snapshot_step_row(self) -> Optional[Dict[str, Any]]:
        """Deep copy of the shared database row for the current step."""
        if self.database is None or self.c_step is None or self.c_step >= len(self.database):
            return None
        return copy.deepcopy(self.database.get_row(self.c_step))

    def _restore_step_row(self, snapshot: Optional[Dict[str, Any]]) -> None:
        """Restore the shared row to a snapshot (last complete state)."""
        if snapshot is None or self.database is None or self.c_step is None:
            return
        missing = [key for key in snapshot if key not in self.database]
        if missing:
            self.database.create_attribute(*missing)
        self.database.set_row(self.c_step, copy.deepcopy(snapshot))

    # ------------------------------------------------------------------ observational progress callbacks

    def add_progress_callback(self, callback: Callable[[Dict[str, Any]], None]) -> "Coupler":
        """Register an OBSERVATIONAL progress callback.

        The callback receives a deep-copied read-only snapshot dict
        (``name``, ``c_step``, ``attempt``, ``status``, ``case_names``,
        ``database_row``, ``last_convergence``) after each COMPLETE coupling
        pass. It can never mutate coupler state (only the copy is visible),
        and exceptions raised inside it are swallowed so observation can never
        break the coupling run. Callbacks run in registration order.
        """
        if not callable(callback):
            raise CouplingError("progress callback must be callable(snapshot)")
        if callback not in self._progress_callbacks:
            self._progress_callbacks.append(callback)
        return self

    def _notify_progress(self, **kwargs: Any) -> None:
        if not self._progress_callbacks:
            return
        attempt = kwargs.get("_attempt", 0) or 0
        row = (
            copy.deepcopy(self.database.get_row(self.c_step))
            if self.database is not None and self.c_step is not None
            else None
        )
        snapshot = {
            "name": self.name,
            "c_step": self.c_step,
            "attempt": attempt,
            "status": "complete",
            "case_names": [c.name for c in self.cases],
            "database_row": row,
            "last_convergence": (
                self.last_convergence.to_dict() if self.last_convergence is not None else None
            ),
        }
        for callback in self._progress_callbacks:
            try:
                callback(snapshot)
            except Exception:  # noqa: BLE001 - observers must never break a run
                logger.warning("Coupling progress callback failed (isolated): %s",
                               getattr(callback, "__name__", callback))

    # ------------------------------------------------------------------ coupling-state serialization

    def save_state(self, path: str) -> "Coupler":
        """Serialize the coupling state to a JSON file (atomic write).

        Persists: format/version, coupler name, current step, the shared row
        for the current step (typed, JSON-safe), under-relaxation factors,
        Aitken controls, and divergence thresholds. Python callables
        (coupling functions, divergence detectors, progress callbacks) are
        NOT serializable and must be re-registered after ``load_state``.
        """
        state = {
            "format": "labeeb-coupling-state",
            "version": 1,
            "name": self.name,
            "c_step": self.c_step,
            "row": (
                {k: self._jsonify(v) for k, v in self.database.get_row(self.c_step).items()}
                if self.database is not None and self.c_step is not None
                and self.c_step < len(self.database)
                else None
            ),
            "relaxation_factors": dict(self._relaxation_factors),
            "aitken": {
                "attributes": sorted(self._aitken_attributes),
                "all": self._aitken_all,
                "min_iterations": self._aitken_min_iterations,
            },
            "divergence_thresholds": dict(self._divergence_thresholds),
            "unit_max_exec": dict(self._unit_max_exec),
            "last_convergence": (
                self.last_convergence.to_dict() if self.last_convergence is not None else None
            ),
        }
        destination = os.path.abspath(path)
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = destination + f".tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as handle:
            import json

            json.dump(state, handle, indent=2, sort_keys=True)
        os.replace(tmp, destination)
        return self

    def load_state(self, path: str) -> "Coupler":
        """Restore coupling state previously saved with :meth:`save_state`.

        Applies the shared row (provisioning columns as needed), current step,
        under-relaxation factors, Aitken controls, divergence thresholds and
        unit budgets. Callables must be re-registered by the caller.
        """
        import json

        with open(os.path.abspath(path), "r", encoding="utf-8") as handle:
            state = json.load(handle)
        if state.get("format") != "labeeb-coupling-state":
            raise CouplingError(f"{path} is not a Labeeb coupling state file")
        self.c_step = state.get("c_step")
        row = state.get("row")
        if row is not None and self.database is not None:
            if self.c_step is None:
                raise CouplingError("cannot restore a row without a c_step in the state file")
            missing = [key for key in row if key not in self.database]
            if missing:
                self.database.create_attribute(*missing)
            self.database.set_row(self.c_step, copy.deepcopy(row))
        self._relaxation_factors = dict(state.get("relaxation_factors", {}))
        aitken = state.get("aitken", {})
        self._aitken_attributes = set(aitken.get("attributes", []))
        self._aitken_all = bool(aitken.get("all", False))
        self._aitken_min_iterations = int(aitken.get("min_iterations", 3))
        self._aitken_history.clear()
        self._divergence_thresholds = dict(state.get("divergence_thresholds", {}))
        self._unit_max_exec = {k: int(v) for k, v in state.get("unit_max_exec", {}).items()}
        convergence = state.get("last_convergence")
        if convergence is not None:
            self.last_convergence = ConvergenceResult(**convergence)
        return self

    def set_vars(self, **kwargs: Any) -> "Coupler":
        """Set variables dynamically."""
        self._parse_kwargs(**kwargs)
        return self

    def update_db(self) -> None:
        """Mock method."""
        pass

    def __dir__(self) -> List[str]:
        return [x for x in self.__dict__.keys() if not x.startswith("_")] + ["case"]

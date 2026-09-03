"""Simulation-based optimization controller for Labeeb (LAB-OPTIMIZATION-API-01).

The :class:`Optimizer` proposes candidate parameter sets inside user-declared
bounds (grid or seeded random search), evaluates each candidate through a
user-supplied objective function that typically runs a :class:`Case` or
:class:`Campaign` simulation, honors optional constraints, and records every
evaluation into a durable history with checkpoint/resume support.

Design rules (see docs/DEVELOPER_GUIDE.md, section 3):
  * Python-first: the objective is an ordinary callable receiving a candidate
    dict of variables -> float. No external optimizer dependency (stdlib only).
  * Every examined candidate becomes an :class:`EvaluationRecord` in history:
    simulated successes, simulation failures, and constraint-infeasible
    proposals are all cataloged with status and message.
  * Deterministic proposals: ``random`` uses a per-index seeded stream, so
    resume reproduces the exact same candidate sequence as a fresh run.
  * Checkpoints are written atomically after every evaluation; resuming skips
    already-evaluated candidates (cached) and continues from the stored index.
"""

import hashlib
import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .exceptions import OptimizationError

__all__ = [
    "Constraint",
    "EvaluationRecord",
    "OptimizationError",
    "OptimizeResult",
    "Optimizer",
    "export_optimization_history",
]

_CHECKPOINT_FORMAT = "labeeb-optimization-checkpoint"
_CHECKPOINT_VERSION = 1

#: Proposal methods available to the Optimizer.
METHODS = ("grid", "random")
#: Objective directions available to the Optimizer.
DIRECTIONS = ("minimize", "maximize")
_EXPORT_SUFFIXES = (".csv", ".json", ".xlsx", ".parquet")


@dataclass
class Constraint:
    """Named feasibility predicate over a candidate parameter dict.

    ``predicate`` returns ``True`` when the candidate is *satisfying* the
    constraint (feasible). Candidates failing any constraint are recorded as
    ``infeasible`` and never simulated, so they consume no simulation budget.
    """

    name: str
    predicate: Callable[[Dict[str, float]], bool]


@dataclass
class EvaluationRecord:
    """One examined candidate: simulated result, failure, or infeasibility."""

    index: int
    parameters: Dict[str, float]
    status: str  # "evaluated" | "failed" | "infeasible"
    simulated: bool
    objective: Optional[float]
    feasible: bool
    violated_constraints: List[str] = field(default_factory=list)
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "parameters": dict(self.parameters),
            "status": self.status,
            "simulated": self.simulated,
            "objective": self.objective,
            "feasible": self.feasible,
            "violated_constraints": list(self.violated_constraints),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvaluationRecord":
        return cls(
            index=int(data["index"]),
            parameters=dict(data["parameters"]),
            status=str(data["status"]),
            simulated=bool(data["simulated"]),
            objective=data.get("objective"),
            feasible=bool(data.get("feasible", True)),
            violated_constraints=list(data.get("violated_constraints", [])),
            message=data.get("message"),
        )


@dataclass
class OptimizeResult:
    """Outcome of :meth:`Optimizer.run` (also the live best during the run)."""

    direction: str
    method: str
    best_candidate: Optional[Dict[str, float]]
    best_objective: Optional[float]
    evaluations: int = 0  # simulated evaluations consumed (successes + failures)
    proposals: int = 0  # candidates examined (incl. infeasible)
    infeasible: int = 0
    failed: int = 0
    cached: int = 0  # resumed/duplicate candidates skipped from simulation
    reason: str = "budget"
    history: List[EvaluationRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "method": self.method,
            "best_candidate": self.best_candidate,
            "best_objective": self.best_objective,
            "evaluations": self.evaluations,
            "proposals": self.proposals,
            "infeasible": self.infeasible,
            "failed": self.failed,
            "cached": self.cached,
            "reason": self.reason,
            "history": [record.to_dict() for record in self.history],
        }

    def to_dataframe(self) -> Any:
        """Flatten history into a pandas DataFrame (pandas required)."""
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise OptimizationError(
                "pandas is required for to_dataframe(); install with: pip install pandas"
            ) from exc
        return pd.DataFrame([record.to_dict() for record in self.history])


class Optimizer:
    """Python-first simulation-based optimization controller.

    Parameters
    ----------
    variables:
        ``{name: (low, high)}`` search domain for each continuous variable.
    objective_fn:
        ``objective_fn(candidate) -> Optional[float]`` — evaluates ONE candidate
        (typically by running a :class:`Case`/`:class:`Campaign` simulation and
        harvesting a metric). Return ``None`` (or raise) to record a simulation
        failure; the run continues and the budget is charged.
    direction:
        ``"minimize"`` (default) or ``"maximize"``.
    method:
        ``"grid"`` — full-factorial grid over ``grid_points`` per variable
        (deterministic); ``"random"`` — seeded uniform random sampling.
    budget:
        Maximum number of *simulated* evaluations (successes + failures).
        Infeasible candidates and resumed cache hits do not consume budget.
    constraints:
        Optional sequence of :class:`Constraint` (or callables taking the
        candidate and returning bool) — cheap feasibility filters applied
        before any simulation.
    grid_points:
        Divisions per variable for ``"grid"`` (default 5).
    seed:
        Seeding for ``"random"`` proposals (deterministic across runs/resume).
    patience / tolerance:
        Optional early termination: stop after ``patience`` consecutive
        simulated evaluations without improvement beyond ``tolerance``.
    min_evaluations:
        Simulated evaluations required before the patience rule may fire.
    checkpoint_path:
        JSON checkpoint written atomically after every evaluation; enables
        resume. Configuration (variables/method/direction/seed/grid_points)
        must match on resume; budget may grow.
    resume:
        When ``True`` and ``checkpoint_path`` exists, load prior history,
        skip already-evaluated candidates, and continue from the stored index.
    time_budget_seconds:
        Optional wall-clock cap checked between evaluations.

    Example
    -------
    >>> def run_simulation(candidate):  # runs a Case/Campaign under the hood
    ...     return (candidate["x"] - 1.0) ** 2
    >>> opt = Optimizer({"x": (-3.0, 3.0)}, run_simulation, method="grid",
    ...                 grid_points=7, budget=20)
    >>> result = opt.run()
    >>> round(result.best_candidate["x"], 3)
    1.0
    """

    def __init__(
        self,
        variables: Dict[str, Tuple[float, float]],
        objective_fn: Callable[[Dict[str, float]], Optional[float]],
        direction: str = "minimize",
        method: str = "grid",
        *,
        constraints: Sequence[Constraint] = (),
        budget: int = 50,
        grid_points: Optional[int] = None,
        seed: int = 42,
        patience: Optional[int] = None,
        tolerance: float = 1e-9,
        min_evaluations: int = 1,
        checkpoint_path: Optional[str] = None,
        resume: bool = False,
        time_budget_seconds: Optional[float] = None,
    ) -> None:
        self.variables = self._validate_variables(variables)
        if not callable(objective_fn):
            raise OptimizationError("objective_fn must be callable(candidate) -> Optional[float]")
        self.objective_fn = objective_fn
        self.direction = self._validate_choice("direction", direction, DIRECTIONS)
        self.method = self._validate_choice("method", method, METHODS)
        self.budget = self._validate_int("budget", budget, minimum=1)
        self.grid_points = (
            self._validate_int("grid_points", grid_points, minimum=1)
            if grid_points is not None
            else 5
        )
        self.seed = self._validate_int("seed", seed, minimum=0)
        self.patience = (
            self._validate_int("patience", patience, minimum=1) if patience is not None else None
        )
        self.tolerance = self._validate_float("tolerance", tolerance, minimum=0.0)
        self.min_evaluations = self._validate_int("min_evaluations", min_evaluations, minimum=1)
        if time_budget_seconds is not None:
            self.time_budget_seconds = self._validate_float(
                "time_budget_seconds", time_budget_seconds, minimum=0.0
            )
        else:
            self.time_budget_seconds = None
        self.constraints = self._validate_constraints(constraints)
        self.checkpoint_path = str(checkpoint_path) if checkpoint_path is not None else None
        self.resume = resume

        # per-run state (reset by run(); repopulated by resume)
        self._history: List[EvaluationRecord] = []
        self._cache: Dict[str, EvaluationRecord] = {}
        self._next_index = 0
        self._best_candidate: Optional[Dict[str, float]] = None
        self._best_objective: Optional[float] = None
        self._consecutive_no_improve = 0
        self._cached_count = 0
        self._result = OptimizeResult(
            direction=self.direction,
            method=self.method,
            best_candidate=None,
            best_objective=None,
        )

    # ------------------------------------------------------------------ config

    @staticmethod
    def _validate_variables(variables: Any) -> Dict[str, Tuple[float, float]]:
        if not isinstance(variables, dict) or not variables:
            raise OptimizationError("variables must be a non-empty {name: (low, high)} dict")
        cleaned: Dict[str, Tuple[float, float]] = {}
        for name, bounds in variables.items():
            if not isinstance(name, str) or not name:
                raise OptimizationError("variable names must be non-empty strings")
            try:
                low, high = (float(bounds[0]), float(bounds[1]))
            except (TypeError, ValueError, IndexError) as exc:
                raise OptimizationError(
                    f"variable {name!r}: bounds must be a (low, high) pair of numbers"
                ) from exc
            if not math.isfinite(low) or not math.isfinite(high):
                raise OptimizationError(f"variable {name!r}: bounds must be finite")
            if low > high:
                raise OptimizationError(f"variable {name!r}: low bound exceeds high bound")
            cleaned[name] = (low, high)
        return cleaned

    @staticmethod
    def _validate_choice(param: str, value: Any, allowed: Sequence[str]) -> str:
        if value not in allowed:
            raise OptimizationError(f"{param} must be one of {list(allowed)}, got {value!r}")
        return str(value)

    @staticmethod
    def _validate_int(param: str, value: Any, minimum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise OptimizationError(f"{param} must be an integer >= {minimum}")
        if value < minimum:
            raise OptimizationError(f"{param} must be >= {minimum}")
        return value

    @staticmethod
    def _validate_float(param: str, value: Any, minimum: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise OptimizationError(f"{param} must be a number >= {minimum}") from exc
        if number < minimum:
            raise OptimizationError(f"{param} must be >= {minimum}")
        return number

    @staticmethod
    def _validate_constraints(constraints: Any) -> List[Constraint]:
        normalized: List[Constraint] = []
        for item in constraints or ():
            if isinstance(item, Constraint):
                normalized.append(item)
            elif callable(item):
                normalized.append(Constraint(name=getattr(item, "__name__", "constraint"), predicate=item))
            else:
                raise OptimizationError(
                    "constraints must be Constraint instances or callables -> bool"
                )
        return normalized

    # ------------------------------------------------------------- proposals

    def _var_names(self) -> List[str]:
        return list(self.variables.keys())

    def _proposal(self, index: int) -> Dict[str, float]:
        """Deterministic candidate for a proposal index (replayable on resume)."""
        names = self._var_names()
        if self.method == "grid":
            divisions = self.grid_points
            size = divisions ** len(names)
            pos = index % size
            candidate: Dict[str, float] = {}
            for name in names:
                low, high = self.variables[name]
                if divisions <= 1:
                    value = 0.5 * (low + high)
                else:
                    step = (high - low) / (divisions - 1)
                    value = low + (pos % divisions) * step
                candidate[name] = value
                pos //= divisions
            return candidate
        # random: per-index seeded stream keeps resume deterministic
        rng = random.Random(f"{self.seed}:{index}")
        return {
            name: low + rng.random() * (high - low)
            for name, (low, high) in ((n, self.variables[n]) for n in names)
        }

    def _grid_size(self) -> Optional[int]:
        if self.method != "grid":
            return None
        return self.grid_points ** len(self.variables)

    @staticmethod
    def _param_key(parameters: Dict[str, float]) -> str:
        rounded = sorted((name, round(value, 9)) for name, value in parameters.items())
        digest = hashlib.sha1(repr(rounded).encode("utf-8")).hexdigest()
        return digest[:16]

    # --------------------------------------------------------------- best

    def _improves(self, value: float) -> bool:
        if self._best_objective is None:
            return True
        if self.direction == "minimize":
            return value < self._best_objective - self.tolerance
        return value > self._best_objective + self.tolerance

    def _consider_best(self, record: EvaluationRecord) -> None:
        """Replay one evaluated record into best/stall state (idempotent)."""
        self._result.evaluations += 1
        if record.objective is not None and self._improves(record.objective):
            self._best_candidate = dict(record.parameters)
            self._best_objective = record.objective
            self._consecutive_no_improve = 0
        elif record.status == "evaluated":
            self._consecutive_no_improve += 1

    # ------------------------------------------------------------ checkpoints

    def _checkpoint_config(self) -> Dict[str, Any]:
        return {
            "variables": {k: list(v) for k, v in self.variables.items()},
            "method": self.method,
            "direction": self.direction,
            "seed": self.seed,
            "grid_points": self.grid_points,
            "budget": self.budget,
            "time_budget_seconds": self.time_budget_seconds,
        }

    def _write_checkpoint(self) -> None:
        if self.checkpoint_path is None:
            return
        payload = {
            "format": _CHECKPOINT_FORMAT,
            "version": _CHECKPOINT_VERSION,
            "config": self._checkpoint_config(),
            "next_index": self._next_index,
            "best_candidate": self._best_candidate,
            "best_objective": self._best_objective,
            "result": self._result.to_dict(),
        }
        destination = os.path.abspath(self.checkpoint_path)
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = destination + f".tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp, destination)

    def _load_checkpoint(self) -> None:
        if not self.resume or self.checkpoint_path is None:
            return
        if not os.path.exists(self.checkpoint_path):
            return  # nothing to resume: start fresh
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            raise OptimizationError(
                f"cannot read checkpoint {self.checkpoint_path}: {exc}"
            ) from exc
        if payload.get("format") != _CHECKPOINT_FORMAT:
            raise OptimizationError(f"{self.checkpoint_path} is not a Labeeb optimization checkpoint")
        stored_config = payload.get("config", {})
        for key in ("variables", "method", "direction", "seed", "grid_points"):
            if stored_config.get(key) != self._checkpoint_config()[key]:
                raise OptimizationError(
                    f"checkpoint config mismatch on {key!r}: cannot resume with different "
                    f"optimization configuration (objective_fn/tolerance/patience are not "
                    f"persisted and must be re-supplied identically)"
                )
        records = [
            EvaluationRecord.from_dict(item) for item in payload["result"]["history"]
        ]
        self._next_index = int(payload.get("next_index", len(records)))
        self._history = list(records)
        self._cache = {self._param_key(record.parameters): record for record in records}
        self._cached_count = len(records)
        self._result.history = list(records)
        # replay counters/best/stall deterministically from persisted records
        for record in records:
            self._result.proposals += 1
            if record.status == "infeasible":
                self._result.infeasible += 1
            elif record.status == "failed":
                self._result.failed += 1
                self._result.evaluations += 1
            else:
                self._consider_best(record)
        self._result.cached = self._cached_count
        self._best_candidate = payload.get("best_candidate")
        self._best_objective = payload.get("best_objective")

    # ------------------------------------------------------------------ run

    def run(self, on_evaluation: Optional[Callable[[EvaluationRecord, "OptimizeResult"], None]] = None) -> OptimizeResult:
        """Run the optimization loop until a termination condition fires.

        ``on_evaluation`` (optional) is called after every recorded evaluation
        with ``(record, live_result)`` — use it for progress reporting or live
        observers.
        """
        self._load_checkpoint()
        started = time.monotonic()
        if self.resume and self.checkpoint_path is not None and self._history:
            if self.budget < self._result.evaluations:
                raise OptimizationError(
                    f"budget {self.budget} is smaller than the {self._result.evaluations} "
                    f"evaluations already recorded in the checkpoint"
                )
        reason = "budget"
        examined_guard = 0
        max_examined = 1_000_000

        while True:
            if self.time_budget_seconds is not None and time.monotonic() - started >= self.time_budget_seconds:
                reason = "time"
                break
            if self._result.evaluations >= self.budget:
                reason = "budget"
                break
            if (
                self.patience is not None
                and self._result.evaluations >= self.min_evaluations
                and self._consecutive_no_improve >= self.patience
            ):
                reason = "patience"
                break
            if self._next_index >= self._max_proposals():
                reason = "exhausted"
                break
            examined_guard += 1
            if examined_guard > max_examined:
                raise OptimizationError("proposal loop exceeded safety guard (duplicate storm?)")

            index = self._next_index
            candidate = self._proposal(index)
            self._next_index += 1

            # duplicate cache hit (resume boundary or repeated proposal)
            key = self._param_key(candidate)
            if key in self._cache:
                self._result.cached += 1
                continue

            # constraints: cheap feasibility gate BEFORE any simulation
            violated = [
                c.name for c in self.constraints if not c.predicate(candidate)
            ]
            if violated:
                record = EvaluationRecord(
                    index=index,
                    parameters=candidate,
                    status="infeasible",
                    simulated=False,
                    objective=None,
                    feasible=False,
                    violated_constraints=violated,
                    message="violated: " + ", ".join(violated),
                )
                self._result.proposals += 1
                self._result.infeasible += 1
                self._history.append(record)
                self._result.history.append(record)
                self._cache[key] = record
                self._write_checkpoint()
                if on_evaluation is not None:
                    on_evaluation(record, self._result)
                continue

            # simulate
            message = None
            objective: Optional[float] = None
            status = "evaluated"
            try:
                objective = self.objective_fn(candidate)
            except Exception as exc:  # noqa: BLE001 - failures are data, not control flow
                status = "failed"
                objective = None
                message = f"{type(exc).__name__}: {exc}"
            if status == "evaluated" and objective is None:
                status = "failed"
                message = "objective_fn returned None (simulation failure)"
            elif status == "evaluated" and isinstance(objective, float) and math.isnan(objective):
                status = "failed"
                objective = None
                message = "objective_fn returned NaN"
            elif status == "evaluated" and objective is not None:
                objective = float(objective)

            record = EvaluationRecord(
                index=index,
                parameters=candidate,
                status=status,
                simulated=True,
                objective=objective,
                feasible=True,
                message=message,
            )
            self._result.proposals += 1
            self._history.append(record)
            self._result.history.append(record)
            self._cache[key] = record
            if status == "failed":
                self._result.failed += 1
            else:
                self._consider_best(record)
            self._write_checkpoint()
            if on_evaluation is not None:
                on_evaluation(record, self._result)

        self._result.best_candidate = self._best_candidate
        self._result.best_objective = self._best_objective
        self._result.reason = reason
        self._result.evaluations = self._result.evaluations
        self._last_result = self._result
        return self._result

    def _max_proposals(self) -> int:
        if self.method == "grid":
            return self._grid_size()  # type: ignore[return-value]
        return 10_000_000  # random is unbounded by construction


def export_optimization_history(result: Any, path: str) -> None:
    """Export an OptimizeResult (or a sequence of EvaluationRecord) to a file.

    Supported formats: ``.csv``, ``.json``, ``.xlsx``, ``.parquet`` (Excel and
    Parquet require openpyxl / pandas+pyarrow respectively).
    """
    if isinstance(result, OptimizeResult):
        records = result.history
    else:
        records = list(result)
        if records and not all(isinstance(r, EvaluationRecord) for r in records):
            raise OptimizationError("export_optimization_history expects an OptimizeResult or a list of EvaluationRecord")
    destination = os.path.abspath(path)
    ext = os.path.splitext(destination)[1].lower()
    if ext not in _EXPORT_SUFFIXES:
        raise OptimizationError(
            f"Unsupported export format {ext!r}: use one of {list(_EXPORT_SUFFIXES)}"
        )
    parent = os.path.dirname(destination)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if ext == ".json":
        payload = {
            "format": "labeeb-optimization-history",
            "records": [record.to_dict() for record in records],
        }
        if isinstance(result, OptimizeResult):
            payload["best_candidate"] = result.best_candidate
            payload["best_objective"] = result.best_objective
            payload["direction"] = result.direction
            payload["method"] = result.method
            payload["reason"] = result.reason
        with open(destination, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        return
    rows = [record.to_dict() for record in records]
    if not rows:  # still write headers for empty histories
        rows = [{"index": 0, "status": "", "simulated": "", "objective": "", "feasible": "", "message": ""}]
        rows.clear()
    if ext == ".csv":
        var_names = sorted(
            {name for record in records for name in record.parameters}
        ) if records else []
        header = ["index", "status", "simulated", "objective", "feasible"] + var_names + ["message"]
        import csv as _csv

        with open(destination, "w", encoding="utf-8", newline="") as handle:
            writer = _csv.writer(handle)
            writer.writerow(header)
            for record in records:
                writer.writerow(
                    [record.index, record.status, int(record.simulated), record.objective,
                     int(record.feasible)]
                    + [record.parameters.get(name, "") for name in var_names]
                    + [record.message or ""]
                )
        return
    try:
        frame = result.to_dataframe() if isinstance(result, OptimizeResult) else __import__("pandas").DataFrame(rows)
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise OptimizationError(
            f"{ext} export requires pandas; install with: pip install pandas"
        ) from exc
    if ext == ".parquet":
        frame.to_parquet(destination, index=False)
        return
    if ext == ".xlsx":
        try:
            frame.to_excel(destination, index=False, sheet_name="optimization_history")
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise OptimizationError(
                ".xlsx export requires openpyxl; install with: pip install openpyxl"
            ) from exc
        return

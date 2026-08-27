"""
Shared convergence-driven execution contract for Case and Coupler.

Design note (resolves the row-driven vs. convergence-driven ambiguity):
`run_to_convergence` never reads `len(database)` or any row/scenario count.
Row/scenario looping stays exclusively in each subclass's own `launch()`.
`run_to_convergence` only ever counts *execution attempts* of a single
unit against `max_exec`, driven by `check_fn`.
"""

import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConvergenceResult:
    """Outcome of a `run_to_convergence` call."""

    unit: str
    converged: bool
    executions: int
    residual: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


class CoupledUnit:
    """
    Shared base for `Case` and `Coupler`.

    Provides a convergence-driven execution loop (`run_to_convergence`) on
    top of each subclass's own single-pass execution (`_run_once`).

    Invariant: when a child unit is itself a `CoupledUnit` (e.g. a nested
    `Coupler`), a parent's `check_fn` must only ever be evaluated AFTER
    that child's own `run_to_convergence` has finished (converged or
    exhausted `max_exec`) -- never mid-iteration on a partially resolved
    child. Callers composing units must call the child's
    `run_to_convergence` to completion before passing its result to a
    parent-level check.
    """

    default_max_exec: int = 1

    def __init__(self) -> None:
        self.pre_functions: List[Callable[..., Any]] = []
        self.post_functions: List[Callable[..., Any]] = []
        self.last_convergence: Optional[ConvergenceResult] = None

    def add_pre_functions(self, *funcs: Callable[..., Any]) -> "CoupledUnit":
        """Register ordered pre-execution callback(s), run before every pass."""
        for f in funcs:
            if f not in self.pre_functions:
                self.pre_functions.append(f)
        return self

    def add_post_functions(self, *funcs: Callable[..., Any]) -> "CoupledUnit":
        """Register ordered post-execution callback(s), run after every pass."""
        for f in funcs:
            if f not in self.post_functions:
                self.post_functions.append(f)
        return self

    def _run_once(self, **kwargs: Any) -> None:
        """Execute a single pass. Subclasses must implement, and are
        responsible for invoking `self.pre_functions`/`self.post_functions`
        around their own pass body."""
        raise NotImplementedError

    def run_to_convergence(
        self,
        max_exec: Optional[int] = None,
        check_fn: Optional[Callable[..., bool]] = None,
        **kwargs: Any,
    ) -> ConvergenceResult:
        """
        Repeatedly call `_run_once` until `check_fn(self, **kwargs)` returns
        True or `max_exec` attempts are used. With no `check_fn`, converges
        after a single pass (matches today's non-iterative behavior).
        """
        n = max_exec if max_exec is not None else self.default_max_exec
        unit_name = getattr(self, "name", self.__class__.__name__)

        for i in range(n):
            self._run_once(**kwargs)

            converged = True if check_fn is None else bool(check_fn(self, **kwargs))
            if converged:
                result = ConvergenceResult(unit=unit_name, converged=True, executions=i + 1)
                self.last_convergence = result
                return result

        logger.warning(f"'{unit_name}' did not converge within max_exec={n} executions.")
        result = ConvergenceResult(unit=unit_name, converged=False, executions=n)
        self.last_convergence = result
        return result

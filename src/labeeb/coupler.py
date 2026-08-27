"""
Coupler module to couple multiple cases (e.g., MCNP and RELAP5 simulations)
in an iterative loop, utilizing database parameters and user-defined coupling functions.
"""

import copy
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from .case import Case
from .database import Database
from .exceptions import CouplingError
from .utils import os_ops, progress

logger = logging.getLogger(__name__)


class Coupler(dict):
    """
    Coordinates and launches multiple simulation cases in a coupled workflow.
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
        super().__init__()
        self.name: str = name
        self.description: Optional[str] = None
        self.database: Optional[Database] = None

        self.cases: List[Case] = []
        self.case_mappings: Dict[str, List[str]] = {}
        self._coupling_functions: List[Callable[..., Any]] = []

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

    def add_case(self, case: Case, attributes: Optional[List[str]] = None) -> "Coupler":
        """
        Register a single Case, optionally specifying which attributes to copy.
        """
        if case not in self.cases:
            if case.name in [c.name for c in self.cases]:
                logger.warning(f"Duplicate case name '{case.name}' detected.")
            self.cases.append(case)
        if attributes is not None:
            self.case_mappings[case.name] = attributes
        return self

    def add_cases(self, *args: Any, **kwargs: Any) -> "Coupler":
        """
        Register multiple cases.
        Supports either:
          - Multiple Case instances: add_cases(case1, case2)
          - A single dictionary mapping Case -> attribute list: add_cases({case1: ['RHO'], case2: []})
        """
        if len(args) == 1 and isinstance(args[0], dict):
            for case, attributes in args[0].items():
                self.add_case(case, attributes)
        else:
            for c in args:
                if isinstance(c, Case):
                    self.add_case(c)
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
                logger.warning(
                    f"Coupler '{self.name}' reached max_steps guard ({self.max_steps}); stopping."
                )
                break

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

        idx = self.c_step
        if idx is None:
            idx = 0
            self.c_step = 0

        self.current_case_dir = os_ops.set_fullpath(
            self.main_dir, self.run_case_main_dir, f"{self.run_case_sub_dir}_{idx}"
        )

        for case in self.cases:
            self.case_name = case.name
            case.set_vars(root_dir=self.current_case_dir)

            # Update the case database row with the coupler's current database row parameters
            if self.database and case.database:
                row_data = self.database.get_row(idx)
                mapped_atts = self.case_mappings.get(case.name)
                if mapped_atts is not None:
                    row_data = {k: v for k, v in row_data.items() if k in mapped_atts}
                case.database.update_row(row_id=0, data=row_data, add_new=False)

            case.launch(indent=1, **kwargs)
            self._execute_coupling_functions(**kwargs)

        return self

    def _shall_stop(self) -> bool:
        return False

    def set_vars(self, **kwargs: Any) -> "Coupler":
        """Set variables dynamically."""
        self._parse_kwargs(**kwargs)
        return self

    def update_db(self) -> None:
        """Mock method."""
        pass

    def __dir__(self) -> List[str]:
        return [x for x in self.__dict__.keys() if not x.startswith("_")] + ["case"]

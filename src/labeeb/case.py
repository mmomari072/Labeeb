"""
Case module to define case configuration, directory structure,
input processing, simulation runs, and parsing outputs.
"""

import logging
import os
import shlex
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pandas as pd

from .coupled_unit import CoupledUnit
from .database import Attribute, Database
from .exceptions import CaseExecutionError, TemplateError
from .execution import ExecutionBackend, LocalExecutionBackend
from .extractors import run_extractor
from .logging_config import CaseLoggerAdapter, redact_sensitive
from .utils import file_io, os_ops, progress

logger = logging.getLogger(__name__)


def _shutdown_executor(executor: Any, wait: bool = True, cancel_pending: bool = False) -> None:
    """Shut down an executor across Python versions with different signatures."""
    if cancel_pending:
        try:
            executor.shutdown(wait=wait, cancel_futures=True)
            return
        except TypeError:
            # ``cancel_futures`` was added after Python 3.8.
            pass
    executor.shutdown(wait=wait)


class Flag:
    """
    Represents a search-and-replace linkage flag in the template input decks.
    """

    def __init__(self, name: str, attribute_name: str, fmt: Optional[str] = None, **kwargs: Any):
        """
        Initialize a Flag.

        Args:
            name: Flag placeholder string in the template (e.g. '#RHO#').
            attribute_name: Mapped Database attribute column name.
            fmt: Optional format string (e.g. '%5.2f').
        """
        self.name: str = name
        self.attribute: str = attribute_name
        self.format: Optional[str] = fmt
        self.value: Any = None

    def __call__(self, val: Any) -> Any:
        self.set_value(val)
        if self.value is None:
            raise CaseExecutionError(f"Linkage flag '{self.name}' requires modification but no value provided")
        return self.format % self.value if self.format is not None else self.value

    def set_value(self, val: Any) -> "Flag":
        """
        Set the active value for this flag.
        """
        self.value = val
        return self

    def reset(self) -> "Flag":
        """
        Reset flag value to None.
        """
        self.value = None
        return self

    def get_value(self) -> Optional[Any]:
        """
        Get formatted flag value.
        """
        if self.value is None:
            return None
        return self.format % self.value if self.format is not None else self.value


class FlagsMap:
    """
    Manages a dictionary collection of Flag instances.
    """

    def __init__(self):
        """Initialize empty FlagsMap."""
        self._flags: Dict[str, Flag] = {}

    def add_flag(self, *flags: Flag) -> "FlagsMap":
        """
        Add Flag(s) to the map.
        """
        for f in flags:
            if not isinstance(f, Flag):
                logger.error("Only Flag instances can be added to FlagsMap")
                continue
            self._flags[f.name] = f
        return self

    def __setitem__(self, item: str, val: Flag) -> None:
        if not isinstance(val, Flag):
            raise TypeError("Value must be a Flag instance")
        if item != val.name:
            logger.warning(f"FlagsMap key '{item}' does not match flag name '{val.name}'")
        self._flags[item] = val

    def __len__(self) -> int:
        return len(self._flags)

    def __getitem__(self, item: str) -> Flag:
        return self._flags[item]

    def __iter__(self):
        self._current_index = 0
        self._keys = list(self._flags.keys())
        return self

    def __next__(self) -> Flag:
        if self._current_index < len(self):
            val = self._flags[self._keys[self._current_index]]
            self._current_index += 1
            return val
        raise StopIteration

    def set_values_from_attributes(self, att_vals: Dict[str, Any]) -> "FlagsMap":
        """
        Set the values of all mapped flags based on active attribute values.
        """
        for f_class in self._flags.values():
            f_class.reset()

        missing = []
        for f_name, f_class in self._flags.items():
            if f_class.attribute not in att_vals or att_vals[f_class.attribute] is None:
                missing.append(f"{f_name} ({f_class.attribute})")
            else:
                f_class.set_value(att_vals[f_class.attribute])
        if missing:
            raise CaseExecutionError(
                "Missing values for linkage flags: " + ", ".join(missing)
            )
        return self

    def get_flags_values(self, att_vals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get dict mapping flag names to their formatted values.
        """
        if att_vals is not None:
            self.set_values_from_attributes(att_vals)
        values = {f_name: f_obj.get_value() for f_name, f_obj in self._flags.items()}
        missing = [f_name for f_name, value in values.items() if value is None]
        if missing:
            raise CaseExecutionError(
                "Missing values for linkage flags: " + ", ".join(missing)
            )
        return values


class Case(CoupledUnit):
    """
    Main manager for simulating sensitivity analysis cases.
    Pads files with mapped replacement flags, launches runs in separate subdirectories, and parses output files.
    """

    def __init__(self, name: str = "", output_files: Optional[Dict[str, List[str]]] = None, **kwargs: Any):
        """
        Initialize a Case.

        Args:
            name: Case runner name.
            output_files: Dictionary mapping output filenames to lists of column names to parse.
        """
        super().__init__()
        self.name: str = name
        self.database: Optional[Database] = None
        self.attributes: List[str] = []
        self.FlagsMap: Union[FlagsMap, Dict[str, str]] = {}
        self.exe_cmd: List[str] = []
        self.execution_backend: ExecutionBackend = LocalExecutionBackend()
        self.harvesters: Dict[str, Any] = {}
        self.input_files: List[file_io.File] = []
        self.assignment_map: Optional[Dict[str, Any]] = None
        self.assignment_fmt: Optional[Union[str, Dict[str, Any]]] = None
        self.strict_assignments: bool = False
        self.expression_context: Optional[Dict[str, Any]] = None
        self.strict_expressions: bool = False
        self.enable_expressions: bool = False

        self.main_dir: str = os.getcwd()
        self.run_case_main_dir: str = "omari"
        self.run_case_sub_dir: str = "case"
        self.current_case_dir: Optional[str] = None

        self.objects_to_be_copied: List[str] = []
        self.new: bool = True
        self.run_type: str = "read_only"
        self.case_id: int = 0

        # Post-output hooks: (name, callable) pairs run after outputs/harvesters
        # are read and before results are finalized (LAB-POST-OUTPUT-HOOKS-01).
        self.post_output_hooks: List[Tuple[str, Callable[..., Any]]] = []
        self.post_output_hook_failures: List[str] = []

        # Secure subprocess execution: None/False -> argv-style (no shell);
        # True -> explicit shell semantics for legacy command strings.
        self.shell: Optional[bool] = None

        # Output specifications
        self.output_files: Dict[str, List[str]] = (
            output_files if output_files is not None else {"omari.csv": ["Time", "Pu239"]}
        )
        self.outputs: Dict[str, List[Any]] = {}
        self.outputs_db: pd.DataFrame = pd.DataFrame()
        self.execution_history: List[Dict[str, Any]] = []
        self._output_att()

        # Failure-handling policy (LAB-FAILURE-POLICY-01):
        #   command_failure_policy: "stop" (default, current semantics - raise),
        #                           "continue" (record FAILED, skip remaining commands),
        #                           "retry" (retry up to max_attempts, then stop).
        #   harvest_failure_policy: "stop" (default, current semantics - raise) or
        #                           "continue" (record None outputs instead of raising).
        # Repeated command retries/recorded failures are stored in
        # execution_history and surfaced through `_case_failed` / `failure` so
        # launchers and campaigns can record the failure without an exception.
        self.command_failure_policy: str = "stop"
        self.harvest_failure_policy: str = "stop"
        self.max_attempts: int = 1
        self._case_failed: bool = False
        self.failure: Optional[str] = None

        self._parse_kwargs(**kwargs)
        self._validate_failure_policies()

    def _validate_failure_policies(self) -> None:
        """Validate failure-policy configuration (called after kwargs parsing)."""
        if self.command_failure_policy not in ("stop", "continue", "retry"):
            raise CaseExecutionError(
                "command_failure_policy must be 'stop', 'continue', or 'retry', "
                f"got '{self.command_failure_policy}'"
            )
        if self.harvest_failure_policy not in ("stop", "continue"):
            raise CaseExecutionError(
                "harvest_failure_policy must be 'stop' or 'continue', "
                f"got '{self.harvest_failure_policy}'"
            )
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise CaseExecutionError("max_attempts must be an integer >= 1")
        if self.command_failure_policy == "retry" and self.max_attempts < 2:
            raise CaseExecutionError(
                "max_attempts must be >= 2 when command_failure_policy='retry'"
            )

    def import_database(self, filename: str = "omari.xlsx", sheetname: str = "omari") -> "Case":
        """
        Import Case parameter database from an Excel sheet.
        """
        try:
            df = pd.read_excel(filename, sheet_name=sheetname)
            data_dict = {col: list(df[col]) for col in df.columns}
            self.database = Database(name=sheetname, data=data_dict)
            self.attributes = list(df.columns)
        except Exception as e:
            raise CaseExecutionError(f"Failed to import database from Excel: {e}") from e
        return self

    def _output_att(self) -> None:
        """Parse output parameters based on output_files structure."""
        self.outputs = {}
        for _, val in self.output_files.items():
            for att in val:
                self.outputs[att] = []
        for name in self.harvesters:
            self.outputs[name] = []
        self.outputs_db = pd.DataFrame()

    def import_FlagsMap(self, filename: str = "omari.xlsx", sheetname: str = "omari") -> "Case":
        """
        Import Flag mappings from an Excel file.
        """
        try:
            df = pd.read_excel(filename, sheet_name=sheetname)
            self.FlagsMap = {row["flag"]: row["attribute"] for _, row in df.iterrows()}
        except Exception as e:
            raise CaseExecutionError(f"Failed to import flags map from Excel: {e}") from e
        return self

    def add_file(self, *files: file_io.File) -> "Case":
        """
        Add input template File(s) to the case.
        """
        for f in files:
            if not isinstance(f, file_io.File):
                logger.error(f"Cannot add file of type {type(f)}. Must be a File instance.")
                continue
            if f not in self.input_files:
                f.read()
                self.input_files.append(f)
                logger.info(f"File {f.fname} has been added to [{self.name}]. Total: {len(self.input_files)}")
            else:
                logger.warning("Duplicate file ignored.")
        return self

    def add_harvester(
        self,
        name_or_harvester: Union[str, Any],
        pattern: Optional[Any] = None,
        file_target: Optional[str] = None,
        optional: bool = False,
    ) -> "Case":
        """Register a named CSV/JSON/regex/Excel or callable output extractor.

        Args:
            name_or_harvester: Harvester instance, or a name for a built-in
                extractor (column name / dotted JSON key / regex pattern /
                Excel column) applied to ``file_target``.
            pattern: Extractor pattern when ``name_or_harvester`` is a name.
            file_target: Output file (relative to the case run directory).
            optional: If True, a missing output file yields ``None`` instead of
                failing the case (explicit optional-output discovery contract).
        """
        from .extractors import Harvester

        if isinstance(name_or_harvester, Harvester):
            harvester = name_or_harvester
            self.harvesters[harvester.name] = harvester
            self.outputs.setdefault(harvester.name, [])
            return self
        name = str(name_or_harvester)
        if not name or not file_target:
            raise CaseExecutionError("Harvester name and file_target are required")
        self.harvesters[name] = (pattern, file_target, optional)
        self.outputs.setdefault(name, [])
        return self

    def set_assignment_map(
        self,
        mapping: Dict[str, Any],
        fmt: Optional[Union[str, Dict[str, Any]]] = None,
        strict: bool = False,
    ) -> "Case":
        """Configure assignment-style parameter replacement for input decks.

        Args:
            mapping: Dictionary mapping assignment keys in templates to database column names or values.
            fmt: Optional format string or dictionary of formatters per key.
            strict: If True, raise TemplateError if an assignment key is missing from template files.
        """
        self.assignment_map = mapping
        self.assignment_fmt = fmt
        self.strict_assignments = strict
        return self

    def set_expression_context(
        self,
        context: Optional[Dict[str, Any]] = None,
        strict: bool = False,
    ) -> "Case":
        """Configure inline expression evaluation context for template files.

        Args:
            context: Optional dictionary of variables and custom functions for expression evaluation.
            strict: If True, raise TemplateError on undefined variables or expression errors.
        """
        self.expression_context = context or {}
        self.strict_expressions = strict
        self.enable_expressions = True
        return self

    def launch_case(self, case_id: Optional[int] = None, **kwargs: Any) -> "Case":
        """
        Launch simulation run for a single case ID.
        """
        timer = progress.Timer()
        timer.tic()

        if case_id is not None:
            self.case_id = case_id

        idx = self.case_id
        if self.database is None:
            raise CaseExecutionError("Cannot launch case without registering a database")

        active_attributes = kwargs.pop("_active_flag_attributes", None)

        # `_attempt` (set by run_to_convergence's repeated passes) keeps
        # repeated self-convergence executions of the same case_id from
        # overwriting each other's run directory. The first attempt (0 or
        # unset, i.e. the normal non-convergence path) keeps today's
        # unsuffixed naming.
        attempt = kwargs.pop("_attempt", 0) or 0
        self._attempt = attempt
        self._case_failed = False
        self.failure = None
        self.post_output_hook_failures = []
        dir_name = (
            f"{self.run_case_sub_dir}_{idx}"
            if not attempt
            else f"{self.run_case_sub_dir}_{idx}_iter{attempt}"
        )
        self.current_case_dir = os_ops.set_fullpath(self.main_dir, self.run_case_main_dir, dir_name)

        for f in self.pre_functions:
            f(self, **kwargs)

        if self.new:
            os_ops.mkdir(self.current_case_dir)

            # Copy required files/directories
            for obj in self.objects_to_be_copied:
                os_ops.cp(obj, self.current_case_dir)

            # Get flags map values
            row_data = self.database.get_row(idx)
            if isinstance(self.FlagsMap, FlagsMap):
                flags = self.FlagsMap
                if active_attributes is not None:
                    flags = FlagsMap().add_flag(
                        *[flag for flag in self.FlagsMap if flag.attribute in active_attributes]
                    )
                flagsmap = flags.get_flags_values(row_data)
            else:
                active_flags = {
                    flag_key: att_name
                    for flag_key, att_name in self.FlagsMap.items()
                    if active_attributes is None or att_name in active_attributes
                }
                missing = [
                    f"{flag_key} ({att_name})"
                    for flag_key, att_name in active_flags.items()
                    if att_name not in row_data or row_data[att_name] is None
                ]
                if missing:
                    raise CaseExecutionError(
                        "Missing values for linkage flags: " + ", ".join(missing)
                    )
                flagsmap = {
                    flag_key: str(row_data[att_name])
                    for flag_key, att_name in active_flags.items()
                }

            # Write input templates with replaced placeholder flags
            self._write_input(flagsmap)

            # Execute case commands
            self._execute()

        # Parse outputs
        self._read_outputs()

        # Post-output hooks: enrichment/derivation after outputs are read,
        # before results are finalized (runs before post_functions).
        self._run_post_output_hooks()

        for f in self.post_functions:
            f(self, **kwargs)

        timer.toc()
        return self

    def _run_once(self, **kwargs: Any) -> None:
        """Single execution pass, used by `run_to_convergence()`."""
        self.launch_case(**kwargs)

    def create_case_main_dir(self) -> "Case":
        """Helper to call initialization."""
        return self.initialization()

    def initialization(self) -> "Case":
        """Clean and initialize case directory layout."""
        cases_root_path = os_ops.set_fullpath(self.main_dir, self.run_case_main_dir)
        if self.run_type != "new":
            self.new = False
        else:
            self.new = True
            os_ops.rmdir(cases_root_path)

        os_ops.mkdir(cases_root_path)
        return self

    def launch(self, parallel: bool = False, n_workers: Optional[int] = None, **kwargs: Any) -> "Case":
        """
        Launch the full multi-case runs.
        """
        self.initialization()
        self._output_att()

        if not self.database:
            raise CaseExecutionError("No database imported for Case Launcher")

        num_rows = len(self.database)

        if not parallel:
            indent = kwargs.get("indent", 0)
            prog_bar = progress.ProgressBar(name=self.name, start=0, end=num_rows, indent=indent)
            failures: List[CaseExecutionError] = []
            for i in prog_bar:
                if self._shall_stop():
                    logger.info("Launcher stopped by the user via STOP_ALL condition")
                    break
                self.case_id = i
                try:
                    self.launch_case(**kwargs)
                    if getattr(self, "_case_failed", False):
                        # continue-policy failure: outputs already recorded;
                        # surface the failure without double-recording Nones.
                        exc = CaseExecutionError(self.failure or "Case failed (continue policy)")
                        self._record_failed_case(exc)
                        failures.append(exc)
                except CaseExecutionError as exc:
                    self._record_failed_case(exc)
                    failures.append(exc)
            if failures:
                raise CaseExecutionError(
                    f"{len(failures)} of {num_rows} cases failed; see execution_history for details"
                ) from failures[0]
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            import multiprocessing

            max_workers = n_workers or max(1, multiprocessing.cpu_count() - 1)
            logger.info(f"Launching {num_rows} cases in parallel using {max_workers} processes...")

            # Clean outputs so we can append results
            for key in self.outputs:
                self.outputs[key] = []

            # We use a list to preserve original order of outputs and history
            temp_results = [None] * num_rows
            failures = []

            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_run_case_worker, self, i, kwargs): i
                    for i in range(num_rows)
                }

                indent = kwargs.get("indent", 0)
                prog_bar = progress.ProgressBar(name=f"{self.name} (Parallel)", start=0, end=num_rows, indent=indent)
                for future in as_completed(futures):
                    if self._shall_stop():
                        logger.info("Parallel run requested stop, cancelling pending tasks")
                        _shutdown_executor(executor, wait=False, cancel_pending=True)
                        break

                    idx = futures[future]
                    try:
                        outputs, exec_hist, case_id = future.result()
                        temp_results[idx] = (outputs, exec_hist)
                    except Exception as e:
                        logger.error(f"Parallel case execution {idx} failed: {e}")
                        temp_results[idx] = (
                            {key: [None] for key in self.outputs},
                            [{
                                "case_id": idx,
                                "command": None,
                                "exit_code": None,
                                "status": "FAILED",
                                "error": str(e),
                            }],
                        )
                        failures.append(e)

                    prog_bar.update(prog_bar._index + 1)

            # Reconstruct outputs and execution history in correct order of case_ids
            for idx in range(num_rows):
                res = temp_results[idx]
                if res:
                    outputs, exec_hist = res
                    for key, val_list in outputs.items():
                        if key not in self.outputs:
                            self.outputs[key] = []
                        self.outputs[key].extend(val_list)
                    self.execution_history.extend(exec_hist)

                    if any(entry.get("status") in {"FAILED", "TIMEOUT"} for entry in exec_hist):
                        failures.append(CaseExecutionError(f"Case {idx} failed"))

            if failures:
                raise CaseExecutionError(
                    f"{len(failures)} of {num_rows} cases failed; see execution_history for details"
                ) from failures[0]

        return self

    def _shall_stop(self) -> bool:
        stop_file = os_ops.set_fullpath(self.main_dir, self.run_case_main_dir, "STOP_ALL")
        return os_ops.isfile(stop_file)

    def _redact_cmd(self, cmd: Any) -> str:
        """Redact a command for logs/errors; argv lists are joined first."""
        if isinstance(cmd, str):
            return redact_sensitive(cmd)
        try:
            return redact_sensitive(shlex.join(str(part) for part in cmd))
        except Exception:  # noqa: BLE001
            return redact_sensitive(" ".join(str(part) for part in cmd))

    def _execute(self) -> List[int]:
        exit_codes = []
        command_logger = CaseLoggerAdapter(
            logger,
            {"case_id": self.case_id, "unit": self.name, "attempt": getattr(self, "_attempt", 0)},
        )
        if hasattr(self.execution_backend, "set_logger"):
            self.execution_backend.set_logger(command_logger)  # type: ignore[attr-defined]
        import time
        from datetime import datetime

        try:
            for cmd in self.exe_cmd:
                if getattr(self, "_case_failed", False):
                    break  # continue policy: stop after a recorded failure
                timeout = getattr(self, "timeout", None)
                log_file = getattr(self, "log_file", None)
                if log_file and not os.path.isabs(log_file):
                    log_file = os.path.join(self.current_case_dir, log_file)

                attempts_left = (
                    self.max_attempts if self.command_failure_policy == "retry" else 1
                )
                while attempts_left > 0:
                    attempts_left -= 1

                    # Record execution details
                    t_start = time.time()
                    t_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if isinstance(self.execution_backend, LocalExecutionBackend):
                        # Secure-execution opt-in applies to the local backend.
                        result = self.execution_backend.run(
                            cmd, cwd=self.current_case_dir, timeout=timeout,
                            log_file=log_file, shell=self.shell,
                        )
                    else:
                        # Injected/custom backends keep their own contract.
                        result = self.execution_backend.run(
                            cmd, cwd=self.current_case_dir, timeout=timeout, log_file=log_file
                        )
                    if getattr(self, "capture_output", False) and self.current_case_dir:
                        if result.stdout:
                            with open(os.path.join(self.current_case_dir, "stdout.log"), "a", encoding="utf-8") as stream:
                                stream.write(result.stdout)
                        if result.stderr:
                            with open(os.path.join(self.current_case_dir, "stderr.log"), "a", encoding="utf-8") as stream:
                                stream.write(result.stderr)
                    code = result.returncode

                    t_duration = time.time() - t_start
                    status_str = "SUCCESS" if code == 0 else ("TIMEOUT" if code == -999 else "FAILED")
                    message = None
                    if result.event is not None:
                        message = result.event.message

                    if code != 0 and attempts_left > 0:
                        # Policy "retry": record the failed attempt, then retry.
                        logger.warning(
                            "Simulation command returned exit status %s (%s) for command '%s'; "
                            "%s retr%s remaining",
                            status_str, code, self._redact_cmd(cmd), attempts_left,
                            "y" if attempts_left == 1 else "ies",
                        )
                        self.execution_history.append({
                            "case_id": self.case_id,
                            "command": self._redact_cmd(cmd),
                            "exit_code": code,
                            "status": status_str,
                            "timestamp": t_stamp,
                            "duration_seconds": round(result.duration_seconds or t_duration, 3),
                            "message": message or f"attempt failed; {attempts_left} retr{'y' if attempts_left == 1 else 'ies'} left",
                        })
                        if result.event is not None:
                            self.execution_history[-1].update(result.event.to_dict())
                            self.execution_history[-1]["execution_event"] = result.event.to_dict()
                        continue

                    self.execution_history.append({
                        "case_id": self.case_id,
                        "command": self._redact_cmd(cmd),
                        "exit_code": code,
                        "status": status_str,
                        "timestamp": t_stamp,
                        "duration_seconds": round(result.duration_seconds or t_duration, 3)
                    })
                    if result.event is not None:
                        self.execution_history[-1].update(result.event.to_dict())
                        self.execution_history[-1]["execution_event"] = result.event.to_dict()

                    if code != 0:
                        logger.error(f"Simulation command returned exit status {status_str} ({code}) for command '{self._redact_cmd(cmd)}'")
                        if self.command_failure_policy == "continue":
                            self._mark_case_failed(
                                f"Simulation command failed for case {self.case_id}: "
                                f"'{self._redact_cmd(cmd)}' ({status_str}, exit code {code})"
                            )
                            # Record the failure in the last history entry's message
                            self.execution_history[-1]["message"] = self.failure
                            break  # skip remaining commands for this case
                        raise CaseExecutionError(
                            f"Simulation command failed for case {self.case_id}: '{self._redact_cmd(cmd)}' ({status_str}, exit code {code})"
                        )
                    exit_codes.append(code)
                    break
        except Exception as e:
            logger.error(f"Error during simulation command execution: {e}")
            raise CaseExecutionError(f"Failed to execute simulation commands: {e}") from e
        return exit_codes

    def _mark_case_failed(self, message: str) -> None:
        """Record a policy-continued failure so launchers/campaigns see it."""
        self._case_failed = True
        self.failure = self.failure or message

    def _cd(self, directory: str) -> "Case":
        os_ops.chdir(directory)
        return self

    def _write_input(self, flagsmap: Dict[str, Any]) -> "Case":
        row_data = self.database.get_row(self.case_id) if self.database is not None else {}
        for f in self.input_files:
            has_rendered = False
            if flagsmap:
                f.replace(flagsmap)
                has_rendered = True

            if getattr(self, "assignment_map", None):
                assignments: Dict[str, Any] = {}
                for key, attr_or_val in self.assignment_map.items():
                    if isinstance(attr_or_val, str) and attr_or_val in row_data:
                        assignments[key] = row_data[attr_or_val]
                    else:
                        assignments[key] = attr_or_val
                f.replace_assignments(
                    assignments,
                    strict=getattr(self, "strict_assignments", False),
                    fmt=getattr(self, "assignment_fmt", None),
                    evaluate_expressions=True,
                    context=row_data,
                    reset=not has_rendered,
                )
                has_rendered = True

            if getattr(self, "enable_expressions", False) or getattr(self, "expression_context", None):
                ctx = {
                    **{k.lower(): v for k, v in row_data.items()},
                    **row_data,
                    **(getattr(self, "expression_context", {}) or {}),
                }
                f.replace_expressions(
                    ctx,
                    strict=getattr(self, "strict_expressions", False),
                    reset=not has_rendered,
                )
                has_rendered = True

            f.write(os.path.join(self.current_case_dir, f.filename))
        return self

    def _read_outputs(self) -> "Case":
        parsed_outputs: Dict[str, List[Any]] = {}
        for fname, cols in self.output_files.items():
            fullname = os.path.join(self.current_case_dir, fname)
            if not os_ops.isfile(fullname):
                if self.harvest_failure_policy == "continue":
                    logger.warning(f"Output file '{fullname}' was not produced (continue policy)")
                    for col in cols:
                        parsed_outputs[col] = [None]
                    self._mark_case_failed(f"Required output file '{fullname}' was not produced")
                    continue
                raise CaseExecutionError(f"Required output file '{fullname}' was not produced")
            try:
                df = pd.read_csv(fullname, usecols=cols, low_memory=True)
                for col in cols:
                    parsed_outputs[col] = df[col].tolist()
            except Exception as e:
                logger.error(f"Failed to read output file {fullname}: {e}")
                if self.harvest_failure_policy == "continue":
                    for col in cols:
                        parsed_outputs[col] = [None]
                    self._mark_case_failed(f"Failed to read simulation output from '{fullname}': {e}")
                    continue
                raise CaseExecutionError(f"Failed to read simulation output from '{fullname}': {e}") from e
        for col, values in parsed_outputs.items():
            self.outputs[col].append(values)
        for name, spec in self.harvesters.items():
            try:
                from .extractors import Harvester

                if isinstance(spec, Harvester):
                    self.outputs[name].append(spec.harvest(self.current_case_dir))
                else:
                    pattern, file_target, optional = (list(spec) + [False])[:3]  # type: ignore[misc]
                    target = Path(file_target)
                    if not target.is_absolute():
                        target = Path(self.current_case_dir) / target
                    if optional and not os_ops.isfile(str(target)):
                        self.outputs[name].append(None)
                        continue
                    self.outputs[name].append(run_extractor(target, pattern))
            except Exception as exc:
                if self.harvest_failure_policy == "continue":
                    logger.warning(f"Failed to harvest '{name}': {exc} (continue policy)")
                    self.outputs[name].append(None)
                    self._mark_case_failed(f"Failed to harvest '{name}': {exc}")
                    continue
                raise CaseExecutionError(
                    f"Failed to harvest '{name}': {exc}"
                ) from exc
        return self

    def _record_failed_case(self, exc: BaseException) -> None:
        """Record one failed result for every declared output column."""
        # continue-policy failures already recorded their outputs (None/partial);
        # avoid double-recording so row alignment is preserved.
        if not getattr(self, "_case_failed", False):
            for col in self.outputs:
                self.outputs[col].append(None)
        if not any(
            entry.get("case_id") == self.case_id
            and entry.get("status") in {"FAILED", "TIMEOUT"}
            for entry in self.execution_history
        ):
            self.execution_history.append({
                "case_id": self.case_id,
                "command": None,
                "exit_code": None,
                "status": "FAILED",
                "error": str(exc),
            })

    def _parse_kwargs(self, **kwargs: Any) -> None:
        for key, val in kwargs.items():
            if key in self.__dict__:
                setattr(self, key, val)
            elif key.lower() in ["root_dir", "main_dir"]:
                self.main_dir = val
            else:
                logger.warning(f"Case setup parameter '{key}' is not supported")

    def add_post_output_hook(self, name: str, fn: Optional[Callable[..., Any]] = None) -> "Case":
        """Register a post-output hook.

        ``name`` is a unique label (used in error messages and failure
        records). When called with a single callable argument, its
        ``__name__`` is used as the label.

        The hook runs after output files/harvesters have been read and before
        results are finalized — i.e. between ``_read_outputs()`` and
        ``post_functions`` in ``launch_case``. Contract:

        * ``hook(outputs, case)`` receives the live ``case.outputs`` mapping
          (per-column row lists; mutations are honored) and the ``Case``
          itself (``case.case_id``, ``case.current_case_dir``,
          ``case.execution_history``, ...).
        * Returning a dict ``{metric: value}`` appends one row entry to each
          named output column (creating the column if new) — synthesized
          metrics then flow into results and, when configured, per-attempt
          catalog rows (the catalog records per-key output deltas).
        * Returning ``None`` contributes nothing beyond any in-place
          mutations.
        * A return that is neither ``None`` nor a dict is a contract
          violation and raises ``CaseExecutionError``. Exceptions raised
          *inside* a hook follow ``harvest_failure_policy``: ``stop``
          (default) fails the case with ``CaseExecutionError``; ``continue``
          records the failure on ``case.post_output_hook_failures``, keeps the
          outputs, and proceeds with the remaining hooks.
        """
        if fn is None:
            fn = name  # type: ignore[assignment]
            name = getattr(fn, "__name__", "hook")
        if not callable(fn):
            raise CaseExecutionError(
                f"post-output hook {name!r} must be callable(outputs, case)"
            )
        existing = {hook_name for hook_name, _ in self.post_output_hooks}
        if name in existing:
            raise CaseExecutionError(
                f"post-output hook name {name!r} is already registered (names must be unique)"
            )
        self.post_output_hooks.append((str(name), fn))
        return self

    def _validate_post_output_hooks(self) -> None:
        seen: List[str] = []
        normalized: List[Tuple[str, Callable[..., Any]]] = []
        for item in self.post_output_hooks:
            name: str
            fn: Callable[..., Any]
            if isinstance(item, tuple) and len(item) == 2:
                name, fn = item  # type: ignore[misc]
            else:
                fn = item  # type: ignore[assignment]
                name = getattr(fn, "__name__", "hook")
            if not isinstance(name, str) or not name:
                raise CaseExecutionError(
                    "post-output hook entries must carry a non-empty string name"
                )
            if not callable(fn):
                raise CaseExecutionError(
                    f"post-output hook {name!r} must be callable(outputs, case), got {type(fn).__name__}"
                )
            if name in seen:
                raise CaseExecutionError(
                    f"post-output hook name {name!r} is registered more than once (names must be unique)"
                )
            seen.append(name)
            normalized.append((name, fn))
        self.post_output_hooks = normalized

    def _run_post_output_hooks(self) -> None:
        """Run registered post-output hooks (see add_post_output_hook)."""
        self._validate_post_output_hooks()
        for name, fn in self.post_output_hooks:
            try:
                extra = fn(self.outputs, self)
            except Exception as exc:  # noqa: BLE001 - governed by harvest_failure_policy
                if getattr(self, "harvest_failure_policy", "stop") == "continue":
                    message = f"{name}: {type(exc).__name__}: {exc}"
                    self.post_output_hook_failures.append(message)
                    logger.warning(f"Post-output hook {message} (continue policy)")
                    continue
                raise CaseExecutionError(
                    f"Post-output hook {name!r} failed for case {self.case_id}: {exc}"
                ) from exc
            if extra is None:
                continue
            if not isinstance(extra, dict):
                raise CaseExecutionError(
                    f"Post-output hook {name!r} must return None or a dict of {{metric: value}}, "
                    f"got {type(extra).__name__}"
                )
            for metric, value in extra.items():
                self.outputs.setdefault(metric, []).append(value)

    def set_vars(self, **kwargs: Any) -> "Case":
        """Set execution parameters dynamically."""
        self._parse_kwargs(**kwargs)
        self._validate_failure_policies()
        return self

    def update_db(self, **kwargs: Any) -> None:
        """Mock method for updating database in subsequent couplers."""
        logger.info(f"Mock database update for Case: {self.name}")


def _run_case_worker(case_obj: Case, case_id: int, kwargs: Dict[str, Any]) -> Tuple[Dict[str, List[Any]], List[Dict[str, Any]], int]:
    """Helper worker function to launch a single case in a separate process."""
    try:
        case_obj.launch_case(case_id=case_id, **kwargs)
        if getattr(case_obj, "_case_failed", False):
            raise CaseExecutionError(case_obj.failure or "Case failed (continue policy)")
    except CaseExecutionError as exc:
        case_obj._record_failed_case(exc)
    return case_obj.outputs, case_obj.execution_history, case_id

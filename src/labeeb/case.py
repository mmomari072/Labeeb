"""
Case module to define case configuration, directory structure,
input processing, simulation runs, and parsing outputs.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from .coupled_unit import CoupledUnit
from .database import Attribute, Database
from .exceptions import CaseExecutionError
from .utils import file_io, os_ops, progress

logger = logging.getLogger(__name__)


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
        for att, val in att_vals.items():
            for f_class in self._flags.values():
                if f_class.attribute == att:
                    f_class.set_value(val)
                    break
        return self

    def get_flags_values(self, att_vals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get dict mapping flag names to their formatted values.
        """
        if att_vals is not None:
            self.set_values_from_attributes(att_vals)
        return {f_name: f_obj.get_value() for f_name, f_obj in self._flags.items()}


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
        self.input_files: List[file_io.File] = []

        self.main_dir: str = os.getcwd()
        self.run_case_main_dir: str = "omari"
        self.run_case_sub_dir: str = "case"
        self.current_case_dir: Optional[str] = None

        self.objects_to_be_copied: List[str] = []
        self.new: bool = True
        self.run_type: str = "read_only"
        self.case_id: int = 0

        # Output specifications
        self.output_files: Dict[str, List[str]] = (
            output_files if output_files is not None else {"omari.csv": ["Time", "Pu239"]}
        )
        self.outputs: Dict[str, List[Any]] = {}
        self.outputs_db: pd.DataFrame = pd.DataFrame()
        self.execution_history: List[Dict[str, Any]] = []
        self._output_att()

        self._parse_kwargs(**kwargs)

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

        self.current_case_dir = os_ops.set_fullpath(
            self.main_dir, self.run_case_main_dir, f"{self.run_case_sub_dir}_{idx}"
        )

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
                flagsmap = self.FlagsMap.get_flags_values(row_data)
            else:
                flagsmap = {
                    flag_key: str(row_data.get(att_name, ""))
                    for flag_key, att_name in self.FlagsMap.items()
                }

            # Write input templates with replaced placeholder flags
            self._write_input(flagsmap)

            # Execute case commands
            self._execute()

        # Parse outputs
        self._read_outputs()

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
            for i in prog_bar:
                if self._shall_stop():
                    logger.info("Launcher stopped by the user via STOP_ALL condition")
                    break
                self.case_id = i
                self.launch_case(**kwargs)
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
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    idx = futures[future]
                    try:
                        outputs, exec_hist, case_id = future.result()
                        temp_results[idx] = (outputs, exec_hist)
                    except Exception as e:
                        logger.error(f"Parallel case execution {idx} failed: {e}")

                    prog_bar.update(prog_bar._index + 1)

            # Reconstruct outputs and execution history in correct order of case_ids
            for idx in range(num_rows):
                res = temp_results[idx]
                if res:
                    outputs, exec_hist = res
                    for key, val_list in outputs.items():
                        if key in self.outputs:
                            self.outputs[key].extend(val_list)
                    self.execution_history.extend(exec_hist)

        return self

    def _shall_stop(self) -> bool:
        stop_file = os_ops.set_fullpath(self.main_dir, self.run_case_main_dir, "STOP_ALL")
        return os_ops.isfile(stop_file)

    def _execute(self) -> List[int]:
        self._cd(self.current_case_dir)
        exit_codes = []
        try:
            for cmd in self.exe_cmd:
                timeout = getattr(self, "timeout", None)
                log_file = getattr(self, "log_file", None)
                if log_file and not os.path.isabs(log_file):
                    log_file = os.path.join(self.current_case_dir, log_file)

                # Record execution details
                import time
                from datetime import datetime
                t_start = time.time()
                t_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                code = os_ops.execute(cmd, timeout=timeout, log_file=log_file)

                t_duration = time.time() - t_start
                status_str = "SUCCESS" if code == 0 else ("TIMEOUT" if code == -999 else "FAILED")

                self.execution_history.append({
                    "case_id": self.case_id,
                    "command": cmd,
                    "exit_code": code,
                    "status": status_str,
                    "timestamp": t_stamp,
                    "duration_seconds": round(t_duration, 3)
                })

                if code != 0:
                    logger.error(f"Simulation command returned exit status {status_str} ({code}) for command '{cmd}'")
                exit_codes.append(code)
        except Exception as e:
            logger.error(f"Error during simulation command execution: {e}")
            raise CaseExecutionError(f"Failed to execute simulation commands: {e}") from e
        finally:
            self._cd(self.main_dir)
        return exit_codes

    def _cd(self, directory: str) -> "Case":
        os_ops.chdir(directory)
        return self

    def _write_input(self, flagsmap: Dict[str, Any]) -> "Case":
        for f in self.input_files:
            f.replace(flagsmap)
            f.write(os.path.join(self.current_case_dir, f.filename))
        return self

    def _read_outputs(self) -> "Case":
        for fname, cols in self.output_files.items():
            fullname = os.path.join(self.current_case_dir, fname)
            if not os_ops.isfile(fullname):
                logger.warning(f"Output file {fullname} not found")
                continue
            try:
                df = pd.read_csv(fullname, usecols=cols, low_memory=True)
                for col in cols:
                    self.outputs[col].append(df[col].tolist())
            except Exception as e:
                logger.error(f"Failed to read output file {fullname}: {e}")
                raise CaseExecutionError(f"Failed to read simulation output from '{fullname}': {e}") from e
        return self

    def _parse_kwargs(self, **kwargs: Any) -> None:
        for key, val in kwargs.items():
            if key in self.__dict__:
                setattr(self, key, val)
            elif key.lower() in ["root_dir", "main_dir"]:
                self.main_dir = val
            else:
                logger.warning(f"Case setup parameter '{key}' is not supported")

    def set_vars(self, **kwargs: Any) -> "Case":
        """Set execution parameters dynamically."""
        self._parse_kwargs(**kwargs)
        return self

    def update_db(self, **kwargs: Any) -> None:
        """Mock method for updating database in subsequent couplers."""
        logger.info(f"Mock database update for Case: {self.name}")


def _run_case_worker(case_obj: Case, case_id: int, kwargs: Dict[str, Any]) -> Tuple[Dict[str, List[Any]], List[Dict[str, Any]], int]:
    """Helper worker function to launch a single case in a separate process."""
    case_obj.launch_case(case_id=case_id, **kwargs)
    return case_obj.outputs, case_obj.execution_history, case_id

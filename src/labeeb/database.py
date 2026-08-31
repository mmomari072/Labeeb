"""
Database and Attribute structures for managing tabular parameters and cases.
Provides a pure Python list/dict subclass implementation backed internally by Pandas
for element-wise calculations, Excel/CSV/Parquet importing/exporting, and robust validation.
"""

import copy
import datetime
import json
import logging
import operator
import os
import pickle
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pandas as pd

from .exceptions import DatabaseError

logger = logging.getLogger(__name__)


def str_to_num(val: Any, target_type: Callable[[Any], Any] = float) -> Any:
    """
    Safely convert string to numerical type (float/int). Returns original if conversion fails.

    Args:
        val: Value to convert.
        target_type: Target conversion constructor (e.g. float or int).

    Returns:
        Converted numeric value, None if empty, or original value on failure.
    """
    if val is None:
        return None
    if isinstance(val, (int, float, bool)):
        return target_type(val)
    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned == "":
            return None
        try:
            return target_type(cleaned)
        except (ValueError, TypeError):
            return val
    return val


class Attribute(list):
    """
    A list subclass representing a column/attribute in the database.
    Operates like a Series, utilizing Pandas internally for element-wise calculations.
    """

    def __init__(
        self,
        name: str,
        data: Optional[List[Any]] = None,
        description: Optional[str] = None,
        Type: Optional[Callable[[Any], Any]] = float,
        unit: Optional[str] = None,
        **kwargs: Any,
    ):
        """
        Initialize an Attribute list.

        Args:
            name: Column name.
            data: Initial list data.
            description: Column explanation.
            Type: Numeric cast type (float, int, bool, etc.).
            unit: Physical unit.
        """
        super().__init__()
        self.name: str = name
        self.description: Optional[str] = description
        self.type: Optional[Callable[[Any], Any]] = Type
        self.unit: Optional[str] = unit
        self._fun_list: List[Callable[..., Any]] = []
        self.non_entered_datum_value: Any = None
        self.instance_type_check: bool = True

        for key, val in kwargs.items():
            if key in self.__dict__:
                setattr(self, key, val)
            else:
                logger.warning(f"Attribute config '{key}' is not supported")

        if data:
            for item in data:
                self.append(str_to_num(item, self.type) if self.type else item)

    def validate(self) -> None:
        """
        Validate that all non-None elements match the attribute's type.
        Raises DatabaseError if invalid data is found.
        """
        if self.type is None:
            return
        for idx, val in enumerate(self):
            if val is None:
                continue
            try:
                # Test type coercion
                _ = self.type(val)
            except (ValueError, TypeError) as e:
                raise DatabaseError(
                    f"Validation failed for attribute '{self.name}' at index {idx}: "
                    f"value '{val}' cannot be converted to type {self.type.__name__}"
                ) from e

    def _operation(self, other: Any, op_str: str, is_right: bool = False) -> "Attribute":
        """
        Perform element-wise operations using Pandas Series internally for speed and correctness.
        """
        s_self = pd.Series(self)

        if isinstance(other, (Attribute, list, tuple)):
            if len(other) != len(self):
                raise DatabaseError(
                    f"Dimensions mismatch for operation '{op_str}': {len(self)} vs {len(other)}"
                )
            s_other = pd.Series(list(other))
        else:
            s_other = other

        # Map operator string to standard operators
        op_map = {
            "+": operator.add,
            "-": operator.sub,
            "*": operator.mul,
            "/": operator.truediv,
            "%": operator.mod,
            "**": operator.pow,
            "//": operator.floordiv,
            "==": operator.eq,
            "!=": operator.ne,
            "<": operator.lt,
            "<=": operator.le,
            ">": operator.gt,
            ">=": operator.ge,
            "and": lambda a, b: a & b,
            "or": lambda a, b: a | b,
        }

        op_func = op_map.get(op_str)
        if op_func is None:
            raise NotImplementedError(f"Operator '{op_str}' is not supported")

        try:
            if is_right:
                res = op_func(s_other, s_self)
            else:
                res = op_func(s_self, s_other)
        except Exception as e:
            raise DatabaseError(f"Math operation '{op_str}' failed: {e}") from e

        # Determine output type
        is_comparison = op_str in [">", ">=", "<", "<=", "==", "!=", "and", "or"]
        out_type = bool if is_comparison else self.type

        # Build clean output name
        other_name = other.name if isinstance(other, Attribute) else str(other)
        name = (
            f"({self.name} {op_str} {other_name})"
            if not is_right
            else f"({other_name} {op_str} {self.name})"
        )

        return Attribute(name=name, data=res.tolist(), Type=out_type)

    # Math operators
    def __add__(self, other: Any) -> "Attribute":
        return self._operation(other, "+")

    def __sub__(self, other: Any) -> "Attribute":
        return self._operation(other, "-")

    def __mul__(self, other: Any) -> "Attribute":
        return self._operation(other, "*")

    def __truediv__(self, other: Any) -> "Attribute":
        return self._operation(other, "/")

    def __mod__(self, other: Any) -> "Attribute":
        return self._operation(other, "%")

    def __pow__(self, other: Any) -> "Attribute":
        return self._operation(other, "**")

    def __and__(self, other: Any) -> "Attribute":
        return self._operation(other, "and")

    def __or__(self, other: Any) -> "Attribute":
        return self._operation(other, "or")

    # Right hand operators
    def __radd__(self, other: Any) -> "Attribute":
        return self._operation(other, "+", is_right=True)

    def __rsub__(self, other: Any) -> "Attribute":
        return self._operation(other, "-", is_right=True)

    def __rmul__(self, other: Any) -> "Attribute":
        return self._operation(other, "*", is_right=True)

    def __rtruediv__(self, other: Any) -> "Attribute":
        return self._operation(other, "/", is_right=True)

    def __rmod__(self, other: Any) -> "Attribute":
        return self._operation(other, "%", is_right=True)

    def __rpow__(self, other: Any) -> "Attribute":
        return self._operation(other, "**", is_right=True)

    # In-place operators (delegate to normal math operators)
    def __iadd__(self, other: Any) -> "Attribute":
        return self.__add__(other)

    def __isub__(self, other: Any) -> "Attribute":
        return self.__sub__(other)

    def __imul__(self, other: Any) -> "Attribute":
        return self.__mul__(other)

    def __itruediv__(self, other: Any) -> "Attribute":
        return self.__truediv__(other)

    def __imod__(self, other: Any) -> "Attribute":
        return self.__mod__(other)

    def __ipow__(self, other: Any) -> "Attribute":
        return self.__pow__(other)

    # Comparisons
    def __eq__(self, other: Any) -> "Attribute":
        return self._operation(other, "==")

    def __ne__(self, other: Any) -> "Attribute":
        return self._operation(other, "!=")

    def __lt__(self, other: Any) -> "Attribute":
        return self._operation(other, "<")

    def __le__(self, other: Any) -> "Attribute":
        return self._operation(other, "<=")

    def __gt__(self, other: Any) -> "Attribute":
        return self._operation(other, ">")

    def __ge__(self, other: Any) -> "Attribute":
        return self._operation(other, ">=")

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, Attribute):
            if index.type is bool:
                return Attribute(
                    name=self.name,
                    data=[self[j] for j, val in enumerate(index) if val],
                    Type=self.type,
                )
            return Attribute(
                name=self.name,
                data=[self[j] for j in index],
                Type=self.type,
            )
        if isinstance(index, (int, slice)):
            return super().__getitem__(index)
        if isinstance(index, (list, tuple)):
            return Attribute(
                name=self.name,
                data=[self[j] for j in index],
                Type=self.type,
            )
        raise IndexError(f"Invalid index type for Attribute: {type(index)}")

    def __setitem__(self, index: Any, val: Any) -> None:
        value = str_to_num(val, self.type) if self.type else val
        try:
            super().__setitem__(index, value)
        except IndexError:
            if isinstance(index, int):
                if index >= 0:
                    for _ in range(len(self), index):
                        self.append(self.non_entered_datum_value)
                    self.append(value)
                else:
                    raise NotImplementedError("Negative out-of-bounds indexing not supported yet")
            elif isinstance(index, (tuple, set, list)):
                if isinstance(value, (tuple, list, set)):
                    if len(value) == len(index):
                        for ii, vv in zip(index, value):
                            self[ii] = vv
                    else:
                        raise DatabaseError("Mismatch in size of index list and values list")
                else:
                    for ii in index:
                        self[ii] = value
            elif isinstance(index, slice):
                start = index.start if index.start is not None else 0
                stop = index.stop if index.stop is not None else len(self)
                step = index.step if index.step is not None else 1
                for ii in range(start, stop, step):
                    self[ii] = value
            else:
                raise IndexError(f"Unsupported index type {type(index)}")

    def __bool__(self) -> bool:
        return all(self)

    def add_functions(self, *funcs: Callable[..., Any]) -> "Attribute":
        """Add processing functions to the attribute instance."""
        for f in funcs:
            func_name = f.__name__
            if func_name in self.__dict__:
                continue
            self.__dict__[func_name] = f.__get__(self)
            self._fun_list.append(f)
        return self

    def resize(self, new_length: int) -> "Attribute":
        """Resize the attribute list, padding with non_entered_datum_value or trimming."""
        if len(self) < new_length:
            logger.warning(
                f"Attribute '{self.name}' auto-padded from {len(self)} to {new_length} rows "
                f"with non_entered_datum_value={self.non_entered_datum_value!r}. "
                "This usually means another column in the Database has more rows than this one."
            )
            self[new_length - 1] = self.non_entered_datum_value
        elif len(self) > new_length:
            logger.warning(
                f"Attribute '{self.name}' auto-trimmed from {len(self)} to {new_length} rows."
            )
            while len(self) > new_length:
                self.pop()
        return self

    def sum(self) -> Any:
        """Calculate column sum."""
        return sum(self)

    def mean(self) -> float:
        """Calculate column mean."""
        return sum(self) / len(self) if len(self) > 0 else 0.0

    def filter(self, function: Callable[[Any], bool] = lambda x: x > 1, return_index: bool = False) -> Any:
        """Filter the attribute list."""
        filtered_flags = [function(x) for x in self]
        if not return_index:
            return Attribute(name="", data=filtered_flags, Type=bool)
        return [i for i, x in enumerate(filtered_flags) if x]

    def add_data(self, *args: Any) -> "Attribute":
        """Flatten and append data values to the attribute."""
        for data in args:
            if isinstance(data, (list, tuple, set)):
                for item in data:
                    self.add_data(item)
            else:
                self.append(str_to_num(data, self.type) if self.type else data)
        return self

    def remove_data(self, *args: Any) -> "Attribute":
        """Remove matching elements from the attribute."""
        for val in args:
            while val in self:
                self.remove(val)
        return self

    def convert_to_num(self) -> "Attribute":
        """Convert all string elements to floats, turning failed conversions to NaN."""
        s = pd.to_numeric(pd.Series(self), errors="coerce")
        self.clear()
        self.extend(s.tolist())
        return self

    def set_index(self, index: List[int]) -> "Attribute":
        """Keep only elements at the specified indices."""
        s = pd.Series(self).iloc[index]
        self.clear()
        self.extend(s.tolist())
        return self

    def statistics(self) -> pd.Series:
        """Return descriptive statistics of the attribute values using Pandas."""
        return pd.Series(self).describe()

    def __repr__(self) -> str:
        return f"NAME: {self.name} | UNIT: {self.unit} | TYPE: {self.type} | LEN: {len(self)}"

    def set_type(self) -> "Attribute":
        """Recast all elements to the specified type."""
        if self.type:
            for i in range(len(self)):
                self[i] = str_to_num(self[i], self.type)
        return self


class Database(dict):
    """
    A custom dictionary mapping attribute names to Attribute columns.
    Behaves like a simple, lightweight DataFrame.
    """

    class DataAccessor:
        """Helper to mimic .iloc index-based rows/columns access."""

        def __init__(self, db: "Database"):
            self.db = db

        def show(self) -> Dict[str, Attribute]:
            return dict(self.db)

        def __getitem__(self, index: int) -> Dict[str, Any]:
            return self.db.get_row(index)

        def row(self, row_id: int) -> Dict[str, Any]:
            return self.db.get_row(row_id)

        def column(self, column_id: str) -> Attribute:
            return self.db.get_column(column_id)

    def __init__(
        self,
        name: Optional[str] = None,
        data: Optional[Dict[str, List[Any]]] = None,
        description: Optional[str] = None,
        attr_list: Optional[List[str]] = None,
        **kwargs: Any,
    ):
        """
        Initialize Database.

        Args:
            name: Database identifier.
            data: Initial dictionary mapping column names to data lists.
            description: Detailed database explanation.
            attr_list: Initial empty attribute column names.
        """
        super().__init__()
        self.name: Optional[str] = name
        self.description: Optional[str] = description
        self.db_filepath: str = "./omari.pkl"
        self.auto_refresh: bool = False
        self.__selected_att__: List[str] = []
        self._derived_specs: Dict[str, Dict[str, Any]] = {}

        if data:
            for key, val in data.items():
                self[key] = Attribute(name=key, data=val)

        if attr_list:
            for key in attr_list:
                if key not in self:
                    self[key] = Attribute(name=key, data=[])

        self.auto_refresh = True
        self["__db_index__"] = Attribute(
            name="__db_index__",
            data=list(range(self._get_max_column_length())),
            Type=int,
        )
        self._creation_date = datetime.datetime.now()

        # Parse configurations
        for key, val in kwargs.items():
            if key in self.__dict__:
                setattr(self, key, val)
            else:
                logger.warning(f"Database config '{key}' is not supported")

        self.get = self.DataAccessor(self)

    def validate(self) -> None:
        """Validate all Attribute columns inside the database."""
        for col_name, col in self.items():
            if isinstance(col, Attribute):
                col.validate()

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the Database contents to a Pandas DataFrame."""
        cols = {k: list(v) for k, v in self.items() if k != "__db_index__"}
        return pd.DataFrame(cols)

    def from_dataframe(self, df: pd.DataFrame) -> "Database":
        """Load database columns and rows from a Pandas DataFrame."""
        self.clear_all()
        for col in df.columns:
            # Infer standard python type from series
            col_type = float
            if df[col].dtype == bool:
                col_type = bool
            elif df[col].dtype in [int, "int64"]:
                col_type = int
            self[col] = Attribute(name=col, data=df[col].tolist(), Type=col_type)
        self.refresh_index()
        return self

    def _get_max_column_length(self) -> int:
        lengths = [len(val) for key, val in super().items() if key != "__db_index__"]
        return max(lengths) if lengths else 0

    def add_attribute(self, *attributes: Attribute) -> "Database":
        """Add attribute columns to the database."""
        for a in attributes:
            if isinstance(a, Attribute):
                self[a.name] = a
        return self

    def add_derived_attribute(
        self,
        name: str,
        function: Callable[[Dict[str, Any]], Any],
        dependencies: List[str],
    ) -> "Database":
        """Add a computed column evaluated from row values.

        ``function`` receives a mapping of column names to values for one row.
        Derived columns are recomputed when a source column is replaced.
        """
        if not isinstance(name, str) or not name:
            raise DatabaseError("Derived attribute name must be a non-empty string")
        if not callable(function):
            raise DatabaseError("Derived attribute function must be callable")
        if not dependencies or any(dep not in self or dep == "__db_index__" for dep in dependencies):
            raise DatabaseError(f"Derived attribute '{name}' has missing dependencies")
        if name in dependencies:
            raise DatabaseError(f"Derived attribute '{name}' cannot depend on itself")
        graph = {key: set(spec["dependencies"]) for key, spec in self._derived_specs.items()}
        graph[name] = set(dependencies)
        visiting: set = set()
        visited: set = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise DatabaseError("Circular derived attribute dependency detected")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph.get(node, set()):
                if dependency in graph:
                    visit(dependency)
            visiting.remove(node)
            visited.add(node)

        visit(name)
        self._derived_specs[name] = {"function": function, "dependencies": list(dependencies)}
        self[name] = self._evaluate_derived(name)
        return self

    def _evaluate_derived(self, name: str) -> Attribute:
        spec = self._derived_specs[name]
        row_count = self._get_max_column_length()
        values = [spec["function"](self.get_row(index)) for index in range(row_count)]
        if values and isinstance(values[0], (list, tuple, Attribute)):
            values = list(values[0])
        return Attribute(name=name, data=values, Type=None)

    def _refresh_derived(self) -> None:
        for name in self._derived_specs:
            super().__setitem__(name, self._evaluate_derived(name))
        if self._derived_specs:
            self.refresh_index()

    def create_attribute(self, *names: str) -> "Database":
        """Create empty attribute columns by name."""
        for name in names:
            if isinstance(name, str):
                self[name] = Attribute(name=name, data=[])
            else:
                logger.warning(f"Bad Attribute Name Entry [name:{name}]!")
        return self

    def __setitem__(self, name: str, value: Any) -> None:
        if not isinstance(value, (Attribute, list, tuple)):
            if len(self.keys()) != 0:
                raise TypeError(f"Bad Data Type assigned to Database column: {type(value)}")

        if not isinstance(value, Attribute):
            value = Attribute(name=name, data=list(value))

        super().__setitem__(name, value)
        if getattr(self, "auto_refresh", False):
            self.refresh_index()
            if name not in getattr(self, "_derived_specs", {}):
                self._refresh_derived()

    def derived_attributes(self) -> Dict[str, Dict[str, Any]]:
        """Return metadata for computed columns without exposing callables."""
        return {
            name: {"dependencies": list(spec["dependencies"])}
            for name, spec in self._derived_specs.items()
        }

    def refresh_index(self) -> "Database":
        """Align all column lengths, padding short ones and updating the database index."""
        max_len = self._get_max_column_length()
        if "__db_index__" not in self:
            super().__setitem__("__db_index__", Attribute(
                name="__db_index__",
                data=list(range(max_len)),
                Type=int,
            ))
        db_index = self["__db_index__"]

        if len(db_index) < max_len:
            for i in range(len(db_index), max_len):
                db_index.append(i)
        elif len(db_index) > max_len:
            db_index.resize(max_len)

        for name, col in super().items():
            if name != "__db_index__" and len(col) != max_len:
                col.resize(max_len)
        return self

    def __getitem__(self, name: str) -> Attribute:
        try:
            return super().__getitem__(name)
        except KeyError as e:
            raise KeyError(f"Attribute or index '{name}' not found in Database") from e

    def __getattr__(self, name: str) -> Any:
        if name in self.keys():
            return self[name]

        norm_name = name.lower()
        if norm_name in ["columns", "cols"]:
            return self.columns()
        if norm_name in ["iloc", "irow"]:
            return self.get
        if norm_name in ["index"]:
            return self["__db_index__"]
        if name in ["creation_date", "cdate"]:
            return self._creation_date
        if name == "ncols":
            return len(self.keys())
        if name == "nrows":
            return len(self)

        raise AttributeError(f"Database has no attribute '{name}'")

    def columns(self) -> Attribute:
        """Return the column names as an Attribute."""
        return Attribute("columns", data=list(self.keys()))

    def get_data(self, row: Optional[int] = None, column: Optional[Union[str, List[str]]] = None) -> Any:
        """Retrieve data cell(s) by row and column name(s)."""
        if isinstance(column, str):
            return self[column][row] if row is not None else self[column]
        elif isinstance(column, (list, tuple, set)):
            return {c: self.get_data(row, c) for c in column}
        elif column is None and row is not None:
            return self.get_row(row)
        return self

    def get_row(self, row_id: Union[int, List[int], Tuple[int]]) -> Any:
        """Get a single row as a dict, or multiple rows as a sub-database."""
        if isinstance(row_id, (list, tuple)):
            sub_data = {}
            for col_name, col in self.items():
                if col_name != "__db_index__":
                    sub_data[col_name] = [col[r] for r in row_id]
            return Database(name="", data=sub_data)
        elif isinstance(row_id, int):
            return {col_name: col[row_id] for col_name, col in self.items() if col_name != "__db_index__"}
        raise TypeError("row_id must be int, list, or tuple")

    def get_column(self, col_id: str) -> Attribute:
        """Get column vector."""
        return self[col_id]

    def __dir__(self) -> List[str]:
        return list(self.keys()) + ["iloc", "cols", "rows"] + list(self.__dict__.keys())

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "get" and not isinstance(value, self.DataAccessor):
            raise TypeError("Cannot override standard accessor class 'get'")
        if name in self:
            self.__setitem__(name, value)
        super().__setattr__(name, value)

    def import_from_file(
        self,
        filename: str = "omari_labeel.csv",
        option: str = "new",
        columns: Optional[List[str]] = None,
    ) -> "Database":
        """
        Import tabular data from a CSV or Excel file.
        """
        clear_db = option.lower() in ["new", "fresh"]
        append_db = option.lower() in ["append", "attach"]

        if clear_db:
            self.clear_all()

        try:
            if filename.endswith(".xlsx") or filename.endswith(".xls"):
                df = pd.read_excel(filename, usecols=columns)
            else:
                df = pd.read_csv(filename, usecols=columns)

            if append_db:
                current_df = self.to_dataframe()
                df = pd.concat([current_df, df], ignore_index=True)

            self.from_dataframe(df)
        except Exception as e:
            logger.error(f"Failed to import file {filename}: {e}")
            raise DatabaseError(f"Import failed from file '{filename}': {e}") from e
        return self

    def export_to_file(self, filename: str = "omari_labeel.csv") -> "Database":
        """Export database contents to a CSV or Excel file."""
        try:
            df = self.to_dataframe()
            if filename.endswith(".xlsx") or filename.endswith(".xls"):
                df.to_excel(filename, index=False)
            else:
                df.to_csv(filename, index=False)
        except Exception as e:
            logger.error(f"Failed to export to {filename}: {e}")
            raise DatabaseError(f"Export failed to file '{filename}': {e}") from e
        return self

    def to_parquet(self, filepath: str) -> "Database":
        """
        Export database contents to a Parquet file.
        """
        try:
            df = self.to_dataframe()
            df.to_parquet(filepath, index=False)
        except Exception as e:
            logger.error(f"Failed to export to Parquet '{filepath}': {e}")
            raise DatabaseError(f"Failed to export to Parquet '{filepath}': {e}") from e
        return self

    def read_parquet(self, filepath: str) -> "Database":
        """
        Import database from a Parquet file.
        """
        try:
            df = pd.read_parquet(filepath)
            self.from_dataframe(df)
        except Exception as e:
            logger.error(f"Failed to read Parquet '{filepath}': {e}")
            raise DatabaseError(f"Failed to read from Parquet '{filepath}': {e}") from e
        return self

    def select_attribute(self, *att: str) -> "Database":
        """Select a subset of active attributes to keep or display."""
        selected = []
        for a in att:
            if isinstance(a, (list, tuple, set)):
                for sub_a in a:
                    if sub_a in self:
                        selected.append(sub_a)
            else:
                if a in self:
                    selected.append(a)
        self.__selected_att__ = selected
        return self

    def rename_attribute(self, old_att: str, new_att: str) -> "Database":
        """Rename an attribute column in the database."""
        if old_att in self:
            val = self.pop(old_att)
            val.name = new_att
            self[new_att] = val
        return self

    def plot(self, att1: str, att2: str, hold: bool = False, fig_id: int = 1, **kwargs: Any) -> Any:
        """Plot one attribute against another using Matplotlib."""
        try:
            import matplotlib.pyplot as plt
        except ImportError as e:
            logger.error("matplotlib is required to use the plot method. Install it with: pip install matplotlib")
            raise ImportError("Matplotlib package is not installed.") from e

        fig = plt.figure(fig_id)
        plt.plot(self[att1], self[att2], 'b--o')
        plt.xlabel(att1 if not getattr(self[att1], "unit", None) else f"{att1} ({self[att1].unit})")
        plt.ylabel(att2 if not getattr(self[att2], "unit", None) else f"{att2} ({self[att2].unit})")
        plt.grid(True, which='both', axis='both')

        for key, val in kwargs.items():
            if key in plt.__dict__:
                plt.__dict__[key](val)

        if not hold:
            plt.show()
        return plt

    def export_variables(self, local_dict: Dict[str, Any]) -> None:
        """Export attribute columns directly into the caller's local namespace."""
        for col_name, col in self.items():
            if col_name != "__db_index__":
                local_dict[col_name] = col

    def save(self, filepath: Optional[str] = None) -> "Database":
        """Pickle the database object to disk."""
        target = filepath or self.db_filepath
        try:
            with open(target, "wb") as fid:
                pickle.dump(self, fid)
        except Exception as e:
            logger.error(f"Failed to save Database pickle to {target}: {e}")
            raise DatabaseError(f"Pickle save failed to path '{target}': {e}") from e
        return self

    def load(self, filepath: str) -> "Database":
        """Load database contents from a pickled file."""
        try:
            with open(filepath, "rb") as fid:
                loaded_db = pickle.load(fid)
                self.__dict__.update(loaded_db.__dict__)
                for col_name, col_data in loaded_db.items():
                    self[col_name] = col_data
        except Exception as e:
            logger.error(f"Failed to load Database pickle from {filepath}: {e}")
            raise DatabaseError(f"Pickle load failed from path '{filepath}': {e}") from e
        return self

    def update_row(self, row_id: int = 0, data: Optional[Dict[str, Any]] = None, add_new: bool = True) -> "Database":
        """Update or insert values at a specific row index."""
        if not data:
            return self

        for col_name, val in data.items():
            if col_name not in self:
                if add_new:
                    self[col_name] = Attribute(name=col_name, data=[])
                else:
                    raise KeyError(f"Column '{col_name}' does not exist and add_new is False")
            self[col_name][row_id] = val

        self.refresh_index()
        return self

    def size(self) -> Tuple[int, int]:
        """Return the (nrows, ncols) size of the database."""
        return len(self), len(self.keys())

    def append(self, other: "Database") -> "Database":
        """Append another Database's rows to this database."""
        is_same = other is self
        prev_len = len(self)

        for col_name, col in other.items():
            if col_name == "__db_index__":
                continue
            copied_col = copy.deepcopy(col)
            for idx, val in enumerate(copied_col):
                if is_same:
                    self[col_name][idx + prev_len] = val
                else:
                    self[col_name].append(val)

        self.refresh_index()
        return self

    def clear(self, attr_list: Optional[List[str]] = None) -> "Database":
        """Clear the data inside specific columns (or all columns if none specified)."""
        cols = attr_list if attr_list else list(self.keys())
        for c in cols:
            if c in self:
                self[c].clear()
        self.refresh_index()
        return self

    def clear_all(self) -> "Database":
        """Delete all columns and clear self completely."""
        keys = list(self.keys())
        for key in keys:
            del self[key]
        return self

    def __len__(self) -> int:
        return self._get_max_column_length()

    def to_json(self, filename: str = "omari.json") -> "Database":
        """Export database to a JSON file."""
        try:
            with open(filename, "w", encoding="utf-8") as fid:
                fid.write(self.toJSON())
        except Exception as e:
            logger.error(f"Failed to export to JSON {filename}: {e}")
            raise DatabaseError(f"JSON export failed to file '{filename}': {e}") from e
        return self

    def read_json(self, filename: str = "omari.json") -> "Database":
        """Import database from a JSON file."""
        try:
            with open(filename, "r", encoding="utf-8") as fid:
                raw = json.load(fid)
                self.name = raw.get("name")
                self.description = raw.get("description")
                # Load columns
                data_dict = raw.get("data", {})
                for col_name, col_data in data_dict.items():
                    self[col_name] = Attribute(name=col_name, data=col_data)
            self.refresh_index()
        except Exception as e:
            logger.error(f"Failed to load from JSON {filename}: {e}")
            raise DatabaseError(f"JSON import failed from file '{filename}': {e}") from e
        return self

    def toJSON(self) -> str:
        """Convert database structure to a serialized JSON string."""
        serialized = {
            "name": self.name,
            "description": self.description,
            "creation_date": str(self._creation_date),
            "data": {col_name: list(col) for col_name, col in self.items() if col_name != "__db_index__"},
        }
        return json.dumps(serialized, sort_keys=True, indent=4)

    def __getstate__(self) -> Dict[str, Any]:
        return self.__dict__

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)

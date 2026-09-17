"""
Database and Attribute structures for managing tabular parameters and cases.
Provides a pure Python list/dict subclass implementation backed internally by Pandas
for element-wise calculations, Excel/CSV/Parquet importing/exporting, and robust validation.
"""

import ast
import copy
import datetime
import inspect
import json
import logging
import math
from statistics import NormalDist
import operator
import os
import pickle
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd

from .exceptions import DatabaseError, SamplingError
from .sampler import OATConstructor
from .utils.file_io import evaluate_expression

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Normal:
    """Normal-distribution sampling specification for an ``Attribute``."""

    mean: float
    std: float

    def draw(self, size: int, rng: Any) -> List[float]:
        if not math.isfinite(self.mean) or not math.isfinite(self.std) or self.std < 0:
            raise SamplingError("Normal parameters must be finite and standard deviation non-negative")
        return rng.normal(self.mean, self.std, size).tolist()


@dataclass(frozen=True)
class Uniform:
    """Uniform-distribution sampling specification for an ``Attribute``."""

    low: float
    high: float

    def draw(self, size: int, rng: Any) -> List[float]:
        if not math.isfinite(self.low) or not math.isfinite(self.high) or self.low > self.high:
            raise SamplingError("Uniform bounds must be finite and ordered")
        return rng.uniform(self.low, self.high, size).tolist()


@dataclass(frozen=True)
class OAT:
    """One-at-a-time values for an ``Attribute`` in a database design."""

    values: Sequence[Any]


@dataclass(frozen=True)
class Derived:
    """Reactive expression or row callback.

    Expressions infer dependencies. Callbacks declare dependencies for derived
    chains; omitted dependencies default to all non-derived input columns.
    """

    function: Union[str, Callable[[Dict[str, Any]], Any]]
    dependencies: Optional[Sequence[str]] = None


@dataclass(frozen=True)
class Constant:
    """Scalar constant repeated for every row of an ``Attribute``."""

    value: Any


def _extract_expression_dependencies(expr: str, available_columns: Sequence[str]) -> List[str]:
    """Extract column names referenced in a mathematical expression."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise DatabaseError(f"Invalid syntax in derived expression '{expr}': {exc}") from exc

    available_set = set(available_columns)
    deps: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id in available_set and node.id not in deps and node.id != "__db_index__":
                deps.append(node.id)
    return deps


def _invoke_db_callback(func: Callable[..., Any], db: "Database", index: Optional[int] = None) -> Any:
    """Invoke a database-context callback supporting (database, index=None), (database, index), or (database)."""
    try:
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        param_names = [p.name for p in params]
        has_varkw = any(p.kind == p.VAR_KEYWORD for p in params)
        has_varpos = any(p.kind == p.VAR_POSITIONAL for p in params)

        if "index" in param_names or has_varkw:
            return func(db, index=index)
        if len(params) >= 2 or has_varpos:
            return func(db, index)
        return func(db)
    except (TypeError, ValueError):
        if index is not None:
            try:
                return func(db, index=index)
            except TypeError:
                try:
                    return func(db, index)
                except TypeError:
                    return func(db)
        else:
            try:
                return func(db, index=None)
            except TypeError:
                try:
                    return func(db)
                except TypeError:
                    return func(db, None)



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

    Attributes:
        name (str): Column attribute name identifier.
        unit (str, optional): Physical or mathematical unit of measurement (e.g. "kg/m3", "K").
        description (str, optional): Human-readable summary of what this attribute represents.
        type (callable, optional): Target type caster for items in the column (e.g. float, int).
        sampling (Normal, Uniform, OAT, Derived, or Constant, optional): Deferred sampling specification.
    """

    def __init__(
        self,
        name: str,
        data: Optional[List[Any]] = None,
        description: Optional[str] = None,
        Type: Optional[Callable[[Any], Any]] = float,
        unit: Optional[str] = None,
        sampling: Optional[Any] = None,
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
            sampling: Deferred distribution, OAT, constant, or derived specification;
                mutually exclusive with data. Materialized by Database(attributes=...).
        """
        if not isinstance(name, str) or not name.strip():
            raise DatabaseError("Attribute name must be a non-empty string")
        super().__init__()
        self.name: str = name
        self.description: Optional[str] = description
        self.type: Optional[Callable[[Any], Any]] = Type
        self.unit: Optional[str] = unit
        if data is not None and sampling is not None:
            raise DatabaseError(f"Attribute '{name}' cannot specify both data and sampling")
        self.sampling: Optional[Any] = sampling
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

    def tolist(self) -> List[Any]:
        """Convert Attribute to a standard Python list."""
        return list(self)

    def to_list(self) -> List[Any]:
        """Alias for tolist."""
        return list(self)

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

    Attributes:
        name (str, optional): Database identifier name.
        description (str, optional): Summary description of the database.
        db_filepath (str): Default path used when saving or loading the database.
        auto_refresh (bool): Whether derived expression columns automatically re-evaluate upon query.
        get (DataAccessor): Helper interface providing index/row access (.get[row_index] or .get.row(id)).
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
        attributes: Optional[Sequence[Attribute]] = None,
        n: Optional[int] = None,
        seed: Optional[int] = None,
        method: str = "monte_carlo",
        random_reuse: str = "independent",
        row_filter: Optional[callable] = None,
        max_rejections: Optional[int] = None,
        **kwargs: Any,
    ):
        """
        Initialize Database.

        Args:
            name: Database identifier.
            data: Initial dictionary mapping column names to data lists.
            description: Detailed database explanation.
            attr_list: Initial empty attribute column names.
            attributes: Columns with data or deferred sampling specifications.
            n: Total random samples, or repetitions per OAT design row (default 1).
            seed: Seed for built-in distributions and custom draw(size, rng) samplers.
            method: "monte_carlo" (default) or "lhs"; LHS stratifies each OAT group.
            random_reuse: "independent" (default) or "shared" across OAT rows.
            row_filter: Optional callable(row: Dict) -> bool for row-by-row validation.
                       Returns True to keep row, False to reject and resample.
            max_rejections: Maximum consecutive rejections before error (default n*100).
        """
        super().__init__()
        self.name: Optional[str] = name
        self.description: Optional[str] = description
        self.db_filepath: str = "./omari.pkl"
        self.auto_refresh: bool = False
        self.__selected_att__: List[str] = []
        self._derived_specs: Dict[str, Dict[str, Any]] = {}

        if attributes is not None and data is not None:
            raise DatabaseError("Specify either data or attributes when constructing a Database, not both")
        if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 1):
            raise DatabaseError("Sample count n must be a positive integer")

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

        # Store sampling metadata
        self.row_filter = row_filter
        self.max_rejections = max_rejections
        self.sampling_stats: Dict[str, Any] = {}

        # Parse configurations
        for key, val in kwargs.items():
            if key in self.__dict__:
                setattr(self, key, val)
            else:
                logger.warning(f"Database config '{key}' is not supported")

        self.get = self.DataAccessor(self)

        if attributes is not None:
            id_start = kwargs.pop('id_start', 1)
            index_placement = kwargs.pop('index_placement', 'end')
            include_indices = kwargs.pop('include_indices', True)
            self._construct_from_attributes(
                attributes, n=n, seed=seed, method=method, random_reuse=random_reuse,
                id_start=id_start, index_placement=index_placement, include_indices=include_indices,
                row_filter=row_filter, max_rejections=max_rejections
            )

    def _apply_row_filter_during_sampling(
        self, attrs: List[Attribute], deferred: List[Attribute], dependencies: Dict[str, List[str]],
        generated: Dict[str, List[Any]], rng: Any, row_count: int, row_filter: callable,
        max_rejections: Optional[int]
    ) -> None:
        """Apply row filter during attribute addition by filtering Database columns in-place.

        This works on already-added columns by cycling through rows and filtering valid ones.
        The Database already has all rows added; we filter them down to row_count valid rows.
        """
        if max_rejections is None:
            max_rejections = row_count * 100

        stats = {
            "total_attempts": 0,
            "total_accepted": 0,
            "total_rejected": 0,
            "acceptance_rate": 0.0,
        }

        # Get all columns currently in database (non-derived)
        valid_indices = []
        current_length = self._get_max_column_length()

        for row_idx in range(current_length):
            row = self.get_row(row_idx)
            stats["total_attempts"] += 1

            try:
                is_valid = row_filter(row)
            except Exception as exc:
                logger.debug(f"Row filter evaluation failed for row {row_idx}: {exc}")
                is_valid = False

            if is_valid:
                valid_indices.append(row_idx)
                stats["total_accepted"] += 1
            else:
                stats["total_rejected"] += 1

        # If we don't have enough valid rows, warn and suggest n adjustment
        if stats["total_accepted"] < row_count:
            acceptance_rate = stats["total_accepted"] / stats["total_attempts"]
            suggested_n = int(row_count / acceptance_rate) if acceptance_rate > 0 else row_count * 2
            logger.warning(
                f"Row filter: only {stats['total_accepted']}/{row_count} valid rows after filtering "
                f"({acceptance_rate:.1%} acceptance rate). "
                f"Got {stats['total_accepted']} valid rows instead. "
                f"To get exactly {row_count} rows: use n={suggested_n} (or relax filter constraints)."
            )

        if stats["total_accepted"] == 0:
            raise DatabaseError("Row filter rejected all rows; no valid samples generated")

        # Keep only valid rows by filtering all columns
        for col_name, col_attr in list(self.items()):
            if col_name == "__db_index__" or col_name == "__id__":
                continue
            if isinstance(col_attr, Attribute):
                filtered_data = [col_attr[idx] for idx in valid_indices]
                col_attr[:] = filtered_data

        # Update __id__ and __db_index__ if they exist
        if "__id__" in self:
            id_attr = self["__id__"]
            filtered_ids = [id_attr[idx] for idx in valid_indices]
            id_attr[:] = filtered_ids

        if "__db_index__" in self:
            index_attr = self["__db_index__"]
            filtered_indices = list(range(len(valid_indices)))
            index_attr[:] = filtered_indices

        self.refresh_index()

        stats["acceptance_rate"] = (
            stats["total_accepted"] / stats["total_attempts"]
            if stats["total_attempts"] > 0 else 0.0
        )
        self.sampling_stats = stats

    def _apply_row_filter(
        self, generated: Dict[str, List[Any]], attrs: List[Attribute], deferred: List[Attribute],
        dependencies: Dict[str, List[str]], rng: Any, method: str, random_reuse: str,
        row_count: int, repeats: int, design: Dict[str, List[Any]], oat_attrs: List[Attribute],
        row_filter: callable, max_rejections: Optional[int]
    ) -> tuple:
        """Apply row-by-row validation filtering with rejection sampling.

        Returns:
            Tuple of (filtered_generated, stats_dict)
        """
        if max_rejections is None:
            max_rejections = row_count * 100

        stats = {
            "total_attempts": 0,
            "total_accepted": 0,
            "total_rejected": 0,
            "acceptance_rate": 0.0,
            "rejection_reasons": {}
        }

        filtered_generated: Dict[str, List[Any]] = {k: [] for k in generated.keys()}
        current_row_idx = 0
        consecutive_rejections = 0

        while len(filtered_generated[list(filtered_generated.keys())[0]]) < row_count:
            stats["total_attempts"] += 1

            # Generate one row worth of data
            row_data: Dict[str, Any] = {}

            # Extract current row from generated data
            for attr_name, values in generated.items():
                if current_row_idx < len(values):
                    row_data[attr_name] = values[current_row_idx]

            # Evaluate Derived attributes for this row
            try:
                for attr in deferred:
                    spec = attr.sampling
                    deps = dependencies[attr.name]

                    if isinstance(spec.function, str):
                        # Evaluate expression
                        result = eval(spec.function, {"__builtins__": {}}, row_data)
                    elif callable(spec.function):
                        # Call function with row dict
                        result = spec.function(row_data)
                    else:
                        result = spec.function

                    row_data[attr.name] = result
            except Exception as exc:
                logger.debug(f"Derived attribute evaluation failed for row: {exc}")
                consecutive_rejections += 1
                if consecutive_rejections > max_rejections:
                    raise DatabaseError(
                        f"Row filter: {consecutive_rejections} consecutive rejections; "
                        f"check filter constraints or increase max_rejections"
                    )
                current_row_idx = (current_row_idx + 1) % row_count
                continue

            # Apply row filter
            try:
                is_valid = row_filter(row_data)
            except Exception as exc:
                logger.debug(f"Row filter evaluation failed: {exc}")
                is_valid = False

            if is_valid:
                # Keep this row
                for attr_name, value in row_data.items():
                    if attr_name in filtered_generated:
                        filtered_generated[attr_name].append(value)
                consecutive_rejections = 0
                stats["total_accepted"] += 1
            else:
                # Reject and try next row
                stats["total_rejected"] += 1
                consecutive_rejections += 1
                if consecutive_rejections > max_rejections:
                    raise DatabaseError(
                        f"Row filter: {consecutive_rejections} consecutive rejections; "
                        f"check filter constraints or increase max_rejections"
                    )

            current_row_idx = (current_row_idx + 1) % row_count

        stats["acceptance_rate"] = (
            stats["total_accepted"] / stats["total_attempts"]
            if stats["total_attempts"] > 0 else 0.0
        )

        return filtered_generated, stats

    def _apply_row_filter_to_database(self, row_filter: callable, target_row_count: int, max_rejections: Optional[int]) -> None:
        """Apply row-by-row validation, keeping target_row_count valid rows.

        This works by iterating through all rows in the current database and filtering
        those that don't pass the filter. Tracks acceptance statistics.
        """
        if max_rejections is None:
            max_rejections = target_row_count * 100

        stats = {
            "total_attempts": 0,
            "total_accepted": 0,
            "total_rejected": 0,
            "acceptance_rate": 0.0,
        }

        # Collect rows that pass the filter
        valid_indices = []
        current_length = self._get_max_column_length()

        for row_idx in range(current_length):
            row = self.get_row(row_idx)
            stats["total_attempts"] += 1

            try:
                is_valid = row_filter(row)
            except Exception as exc:
                logger.debug(f"Row filter evaluation failed for row {row_idx}: {exc}")
                is_valid = False

            if is_valid:
                valid_indices.append(row_idx)
                stats["total_accepted"] += 1
            else:
                stats["total_rejected"] += 1

        # If we have exactly the right number or more, keep only target_row_count
        if stats["total_accepted"] >= target_row_count:
            valid_indices = valid_indices[:target_row_count]
            stats["total_accepted"] = target_row_count
        else:
            # Not enough valid rows - warn but keep what we have
            logger.warning(
                f"Row filter: only {stats['total_accepted']}/{target_row_count} valid rows "
                f"after filtering. Keeping all {stats['total_accepted']} valid rows. "
                f"(Acceptance rate: {stats['total_accepted']/stats['total_attempts']:.1%})"
            )

        if stats["total_accepted"] == 0:
            raise DatabaseError("Row filter rejected all rows; no valid samples generated")

        # Filter all columns to keep only valid rows
        for col_name, col_attr in list(self.items()):
            if col_name == "__db_index__":
                continue
            if isinstance(col_attr, Attribute):
                filtered_data = [col_attr[idx] for idx in valid_indices]
                col_attr[:] = filtered_data

        # Recalculate derived attributes on filtered data
        self.refresh_index()

        stats["acceptance_rate"] = (
            stats["total_accepted"] / stats["total_attempts"]
            if stats["total_attempts"] > 0 else 0.0
        )
        self.sampling_stats = stats

    def _construct_from_attributes(
        self, attributes: Sequence[Attribute], *, n: Optional[int], seed: Optional[int],
        method: str, random_reuse: str, id_start: int = 1, index_placement: str = 'end',
        include_indices: bool = True, row_filter: Optional[callable] = None,
        max_rejections: Optional[int] = None
    ) -> None:
        """Materialize attribute data and sampling specifications as aligned rows.

        Args:
            id_start: Starting value for row IDs (0 or 1, default 1)
            index_placement: Where to place OAT indices - 'end' (default) or 'interleaved'
            include_indices: Whether to include row ID and OAT indices (default True)
            row_filter: Optional callable for row-by-row acceptance/rejection
            max_rejections: Maximum consecutive rejections before error
        """
        if method not in ("monte_carlo", "lhs"):
            raise DatabaseError("Sampling method must be 'monte_carlo' or 'lhs'")
        if random_reuse not in ("independent", "shared"):
            raise DatabaseError("random_reuse must be 'independent' or 'shared'")
        attrs = list(attributes)
        if any(not isinstance(attr, Attribute) for attr in attrs):
            raise DatabaseError("attributes must contain only Attribute instances")
        names = [attr.name for attr in attrs]
        if any(not isinstance(name, str) or not name.strip() or name != name.strip()
               or name == "__db_index__" for name in names):
            raise DatabaseError("Attribute names must be non-empty, trimmed, and not __db_index__")
        if len(names) != len(set(names)):
            raise DatabaseError("Attribute names must be unique during database construction")

        oat_attrs = [attr for attr in attrs if isinstance(attr.sampling, OAT)]
        design: Dict[str, List[Any]] = {}
        oat_indices: Dict[str, List[int]] = {}
        if oat_attrs:
            constructor = OATConstructor()
            constructor.add_case({attr.name: list(attr.sampling.values) for attr in oat_attrs})
            full_design = constructor.construct()
            design = {attr.name: full_design[attr.name] for attr in oat_attrs}
            oat_indices = {f"__{attr.name}_index__": full_design[f"__{attr.name}_index__"]
                          for attr in oat_attrs if f"__{attr.name}_index__" in full_design}
            repeats = n if n is not None else 1
            row_count = len(next(iter(design.values()))) * repeats
        else:
            row_count = n if n is not None else 1
            repeats = 1

        rng = np.random.default_rng(seed)
        generated: Dict[str, List[Any]] = {}
        deferred: List[Attribute] = []
        for attr in attrs:
            spec = attr.sampling
            if isinstance(spec, Derived):
                deferred.append(attr)
                continue
            if isinstance(spec, OAT):
                values = [value for value in design[attr.name] for _ in range(repeats)]
            elif isinstance(spec, Constant):
                values = [spec.value] * row_count
            elif spec is not None:
                block_size = repeats if oat_attrs else row_count
                block_count = row_count // block_size
                values = []
                for block in range(block_count):
                    if block and random_reuse == "shared":
                        values.extend(values[:block_size])
                        continue
                    try:
                        if method == "lhs":
                            probabilities = (np.arange(block_size) + rng.random(block_size)) / block_size
                            rng.shuffle(probabilities)
                            probabilities = np.clip(probabilities, np.nextafter(0., 1.), np.nextafter(1., 0.))
                            if isinstance(spec, Uniform):
                                spec.draw(0, rng)  # Validate distribution parameters.
                                draws = spec.low + probabilities * (spec.high - spec.low)
                            elif isinstance(spec, Normal):
                                spec.draw(0, rng)
                                draws = [spec.mean + spec.std * NormalDist().inv_cdf(float(p))
                                         for p in probabilities]
                            elif callable(getattr(spec, "ppf", None)):
                                draws = spec.ppf(probabilities)
                            else:
                                raise DatabaseError("LHS requires Normal, Uniform, or a sampler with ppf(probabilities)")
                        elif callable(getattr(spec, "draw", None)):
                            draws = spec.draw(block_size, rng)
                        elif hasattr(spec, "get_random_sample"):
                            draws = spec.get_random_sample(block_size)
                        elif callable(spec):
                            draws = spec(block_size)
                        else:
                            raise DatabaseError("Unsupported sampling specification")
                        if hasattr(draws, "tolist"):
                            draws = draws.tolist()
                        if isinstance(draws, (str, bytes)) or not isinstance(draws, Sequence):
                            draws = [draws]
                        if len(draws) != block_size:
                            raise DatabaseError(f"Sampler returned {len(draws)} values; expected {block_size}")
                        values.extend(draws)
                    except Exception as exc:
                        raise DatabaseError(f"Sampling attribute '{attr.name}' failed: {exc}") from exc
            elif attr:
                source = list(attr)
                if len(source) == 1:
                    values = source * row_count
                elif len(source) == row_count:
                    values = source
                else:
                    raise DatabaseError(
                        f"Data for attribute '{attr.name}' has {len(source)} values; expected 1 or {row_count}"
                    )
            else:
                raise DatabaseError(
                    f"Attribute '{attr.name}' must provide data or a sampling specification"
                )
            generated[attr.name] = list(values)

        # Prepare OAT indices (replicated for each random replicate if needed)
        replicated_oat_indices: Dict[str, List[int]] = {}
        if include_indices and oat_indices:
            if repeats > 1:
                for oat_col_name, base_indices in oat_indices.items():
                    replicated_oat_indices[oat_col_name] = [idx for idx in base_indices for _ in range(repeats)]
            else:
                replicated_oat_indices = oat_indices

        # Add row ID first if include_indices (will appear at beginning)
        if include_indices:
            id_values = list(range(id_start, id_start + row_count))
            self['__id__'] = Attribute(name="__id__", data=id_values,
                                       description=f"Row ID ({id_start}-indexed)", Type=int)

        # Handle index placement
        if include_indices and index_placement == 'interleaved':
            # Interleave: attribute → __attr_index__ → next attribute
            for attr in attrs:
                if isinstance(attr.sampling, Derived):
                    continue
                self.add_attribute(Attribute(name=attr.name, data=generated[attr.name],
                                             description=attr.description, Type=attr.type, unit=attr.unit))

                oat_col_name = f"__{attr.name}_index__"
                if oat_col_name in replicated_oat_indices:
                    self.add_attribute(Attribute(name=oat_col_name, data=replicated_oat_indices[oat_col_name],
                                                 description=f"OAT index for {attr.name} (0-indexed)", Type=int))
        else:
            # Default: all attributes, then all indices
            for attr in attrs:
                if isinstance(attr.sampling, Derived):
                    continue
                self.add_attribute(Attribute(name=attr.name, data=generated[attr.name],
                                             description=attr.description, Type=attr.type, unit=attr.unit))

            # Add OAT index columns at the end if not interleaved
            if include_indices:
                for oat_col_name, indices in replicated_oat_indices.items():
                    self.add_attribute(Attribute(name=oat_col_name, data=indices,
                                                 description=f"OAT index for {oat_col_name[2:-7]} (0-indexed)", Type=int))

        # Resolve dependencies before registering with the existing reactive system.
        base_names = list(generated)
        dependencies: Dict[str, List[str]] = {}
        for attr in deferred:
            spec = attr.sampling
            if spec.dependencies is not None:
                deps = list(spec.dependencies)
            elif isinstance(spec.function, str):
                deps = _extract_expression_dependencies(spec.function, names)
            else:
                # Preserve legacy row-callable construction; chained callables declare dependencies.
                deps = list(base_names)
            missing = [dep for dep in deps if dep not in names]
            if missing:
                raise DatabaseError(f"Derived attribute '{attr.name}' has missing dependencies: {missing}")
            dependencies[attr.name] = deps

        pending = list(deferred)
        while pending:
            ready = [attr for attr in pending
                     if all(dep in self for dep in dependencies[attr.name])]
            if not ready:
                raise DatabaseError("Circular or unresolved derived dependencies: " +
                                    ", ".join(attr.name for attr in pending))
            for attr in ready:
                self.add_derived_attribute(attr.name, attr.sampling.function,
                                           dependencies=dependencies[attr.name],
                                           unit=attr.unit, description=attr.description, Type=attr.type)
                pending = [item for item in pending if item is not attr]

        # Apply row-by-row validation filter if provided (use incremental generation, not post-hoc filtering)
        if row_filter is not None:
            self._apply_row_filter_during_sampling(
                attrs=attrs, deferred=deferred, dependencies=dependencies, generated=generated,
                rng=rng, row_count=row_count, row_filter=row_filter, max_rejections=max_rejections
            )

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

    def add_sampled_attribute(
        self,
        name: str,
        sampler: Union[Sequence[Any], Callable[[int], Sequence[Any]], Any],
        *,
        size: int = 1,
        description: Optional[str] = None,
        Type: Optional[Callable[[Any], Any]] = float,
        unit: Optional[str] = None,
    ) -> "Database":
        """Add one column generated by its own sampler.

        ``sampler`` may be a sequence, a callable accepting ``size``, or an
        object exposing ``get_random_sample(size)``. This lets each attribute
        use an independent sampling strategy while preserving row alignment.
        """
        if not isinstance(name, str) or not name.strip():
            raise DatabaseError("Sampled attribute name must be a non-empty string")
        if size < 1:
            raise DatabaseError("Sampled attribute size must be positive")
        try:
            if hasattr(sampler, "get_random_sample"):
                values = sampler.get_random_sample(size)
            elif callable(sampler):
                values = sampler(size)
            else:
                values = sampler
        except Exception as exc:
            raise DatabaseError(f"Sampling attribute '{name}' failed: {exc}") from exc

        if hasattr(values, "tolist"):
            values = values.tolist()
        elif isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            values = [values]
        values_list = list(values)
        if len(values_list) != size:
            raise DatabaseError(
                f"Sampler for attribute '{name}' returned {len(values_list)} values; expected {size}"
            )
        return self.add_attribute(
            Attribute(name=name.strip(), data=values_list, description=description, Type=Type, unit=unit)
        )

    def add_derived_attribute(
        self,
        name: str,
        function: Union[str, Callable[[Dict[str, Any]], Any], Callable[..., Any]],
        dependencies: Optional[Sequence[str]] = None,
        *,
        context: str = "row",
        unit: Optional[str] = None,
        description: Optional[str] = None,
        Type: Optional[Callable[[Any], Any]] = None,
        vectorized: bool = False,
    ) -> "Database":
        """Add a computed column evaluated from existing database attributes.

        Supports mathematical string expressions (e.g. ``"y + 1"``, ``"2 * a + sin(b)"``)
        or callable functions. When ``context='row'`` (default), the function receives a
        row dictionary ``{col: val}``. When ``context='database'``, the function receives
        ``(database, index=None)`` allowing global, lagged, or cross-row queries.

        Args:
            name: Column name for the derived attribute.
            function: String expression or callable function.
            dependencies: Optional sequence of column names the expression depends on.
                For ``context='database'``, dependencies are optional; when omitted,
                the callback is refreshed conservatively on any database change.
            context: Evaluation context mode, either ``"row"`` (default) or ``"database"``.
            unit: Optional physical unit metadata string.
            description: Optional descriptive text.
            Type: Optional data type constructor.
            vectorized: If True, evaluates function vectorially over full attribute columns.

        Returns:
            Self instance with the computed attribute added.

        Raises:
            DatabaseError: If context is invalid, dependencies are missing/invalid/circular,
                or evaluation fails.
        """
        if not isinstance(name, str) or not name.strip():
            raise DatabaseError("Derived attribute name must be a non-empty string")

        if context not in ("row", "database"):
            raise DatabaseError(f"Derived attribute context must be 'row' or 'database', got '{context}'")

        clean_name = name.strip()
        expr_str: Optional[str] = None
        func_callable: Optional[Callable[..., Any]] = None
        dynamic_dependencies = False
        deps_list: List[str] = []

        if isinstance(function, str):
            expr_str = function.strip()
            if not expr_str:
                raise DatabaseError("Derived attribute expression string must not be empty")
            if dependencies is None:
                deps_list = _extract_expression_dependencies(expr_str, list(self.keys()))
            else:
                deps_list = list(dependencies)
        elif callable(function):
            func_callable = function
            if context == "row":
                if dependencies is None:
                    raise DatabaseError(
                        f"Explicit dependencies list is required when creating derived attribute '{clean_name}' with context='row' and a callable"
                    )
                deps_list = list(dependencies)
            else:
                # context == "database"
                if dependencies is None:
                    dynamic_dependencies = True
                    deps_list = []
                else:
                    deps_list = list(dependencies)
        else:
            raise DatabaseError("Derived attribute function must be a string expression or callable")

        if not dynamic_dependencies:
            if not deps_list and not (isinstance(function, str) and expr_str):
                raise DatabaseError(f"Derived attribute '{clean_name}' has missing dependencies")

            missing_deps = [dep for dep in deps_list if dep not in self or dep == "__db_index__"]
            if missing_deps:
                raise DatabaseError(
                    f"Derived attribute '{clean_name}' has missing dependencies: {', '.join(missing_deps)}"
                )

            if clean_name in deps_list:
                raise DatabaseError(f"Derived attribute '{clean_name}' cannot depend on itself")

            graph = {
                key: set(spec["dependencies"])
                for key, spec in self._derived_specs.items()
                if not spec.get("dynamic_dependencies", False)
            }
            graph[clean_name] = set(deps_list)

            visiting: Set[str] = set()
            visited: Set[str] = set()

            def visit(node: str) -> None:
                if node in visiting:
                    raise DatabaseError(
                        f"Circular derived attribute dependency detected involving '{node}'"
                    )
                if node in visited:
                    return
                visiting.add(node)
                for dependency in graph.get(node, set()):
                    if dependency in graph:
                        visit(dependency)
                visiting.remove(node)
                visited.add(node)

            visit(clean_name)

        self._derived_specs[clean_name] = {
            "function": func_callable,
            "expression": expr_str,
            "dependencies": deps_list,
            "declared_dependencies": list(dependencies) if dependencies is not None else None,
            "context": context,
            "dynamic_dependencies": dynamic_dependencies,
            "unit": unit,
            "description": description,
            "Type": Type,
            "vectorized": vectorized,
        }

        self[clean_name] = self._evaluate_derived(clean_name)
        return self

    def _get_topological_derived_order(self) -> List[str]:
        """Compute topological evaluation order of derived attributes."""
        order: List[str] = []
        visited: Set[str] = set()
        visiting: Set[str] = set()

        def dfs(node: str) -> None:
            if node in visited:
                return
            visiting.add(node)
            spec = self._derived_specs.get(node)
            if spec and spec.get("dependencies"):
                for dep in spec["dependencies"]:
                    if dep in self._derived_specs and dep not in visited:
                        dfs(dep)
            visiting.remove(node)
            visited.add(node)
            order.append(node)

        # 1. Statically dependent derived attributes in dependency order
        for node, spec in self._derived_specs.items():
            if not spec.get("dynamic_dependencies", False) and node not in visited:
                dfs(node)

        # 2. Dynamically dependent database-context derived attributes in registration order
        for node, spec in self._derived_specs.items():
            if spec.get("dynamic_dependencies", False) and node not in visited:
                dfs(node)

        return order

    def _evaluate_derived(self, name: str) -> Attribute:
        """Evaluate a single derived attribute across all rows."""
        spec = self._derived_specs[name]
        row_count = self._get_max_column_length()
        context_mode = spec.get("context", "row")

        try:
            if spec.get("vectorized", False):
                if spec["expression"] is not None:
                    context = {dep: pd.Series(self[dep]) for dep in spec["dependencies"]}
                    res = evaluate_expression(spec["expression"], context)
                    if hasattr(res, "tolist"):
                        values = res.tolist()
                    elif isinstance(res, (list, tuple)):
                        values = list(res)
                    else:
                        values = [res] * row_count
                else:
                    if context_mode == "database":
                        res = _invoke_db_callback(spec["function"], self, index=None)
                    else:
                        res = spec["function"](self)
                    if hasattr(res, "tolist"):
                        values = res.tolist()
                    elif isinstance(res, (list, tuple)):
                        values = list(res)
                    else:
                        values = [res] * row_count
                if len(values) != row_count and row_count > 0:
                    raise DatabaseError(
                        f"Derived attribute '{name}' evaluated to {len(values)} values, expected {row_count}"
                    )
            else:
                values = []
                expr = spec["expression"]
                func = spec["function"]
                for index in range(row_count):
                    if expr is not None:
                        row = self.get_row(index)
                        val = evaluate_expression(expr, row)
                    else:
                        if context_mode == "database":
                            val = _invoke_db_callback(func, self, index=index)
                        else:
                            row = self.get_row(index)
                            val = func(row)
                    values.append(val)
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(
                f"Evaluation of derived attribute '{name}' failed: {exc}"
            ) from exc

        return Attribute(
            name=name,
            data=values,
            unit=spec.get("unit"),
            description=spec.get("description"),
            Type=spec.get("Type"),
        )

    def _refresh_derived(self) -> None:
        """Recompute all derived attributes in topological dependency order."""
        for name in self._get_topological_derived_order():
            super().__setitem__(name, self._evaluate_derived(name))
        if self._derived_specs:
            self.refresh_index()

    def remove_derived_attribute(self, name: str, drop_column: bool = True) -> "Database":
        """Remove a derived attribute definition and optionally drop its column.

        Args:
            name: Name of the derived attribute.
            drop_column: If True, remove the column from the database.

        Raises:
            DatabaseError: If another derived attribute depends on this one.
        """
        if name not in self._derived_specs:
            raise DatabaseError(f"'{name}' is not a registered derived attribute")

        for other_name, spec in self._derived_specs.items():
            deps = spec.get("dependencies")
            if other_name != name and deps and name in deps:
                raise DatabaseError(
                    f"Cannot remove derived attribute '{name}' because '{other_name}' depends on it"
                )

        del self._derived_specs[name]
        if drop_column and name in self:
            del self[name]
        return self

    def create_attribute(self, *names: str) -> "Database":
        """Create empty attribute columns by name."""
        for name in names:
            if isinstance(name, str):
                self[name] = Attribute(name=name, data=[])
            else:
                logger.warning(f"Bad Attribute Name Entry [name:{name}]!")
        return self

    def __setitem__(self, name: str, value: Any) -> None:
        if not isinstance(name, str) or not name.strip():
            raise DatabaseError("Database column name must be a non-empty string")
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

    def __delitem__(self, key: str) -> None:
        if getattr(self, "_derived_specs", None):
            for name, spec in self._derived_specs.items():
                deps = spec.get("dependencies")
                if name != key and deps and key in deps:
                    raise DatabaseError(
                        f"Cannot delete column '{key}' because derived attribute '{name}' depends on it"
                    )
            if key in self._derived_specs:
                del self._derived_specs[key]
        super().__delitem__(key)

    def derived_attributes(self) -> Dict[str, Dict[str, Any]]:
        """Return metadata for computed columns without exposing callables."""
        return {
            name: {
                "dependencies": list(spec["dependencies"]) if not spec.get("dynamic_dependencies", False) else None,
                "expression": spec.get("expression"),
                "unit": spec.get("unit"),
                "description": spec.get("description"),
                "vectorized": spec.get("vectorized", False),
                "context": spec.get("context", "row"),
                "dynamic_dependencies": spec.get("dynamic_dependencies", False),
            }
            for name, spec in self._derived_specs.items()
        }

    def set_row(self, row_id: int, values: Dict[str, Any]) -> "Database":
        """Update values in a single row by index and recompute derived columns.

        Args:
            row_id: Row index to update.
            values: Dictionary mapping column names to new values.
        """
        for col_name, val in values.items():
            if col_name not in self:
                self[col_name] = Attribute(name=col_name, data=[])
            self[col_name][row_id] = val
        self.refresh_index()
        self._refresh_derived()
        return self

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
        if norm_name in ["rows"]:
            return [self.get_row(i) for i in range(len(self))]
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

    def save(self, filepath: Optional[str] = None, format: str = "csv") -> "Database":
        """Export database data to a portable format (CSV, JSON, Parquet).

        Args:
            filepath: Output file path. Auto-detects format from extension if not specified.
            format: Export format ('csv', 'json', 'parquet'). Defaults to 'csv'.

        Returns:
            Self instance.

        Note:
            Exports data only (not functions/metadata). Derived attributes are
            materialized as data columns. Use this instead of pickle to avoid
            issues with lambda functions or unpicklable objects.
        """
        target = filepath or self.db_filepath

        if filepath:
            ext = filepath.lower().split('.')[-1]
            if ext in ['csv']:
                format = 'csv'
            elif ext in ['json']:
                format = 'json'
            elif ext in ['parquet', 'pq']:
                format = 'parquet'

        try:
            if format.lower() == 'csv':
                self.export_to_file(target)
            elif format.lower() == 'json':
                self.to_json(target)
            elif format.lower() == 'parquet':
                self.to_parquet(target)
            else:
                raise DatabaseError(f"Unsupported format: {format}. Use 'csv', 'json', or 'parquet'")
        except Exception as e:
            logger.error(f"Failed to save database to {target}: {e}")
            raise DatabaseError(f"Save failed to path '{target}': {e}") from e
        return self

    def load(self, filepath: str) -> "Database":
        """Load database contents from a CSV, JSON, or Parquet file.

        Auto-detects format from file extension.
        """
        try:
            ext = filepath.lower().split('.')[-1]
            if ext in ['csv']:
                self.import_from_file(filepath)
            elif ext in ['json']:
                self.read_json(filepath)
            elif ext in ['parquet', 'pq']:
                self.read_parquet(filepath)
            else:
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
        self._refresh_derived()
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

    def filter(self, save: Optional[str] = None, return_data: bool = False, **conditions: Any) -> Union["Database", Dict[str, List[Any]]]:
        """Filter database rows by column conditions.

        Args:
            save: Optional file path to save filtered data (csv, json, parquet)
                 Format auto-detected from extension
            return_data: If True, return filtered data as dict instead of Database object.
                        Useful for RAM-based execution without creating new Database.
            **conditions: Column name = value or callable for filtering
                         E.g., filter(temp=300, pressure__gt=100)

        Returns:
            If return_data=False: New Database with filtered rows (optionally saved to file)
            If return_data=True: Dictionary {column_name: [values]} ready for execution

        Examples:
            >>> # Filter and return new database
            >>> filtered = db.filter(temperature__gt=350, pressure__lte=110)
            >>>
            >>> # Filter and save to file
            >>> filtered = db.filter(save="filtered_cases.csv", temperature__gt=350)
            >>>
            >>> # Filter and return data dict for execution
            >>> filtered_data = db.filter(return_data=True, temperature__gt=350)
            >>> case.database = Database(data=filtered_data)
            >>>
            >>> # Filter with callable and save
            >>> filtered = db.filter(
            ...     save="results.json",
            ...     stress=lambda x: 200 <= x <= 500
            ... )
        """
        if not conditions:
            if save:
                self.save(save)
            if return_data:
                return {col: self[col] for col in self.keys() if col != '__db_index__'}
            return self

        df = self.to_dataframe()
        mask = pd.Series([True] * len(df))

        for col_expr, value in conditions.items():
            if '__' in col_expr:
                col, op = col_expr.rsplit('__', 1)
                if col not in df.columns:
                    raise DatabaseError(f"Column '{col}' not found")
                if op == 'gt':
                    mask &= df[col] > value
                elif op == 'lt':
                    mask &= df[col] < value
                elif op == 'gte':
                    mask &= df[col] >= value
                elif op == 'lte':
                    mask &= df[col] <= value
                elif op == 'eq':
                    mask &= df[col] == value
                elif op == 'ne':
                    mask &= df[col] != value
                elif op == 'in':
                    mask &= df[col].isin(value)
                else:
                    raise DatabaseError(f"Unknown operator: {op}")
            else:
                if col_expr not in df.columns:
                    raise DatabaseError(f"Column '{col_expr}' not found")
                if callable(value):
                    mask &= df[col_expr].apply(value)
                else:
                    mask &= df[col_expr] == value

        filtered_df = df[mask]
        filtered_data = {col: filtered_df[col].tolist() for col in filtered_df.columns}
        filtered_data.pop('__db_index__', None)

        filtered_db = Database(name=f"{self.name}_filtered", data=filtered_data)

        # Save if requested
        if save:
            filtered_db.save(save)

        # Return data dict if requested (for RAM-based execution)
        if return_data:
            return filtered_data

        return filtered_db

    def filter_and_save(self, filepath: str, format: Optional[str] = None, **conditions: Any) -> "Database":
        """Filter database rows and save to file in one operation.

        Convenience method that combines filtering and saving.

        Args:
            filepath: Path to save filtered data (csv, json, parquet)
            format: Optional format override ('csv', 'json', 'parquet')
                   Auto-detected from filepath extension if not specified
            **conditions: Column name = value or callable for filtering

        Returns:
            New Database with filtered rows (saved to file)

        Examples:
            >>> # Filter and save to CSV
            >>> filtered = db.filter_and_save(
            ...     "execution_cases.csv",
            ...     temperature__gt=350,
            ...     pressure__lte=110
            ... )
            >>>
            >>> # Filter with callable and save to JSON
            >>> filtered = db.filter_and_save(
            ...     "results.json",
            ...     stress=lambda x: 200 <= x <= 500
            ... )
            >>>
            >>> # Explicit format specification
            >>> filtered = db.filter_and_save(
            ...     "data.dat",
            ...     format="csv",
            ...     velocity__gte=10
            ... )
        """
        filtered_db = self.filter(**conditions)
        inferred_format = format
        if not inferred_format and filepath:
            ext = filepath.lower().split('.')[-1]
            if ext in ['csv']:
                inferred_format = 'csv'
            elif ext in ['json']:
                inferred_format = 'json'
            elif ext in ['parquet', 'pq']:
                inferred_format = 'parquet'
        filtered_db.save(filepath, format=inferred_format or 'csv')
        return filtered_db

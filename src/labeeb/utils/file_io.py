"""
File I/O utilities for searching, replacing placeholders, and processing text files.
Used heavily for managing code input decks (e.g. MCNP, RELAP5 inputs).
"""

import ast
import logging
import math
import os
import re
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..exceptions import CaseExecutionError, TemplateError

logger = logging.getLogger(__name__)


DEFAULT_MATH_FUNCTIONS: Dict[str, Any] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "asinh": getattr(math, "asinh", None),
    "acosh": getattr(math, "acosh", None),
    "atanh": getattr(math, "atanh", None),
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
    "fabs": math.fabs,
    "abs": abs,
    "round": round,
    "pow": math.pow,
    "min": min,
    "max": max,
    "pi": math.pi,
    "e": math.e,
    "tau": getattr(math, "tau", 2 * math.pi),
    "radians": math.radians,
    "degrees": math.degrees,
    "deg2rad": math.radians,
    "rad2deg": math.degrees,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
}

_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Constant,
    ast.UnaryOp,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.Invert,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.BitAnd,
    ast.BitOr,
    ast.BitXor,
    ast.LShift,
    ast.RShift,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.IfExp,
    ast.Name,
    ast.Call,
    ast.keyword,
    ast.Attribute,
    ast.Subscript,
    ast.Slice,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.Load,
)
for _compat_name in ("Index", "Num", "Str", "Bytes", "NameConstant", "Ellipsis"):
    _node_cls = getattr(ast, _compat_name, None)
    if _node_cls is not None:
        _ALLOWED_AST_NODES = _ALLOWED_AST_NODES + (_node_cls,)


def evaluate_expression(
    expr: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    allow_custom_functions: bool = True,
) -> Any:
    """Safely evaluate a mathematical or parameter expression in a sandboxed context.

    Supports standard arithmetic, comparisons, boolean operations, ternary conditionals,
    and mathematical functions (sin, cos, exp, log, sqrt, etc.). Rejects arbitrary code
    execution, import statements, private attribute access, and unsafe built-ins.

    Args:
        expr: String expression to evaluate (e.g., ``"x + 2 * sin(theta)"``).
        context: Optional dictionary of parameter variables and custom helper functions.
        allow_custom_functions: Whether custom callable functions in context are allowed.

    Returns:
        Evaluated Python object (e.g. float, int, str, bool).

    Raises:
        TemplateError: If expression syntax is invalid, uses disallowed AST operations,
            accesses undefined variables, divides by zero, or produces evaluation errors.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise TemplateError("Expression must be a non-empty string")

    expr_str = expr.strip()

    try:
        tree = ast.parse(expr_str, mode="eval")
    except SyntaxError as exc:
        raise TemplateError(f"Invalid syntax in expression '{expr_str}': {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise TemplateError(
                f"Disallowed syntax element '{type(node).__name__}' in expression: '{expr_str}'"
            )
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise TemplateError(
                    f"Access to private identifier '{node.id}' is forbidden in expression: '{expr_str}'"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise TemplateError(
                    f"Access to private attribute '{node.attr}' is forbidden in expression: '{expr_str}'"
                )

    try:
        code = compile(tree, filename="<template_expr>", mode="eval")
    except Exception as exc:
        raise TemplateError(f"Failed to compile expression '{expr_str}': {exc}") from exc

    safe_env = {k: v for k, v in DEFAULT_MATH_FUNCTIONS.items() if v is not None}
    if context:
        for k, v in context.items():
            if k.startswith("_"):
                continue
            if callable(v) and not allow_custom_functions:
                continue
            safe_env[k] = v

    try:
        return eval(code, {"__builtins__": {}}, safe_env)
    except ZeroDivisionError as exc:
        raise TemplateError(f"Division by zero in expression '{expr_str}'") from exc
    except NameError as exc:
        raise TemplateError(f"Undefined variable or function in expression '{expr_str}': {exc}") from exc
    except TypeError as exc:
        raise TemplateError(f"Type error evaluating expression '{expr_str}': {exc}") from exc
    except ValueError as exc:
        raise TemplateError(f"Value error evaluating expression '{expr_str}': {exc}") from exc
    except TemplateError:
        raise
    except Exception as exc:
        raise TemplateError(f"Error evaluating expression '{expr_str}': {exc}") from exc


def format_value(value: Any, fmt: Optional[Union[str, Callable[[Any], str]]] = None) -> str:
    """Format a value using printf-style, str.format-style, or callable formatters."""
    if fmt is None:
        return str(value)
    if callable(fmt):
        try:
            return str(fmt(value))
        except Exception as exc:
            raise TemplateError(f"Custom formatter failed for value {value!r}: {exc}") from exc
    if isinstance(fmt, str):
        if "%" in fmt:
            try:
                return fmt % value
            except (TypeError, ValueError):
                pass
        if "{" in fmt and "}" in fmt:
            try:
                return fmt.format(value)
            except (TypeError, ValueError, KeyError):
                pass
        try:
            return format(value, fmt)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _split_line_comment(line: str) -> Tuple[str, str]:
    """Split line into (code_part, comment_part) preserving trailing comments."""
    # Match comment indicators that are not part of expression or flag delimiters:
    # 1. $ not followed by { (e.g. '$ comment', '   $ comment', but not '${expr}')
    dollar_match = re.search(r"(?:\s|^)(\$(?!\{))", line)
    dollar_idx = dollar_match.start(1) if dollar_match else -1

    # 2. ! comment in fortran (preceded by whitespace or start of line, not !=)
    excl_match = re.search(r"(?:\s|^)(!(?!=))", line)
    excl_idx = excl_match.start(1) if excl_match else -1

    # 3. // comment
    slash_idx = line.find("//")

    # 4. # comment (only if preceded by whitespace or at start, and not #WORD# flag or #{expr}#)
    hash_match = re.search(r"(?:\s|^)(#(?!\w+#|\{))", line)
    hash_idx = hash_match.start(1) if hash_match else -1

    candidates = [idx for idx in (dollar_idx, excl_idx, slash_idx, hash_idx) if idx != -1]
    if not candidates:
        return line, ""
    min_idx = min(candidates)
    return line[:min_idx], line[min_idx:]


def _find_delimited_spans(text: str, start_d: str, end_d: str) -> List[Tuple[int, int, str]]:
    """Find non-overlapping spans of delimited expressions with bracket/brace nesting support."""
    spans: List[Tuple[int, int, str]] = []
    pos = 0
    while pos < len(text):
        idx = text.find(start_d, pos)
        if idx == -1:
            break
        body_start = idx + len(start_d)

        # If delimiters are ${ and }, track nesting of { and }
        if start_d.endswith("{") and end_d == "}":
            nesting = 1
            curr = body_start
            found = False
            while curr < len(text):
                if text[curr] == "{":
                    nesting += 1
                elif text[curr] == "}":
                    nesting -= 1
                    if nesting == 0:
                        spans.append((idx, curr + 1, text[body_start:curr]))
                        pos = curr + 1
                        found = True
                        break
                curr += 1
            if not found:
                break
        else:
            end_idx = text.find(end_d, body_start)
            if end_idx == -1:
                break
            spans.append((idx, end_idx + len(end_d), text[body_start:end_idx]))
            pos = end_idx + len(end_d)
    return spans


def _parse_expression_and_format(body: str) -> Tuple[str, Optional[str]]:
    """Split expression body into (expression, optional_format_string)."""
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    colon_idx = -1
    for i, ch in enumerate(body):
        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket = max(0, depth_bracket - 1)
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)
        elif ch == ":" and depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
            colon_idx = i

    if colon_idx != -1:
        expr_part = body[:colon_idx].strip()
        fmt_part = body[colon_idx + 1:].strip()
        if expr_part:
            return expr_part, (fmt_part if fmt_part else None)
    return body.strip(), None


class File:
    """
    Represents a text file with utility functions for search and replace operations,
    and post-processing pipelines.
    """

    def __init__(
        self,
        file_path: str = "",
        mode: str = "r",
        keep_path_struct: bool = False,
        **kwargs: Any,
    ):
        self.file_path: str = file_path
        self.mode: str = mode
        self.keep_path_struct: bool = keep_path_struct
        self._db: List[str] = []
        self._replaced: List[str] = []
        self.search_index: Dict[str, List[int]] = {}
        self.force_read: bool = False
        self._process_functions: List[Callable[..., Any]] = []
        self.processed: List[Any] = []
        self.refresh_read_before_write: bool = False
        self.fname_is_file_path: bool = False

        self._parse_kwargs(**kwargs)

    @property
    def filename(self) -> str:
        """Get the base filename or the full path depending on settings."""
        if self.fname_is_file_path:
            return self.file_path
        return os.path.basename(self.file_path)

    @property
    def fname(self) -> str:
        """Alias for filename."""
        return self.filename

    @property
    def dir_path(self) -> str:
        """Get the directory path containing the file."""
        return os.path.dirname(self.file_path)

    @property
    def dir(self) -> str:
        """Alias for dir_path."""
        return self.dir_path

    @property
    def location(self) -> str:
        """Alias for dir_path."""
        return self.dir_path

    def read(self, file_path: Optional[str] = None, force_read: bool = False) -> "File":
        """
        Read the file content into memory.

        Args:
            file_path: Optional path to override the default file_path.
            force_read: If True, force re-reading from disk even if already loaded.
        """
        if file_path is not None:
            self.file_path = file_path
        if len(self._db) > 0 and not self.force_read and not force_read:
            return self

        try:
            with open(self.file_path, "r", encoding="utf-8") as fid:
                self._db = [line.rstrip("\n") for line in fid]
        except Exception as e:
            logger.error(f"Error reading file {self.file_path}: {e}")
            raise e
        return self

    def search(self, *keywords: str) -> "File":
        """
        Search for keywords in the file content and cache their line numbers.
        """
        if not keywords:
            logger.warning("No search keywords provided.")
            return self

        self.search_index = {kw: [] for kw in keywords}
        for i, line in enumerate(self._db):
            for kw in keywords:
                if kw in line:
                    self.search_index[kw].append(i)
        return self

    def replace(self, rep_dict: Dict[str, Any], **kwargs: Any) -> "File":
        """
        Replace mapped keywords with their corresponding values sequentially.
        """
        # Ensure all keys in rep_dict are searched first
        missing_keys = [kw for kw in rep_dict if kw not in self.search_index]
        if missing_keys:
            self.search(*missing_keys)

        self._replaced = deepcopy(self._db)
        for word, line_ids in self.search_index.items():
            val = rep_dict.get(word)
            if val is None:
                continue
            str_val = str(val)
            for line_id in line_ids:
                self._replaced[line_id] = self._replaced[line_id].replace(word, str_val)
        return self

    def replace_assignments(
        self,
        values: Dict[str, Any],
        *,
        strict: bool = False,
        fmt: Optional[Union[str, Dict[str, Union[str, Callable[[Any], str]]]]] = None,
        evaluate_expressions: bool = False,
        context: Optional[Dict[str, Any]] = None,
        reset: bool = True,
    ) -> "File":
        """Replace values in assignment-style records while preserving syntax and comments.

        For example, ``x=1`` becomes ``x=42`` when ``{"x": 42}`` is supplied.
        Whitespace, separators, comments, and unrelated identifiers are retained.

        Args:
            values: Dictionary mapping variable names to replacement values, expressions, or callables.
            strict: If True, raise TemplateError when any specified key is missing from the template.
            fmt: Optional format string (e.g. ``"%6.2f"`` or ``"{:.3e}"``), callable, or dict mapping
                key names to individual formatters.
            evaluate_expressions: If True, evaluate string values as safe mathematical expressions.
            context: Optional evaluation context dictionary passed when evaluating expressions or callables.
            reset: If True, start substitution from ``_db``; if False, continue from ``_replaced``.

        Returns:
            Self instance with updated ``_replaced`` lines.

        Raises:
            TemplateError: If values are invalid, strict keys are missing, or expression evaluation fails.
        """
        if not isinstance(values, dict):
            raise TemplateError("Assignment values must be a dictionary")

        for key in values:
            if not isinstance(key, str) or not key.strip():
                raise TemplateError("Assignment keys must be non-empty strings")

        eval_context = {**(context or {})}
        prepared_values: Dict[str, str] = {}
        for key, val in values.items():
            if callable(val):
                try:
                    raw_val = val(eval_context)
                except Exception as exc:
                    raise TemplateError(f"Callable value for assignment '{key}' failed: {exc}") from exc
            elif evaluate_expressions and isinstance(val, str):
                raw_val = evaluate_expression(val, eval_context)
            else:
                raw_val = val

            key_fmt = None
            if isinstance(fmt, dict):
                key_fmt = fmt.get(key)
            elif fmt is not None:
                key_fmt = fmt

            prepared_values[key] = format_value(raw_val, key_fmt)

        lines = deepcopy(self._db) if reset or not self._replaced else deepcopy(self._replaced)
        match_counts: Dict[str, int] = {k: 0 for k in values}

        for key, formatted_str in prepared_values.items():
            pattern = re.compile(
                rf"(?<![A-Za-z0-9_.-])({re.escape(key)}(?![A-Za-z0-9_])\s*=\s*)"
                r"([^\s,;!#$/]+)"
            )

            new_lines: List[str] = []
            for line in lines:
                code_part, comment_part = _split_line_comment(line)

                def _repl(match: re.Match) -> str:
                    match_counts[key] += 1
                    return match.group(1) + formatted_str

                new_code = pattern.sub(_repl, code_part)
                new_lines.append(new_code + comment_part)
            lines = new_lines

        if strict:
            missing = [k for k, count in match_counts.items() if count == 0]
            if missing:
                raise TemplateError(
                    f"Strict assignment replacement failed: missing assignment key(s): {', '.join(sorted(missing))}"
                )

        self._replaced = lines
        return self

    def replace_expressions(
        self,
        context: Optional[Dict[str, Any]] = None,
        *,
        delimiters: Tuple[str, str] = ("${", "}"),
        strict: bool = False,
        fmt: Optional[Union[str, Dict[str, Union[str, Callable[[Any], str]]]]] = None,
        reset: bool = False,
    ) -> "File":
        """Replace inline expressions embedded in template files.

        Supports expressions of the form ``${expr}`` or ``${expr : fmt}`` (e.g.
        ``${x * 2 + 1}``, ``${rho / 1000.0 : %6.3f}``, ``${power * 1e6 : {:.2e}}``).

        Args:
            context: Dictionary containing variable values and custom functions.
            delimiters: Tuple of (start_delimiter, end_delimiter). Defaults to ``("${", "}")``.
            strict: If True, raise TemplateError on undefined variables or missing expressions.
            fmt: Optional default formatter if not specified within the inline expression tag.
            reset: If True, start substitution from ``_db``; if False, continue from ``_replaced``.

        Returns:
            Self instance with updated ``_replaced`` lines.

        Raises:
            TemplateError: If expression syntax is invalid, unsafe, or evaluation fails.
        """
        if len(delimiters) != 2 or not delimiters[0] or not delimiters[1]:
            raise TemplateError("Delimiters must be a tuple of two non-empty strings")

        start_d, end_d = delimiters
        lines = deepcopy(self._db) if reset or not self._replaced else deepcopy(self._replaced)
        eval_context = {**(context or {})}

        new_lines: List[str] = []
        for line in lines:
            code_part, comment_part = _split_line_comment(line)
            spans = _find_delimited_spans(code_part, start_d, end_d)
            if not spans:
                new_lines.append(line)
                continue

            result_pieces: List[str] = []
            last_idx = 0
            for start_idx, end_idx, raw_content in spans:
                result_pieces.append(code_part[last_idx:start_idx])
                last_idx = end_idx

                body = raw_content.strip()
                if not body:
                    raise TemplateError("Empty expression inside template delimiters")

                expr_part, inline_fmt = _parse_expression_and_format(body)
                val = evaluate_expression(expr_part, eval_context)

                chosen_fmt = inline_fmt
                if chosen_fmt is None:
                    if isinstance(fmt, dict):
                        chosen_fmt = fmt.get(expr_part)
                    elif fmt is not None:
                        chosen_fmt = fmt

                formatted = format_value(val, chosen_fmt)
                result_pieces.append(formatted)

            result_pieces.append(code_part[last_idx:])
            new_lines.append("".join(result_pieces) + comment_part)

        self._replaced = new_lines
        return self


    def render_jinja(self, context: Dict[str, Any]) -> "File":
        """
        Render the file template using Jinja2 with the provided context dictionary.
        Automatically exposes python standard math library functions (sin, cos, sqrt, pi, etc.) to the template.

        Args:
            context: Dictionary of values and helper functions to interpolate.
        """
        try:
            import jinja2
        except ImportError as e:
            logger.error("Jinja2 package is required to use render_jinja. Install it with: pip install jinja2")
            raise ImportError("Jinja2 package is not installed. Run 'pip install jinja2' to enable this feature.") from e

        # Inject standard math functions for ease of template logic
        import math
        math_helpers = {
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "exp": math.exp,
            "log": math.log,
            "log10": math.log10,
            "sqrt": math.sqrt,
            "pi": math.pi,
            "e": math.e,
            "abs": abs,
            "round": round,
            "pow": math.pow,
        }

        # Context takes priority over default math functions
        combined_context = {**math_helpers, **context}

        template_text = "\n".join(self._db)
        template = jinja2.Template(template_text)
        rendered_text = template.render(combined_context)
        self._replaced = rendered_text.splitlines()
        return self

    def write(self, filename: str, mode: str = "w") -> "File":
        """
        Write content (either original or replaced if replaced exists) to a file.
        """
        if self.refresh_read_before_write:
            self.read()

        head = os.path.dirname(filename)
        if head and not os.path.exists(head):
            os.makedirs(head, exist_ok=True)

        try:
            with open(filename, mode, encoding="utf-8") as fid:
                content = self._replaced if self._replaced else self._db
                for line in content:
                    fid.write(f"{line}\n")
        except Exception as e:
            logger.error(f"Error writing file {filename}: {e}")
            raise e
        return self

    def __iter__(self) -> "File":
        self._current_index = 0
        return self

    def __next__(self) -> str:
        if self._current_index < len(self):
            val = self[self._current_index]
            self._current_index += 1
            return val
        raise StopIteration

    def __getitem__(self, index: Union[int, slice]) -> Union[str, List[str]]:
        content = self._replaced if self._replaced else self._db
        return content[index]

    def __len__(self) -> int:
        return len(self._db)

    def clear(self) -> None:
        """Clear all content and configurations."""
        self._db = []
        self._replaced = []
        self.search_index = {}
        self._process_functions = []
        self.processed = []

    def add_processing_func(self, *funcs: Callable[..., Any]) -> "File":
        """Add pipeline functions for processing."""
        for f in funcs:
            if f not in self._process_functions:
                self._process_functions.append(f)
        return self

    def process(self, **kwargs: Any) -> "File":
        """Execute all post-processing pipeline functions."""
        for f in self._process_functions:
            f(self, **kwargs)
        return self

    def _parse_kwargs(self, **kwargs: Any) -> None:
        """Parse configuration keyword arguments."""
        for key, val in kwargs.items():
            norm_key = key.lower()
            if norm_key in self.__dict__:
                setattr(self, norm_key, val)
            elif norm_key == "refresh":
                self.refresh_read_before_write = bool(val)
            elif norm_key == "fname_is_path":
                self.fname_is_file_path = bool(val)

    def set_args(self, **kwargs: Any) -> "File":
        """Update configurations via keyword arguments."""
        self._parse_kwargs(**kwargs)
        return self

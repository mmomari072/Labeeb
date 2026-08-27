"""
File I/O utilities for searching, replacing placeholders, and processing text files.
Used heavily for managing code input decks (e.g. MCNP, RELAP5 inputs).
"""

import logging
import os
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


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

"""
Timer and Progress Bar utilities to track and display execution times.
"""

import os
import sys
import time
from typing import Any, List, Optional, Tuple


class Timer:
    """
    A simple timer class to measure elapsed time.
    """

    def __init__(self, name: Optional[str] = None):
        self.name: Optional[str] = name
        self.description: Optional[str] = None
        self.start: float = time.time()
        self.end: Optional[float] = None
        self.delta: Optional[float] = None
        self._deltas: List[float] = [0.0]
        self._times: List[int] = [0]

    def tic(self) -> "Timer":
        """Start the timer."""
        self.start = time.time()
        return self

    def toc(self, print_time: bool = False) -> float:
        """
        Record elapsed time since start.

        Args:
            print_time: If True, prints the elapsed time.

        Returns:
            Elapsed time in seconds.
        """
        self.end = time.time()
        self.delta = self.end - self.start
        self._deltas.append(self.delta)
        self._times.append(self._times[-1] + 1)
        if print_time:
            print(self.__repr__())
        return self.delta

    def __repr__(self) -> str:
        h, m, s, frac = Timer.convert_sec_to_time(self.delta if self.delta is not None else 0.0)
        return f"Elapsed time {h:02d}:{m:02d}:{s:02d}:{frac:06.3f}"

    def __str__(self) -> str:
        h, m, s, frac = Timer.convert_sec_to_time(self.delta if self.delta is not None else 0.0)
        return f"{h:02d}:{m:02d}:{s:02d}:{frac:06.3f}"

    @staticmethod
    def convert_sec_to_time(seconds: float) -> Tuple[int, int, int, float]:
        """
        Convert seconds into hours, minutes, seconds, and fractional milliseconds.

        Args:
            seconds: Total elapsed time in seconds.

        Returns:
            Tuple of (hours, minutes, seconds, fractional_milliseconds)
        """
        ss = seconds
        parts = []
        for divisor in [24 * 3600, 3600, 60, 1]:
            val = int(ss // divisor)
            parts.append(val)
            ss %= divisor
        # parts: [days, hours, minutes, seconds]
        # ss now contains the fractional remainder

        # Convert days and hours into total hours
        hours = parts[0] * 24 + parts[1]
        minutes = parts[2]
        seconds_int = parts[3]

        # Return hours, minutes, seconds, and fractional milliseconds
        frac_milliseconds = ss * 1000.0
        return hours, minutes, seconds_int, frac_milliseconds


def format_seconds(seconds: float) -> str:
    """Helper to format seconds into HH:MM:SS.FFF"""
    if seconds is None or seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    frac = (seconds - int(seconds))
    return f"{h:02d}:{m:02d}:{s:02d}:{frac * 1000:03.0f}"


class ProgressBar:
    """
    Console-based progress bar representation with health metrics.

    Rendering styles: ``default`` (legacy), ``apt``, ``powershell``. When the
    output stream is not a TTY (or ``headless=True`` is forced), a plain
    one-line-per-item fallback is used instead of carriage-return redraws.
    Nested runs (Coupler/Case) pass increasing ``indent`` levels, which render
    as deeper indentation in every style.

    Health Metrics (NEW):
    - Tracks error count, warning count, success count
    - Displays with automatic style fallback: rich → detailed → compact → headless
    """

    STYLES = ("default", "apt", "powershell")

    def __init__(
        self,
        name: str,
        start: int,
        end: int,
        step: int = 1,
        indent: int = 0,
        *,
        style: str = "default",
        headless: Optional[bool] = None,
        stream: Any = None,
        health_metrics: bool = True,
    ):
        if style not in self.STYLES:
            raise ValueError(
                f"ProgressBar style must be one of {list(self.STYLES)}, got {style!r}"
            )
        self.name: str = name
        self.start: int = start
        self.end: int = end
        self.step: int = step
        self.col_len: int = 40
        self.timer: Timer = Timer()
        self.is_started: bool = False
        self._progress: float = 0.0
        self._index: int = 0
        self._time_remaining: float = 0.0
        self._tmp_len_char: int = -1
        self.indent: int = indent
        self.style: str = style
        self._stream: Any = stream if stream is not None else sys.stdout
        if headless is None:
            isatty = getattr(self._stream, "isatty", None)
            self._headless: bool = not (callable(isatty) and isatty())
        else:
            self._headless = bool(headless)

        # Health metrics tracking
        self.health_metrics: bool = health_metrics
        self.error_count: int = 0
        self.warning_count: int = 0
        self.success_count: int = 0
        self._total_cases: int = end - start

        # Color support detection
        self._supports_color: bool = self._detect_color_support()

    def _indent_prefix(self) -> str:
        return "    " * self.indent

    def _detect_color_support(self) -> bool:
        """Detect if terminal supports ANSI color codes."""
        # Check common environment variables
        no_color = os.environ.get("NO_COLOR")
        if no_color:
            return False

        # Check if stream is TTY and color support
        isatty = getattr(self._stream, "isatty", None)
        if not (callable(isatty) and isatty()):
            return False

        # Check platform/terminal
        import platform
        if platform.system() == "Windows":
            # Windows console support is limited
            return os.environ.get("TERM", "").lower() in ("xterm", "xterm-256color")

        return True

    def report_case_status(self, status: str, error_msg: str = None) -> None:
        """
        Report the execution status of a case.

        Args:
            status: One of "success", "warning", "error"
            error_msg: Optional error message (unused, for future use)
        """
        if not self.health_metrics:
            return

        if status == "success":
            self.success_count += 1
        elif status == "warning":
            self.warning_count += 1
        elif status == "error":
            self.error_count += 1

    def _get_health_metrics_str(self, format_type: str = "detailed") -> str:
        """
        Generate health metrics string in specified format.

        Args:
            format_type: "compact", "detailed", or "rich"

        Returns:
            Formatted health metrics string
        """
        if not self.health_metrics or self._total_cases == 0:
            return ""

        total = self.success_count + self.warning_count + self.error_count
        success_pct = (self.success_count / total * 100) if total > 0 else 0
        warning_pct = (self.warning_count / total * 100) if total > 0 else 0
        error_pct = (self.error_count / total * 100) if total > 0 else 0

        if format_type == "compact":
            return f"[{total}/{self._total_cases}][E:{error_pct:.0f}% W:{warning_pct:.0f}%]"

        elif format_type == "detailed":
            return f"Cases: {total}/{self._total_cases} | ✓ Success: {success_pct:.1f}% | ⚠ Warnings: {warning_pct:.1f}% | ✗ Errors: {error_pct:.1f}%"

        elif format_type == "rich":
            # Format with colors if supported
            if self._supports_color:
                # ANSI color codes
                GREEN = "\033[92m"
                YELLOW = "\033[93m"
                RED = "\033[91m"
                RESET = "\033[0m"

                success_str = f"{GREEN}✓ {success_pct:.1f}%{RESET}"
                warning_str = f"{YELLOW}⚠ {warning_pct:.1f}%{RESET}"
                error_str = f"{RED}✗ {error_pct:.1f}%{RESET}" if error_pct > 0 else f"{GREEN}✗ 0%{RESET}"
            else:
                success_str = f"✓ {success_pct:.1f}%"
                warning_str = f"⚠ {warning_pct:.1f}%"
                error_str = f"✗ {error_pct:.1f}%"

            return f"Cases: {total}/{self._total_cases} | Success: {success_str} | Warnings: {warning_str} | Errors: {error_str}"

        return ""

    def _get_display_format(self) -> str:
        """
        Determine which display format to use based on capabilities.

        Fallback priority: rich → detailed → compact → headless
        """
        if self._headless:
            return "headless"

        # Try rich format if colors supported
        if self._supports_color:
            return "rich"

        # Check if terminal is wide enough for detailed
        try:
            import shutil
            cols = shutil.get_terminal_size().columns
            if cols >= 120:  # Detailed format needs more space
                return "detailed"
        except:
            pass

        # Default to compact
        return "compact"

    def _calculate_progress(self) -> None:
        total = self.end - self.start
        if total <= 0:
            self._progress = 1.0
            self._time_remaining = 0.0
            return

        self._progress = (self._index - self.start) / total
        self._progress = min(max(self._progress, 0.0), 1.0)

        # Estimate time remaining based on average elapsed time per tick
        delta_last = self.timer._deltas[-1] if self.timer._deltas else 0.0
        times_last = self.timer._times[-1] if self.timer._times else 1
        if times_last > 0:
            avg_time = delta_last / times_last
            self._time_remaining = (self.end - self._index - 1) * avg_time
        else:
            self._time_remaining = 0.0

    def __iter__(self) -> "ProgressBar":
        self._index = self.start
        self._tmp_len_char = -1
        self.timer.tic()
        return self

    def __next__(self) -> int:
        if self.end - self.start <= 0:
            raise StopIteration

        if self._index < self.end:
            self.timer.toc()
            self._calculate_progress()
            self._index += 1
            self._print_progress()
            return self._index - 1

        self._progress = 1.0
        if not self._headless:
            # TTY modes redraw the completed bar; headless already emitted the
            # final item line on the last tick.
            self._print_progress()
            self._finish_line()
        raise StopIteration

    def _print_progress(self) -> None:
        len_char = int(self.col_len * self._progress)
        elapsed_str = str(self.timer)
        remaining_str = format_seconds(self._time_remaining)
        indent_space = self._indent_prefix()
        pct = 100 * self._progress

        # Determine display format based on capabilities
        format_type = self._get_display_format()

        if format_type == "headless":
            # Plain one-line-per-item fallback (no carriage-return redraws).
            health_str = self._get_health_metrics_str("compact")
            metrics_part = f" {health_str}" if health_str else ""
            self._stream.write(f"{indent_space}{self.name}: {self._index}/{self.end}{metrics_part}\n")
            self._stream.flush()
            return

        # Get health metrics in appropriate format
        health_str = self._get_health_metrics_str(format_type)
        health_part = f" [{health_str}]" if health_str else ""

        if self.style == "default":
            filled = "=" * len_char
            empty = " " * (self.col_len - len_char)

            if format_type == "rich" and self.health_metrics:
                # Rich format: show metrics below progress bar
                self._stream.write(
                    f"\r{indent_space}[CASE:{self.name}]({pct:6.2f}%)[{filled}{empty}] [Et:{elapsed_str}][Rt:{remaining_str}]\n"
                )
                self._stream.write(f"{indent_space}  {health_str}\r")
            else:
                # Compact format: inline metrics
                self._stream.write(
                    f"\r{indent_space}[CASE:{self.name}]({pct:6.2f}%)[{filled}{empty}]{health_part} [Et:{elapsed_str}][Rt:{remaining_str}]"
                )
            self._stream.flush()
            return

        if self.style == "apt":
            apt_bar = "=" * len_char
            if len_char < self.col_len:
                apt_bar += ">" + " " * (self.col_len - len_char - 1)

            if format_type == "rich" and self.health_metrics:
                # Detailed format
                self._stream.write(f"\r{indent_space}{self.name}: {pct:5.1f}% [{apt_bar}]\n")
                self._stream.write(f"{indent_space}  {health_str}\r")
            else:
                self._stream.write(f"\r{indent_space}{self.name}: {pct:5.1f}% [{apt_bar}]{health_part}")
            self._stream.flush()
            return

        # powershell
        filled = "=" * len_char
        empty = " " * (self.col_len - len_char)

        if format_type == "rich" and self.health_metrics:
            # Detailed format
            self._stream.write(f"\r{indent_space}>> {self.name} >> {pct:6.2f}% [{filled}{empty}]\n")
            self._stream.write(f"{indent_space}  {health_str}\r")
        else:
            self._stream.write(f"\r{indent_space}>> {self.name} >> {pct:6.2f}% [{filled}{empty}]{health_part}")
        self._stream.flush()

    def _finish_line(self) -> None:
        """Final newline after a completed bar (TTY modes only)."""
        if not self._headless:
            print()

    def update(self, index: int) -> None:
        """
        Manually update the progress bar to a specific index.
        """
        if not self.is_started:
            self.timer.tic()
            self.is_started = True

        self._index = min(max(index, self.start), self.end)
        self.timer.toc()
        self._calculate_progress()
        self._print_progress()
        if self._index >= self.end:
            self._finish_line()

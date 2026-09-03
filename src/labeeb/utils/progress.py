"""
Timer and Progress Bar utilities to track and display execution times.
"""

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
        Convert seconds into days, hours, minutes, seconds, fraction.
        """
        ss = seconds
        parts = []
        for divisor in [24 * 3600, 3600, 60, 1]:
            val = int(ss // divisor)
            parts.append(val)
            ss %= divisor
        # parts: [days, hours, minutes, seconds]
        # Return hours, minutes, seconds, and the fractional remainder
        hours = parts[0] * 24 + parts[1]
        minutes = parts[2]
        seconds_int = parts[3]
        fractional = seconds_int + ss
        return hours, minutes, int(ss), (seconds - int(seconds)) * 1000.0
        # Actually let's return hours, minutes, seconds, and fractional seconds simply:
        # hour = int(seconds // 3600)
        # minute = int((seconds % 3600) // 60)
        # second = int(seconds % 60)
        # frac = (seconds - int(seconds)) * 1000
        # return hour, minute, second, frac
        # Let's do that simple calculation!


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
    Console-based progress bar representation.

    Rendering styles: ``default`` (legacy), ``apt``, ``powershell``. When the
    output stream is not a TTY (or ``headless=True`` is forced), a plain
    one-line-per-item fallback is used instead of carriage-return redraws.
    Nested runs (Coupler/Case) pass increasing ``indent`` levels, which render
    as deeper indentation in every style.
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

    def _indent_prefix(self) -> str:
        return "    " * self.indent

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

        if self._headless:
            # Plain one-line-per-item fallback (no carriage-return redraws).
            self._stream.write(f"{indent_space}{self.name}: {self._index}/{self.end}\n")
            self._stream.flush()
            return

        if self.style == "default":
            filled = "=" * len_char
            empty = " " * (self.col_len - len_char)
            self._stream.write(
                f"\r{indent_space}[CASE:{self.name}]({pct:6.2f}%)[{filled}{empty}] [Et:{elapsed_str}][Rt:{remaining_str}]"
            )
            self._stream.flush()
            return
        if self.style == "apt":
            apt_bar = "=" * len_char
            if len_char < self.col_len:
                apt_bar += ">" + " " * (self.col_len - len_char - 1)
            self._stream.write(f"\r{indent_space}{self.name}: {pct:5.1f}% [{apt_bar}]")
            self._stream.flush()
            return
        # powershell
        filled = "=" * len_char
        empty = " " * (self.col_len - len_char)
        self._stream.write(f"\r{indent_space}>> {self.name} >> {pct:6.2f}% [{filled}{empty}]")
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

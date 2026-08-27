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
    """

    def __init__(self, name: str, start: int, end: int, step: int = 1, indent: int = 0):
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
        self._print_progress()
        print()  # Final newline
        raise StopIteration

    def _print_progress(self) -> None:
        len_char = int(self.col_len * self._progress)
        filled = "=" * len_char
        empty = " " * (self.col_len - len_char)
        elapsed_str = str(self.timer)
        remaining_str = format_seconds(self._time_remaining)

        # Only redraw if character representation block changes
        current_len_char = int(self.col_len * self._progress)
        if self._tmp_len_char != current_len_char:
            indent_space = "    " * self.indent
            sys.stdout.write(
                f"\r{indent_space}[CASE:{self.name}]({100 * self._progress:6.2f}%)[{filled}{empty}] [Et:{elapsed_str}][Rt:{remaining_str}]"
            )
            sys.stdout.flush()
            # self._tmp_len_char = current_len_char

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
            print()  # Print a newline when done

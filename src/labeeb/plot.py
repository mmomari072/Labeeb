"""
Opt-in LivePlot and PlotObserver API for real-time, non-blocking visualization over EventPublisher.
Supports headless/offline disabled mode, bounded update cadence/throttling,
callback failure isolation, and optional matplotlib dependencies.
"""

import copy
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)


class PlotObserver:
    """
    Non-blocking live plotting observer that consumes simulation events
    and updates figures/images at a bounded cadence without mutating simulation results.
    """

    def __init__(
        self,
        metrics: Optional[Sequence[str]] = None,
        extract_fn: Optional[Callable[[Dict[str, Any]], Dict[str, float]]] = None,
        output_path: Optional[Union[str, Path]] = None,
        enabled: bool = True,
        update_interval_seconds: float = 0.5,
        title: str = "Live Simulation Progress",
        xlabel: str = "Step / Case",
        ylabel: str = "Value",
    ) -> None:
        self.metrics: List[str] = list(metrics) if metrics else []
        self.extract_fn: Optional[Callable[[Dict[str, Any]], Dict[str, float]]] = extract_fn
        self.output_path: Optional[Path] = Path(output_path) if output_path else None
        self.enabled: bool = enabled
        self.update_interval_seconds: float = max(0.0, update_interval_seconds)
        self.title: str = title
        self.xlabel: str = xlabel
        self.ylabel: str = ylabel

        self._history: Dict[str, List[float]] = {}
        self._last_draw_time: float = 0.0
        self._lock = threading.RLock()
        self._dirty: bool = False

    def __call__(self, event: Dict[str, Any]) -> None:
        """Allow PlotObserver to act as a callable observer."""
        self.notify(event)

    def notify(self, event: Dict[str, Any]) -> None:
        """Deliver event to observer with complete failure isolation."""
        self.update(event)

    def update(self, event: Dict[str, Any]) -> None:
        """Extract metrics from event and update plot state."""
        if not self.enabled:
            return

        try:
            extracted: Dict[str, float] = {}
            if self.extract_fn is not None:
                custom_vals = self.extract_fn(copy.deepcopy(event))
                if isinstance(custom_vals, dict):
                    extracted.update(custom_vals)

            if self.metrics:
                for m in self.metrics:
                    if m in event and isinstance(event[m], (int, float)):
                        extracted[m] = float(event[m])

            if not extracted:
                return

            with self._lock:
                for key, val in extracted.items():
                    if key not in self._history:
                        self._history[key] = []
                    self._history[key].append(val)
                self._dirty = True

            now = time.monotonic()
            if now - self._last_draw_time >= self.update_interval_seconds:
                self._render()
        except Exception as exc:
            logger.warning("PlotObserver failed during update: %s", exc)

    def _render(self) -> None:
        """Render and save plot to output_path if configured."""
        if not self.enabled or not self.output_path:
            return

        with self._lock:
            if not self._dirty and self._last_draw_time > 0:
                return
            history_snapshot = {k: list(v) for k, v in self._history.items()}
            self._dirty = False
            self._last_draw_time = time.monotonic()

        try:
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive headless backend
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 4.5))
            for label, series in history_snapshot.items():
                ax.plot(range(len(series)), series, label=label, marker="o", markersize=3)

            ax.set_title(self.title)
            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            if len(history_snapshot) > 1 or history_snapshot:
                ax.legend(loc="best")
            ax.grid(True, linestyle="--", alpha=0.6)

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(self.output_path, dpi=120, bbox_inches="tight")
            plt.close(fig)
        except ImportError:
            logger.debug("matplotlib is not installed; skipping plot image generation.")
        except Exception as exc:
            logger.warning("PlotObserver render failed: %s", exc)

    def get_history(self) -> Dict[str, List[float]]:
        """Return a copy of the accumulated metric history."""
        with self._lock:
            return {k: list(v) for k, v in self._history.items()}

    def flush(self) -> None:
        """Force a render cycle if data is dirty."""
        if self.enabled and self.output_path:
            self._render()

    def reset(self) -> None:
        """Reset historical series data."""
        with self._lock:
            self._history.clear()
            self._dirty = False
            self._last_draw_time = 0.0

    def close(self) -> None:
        """Finalize observer."""
        self.flush()


class LivePlot(PlotObserver):
    """
    Context manager and high-level live plotting interface.
    """

    def __enter__(self) -> "LivePlot":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

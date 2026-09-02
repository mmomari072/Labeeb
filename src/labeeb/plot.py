"""
Opt-in LivePlot and PlotObserver API for real-time, non-blocking visualization over EventPublisher.

Plot rendering runs on an isolated background worker thread: ``notify()`` only
records metric history on the caller thread and wakes the worker, so plotting
never blocks simulation execution. The worker renders at a bounded cadence
(throttled by ``update_interval_seconds``) and is fully failure-isolated:
render/import errors are logged and skipped without affecting observers or the
simulation. Headless mode uses the matplotlib ``Agg`` backend; when no
``output_path`` is configured (or the observer is disabled) no worker is ever
started. ``flush()`` and ``close()`` keep synchronous semantics: they request a
final render and wait (bounded) for the worker to complete it — so context-manager
usage produces the final image before exiting.
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
    and updates figures/images on an isolated background thread at a bounded
    cadence without mutating simulation results.
    """

    _MAX_RENDER_WAIT = 5.0  # bounded wait for final renders (seconds)

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
        self._lock = threading.RLock()
        self._dirty: bool = False
        self._closed: bool = False
        self._render_unavailable: bool = False

        self._thread: Optional[threading.Thread] = None
        self._wake = threading.Condition(self._lock)
        self._last_draw_time: float = 0.0
        self._force_render: bool = False
        self._rendering: bool = False

    # -- public event API ---------------------------------------------------

    def __call__(self, event: Dict[str, Any]) -> None:
        """Allow calling instance directly as a notification callback."""
        self.notify(event)

    def observe(self, event: Dict[str, Any]) -> None:
        """Alias for notify(event)."""
        self.notify(event)

    def update(self, event: Dict[str, Any]) -> None:
        """Alias for notify(event)."""
        self.notify(event)

    def notify(self, event: Dict[str, Any]) -> None:
        """Deliver an event without blocking the caller.

        Metric history is recorded inline (cheap, lock-protected); rendering is
        delegated to the background worker. All failures are isolated.
        """
        if not self.enabled or self._closed:
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
                if self.output_path is not None:
                    self._ensure_worker()
                    self._wake.notify_all()
        except Exception as exc:
            logger.warning("PlotObserver failed during update: %s", exc)

    # -- rendering control ----------------------------------------------------

    def _ensure_worker(self) -> None:
        """Start the isolated render worker when output rendering is needed."""
        if self._thread is not None or not self.enabled or self.output_path is None:
            return
        self._thread = threading.Thread(
            target=self._worker_loop,
            name=f"labeeb-plot-{self.title[:24] or 'observer'}",
            daemon=True,
        )
        self._thread.start()

    def _worker_loop(self) -> None:
        """Background render loop: throttled, dirty-driven, failure-isolated."""
        while True:
            with self._lock:
                if self._closed and not self._dirty:
                    break
                if not self._dirty:
                    # Idle: sleep until woken or polled
                    self._wake.wait(timeout=0.05)
                    continue
                now = time.monotonic()
                remaining = self.update_interval_seconds - (now - self._last_draw_time)
                if remaining > 0 and self._last_draw_time > 0 and not self._force_render:
                    self._wake.wait(timeout=min(remaining, 0.05))
                    continue
                self._dirty = False
                self._force_render = False
                self._rendering = True

            try:
                self._render()
            except Exception as exc:
                # Belt-and-braces: a renderer failure must never kill the worker.
                logger.warning("PlotObserver worker render raised: %s", exc)
            finally:
                with self._lock:
                    self._rendering = False
                    self._wake.notify_all()
            # After a render, give late events a moment to land before idling
            time.sleep(0.005)

    def _render(self) -> None:
        """Render and save the current history snapshot (worker thread only)."""
        if not self.enabled or self.output_path is None:
            return
        if self._render_unavailable:
            return

        with self._lock:
            history_snapshot = {k: list(v) for k, v in self._history.items()}
            self._last_draw_time = time.monotonic()

        if not history_snapshot:
            return

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
            if len(history_snapshot) > 1:
                ax.legend(loc="best")
            ax.grid(True, linestyle="--", alpha=0.6)

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(self.output_path, dpi=120, bbox_inches="tight")
            plt.close(fig)
        except ImportError:
            logger.debug("matplotlib is not installed; skipping plot image generation.")
            self._render_unavailable = True
        except Exception as exc:
            logger.warning("PlotObserver render failed: %s", exc)
            with self._lock:
                self._dirty = False

    def get_history(self) -> Dict[str, List[float]]:
        """Return a copy of the accumulated metric history."""
        with self._lock:
            return {k: list(v) for k, v in self._history.items()}

    def flush(self) -> None:
        """Force a final render (bypassing the cadence) and wait bounded.

        If no worker is running (disabled or no output path) this is a no-op,
        preserving cheap history-only behavior.
        """
        if not self.enabled or self.output_path is None or self._closed:
            return
        self._ensure_worker()
        with self._lock:
            self._force_render = True
            self._wake.notify_all()
            deadline = time.monotonic() + self._MAX_RENDER_WAIT
            while (self._dirty or self._rendering) and time.monotonic() < deadline:
                self._wake.wait(timeout=min(0.05, max(0.0, deadline - time.monotonic())))
            if self._dirty and self._render_unavailable:
                self._dirty = False

    def reset(self) -> None:
        """Reset historical series data."""
        with self._lock:
            self._history.clear()
            self._dirty = False

    def close(self) -> None:
        """Finalize the observer: flush the final frame and stop the worker.

        Bounded join guarantees clean shutdown without ever hanging the caller;
        the worker is a daemon thread as a last-resort safety net.
        """
        if self._closed:
            return
        self.flush()  # render anything still pending (final frame)
        with self._lock:
            self._closed = True
            self._dirty = False
            self._wake.notify_all()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=self._MAX_RENDER_WAIT)
        self._thread = None


class LivePlot(PlotObserver):
    """
    Context manager and high-level live plotting interface.
    """

    def __enter__(self) -> "LivePlot":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

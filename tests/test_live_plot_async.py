"""Focused tests: non-blocking worker-thread rendering, isolated observer,
disabled/headless support, failure isolation, and clean shutdown
(LAB-LIVE-PLOT-01)."""

import time

from labeeb.plot import LivePlot, PlotObserver


class SlowRenderObserver(PlotObserver):
    """Observer whose render call deliberately blocks the worker."""

    def __init__(self, *args, render_delay=0.35, **kwargs):
        super().__init__(*args, **kwargs)
        self.render_delay = render_delay
        self.render_count = 0

    def _render(self):
        time.sleep(self.render_delay)
        self.render_count += 1
        super()._render()


def test_notify_is_non_blocking_while_worker_renders(tmp_path):
    observer = SlowRenderObserver(metrics=["temp"], output_path=tmp_path / "plot.png", enabled=True)
    try:
        started = time.monotonic()
        observer.notify({"temp": 300.0})  # must return immediately, not after the slow render
        elapsed = time.monotonic() - started
        assert elapsed < 0.15, f"notify blocked for {elapsed:.3f}s on the calling thread"
        assert observer._thread is not None and observer._thread.is_alive()
        # history is recorded synchronously
        assert observer.get_history()["temp"] == [300.0]
    finally:
        observer.close()


def test_worker_renders_throttled_and_final_flush_completes(tmp_path):
    observer = SlowRenderObserver(
        metrics=["temp"], output_path=tmp_path / "plot.png",
        enabled=True, update_interval_seconds=10.0,
    )
    observer.notify({"temp": 1.0})
    observer.notify({"temp": 2.0})
    # bounded flush waits for the worker's render to finish
    observer.flush()
    assert observer.get_history()["temp"] == [1.0, 2.0]
    observer.close()
    assert observer._thread is None
    assert (tmp_path / "plot.png").exists()


def test_close_renders_final_frame_and_joins(tmp_path):
    observer = SlowRenderObserver(metrics=["power"], output_path=tmp_path / "final.png")
    observer.notify({"power": 10.0})
    started = time.monotonic()
    observer.close()
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, "close hung waiting on the worker"
    assert (tmp_path / "final.png").exists()
    assert observer._thread is None


def test_close_is_idempotent_and_notify_ignored_after_close(tmp_path):
    observer = PlotObserver(metrics=["x"], output_path=tmp_path / "p.png")
    observer.notify({"x": 1.0})
    observer.close()
    observer.close()  # idempotent
    observer.notify({"x": 2.0})  # ignored post-close
    assert observer.get_history()["x"] == [1.0]


def test_disabled_mode_starts_no_worker_and_writes_nothing(tmp_path):
    observer = PlotObserver(metrics=["x"], output_path=tmp_path / "p.png", enabled=False)
    observer.notify({"x": 1.0})
    observer.flush()
    observer.close()
    assert observer._thread is None
    assert not (tmp_path / "p.png").exists()
    assert observer.get_history() == {}


def test_headless_history_only_mode_starts_no_worker(tmp_path):
    # No output_path -> pure history accumulation, no thread, flush is a no-op
    observer = PlotObserver(metrics=["x"], enabled=True)
    observer.notify({"x": 1.0})
    observer.notify({"x": 2.0})
    observer.flush()
    assert observer._thread is None
    assert observer.get_history()["x"] == [1.0, 2.0]
    observer.close()


def test_worker_render_failure_is_isolated(tmp_path):
    observer = PlotObserver(metrics=["x"], output_path=tmp_path / "p.png")
    original_render = observer._render

    def exploding_render():
        raise RuntimeError("render backend exploded")

    observer._render = exploding_render  # type: ignore[method-assign]
    observer.notify({"x": 1.0})  # must not raise on the caller thread
    observer.flush()
    observer.close()
    # restore for history check
    observer._render = original_render  # type: ignore[method-assign]
    assert observer.get_history()["x"] == [1.0]


def test_extract_failure_still_isolated_with_output(tmp_path):
    def broken(evt):
        raise ValueError("bad metric")

    observer = PlotObserver(extract_fn=broken, output_path=tmp_path / "p.png")
    observer.notify({"x": 1})  # no raise
    observer.flush()
    observer.close()


def test_live_plot_context_manager_clean_exit(tmp_path):
    with LivePlot(metrics=["v"], output_path=tmp_path / "ctx.png") as lp:
        lp.update({"v": 5.0})
        lp.update({"v": 7.0})
    assert (tmp_path / "ctx.png").exists()
    assert lp.get_history()["v"] == [5.0, 7.0]

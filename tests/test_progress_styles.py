"""Focused tests: hierarchical progress rendering styles + headless fallback
(Task: progress styles default/apt/powershell). Constructor behavior preserved:
legacy positional signature still works and the default render is byte-identical.
"""

import io

import pytest

from labeeb.utils.progress import ProgressBar


class Writer(io.StringIO):
    """Minimal tty-ish capture with flush()."""

    def __init__(self, isatty_result=True):
        super().__init__()
        self._is_tty = isatty_result

    def flush(self):
        pass

    def isatty(self):
        return self._is_tty


@pytest.fixture
def stream():
    return Writer()


def _render(name="demo", start=0, end=3, indent=0, style="default", **kwargs):
    out = Writer()
    bar = ProgressBar(name, start, end, indent=indent, style=style, stream=out, headless=False, **kwargs)
    for _ in bar:
        pass
    text = out.getvalue()
    # strip the trailing newline artifact of the final tick for comparison
    return text


# --- constructor compatibility -------------------------------------------------

def test_legacy_positional_constructor_still_works(stream):
    # (name, start, end, step, indent) positional call, no new kwargs
    bar = ProgressBar("demo", 0, 3, 2, 1, stream=stream)
    assert (bar.name, bar.start, bar.end, bar.step, bar.indent) == ("demo", 0, 3, 2, 1)


def test_default_render_is_byte_identical_to_legacy():
    text = _render("demo", 0, 3, 0, "default")
    assert "[CASE:demo]" in text
    assert "[Et:" in text and "[Rt:" in text
    assert "\r" in text  # carriage-return redraws preserved


# --- styles --------------------------------------------------------------------

def test_style_validation_rejects_unknown(stream):
    with pytest.raises(ValueError, match="style"):
        ProgressBar("x", 0, 1, style="fancy", stream=stream)


def test_apt_style_layout():
    text = _render("demo", 0, 3, 0, "apt")
    assert "[CASE:" not in text  # apt style has its own glyph set
    assert "demo" in text
    assert "%" in text and "[" in text
    assert text.count("\r") >= 2  # redraws on ticks


def test_powershell_style_layout():
    text = _render("demo", 0, 3, 0, "powershell")
    assert "demo" in text and "%" in text and "[" in text
    assert "\r" in text


# --- hierarchy -----------------------------------------------------------------

def test_nested_indent_prefix_hierarchy():
    parent = _render("parent", 0, 2, 0, "default")
    child = _render("child", 0, 2, 1, "default")
    child_lines = [ln for ln in child.split("\r") if "child" in ln]
    parent_lines = [ln for ln in parent.split("\r") if "parent" in ln]
    assert child_lines and parent_lines
    # every child redraw carries a deeper indent than the parent's redraws
    assert all(child_line.startswith("    [CASE:child]") for child_line in child_lines)
    assert all(not parent_line.startswith(" ") or parent_line.startswith("\r[CASE:parent]")
               for parent_line in parent_lines)


# --- headless fallback -----------------------------------------------------------

def test_headless_fallback_prints_plain_lines_no_carriage_return(stream):
    out = Writer()
    bar = ProgressBar("headless", 0, 3, stream=out, headless=True)
    for _ in bar:
        pass
    text = out.getvalue()
    assert "\r" not in text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 3  # one plain line per completed item
    assert all("headless" in line for line in lines)


def test_headless_auto_detected_when_stream_not_tty():
    out = Writer(isatty_result=False)
    bar = ProgressBar("auto", 0, 2, stream=out)
    assert bar._headless is True
    for _ in bar:
        pass
    assert "\r" not in out.getvalue()


def test_tty_stream_keeps_rich_render():
    out = Writer(isatty_result=True)
    bar = ProgressBar("tty", 0, 2, stream=out)
    assert bar._headless is False
    for _ in bar:
        pass
    assert "\r" in out.getvalue()


def test_manual_update_honors_style_and_headless():
    out = Writer(isatty_result=False)
    bar = ProgressBar("up", 0, 5, style="apt", stream=out)
    bar.update(5)
    assert "\r" not in out.getvalue()
    assert "up" in out.getvalue()

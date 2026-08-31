import importlib
import os
from contextlib import redirect_stdout
from io import StringIO


def test_import_is_silent_by_default(monkeypatch):
    monkeypatch.delenv("LABEEB_SHOW_BANNER", raising=False)
    import labeeb

    output = StringIO()
    with redirect_stdout(output):
        importlib.reload(labeeb)
    assert output.getvalue() == ""


def test_banner_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setenv("LABEEB_SHOW_BANNER", "1")
    import labeeb

    output = StringIO()
    with redirect_stdout(output):
        importlib.reload(labeeb)
    assert "CREATED BY" in output.getvalue()

    monkeypatch.delenv("LABEEB_SHOW_BANNER", raising=False)
    importlib.reload(labeeb)


def test_banner_can_be_printed_explicitly():
    import labeeb

    output = StringIO()
    with redirect_stdout(output):
        labeeb.print_banner()
    assert "CREATED BY" in output.getvalue()

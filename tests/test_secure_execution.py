"""Focused tests: secure subprocess execution (argv/list default, shell opt-in).

Covers: argv (list) execution as the safe default, string commands parsed
argv-safe unless shell=True is explicit, quoting preservation, timeout and
missing-executable semantics, malformed-quote safe failure, Case plumbing for
both forms, and the campaign manifest shell flag.
"""

import sys
from pathlib import Path

import pytest

from labeeb import Campaign, CampaignManifest, Case, CaseExecutionError, Database
from labeeb.execution import LocalExecutionBackend

PY = sys.executable


def echo_argv(args=None):
    return [PY, "-c", "import sys; print('OK', len(sys.argv) - 1)", *(args or [])]


# ------------------------------------------------------------------ backend argv default

def test_argv_list_execution_safe_default(tmp_path):
    backend = LocalExecutionBackend()
    assert backend.default_shell is False  # argv is the safe default
    result = backend.run([PY, "-c", "print('hello')"], cwd=tmp_path)
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert result.event is not None and result.event.status == "SUCCESS"


def test_string_command_parsed_as_argv_without_shell(tmp_path):
    backend = LocalExecutionBackend()
    # quotes are parsed (shlex) but no shell is involved
    result = backend.run('python -c "print(\'argv mode\')"', cwd=tmp_path)
    assert result.returncode == 0
    assert "argv mode" in result.stdout


def test_shell_metacharacters_require_explicit_optin(tmp_path):
    backend = LocalExecutionBackend()
    # default: '>' is an ordinary argv token -> no redirection happens
    default = backend.run("echo hello > redirected.txt", cwd=tmp_path)
    assert default.returncode == 0
    assert not (tmp_path / "redirected.txt").exists()

    # explicit shell=True restores legacy shell semantics
    legacy = backend.run("echo hello > redirected.txt", cwd=tmp_path, shell=True)
    assert legacy.returncode == 0
    assert (tmp_path / "redirected.txt").read_text() == "hello\n"


def test_backend_constructor_default_shell_flag(tmp_path):
    legacy_backend = LocalExecutionBackend(default_shell=True)
    assert legacy_backend.default_shell is True
    result = legacy_backend.run("echo a | wc -c", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "2"  # shell pipeline honored


def test_quoting_preserved_between_argv_and_shell(tmp_path):
    argv_result = LocalExecutionBackend().run(echo_argv(["a", "b c"]), cwd=tmp_path)
    shell_result = LocalExecutionBackend().run(
        f'"{PY}" -c "import sys; print(\'OK\', len(sys.argv) - 1)" a "b c"',
        cwd=tmp_path, shell=True,
    )
    assert argv_result.returncode == shell_result.returncode == 0
    assert argv_result.stdout == shell_result.stdout == "OK 2\n"


def test_timeout_semantics_for_argv(tmp_path):
    result = LocalExecutionBackend().run(
        [PY, "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout=0.4
    )
    assert result.returncode == -999
    assert result.timed_out is True
    assert result.event is not None and result.event.status == "TIMEOUT"


def test_missing_executable_returns_failure_not_raise(tmp_path):
    result = LocalExecutionBackend().run(
        ["definitely_missing_binary_xyz_12345"], cwd=tmp_path
    )
    assert result.returncode == -1
    assert result.event is not None and result.event.status == "FAILED"
    assert "No such file" in (result.event.message or "") or "not found" in result.stderr


def test_malformed_quotes_fail_safely(tmp_path):
    result = LocalExecutionBackend().run('python -c "unclosed', cwd=tmp_path)
    assert result.returncode == -1
    assert result.event is not None and result.event.status == "FAILED"


# ------------------------------------------------------------------ Case plumbing

def _make_case(tmp_path, exe_cmd, shell=None):
    case = Case(name="secure_case", output_files={})
    case.database = Database(data={"RHO": [19.0]})
    case.main_dir = str(tmp_path)
    case.run_case_main_dir = "runs"
    case.run_type = "new"
    case.exe_cmd = exe_cmd
    if shell is not None:
        case.shell = shell
    return case


def test_case_argv_command_list(tmp_path):
    case = _make_case(tmp_path, [[PY, "-c", "print('case-argv')"]])
    case.launch_case(0)
    assert case.execution_history[-1]["status"] == "SUCCESS"


def test_case_shell_optin_string_with_redirection(tmp_path):
    case = _make_case(tmp_path, ["echo via-shell > marker.txt"], shell=True)
    case.launch_case(0)
    marker = Path(case.current_case_dir) / "marker.txt"
    assert marker.read_text() == "via-shell\n"


def test_case_shell_default_false_leaves_redirection_unapplied(tmp_path):
    case = _make_case(tmp_path, ["echo no-redirect > marker.txt"])
    case.launch_case(0)
    assert not (Path(case.current_case_dir) / "marker.txt").exists()


def test_case_missing_executable_reports_failure(tmp_path):
    case = _make_case(tmp_path, [["missing_binary_zzz_987"]])
    with pytest.raises(CaseExecutionError):
        case.launch_case(0)
    assert case.execution_history[-1]["status"] == "FAILED"
    assert case.execution_history[-1]["exit_code"] == -1


# ------------------------------------------------------------------ campaign manifest flag

def test_campaign_manifest_shell_flag_passthrough(tmp_path):
    def build(shell):
        deck = tmp_path / "input.deck"
        deck.write_text("v=#V#\n", encoding="utf-8")
        manifest = CampaignManifest.from_dict(
            {
                "name": "sec",
                "parameters": {"V": [1.0]},
                "templates": [str(deck)],
                "commands": ["echo via-shell > marker.txt"],
                "execution": {"run_dir": str(tmp_path / "runs"), "shell": shell},
            }
        )
        campaign = Campaign(manifest)
        return campaign, campaign.build_case()

    _, case_true = build(True)
    assert case_true.shell is True
    _, case_false = build(False)
    assert case_false.shell is False

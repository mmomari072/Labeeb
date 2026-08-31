import os
import tempfile
import pytest
import sys
from labeeb.case import Flag, FlagsMap, Case
from labeeb.case import _shutdown_executor
from labeeb.exceptions import CaseExecutionError
from labeeb.database import Database
from labeeb.utils.file_io import File


def test_flag_representation():
    f = Flag(name="#RHO#", attribute_name="rho", fmt="%5.2f")
    assert f.name == "#RHO#"
    assert f.attribute == "rho"

    f.set_value(18.234)
    assert f.get_value() == "18.23"


def test_flags_map():
    f1 = Flag(name="#RHO#", attribute_name="rho", fmt="%5.2f")
    f2 = Flag(name="#WF#", attribute_name="wf", fmt="%s")

    fm = FlagsMap().add_flag(f1, f2)
    assert len(fm) == 2

    vals = fm.get_flags_values({"rho": 12.345, "wf": "abc"})
    assert vals["#RHO#"] == "12.35"
    assert vals["#WF#"] == "abc"


def test_flags_map_resets_values_and_rejects_missing_attributes():
    fm = FlagsMap().add_flag(
        Flag("#RHO#", "rho", "%5.2f"),
        Flag("#WF#", "wf", "%5.3f"),
    )

    fm.get_flags_values({"rho": 19.1, "wf": 0.01})

    with pytest.raises(CaseExecutionError, match="rho"):
        fm.get_flags_values({"wf": 0.02})


def test_case_rejects_missing_mapping_instead_of_reusing_previous_value():
    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = os.path.join(tmpdir, "input.txt")
        with open(template_path, "w") as fid:
            fid.write("RHO = #RHO#\n")

        c = Case(name="stale_flag", output_files={})
        c.database = Database(data={"rho": [19.1, None]})
        c.FlagsMap = {"#RHO#": "rho"}
        c.add_file(File(file_path=template_path))
        c.main_dir = tmpdir
        c.run_case_main_dir = "runs"
        c.run_type = "new"

        c.launch_case(case_id=0)
        with pytest.raises(CaseExecutionError, match="rho"):
            c.launch_case(case_id=1)


def test_case_launcher():
    orig_cwd = os.getcwd()
    # Setup temporary directory and simulation files
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_template_path = os.path.join(tmpdir, "input_template.txt")
            with open(input_template_path, "w") as fid:
                fid.write("DENSITY = #RHO#\nFLOW = #WF#\n")

            db = Database(data={"rho": [19.1, 19.2], "wf": [0.01, 0.02]})

            f = File(file_path=input_template_path)
            fm = FlagsMap().add_flag(
                Flag("#RHO#", "rho", "%5.2f"),
                Flag("#WF#", "wf", "%5.3f")
            )

            c = Case(
                name="test_case",
                output_files={"log.csv": ["Val"]}
            )
            c.database = db
            c.FlagsMap = fm
            c.add_file(f)
            c.main_dir = tmpdir
            c.run_case_main_dir = "runs"
            c.exe_cmd = ["echo Val > log.csv", "echo 42.0 >> log.csv"]  # Mock output file creation
            c.run_type = "new"

            c.launch()

            # Check directories created
            run0_dir = os.path.join(tmpdir, "runs", "case_0")
            run1_dir = os.path.join(tmpdir, "runs", "case_1")
            assert os.path.isdir(run0_dir)
            assert os.path.isdir(run1_dir)

            # Check replaced file content in run0
            run0_input = os.path.join(run0_dir, "input_template.txt")
            assert os.path.isfile(run0_input)
            with open(run0_input, "r") as fid:
                content = fid.read()
                assert "DENSITY = 19.10" in content
                assert "FLOW = 0.010" in content

            # Check replaced file content in run1
            run1_input = os.path.join(run1_dir, "input_template.txt")
            assert os.path.isfile(run1_input)
            with open(run1_input, "r") as fid:
                content = fid.read()
                assert "DENSITY = 19.20" in content
                assert "FLOW = 0.020" in content

            # Check outputs loaded
            assert len(c.outputs["Val"]) == 2
            assert c.outputs["Val"][0] == [42.0]
    finally:
        os.chdir(orig_cwd)


def test_case_harvester_extracts_named_metric():
    with tempfile.TemporaryDirectory() as tmpdir:
        c = Case(name="harvested", output_files={})
        c.database = Database(data={"RHO": [19.0]})
        c.main_dir = tmpdir
        c.run_case_main_dir = "runs"
        c.run_type = "new"
        c.exe_cmd = ["echo 'residual = 1.2e-3' > solver.log"]
        c.add_harvester("residual", r"residual = ([0-9.e-]+)", "solver.log")

        c.launch()

        assert c.outputs["residual"] == ["1.2e-3"]


def test_file_io_sequential_replace():
    # Setup temporary template file
    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = os.path.join(tmpdir, "template.txt")
        with open(template_path, "w") as fid:
            fid.write("#RHO# and #RHO_ALT#\n")

        f = File(file_path=template_path)
        f.read()

        # Under sequential replacement, they are replaced independently because the delimiters keep them distinct
        f.replace({"#RHO#": "18.5", "#RHO_ALT#": "19.5"})
        assert f[0] == "18.5 and 19.5"


def test_file_io_jinja2():
    # Setup temporary template file
    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = os.path.join(tmpdir, "template.txt")
        with open(template_path, "w") as fid:
            fid.write(
                "DENSITY = {{ '%5.2f'|format(rho) }}\n"
                "EXP = {{ '%5.2e'|format(val) }}\n"
                "MATH = {{ x + 1 }} and {{ cos(pi) }}\n"
                "FUNC = {{ f(x) }}\n"
            )

        f = File(file_path=template_path)
        f.read()

        # Render using Jinja2 option with a custom function f
        f.render_jinja({
            "rho": 19.526,
            "val": 12345.6,
            "x": 4.0,
            "f": lambda val: val * 2.0
        })
        assert f[0] == "DENSITY = 19.53"
        assert f[1] == "EXP = 1.23e+04"
        assert f[2] == "MATH = 5.0 and -1.0"
        assert f[3] == "FUNC = 8.0"


def test_case_parallel_log_timeout():
    orig_cwd = os.getcwd()
    try:
        # Setup temporary template file
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "template.txt")
            with open(template_path, "w") as fid:
                fid.write("RHO = #RHO#\n")

            # Setup database
            db = Database(data={"RHO": [18.0, 19.0, 20.0]})

            # Setup Case runner
            c = Case(name="parallel_test", output_files={"out.csv": ["Val"]})
            c.database = db
            c.FlagsMap = {"#RHO#": "RHO"}
            c.add_file(File(file_path=template_path))
            c.run_case_main_dir = "parallel_runs"
            c.run_case_sub_dir = "run"
            c.main_dir = tmpdir
            c.run_type = "new"

            # Mock simulation command that writes to out.csv
            # Also includes sleep to verify timeout
            c.exe_cmd = [
                "echo 'Val' > out.csv",
                "echo '42' >> out.csv",
                "sleep 0.01"
            ]

            # Log redirection config
            c.log_file = "run.log"

            # 1. Test parallel execution
            c.launch(parallel=True, n_workers=2)

            # Check outputs are correct and ordered
            assert len(c.outputs["Val"]) == 3
            assert c.outputs["Val"] == [[42.0], [42.0], [42.0]]

            # Check execution history is populated and tracked
            assert len(c.execution_history) >= 3
            assert c.execution_history[0]["case_id"] == 0
            assert c.execution_history[0]["exit_code"] == 0
            assert c.execution_history[0]["status"] == "SUCCESS"
            assert "timestamp" in c.execution_history[0]
            assert "duration_seconds" in c.execution_history[0]

            # Check log files exist and are populated
            log_run_0 = os.path.join(tmpdir, "parallel_runs", "run_0", "run.log")
            assert os.path.isfile(log_run_0)

            # 2. Test timeout
            c.timeout = 0.05
            c.exe_cmd = ["sleep 2"]
            # Launch case ID 0 with timeout
            with pytest.raises(CaseExecutionError):
                c.launch_case(case_id=0)

            # Verify log file recorded timeout
            with open(log_run_0, "r") as fid:
                log_content = fid.read()
                assert "timed out" in log_content or "Timeout" in log_content
    finally:
        os.chdir(orig_cwd)


def test_launch_raises_and_preserves_alignment_for_failed_commands():
    with tempfile.TemporaryDirectory() as tmpdir:
        c = Case(name="failed_command", output_files={"out.csv": ["Val"]})
        c.database = Database(data={"RHO": [1.0, 2.0]})
        c.main_dir = tmpdir
        c.run_case_main_dir = "runs"
        c.run_type = "new"
        c.exe_cmd = ["exit 7"]

        with pytest.raises(CaseExecutionError):
            c.launch()

        assert c.outputs["Val"] == [None, None]
        assert [entry["case_id"] for entry in c.execution_history] == [0, 1]
        assert all(entry["status"] == "FAILED" for entry in c.execution_history)


def test_launch_raises_and_preserves_alignment_for_missing_outputs():
    with tempfile.TemporaryDirectory() as tmpdir:
        c = Case(name="missing_output", output_files={"missing.csv": ["Val"]})
        c.database = Database(data={"RHO": [1.0, 2.0]})
        c.main_dir = tmpdir
        c.run_case_main_dir = "runs"
        c.run_type = "new"
        c.exe_cmd = []

        with pytest.raises(CaseExecutionError):
            c.launch()

        assert c.outputs["Val"] == [None, None]
        assert [entry["case_id"] for entry in c.execution_history] == [0, 1]
        assert all(entry["status"] == "FAILED" for entry in c.execution_history)


def test_parallel_executor_shutdown_supports_python_38_signature():
    class LegacyExecutor:
        def __init__(self):
            self.wait = None

        def shutdown(self, wait=True):
            self.wait = wait

    executor = LegacyExecutor()
    _shutdown_executor(executor, wait=False, cancel_pending=True)

    assert executor.wait is False


def test_case_worker_annotation_resolves_on_supported_python():
    import labeeb.case as case_module
    from typing import get_type_hints

    hints = get_type_hints(case_module._run_case_worker)

    assert hints["return"]
    assert sys.version_info >= (3, 8)

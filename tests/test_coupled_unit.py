import os
import tempfile

from labeeb.case import Case
from labeeb.coupler import Coupler
from labeeb.coupled_unit import ConvergenceResult
from labeeb.database import Database
from labeeb.utils.file_io import File


def test_case_converges_before_max_exec():
    orig_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "t.txt")
            with open(template_path, "w") as fid:
                fid.write("RHO = #RHO#\n")

            c = Case(name="conv_case", output_files={})
            c.database = Database(data={"RHO": [1.0]})
            c.add_file(File(file_path=template_path))
            c.FlagsMap = {"#RHO#": "RHO"}
            c.main_dir = tmpdir
            c.run_case_main_dir = "runs"
            c.exe_cmd = []
            c.run_type = "new"
            c.case_id = 0

            counter = {"n": 0}

            def check_fn(unit, **kwargs):
                counter["n"] += 1
                return counter["n"] >= 2

            result = c.run_to_convergence(max_exec=5, check_fn=check_fn)

            assert isinstance(result, ConvergenceResult)
            assert result.converged is True
            assert result.executions == 2
    finally:
        os.chdir(orig_cwd)


def test_case_exhausts_max_exec_without_converging():
    orig_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "t.txt")
            with open(template_path, "w") as fid:
                fid.write("RHO = #RHO#\n")

            c = Case(name="never_converges", output_files={})
            c.database = Database(data={"RHO": [1.0]})
            c.add_file(File(file_path=template_path))
            c.FlagsMap = {"#RHO#": "RHO"}
            c.main_dir = tmpdir
            c.run_case_main_dir = "runs"
            c.exe_cmd = []
            c.run_type = "new"
            c.case_id = 0

            result = c.run_to_convergence(max_exec=3, check_fn=lambda unit, **kw: False)

            assert result.converged is False
            assert result.executions == 3
    finally:
        os.chdir(orig_cwd)


def test_case_pre_and_post_functions_run_every_pass():
    orig_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "t.txt")
            with open(template_path, "w") as fid:
                fid.write("RHO = #RHO#\n")

            c = Case(name="hooked_case", output_files={})
            c.database = Database(data={"RHO": [1.0]})
            c.add_file(File(file_path=template_path))
            c.FlagsMap = {"#RHO#": "RHO"}
            c.main_dir = tmpdir
            c.run_case_main_dir = "runs"
            c.exe_cmd = []
            c.run_type = "new"
            c.case_id = 0

            calls = {"pre": 0, "post": 0}
            c.add_pre_functions(lambda unit, **kw: calls.__setitem__("pre", calls["pre"] + 1))
            c.add_post_functions(lambda unit, **kw: calls.__setitem__("post", calls["post"] + 1))

            c.run_to_convergence(max_exec=3, check_fn=lambda unit, **kw: calls["post"] >= 3)

            assert calls["pre"] == 3
            assert calls["post"] == 3
    finally:
        os.chdir(orig_cwd)


def test_coupler_runs_coupling_functions_once_per_pass_not_per_case():
    orig_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            in1 = os.path.join(tmpdir, "in1.txt")
            in2 = os.path.join(tmpdir, "in2.txt")
            with open(in1, "w") as f:
                f.write("RHO = #RHO#\n")
            with open(in2, "w") as f:
                f.write("RHO = #RHO#\n")

            case1 = Case(name="mcnp", output_files={})
            case1.database = Database(data={"RHO": [None]})
            case1.add_file(File(file_path=in1))
            case1.FlagsMap = {"#RHO#": "RHO"}

            case2 = Case(name="relap", output_files={})
            case2.database = Database(data={"RHO": [None]})
            case2.add_file(File(file_path=in2))
            case2.FlagsMap = {"#RHO#": "RHO"}

            coupler = Coupler(name="coupling_timing_test")
            coupler.main_dir = tmpdir
            coupler.add_cases({case1: ["RHO"], case2: ["RHO"]})
            coupler.database = Database(data={"RHO": [1.1, 2.2]})

            call_count = {"n": 0}
            coupler.add_coupling_functions(
                lambda unit, **kw: call_count.__setitem__("n", call_count["n"] + 1)
            )

            coupler.launch_case(c_step=0)

            # Two cases were run this step, but the coupling function must
            # fire exactly once per pass -- after both cases resolved.
            assert call_count["n"] == 1
    finally:
        os.chdir(orig_cwd)


def test_coupler_per_unit_max_exec_runs_case_multiple_times():
    orig_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            in1 = os.path.join(tmpdir, "in1.txt")
            with open(in1, "w") as f:
                f.write("RHO = #RHO#\n")

            case1 = Case(name="mcnp", output_files={})
            case1.database = Database(data={"RHO": [None]})
            case1.add_file(File(file_path=in1))
            case1.FlagsMap = {"#RHO#": "RHO"}

            exec_count = {"n": 0}
            case1.add_post_functions(lambda unit, **kw: exec_count.__setitem__("n", exec_count["n"] + 1))

            coupler = Coupler(name="per_unit_convergence_test")
            coupler.main_dir = tmpdir
            coupler.add_case(
                case1,
                attributes=["RHO"],
                max_exec=3,
                check_fn=lambda unit, **kw: exec_count["n"] >= 3,
            )
            coupler.database = Database(data={"RHO": [1.1]})

            coupler.launch_case(c_step=0)

            assert exec_count["n"] == 3
    finally:
        os.chdir(orig_cwd)

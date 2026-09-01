import os
import tempfile
import pytest
from labeeb.case import Case
from labeeb.coupler import Coupler
from labeeb.database import Database
from labeeb.exceptions import CouplingError
from labeeb.utils.file_io import File


def test_coupler_mapping_behavior():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create dummy inputs
        in1 = os.path.join(tmpdir, "in1.txt")
        in2 = os.path.join(tmpdir, "in2.txt")
        with open(in1, "w") as f:
            f.write("RHO = #RHO#\nWF = #WF#\n")
        with open(in2, "w") as f:
            f.write("RHO = #RHO#\nOMARI = #OMARI#\n")

        # 1. Define Cases
        case1 = Case(name="mcnp", output_files={})
        case1.database = Database(data={"RHO": [None], "WF": [None]})
        case1.add_file(File(file_path=in1))
        case1.FlagsMap = {"#RHO#": "RHO", "#WF#": "WF"}

        case2 = Case(name="relap", output_files={})
        case2.database = Database(data={"RHO": [None], "OMARI": [None]})
        case2.add_file(File(file_path=in2))
        case2.FlagsMap = {"#RHO#": "RHO", "#OMARI#": "OMARI"}

        # 2. Setup Coupler
        coupler = Coupler(name="test_coupling")
        coupler.main_dir = tmpdir

        # Add cases via mapping dictionary (as in old2 syntax)
        coupler.add_cases({
            case1: ["WF"],         # case1 will ONLY map WF from coupler's DB
            case2: ["RHO", "OMARI"]  # case2 will map RHO and OMARI
        })

        assert coupler.case_mappings["mcnp"] == ["WF"]
        assert coupler.case_mappings["relap"] == ["RHO", "OMARI"]

        # Feed main coupler database
        coupler.database = Database(data={
            "RHO": [1.1, 2.2],
            "WF": [10.0, 20.0],
            "OMARI": [100.0, 200.0]
        })

        # Run coupling step 0
        coupler.launch_case(c_step=0)

        # In coupling_iteration_0:
        # Check case1: since RHO was NOT mapped, it should remain None (or not updated)
        assert case1.database["RHO"][0] is None
        assert case1.database["WF"][0] == 10.0

        # Check case2: RHO and OMARI were mapped, so they should be updated
        assert case2.database["RHO"][0] == 1.1
        assert case2.database["OMARI"][0] == 100.0


def test_coupler_launch_processes_all_22_database_rows():
    with tempfile.TemporaryDirectory() as tmpdir:
        case = Case(name="all_rows", output_files={})
        case.database = Database(data={"RHO": [None]})

        coupler = Coupler(name="all_rows_coupling")
        coupler.main_dir = tmpdir
        coupler.add_case(case, attributes=["RHO"])
        coupler.database = Database(data={"RHO": list(range(22))})

        steps = []
        coupler.add_coupling_functions(lambda unit, **kwargs: steps.append(unit.c_step))

        coupler.launch()

        assert steps == list(range(22))


def test_coupler_max_steps_fails_instead_of_silently_omitting_rows():
    with tempfile.TemporaryDirectory() as tmpdir:
        case = Case(name="limited", output_files={})
        case.database = Database(data={"RHO": [None]})

        coupler = Coupler(name="limited_coupling")
        coupler.main_dir = tmpdir
        coupler.add_case(case, attributes=["RHO"])
        coupler.database = Database(data={"RHO": [1, 2, 3]})
        coupler.max_steps = 2

        with pytest.raises(CouplingError, match="max_steps"):
            coupler.launch()


def test_under_relaxation_factor_validation():
    coupler = Coupler(name="relax_test")
    coupler.set_under_relaxation("temperature", 0.5)
    assert coupler.get_under_relaxation("temperature") == 0.5
    assert coupler.get_under_relaxation("unconfigured") == 1.0

    with pytest.raises(ValueError, match="Under-relaxation factor"):
        coupler.set_under_relaxation("temperature", 0.0)

    with pytest.raises(ValueError, match="Under-relaxation factor"):
        coupler.set_under_relaxation("temperature", -0.5)

    with pytest.raises(ValueError, match="Under-relaxation factor"):
        coupler.set_under_relaxation("temperature", 1.2)


def test_under_relaxation_relax_calculation():
    coupler = Coupler(name="relax_calc")
    coupler.set_under_relaxation("temp", 0.4)

    # First call with no prior value initializes and returns new_value
    val1 = coupler.relax("temp", 100.0)
    assert val1 == 100.0

    # Second call relaxes between 200.0 and prior 100.0: 0.4 * 200 + 0.6 * 100 = 140.0
    val2 = coupler.relax("temp", 200.0)
    assert pytest.approx(val2) == 140.0

    # Explicit old_value relaxes directly: 0.4 * 300 + 0.6 * 100 = 180.0
    val3 = coupler.relax("temp", 300.0, old_value=100.0)
    assert pytest.approx(val3) == 180.0


def test_divergence_detector_callback_triggers_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        case = Case(name="div_case", output_files={})
        case.database = Database(data={"RHO": [None]})

        coupler = Coupler(name="div_coupling")
        coupler.main_dir = tmpdir
        coupler.add_case(case, attributes=["RHO"])
        coupler.database = Database(data={"RHO": [1.0]})

        def custom_divergence_check(c):
            return True  # Force divergence trigger

        coupler.add_divergence_detector(custom_divergence_check)

        with pytest.raises(CouplingError, match="Coupling divergence detected"):
            coupler.launch_case(c_step=0)


def test_divergence_threshold_exceeded_triggers_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        case = Case(name="thresh_case", output_files={})
        case.database = Database(data={"RHO": [None]})

        coupler = Coupler(name="thresh_coupling")
        coupler.main_dir = tmpdir
        coupler.add_case(case, attributes=["RHO"])
        coupler.database = Database(data={"RHO": [50.0]})
        coupler.set_divergence_threshold("RHO", max_allowed=10.0)

        with pytest.raises(CouplingError, match="exceeds threshold"):
            coupler.launch_case(c_step=0)


def test_run_to_convergence_error_on_max_exec():
    with tempfile.TemporaryDirectory() as tmpdir:
        case = Case(name="conv_case", output_files={})
        case.database = Database(data={"RHO": [None]})

        coupler = Coupler(name="conv_coupling")
        coupler.main_dir = tmpdir
        coupler.add_case(case, attributes=["RHO"])
        coupler.database = Database(data={"RHO": [1.0]})

        # Non-converging check_fn with error_on_max_exec=False returns result without error
        res = coupler.run_to_convergence(max_exec=2, check_fn=lambda c: False, error_on_max_exec=False)
        assert res.converged is False
        assert res.executions == 2

        # With error_on_max_exec=True raises CouplingError
        with pytest.raises(CouplingError, match="failed to converge within max_exec=2"):
            coupler.run_to_convergence(max_exec=2, check_fn=lambda c: False, error_on_max_exec=True)

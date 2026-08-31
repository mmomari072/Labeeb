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

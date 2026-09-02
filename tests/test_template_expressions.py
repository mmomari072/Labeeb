import math
import os
import tempfile
import pytest

from labeeb import (
    Case,
    CaseExecutionError,
    Database,
    File,
    TemplateError,
    evaluate_expression,
    format_value,
)


def test_evaluate_expression_arithmetic_and_constants():
    assert evaluate_expression("1 + 2 * 3") == 7
    assert evaluate_expression("2 ** 4") == 16
    assert evaluate_expression("10 // 3") == 3
    assert evaluate_expression("10 % 3") == 1
    assert evaluate_expression("-5 + 10") == 5
    assert evaluate_expression("pi") == math.pi
    assert evaluate_expression("e") == math.e


def test_evaluate_expression_math_functions():
    assert evaluate_expression("sin(0)") == 0.0
    assert evaluate_expression("cos(0)") == 1.0
    assert evaluate_expression("sqrt(16)") == 4.0
    assert evaluate_expression("log10(100)") == 2.0
    assert evaluate_expression("exp(0)") == 1.0
    assert evaluate_expression("abs(-42.5)") == 42.5
    assert evaluate_expression("round(3.14159, 2)") == 3.14
    assert evaluate_expression("min(5, 2, 9)") == 2
    assert evaluate_expression("max(5, 2, 9)") == 9


def test_evaluate_expression_comparisons_and_ternary():
    assert evaluate_expression("10 > 5") is True
    assert evaluate_expression("10 == 5") is False
    assert evaluate_expression("100 if flag else 0", {"flag": True}) == 100
    assert evaluate_expression("100 if flag else 0", {"flag": False}) == 0
    assert evaluate_expression("x > 0 and y < 10", {"x": 5, "y": 2}) is True


def test_evaluate_expression_with_context_and_custom_functions():
    context = {
        "rho": 19.25,
        "volume": 100.0,
        "custom_scale": lambda val: val * 1.5,
    }
    assert evaluate_expression("rho * volume", context) == 1925.0
    assert evaluate_expression("custom_scale(rho)", context) == 28.875


def test_evaluate_expression_rejects_unsafe_and_malicious_syntax():
    with pytest.raises(TemplateError, match="forbidden|Disallowed|syntax"):
        evaluate_expression("__import__('os').system('echo 1')")

    with pytest.raises(TemplateError, match="forbidden|Disallowed|Undefined"):
        evaluate_expression("open('/etc/passwd')")

    with pytest.raises(TemplateError, match="private identifier|forbidden"):
        evaluate_expression("_secret + 1", {"_secret": 42})

    with pytest.raises(TemplateError, match="private attribute|forbidden"):
        evaluate_expression("obj.__class__.__name__", {"obj": 123})

    with pytest.raises(TemplateError, match="Disallowed syntax element"):
        evaluate_expression("[x for x in range(10)]")

    with pytest.raises(TemplateError, match="Disallowed syntax element"):
        evaluate_expression("lambda x: x + 1")


def test_evaluate_expression_error_handling():
    with pytest.raises(TemplateError, match="non-empty string"):
        evaluate_expression("")

    with pytest.raises(TemplateError, match="Invalid syntax"):
        evaluate_expression("1 +* 2")

    with pytest.raises(TemplateError, match="Division by zero"):
        evaluate_expression("1 / 0")

    with pytest.raises(TemplateError, match="Undefined variable"):
        evaluate_expression("undefined_var + 1")


def test_format_value_helpers():
    assert format_value(42.12345, "%6.2f") == " 42.12"
    assert format_value(0.0001234, "{:.2e}") == "1.23e-04"
    assert format_value(5, lambda v: f"VAL_{v:03d}") == "VAL_005"
    assert format_value(99, None) == "99"


def test_replace_assignments_basic_and_whitespace():
    f = File()
    f._db = [
        "x=1",
        "  y = 2.5  ",
        "z   =   -100",
        "other_x = 99",
        "x_suffix = 88",
    ]
    f.replace_assignments({"x": 42, "y": 7.5, "z": -200})
    assert f[0] == "x=42"
    assert f[1] == "  y = 7.5  "
    assert f[2] == "z   =   -200"
    assert f[3] == "other_x = 99"
    assert f[4] == "x_suffix = 88"


def test_replace_assignments_repeated_keys_and_separators():
    f = File()
    f._db = [
        "x=1, x=2, y=3; z=4",
        "repeat: x = 10, y = 20",
    ]
    f.replace_assignments({"x": 99, "y": 88, "z": 77})
    assert f[0] == "x=99, x=99, y=88; z=77"
    assert f[1] == "repeat: x = 99, y = 88"


def test_replace_assignments_scientific_notation():
    f = File()
    f._db = [
        "flux = 1.234e-04",
        "power = -4.50E+02, temp = +3.14159",
        "sigma = .75, norm = 100.",
    ]
    f.replace_assignments({
        "flux": 2.500e-04,
        "power": 5.00e02,
        "temp": 300.0,
        "sigma": 0.85,
        "norm": 200,
    })
    assert f[0] == "flux = 0.00025"
    assert f[1] == "power = 500.0, temp = 300.0"
    assert f[2] == "sigma = 0.85, norm = 200"


def test_replace_assignments_comment_preservation():
    f = File()
    f._db = [
        "x=1   $ mcnp comment with x=99",
        "y = 2 ! fortran comment with y=88",
        "z = 3 // c-style comment with z=77",
        "w = 4 # python comment with w=66",
        "# full line comment x=100",
        "$ full line mcnp x=100",
    ]
    f.replace_assignments({"x": 42, "y": 24, "z": 36, "w": 48})
    assert f[0] == "x=42   $ mcnp comment with x=99"
    assert f[1] == "y = 24 ! fortran comment with y=88"
    assert f[2] == "z = 36 // c-style comment with z=77"
    assert f[3] == "w = 48 # python comment with w=66"
    assert f[4] == "# full line comment x=100"
    assert f[5] == "$ full line mcnp x=100"


def test_replace_assignments_strict_mode():
    f = File()
    f._db = ["x = 1, y = 2"]

    # Present keys succeed
    f.replace_assignments({"x": 10, "y": 20}, strict=True)
    assert f[0] == "x = 10, y = 20"

    # Missing key in strict mode raises TemplateError (which is also CaseExecutionError)
    with pytest.raises(TemplateError, match="missing assignment key"):
        f.replace_assignments({"x": 10, "missing_var": 99}, strict=True)

    # Missing key in non-strict mode succeeds
    f.replace_assignments({"x": 50, "missing_var": 99}, strict=False)
    assert f[0] == "x = 50, y = 2"


def test_replace_assignments_formatting():
    f = File()
    f._db = ["rho = 1.0, power = 2.0, idx = 3"]

    # Dict format mapping
    f.replace_assignments(
        {"rho": 19.5268, "power": 123456.0, "idx": 7},
        fmt={"rho": "%6.2f", "power": "{:.2e}", "idx": lambda v: f"{v:03d}"},
    )
    assert f[0] == "rho =  19.53, power = 1.23e+05, idx = 007"


def test_replace_assignments_with_evaluated_expressions():
    f = File()
    f._db = ["mass = 1.0, energy = 2.0"]
    context = {"rho": 19.25, "vol": 10.0, "mass_val": 192.5, "c": 3e8}

    f.replace_assignments(
        {
            "mass": "rho * vol",
            "energy": "mass_val * c ** 2",
        },
        evaluate_expressions=True,
        context=context,
        fmt={"mass": "%.1f", "energy": "{:.2e}"},
    )
    assert f[0] == "mass = 192.5, energy = 1.73e+19"


def test_replace_assignments_invalid_inputs():
    f = File()
    f._db = ["x = 1"]

    with pytest.raises(TemplateError, match="must be a dictionary"):
        f.replace_assignments(["not", "a", "dict"])  # type: ignore[arg-type]

    with pytest.raises(TemplateError, match="non-empty string"):
        f.replace_assignments({"": 123})


def test_replace_expressions_basic_and_formatting():
    f = File()
    f._db = [
        "c Material definition",
        "m1  1001.70c ${h_ratio * 2.0 : %6.4f}  8016.70c ${o_ratio : %6.4f}",
        "s 1 0 0 0 ${radius + 1.5}",
        "power = ${p_mw * 1e6 : {:.2e}} $ target core power",
    ]

    f.replace_expressions({
        "h_ratio": 0.333333,
        "o_ratio": 0.666667,
        "radius": 10.0,
        "p_mw": 15.0,
    })

    assert f[0] == "c Material definition"
    assert f[1] == "m1  1001.70c 0.6667  8016.70c 0.6667"
    assert f[2] == "s 1 0 0 0 11.5"
    assert f[3] == "power = 1.50e+07 $ target core power"


def test_replace_expressions_custom_delimiters():
    f = File()
    f._db = ["VAL = #{x * 10}# and {{y + 5}}"]

    f.replace_expressions({"x": 3}, delimiters=("#{", "}#"), reset=True)
    f.replace_expressions({"y": 20}, delimiters=("{{", "}}"), reset=False)

    assert f[0] == "VAL = 30 and 25"


def test_replace_expressions_error_handling():
    f = File()
    f._db = ["val = ${bad_syntax +*}"]
    with pytest.raises(TemplateError, match="Invalid syntax"):
        f.replace_expressions({"x": 1})

    f._db = ["val = ${undefined_var}"]
    with pytest.raises(TemplateError, match="Undefined variable"):
        f.replace_expressions({"x": 1})

    f._db = ["val = ${1 / 0}"]
    with pytest.raises(TemplateError, match="Division by zero"):
        f.replace_expressions({})


def test_case_integration_with_assignments_and_expressions():
    with tempfile.TemporaryDirectory() as tmpdir:
        template_file = os.path.join(tmpdir, "deck.inp")
        with open(template_file, "w") as fid:
            fid.write(
                "title = Case Simulation\n"
                "rho = 1.0 $ base density\n"
                "power_watts = ${power_mw * 1e6 : {:.2e}}\n"
            )

        db = Database(
            name="sim_params",
            data={
                "DENSITY": [18.5, 19.2],
                "POWER_MW": [10.0, 20.0],
            },
        )

        case = Case(name="thermal_case", output_files={"out.csv": ["val"]})
        case.database = db
        case.main_dir = tmpdir
        case.run_case_main_dir = "runs"

        # Attach template file
        inp = File(file_path=template_file)
        inp.read()
        case.add_file(inp)

        # Configure assignment map and expression context
        case.set_assignment_map({"rho": "DENSITY"}, fmt={"rho": "%5.2f"}, strict=True)
        case.set_expression_context(strict=True)

        # Write input for case 0
        case.case_id = 0
        case.current_case_dir = os.path.join(tmpdir, "runs", "case_0")
        os.makedirs(case.current_case_dir, exist_ok=True)
        case._write_input({})

        # Check rendered file for case 0
        with open(os.path.join(case.current_case_dir, "deck.inp"), "r") as f:
            content_0 = f.read()
        assert "rho = 18.50 $ base density" in content_0
        assert "power_watts = 1.00e+07" in content_0

        # Write input for case 1
        case.case_id = 1
        case.current_case_dir = os.path.join(tmpdir, "runs", "case_1")
        os.makedirs(case.current_case_dir, exist_ok=True)
        case._write_input({})

        with open(os.path.join(case.current_case_dir, "deck.inp"), "r") as f:
            content_1 = f.read()
        assert "rho = 19.20 $ base density" in content_1
        assert "power_watts = 2.00e+07" in content_1

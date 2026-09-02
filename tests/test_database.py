import math
import os
import tempfile
import pytest
from labeeb.database import Attribute, Database
from labeeb.exceptions import DatabaseError


def test_attribute_creation():
    attr = Attribute(name="test_col", data=[1.0, 2.0, 3.0])
    assert len(attr) == 3
    assert attr[0] == 1.0
    assert attr.name == "test_col"


def test_attribute_math():
    attr1 = Attribute(name="a1", data=[1, 2, 3])
    attr2 = Attribute(name="a2", data=[10, 20, 30])

    # Element-wise addition
    result = attr1 + attr2
    assert list(result) == [11, 22, 33]

    # Element-wise multiplication with scalar
    result_scalar = attr1 * 2
    assert list(result_scalar) == [2, 4, 6]

    # Right hand side subtraction
    result_rsub = 10 - attr1
    assert list(result_rsub) == [9, 8, 7]


def test_attribute_division_by_zero():
    attr1 = Attribute(name="a1", data=[1, 0, -1])
    # Divide by 0 should return float("nan") or float("inf") / float("-inf")
    result = attr1 / 0
    import math
    assert result[0] == float("inf")
    assert math.isnan(result[1])
    assert result[2] == float("-inf")


def test_database_creation_and_alignment():
    # Database automatically aligns different lengths
    db = Database(name="my_db")
    attr1 = Attribute(name="col1", data=[1, 2])
    attr2 = Attribute(name="col2", data=[10, 20, 30])

    db.add_attribute(attr1, attr2)

    assert len(db) == 3  # Maximum length of column
    assert db["col1"][2] is None  # Resized and padded with None
    assert list(db["__db_index__"]) == [0, 1, 2]


def test_database_get_row():
    db = Database(data={"col1": [1, 2, 3], "col2": [10, 20, 30]})
    row_1 = db.get_row(1)
    assert row_1 == {"col1": 2, "col2": 20}

    # Slice rows
    sub_db = db.get_row([0, 2])
    assert list(sub_db["col1"]) == [1, 3]
    assert list(sub_db["col2"]) == [10, 30]


def test_database_io():
    db = Database(name="io_db", data={"col1": [1, 2], "col2": [10, 20]})

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = os.path.join(tmpdir, "test.csv")
        json_file = os.path.join(tmpdir, "test.json")

        # CSV export/import
        db.export_to_file(csv_file)
        new_db = Database()
        new_db.import_from_file(csv_file)
        assert list(new_db["col1"]) == [1.0, 2.0]  # Pandas read_csv loads numbers as float by default
        assert list(new_db["col2"]) == [10.0, 20.0]

        # JSON export/import
        db.to_json(json_file)
        new_json_db = Database()
        new_json_db.read_json(json_file)
        assert list(new_json_db["col1"]) == [1, 2]
        assert list(new_json_db["col2"]) == [10, 20]


def test_database_validation():
    # Valid column cast
    attr = Attribute(name="valid_col", data=[1, 2, 3], Type=float)
    attr.validate()

    # Invalid column cast
    attr_invalid = Attribute(name="invalid_col", data=[1, "not_a_float", 3], Type=float)
    with pytest.raises(DatabaseError):
        attr_invalid.validate()


def test_database_parquet_io():
    db = Database(data={"col1": [1.5, 2.5], "col2": [10, 20]})

    with tempfile.TemporaryDirectory() as tmpdir:
        pq_file = os.path.join(tmpdir, "test.parquet")
        db.to_parquet(pq_file)

        new_db = Database()
        new_db.read_parquet(pq_file)
        assert list(new_db["col1"]) == [1.5, 2.5]
        assert list(new_db["col2"]) == [10, 20]


def test_database_legacy_methods():
    # 1. Test Attribute legacy helpers
    attr = Attribute(name="my_col", data=[1, 2], Type=float)
    attr.add_data(3, [4, 5])
    assert list(attr) == [1.0, 2.0, 3.0, 4.0, 5.0]

    attr.remove_data(3.0)
    assert list(attr) == [1.0, 2.0, 4.0, 5.0]

    attr.set_index([0, 2])
    assert list(attr) == [1.0, 4.0]

    attr_mixed = Attribute(name="mixed", data=["1.5", "not_num", "2.5"])
    attr_mixed.convert_to_num()
    import math
    assert attr_mixed[0] == 1.5
    assert math.isnan(attr_mixed[1])
    assert attr_mixed[2] == 2.5

    stats = attr.statistics()
    assert stats["mean"] == 2.5

    # 2. Test Database legacy helpers
    db = Database(data={"col1": [10, 20], "col2": [100, 200]})
    db.select_attribute("col1")
    assert db.__selected_att__ == ["col1"]

    db.rename_attribute("col1", "new_col")
    assert "new_col" in db
    assert "col1" not in db

    local_namespace = {}
    db.export_variables(local_namespace)
    assert "new_col" in local_namespace
    assert "col2" in local_namespace
    assert local_namespace["new_col"][0] == 10


def test_database_derived_attribute_tracks_dependencies_and_recomputes():
    db = Database(data={"y": [1, 2, 3]})

    db.add_derived_attribute("x", lambda row: row["y"] + 1, dependencies=["y"])

    assert list(db["x"]) == [2, 3, 4]
    assert db.derived_attributes()["x"]["dependencies"] == ["y"]
    db["y"] = [10, 20, 30]
    assert list(db["x"]) == [11, 21, 31]


def test_database_derived_attribute_string_expressions():
    db = Database(data={"power_mw": [10.0, 20.0, 50.0], "efficiency": [0.33, 0.35, 0.40]})

    # Auto-inferred dependencies from string expression
    db.add_derived_attribute(
        "electric_power",
        "power_mw * efficiency",
        unit="MWe",
        description="Generated electric power",
    )

    assert list(db["electric_power"]) == pytest.approx([3.3, 7.0, 20.0])
    assert db["electric_power"].unit == "MWe"
    assert db.derived_attributes()["electric_power"]["dependencies"] == ["power_mw", "efficiency"]

    # Recomputing when power_mw changes
    db["power_mw"] = [100.0, 200.0, 500.0]
    assert list(db["electric_power"]) == pytest.approx([33.0, 70.0, 200.0])


def test_database_chained_topological_derived_attributes():
    db = Database(data={"a": [1, 2, 3]})

    # a -> b = a + 1 -> c = b * 2 -> d = c + a
    db.add_derived_attribute("b", "a + 1")
    db.add_derived_attribute("c", "b * 2")
    db.add_derived_attribute("d", "c + a")

    assert list(db["b"]) == [2, 3, 4]
    assert list(db["c"]) == [4, 6, 8]
    assert list(db["d"]) == [5, 8, 11]

    # Recompute cascading updates correctly
    db["a"] = [10, 20, 30]
    assert list(db["b"]) == [11, 21, 31]
    assert list(db["c"]) == [22, 42, 62]
    assert list(db["d"]) == [32, 62, 92]


def test_database_derived_attribute_set_row_and_update_row():
    db = Database(data={"y": [1, 2, 3]})
    db.add_derived_attribute("x", "y * 10")
    assert list(db["x"]) == [10, 20, 30]

    db.set_row(1, {"y": 5})
    assert list(db["x"]) == [10, 50, 30]

    db.update_row(2, {"y": 9})
    assert list(db["x"]) == [10, 50, 90]


def test_database_derived_attribute_vectorized():
    db = Database(data={"a": [1, 2, 3], "b": [4, 5, 6]})
    db.add_derived_attribute(
        "sum_ab",
        lambda database: database["a"] + database["b"],
        dependencies=["a", "b"],
        vectorized=True,
    )
    assert list(db["sum_ab"]) == [5, 7, 9]

    db["a"] = [10, 20, 30]
    assert list(db["sum_ab"]) == [14, 25, 36]


def test_database_derived_attribute_vectorized_string_expressions():
    db = Database(data={"theta": [0.0, math.pi / 2.0, math.pi], "radius": [10.0, 20.0, 30.0]})

    # Vectorized string expression using transcendental functions
    db.add_derived_attribute(
        "x_coord",
        "radius * cos(theta)",
        vectorized=True,
        unit="cm",
    )
    db.add_derived_attribute(
        "y_coord",
        "radius * sin(theta)",
        vectorized=True,
        unit="cm",
    )

    assert list(db["x_coord"]) == pytest.approx([10.0, 0.0, -30.0], abs=1e-6)
    assert list(db["y_coord"]) == pytest.approx([0.0, 20.0, 0.0], abs=1e-6)

    # Recomputing when theta changes
    db["theta"] = [math.pi / 2.0, math.pi, 0.0]
    assert list(db["x_coord"]) == pytest.approx([0.0, -20.0, 30.0], abs=1e-6)
    assert list(db["y_coord"]) == pytest.approx([10.0, 0.0, 0.0], abs=1e-6)


def test_database_derived_attribute_vectorized_advanced_math():
    db = Database(data={"val": [1.0, 4.0, 9.0], "decay": [0.1, 0.2, 0.3]})
    db.add_derived_attribute("root_val", "sqrt(val)", vectorized=True)
    db.add_derived_attribute("exp_decay", "exp(-decay)", vectorized=True)

    assert list(db["root_val"]) == pytest.approx([1.0, 2.0, 3.0])
    assert list(db["exp_decay"]) == pytest.approx([math.exp(-0.1), math.exp(-0.2), math.exp(-0.3)])


def test_database_rejects_missing_and_circular_derived_dependencies():
    db = Database(data={"y": [1]})
    with pytest.raises(DatabaseError, match="missing dependencies"):
        db.add_derived_attribute("x", lambda row: row["z"], dependencies=["z"])

    with pytest.raises(DatabaseError, match="cannot depend on itself"):
        db.add_derived_attribute("y", "y + 1", dependencies=["y"])

    db.add_derived_attribute("x", lambda row: row["y"], dependencies=["y"])
    with pytest.raises(DatabaseError, match="Circular derived attribute dependency"):
        db.add_derived_attribute("y", lambda row: row["x"], dependencies=["x"])


def test_database_deletion_protection_and_remove_derived():
    db = Database(data={"y": [1, 2, 3]})
    db.add_derived_attribute("x", "y + 1")
    db.add_derived_attribute("z", "x * 2")

    # Cannot delete column if derived attribute depends on it
    with pytest.raises(DatabaseError, match="Cannot delete column"):
        del db["y"]

    with pytest.raises(DatabaseError, match="Cannot delete column"):
        del db["x"]

    # Cannot remove derived attribute x while z depends on it
    with pytest.raises(DatabaseError, match="Cannot remove derived attribute"):
        db.remove_derived_attribute("x")

    # Successfully remove z then x
    db.remove_derived_attribute("z")
    assert "z" not in db
    assert "z" not in db.derived_attributes()

    db.remove_derived_attribute("x")
    assert "x" not in db
    assert "x" not in db.derived_attributes()

    # Now y can be deleted cleanly
    del db["y"]
    assert "y" not in db


def test_database_context_derived_attribute_scalar_and_lagged():
    db = Database(data={"power": [10.0, 20.0, 30.0], "time": [1.0, 2.0, 3.0]})

    # 1. Cumulative sum using (database, index)
    db.add_derived_attribute(
        "cum_energy",
        lambda database, index: sum(database["power"][: index + 1]),
        context="database",
        unit="MWs",
    )
    assert list(db["cum_energy"]) == [10.0, 30.0, 60.0]

    # 2. Lagged value using (database, index=None)
    def prev_power(database, index=None):
        if index is None or index == 0:
            return 0.0
        return database["power"][index - 1]

    db.add_derived_attribute(
        "power_lag1",
        prev_power,
        context="database",
    )
    assert list(db["power_lag1"]) == [0.0, 10.0, 20.0]

    # 3. Access global statistics in row evaluation
    db.add_derived_attribute(
        "delta_from_mean",
        lambda db, idx: db["power"][idx] - (sum(db["power"]) / len(db["power"])),
        context="database",
    )
    assert list(db["delta_from_mean"]) == [-10.0, 0.0, 10.0]


def test_database_context_derived_attribute_vectorized():
    db = Database(data={"val": [10, 20, 30]})

    # Vectorized callback receiving database object
    db.add_derived_attribute(
        "doubled",
        lambda database: [x * 2 for x in database["val"]],
        context="database",
        vectorized=True,
    )
    assert list(db["doubled"]) == [20, 40, 60]

    # Scalar broadcasting in vectorized callback
    db.add_derived_attribute(
        "global_mean",
        lambda database: sum(database["val"]) / len(database["val"]),
        context="database",
        vectorized=True,
    )
    assert list(db["global_mean"]) == [20.0, 20.0, 20.0]


def test_database_context_dynamic_dependencies_conservative_refresh():
    db = Database(data={"a": [1, 2, 3], "b": [10, 20, 30]})

    # Derived attribute with omitted dependencies -> dynamic dependencies
    db.add_derived_attribute(
        "cross_sum",
        lambda db, idx: db["a"][idx] + db["b"][idx],
        context="database",
    )
    assert list(db["cross_sum"]) == [11, 22, 33]

    # Check metadata reflects dynamic_dependencies
    meta = db.derived_attributes()["cross_sum"]
    assert meta["context"] == "database"
    assert meta["dynamic_dependencies"] is True
    assert meta["dependencies"] is None

    # Modifying column a triggers conservative refresh
    db["a"] = [10, 20, 30]
    assert list(db["cross_sum"]) == [20, 40, 60]

    # Modifying via set_row triggers refresh
    db.set_row(0, {"b": 50})
    assert list(db["cross_sum"]) == [60, 40, 60]


def test_database_context_explicit_dependencies_validation_and_cycles():
    db = Database(data={"x": [1, 2, 3]})

    # Explicit dependencies with context='database'
    db.add_derived_attribute(
        "y",
        lambda db, idx: db["x"][idx] + 5,
        dependencies=["x"],
        context="database",
    )
    assert list(db["y"]) == [6, 7, 8]

    meta = db.derived_attributes()["y"]
    assert meta["context"] == "database"
    assert meta["dynamic_dependencies"] is False
    assert meta["dependencies"] == ["x"]

    # Missing explicit dependency error
    with pytest.raises(DatabaseError, match="missing dependencies"):
        db.add_derived_attribute(
            "bad_dep",
            lambda db, idx: 0,
            dependencies=["nonexistent"],
            context="database",
        )

    # Self dependency error
    with pytest.raises(DatabaseError, match="cannot depend on itself"):
        db.add_derived_attribute(
            "x",
            lambda db, idx: 0,
            dependencies=["x"],
            context="database",
        )

    # Circular dependency error
    with pytest.raises(DatabaseError, match="Circular derived attribute dependency"):
        db.add_derived_attribute(
            "x",
            lambda db, idx: db["y"][idx],
            dependencies=["y"],
            context="database",
        )

    # Deletion protection when explicit dependency exists
    with pytest.raises(DatabaseError, match="Cannot delete column 'x'"):
        del db["x"]


def test_database_context_rejections_and_invalid_signatures():
    db = Database(data={"x": [1, 2, 3]})

    # Invalid context name
    with pytest.raises(DatabaseError, match="Derived attribute context must be 'row' or 'database'"):
        db.add_derived_attribute("y", lambda row: row["x"], context="invalid_context")

    # Invalid callback signature error wrapped in DatabaseError
    def incompatible_signature(a, b, c, d, e):
        return a + b

    with pytest.raises(DatabaseError, match="Evaluation of derived attribute 'broken' failed"):
        db.add_derived_attribute("broken", incompatible_signature, context="database")

    # Vectorized callback returning mismatched length
    def bad_vector_length(database):
        return [1, 2]  # length 2 instead of 3

    with pytest.raises(DatabaseError, match="expected 3"):
        db.add_derived_attribute("bad_len", bad_vector_length, context="database", vectorized=True)

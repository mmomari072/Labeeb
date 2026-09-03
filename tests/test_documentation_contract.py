import os
import pytest


def test_v2_migration_guide_exists_and_contains_required_sections():
    guide_path = os.path.join("docs", "V2_MIGRATION_GUIDE.md")
    assert os.path.exists(guide_path), "docs/V2_MIGRATION_GUIDE.md must exist"

    with open(guide_path, "r", encoding="utf-8") as f:
        content = f.read()

    required_sections = [
        "# Labeeb v2.0.0 Migration & API Contract Guide",
        "## 1. Migration Overview & Compatibility Guarantees",
        "## 2. Core v2 Component Contracts",
        "### 2.1 Campaign & Case",
        "### 2.2 Database & Derived Attributes",
        "### 2.3 File & Template Replacements",
        "### 2.4 Coupler & CoupledUnit",
        "### 2.5 Optimizer & Sampling",
        "## 3. Breaking Changes & Deprecations",
        "## 4. Result Schemas & Artifact Exports",
    ]

    for section in required_sections:
        assert section in content, f"Migration guide must contain section '{section}'"


def test_v2_documentation_cross_references():
    readme_path = "README.md"
    arch_path = "ARCHITECTURE.md"
    dev_guide_path = os.path.join("docs", "DEVELOPER_GUIDE.md")

    with open(readme_path, "r", encoding="utf-8") as f:
        readme_content = f.read()
    assert "V2_MIGRATION_GUIDE.md" in readme_content, "README.md must link to V2_MIGRATION_GUIDE.md"

    with open(arch_path, "r", encoding="utf-8") as f:
        arch_content = f.read()
    assert "2.7 V2 API Architecture & Migration Contract" in arch_content, "ARCHITECTURE.md must document v2 contract"

    with open(dev_guide_path, "r", encoding="utf-8") as f:
        dev_content = f.read()
    assert "V2_MIGRATION_GUIDE.md" in dev_content, "DEVELOPER_GUIDE.md must link to V2_MIGRATION_GUIDE.md"


def test_v2_migration_snippets_executable():
    from labeeb import Campaign, Case, Database, File

    # Verify snippet 1: Database & derived attributes
    db = Database(data={"POWER": [10.0, 15.0, 20.0]})
    db.add_derived_attribute("POWER_KW", "POWER * 1000.0", unit="kW")

    def _power_delta(database, idx):
        if idx == 0:
            return 0.0
        return database["POWER"][idx] - database["POWER"][idx - 1]

    db.add_derived_attribute("POWER_DELTA", _power_delta, context="database", dependencies=["POWER"])
    assert list(db["POWER_KW"]) == [10000.0, 15000.0, 20000.0]
    assert list(db["POWER_DELTA"]) == [0.0, 5.0, 5.0]

    # Verify snippet 2: File replace_assignment
    f = File()
    f._db = ["POWER = 10.0 $ MW"]
    rendered = f.replace_assignment("POWER", 50.0)
    assert "POWER = 50.0 $ MW" in rendered

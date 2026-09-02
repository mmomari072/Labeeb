"""Focused tests for API-first backup/restore of campaign state + artifacts
with sqlite-safe semantics, manifests/checksums, atomic restore, and the
explicit shared-memory snapshot policy (LAB-DATABASE-BACKUP-01)."""

import json
import sqlite3
from pathlib import Path

import pytest

from labeeb import (
    BackupError,
    CampaignStateStore,
    CaseResult,
    create_backup,
    restore_backup,
    validate_backup,
)


def _seed_state(path, rows=3):
    with CampaignStateStore(path) as state:
        for case_id in range(rows):
            state.save(
                CaseResult(case_id, {"RHO": 19.0 + case_id}, "SUCCESS", 0, 0.1, metrics={"keff": 1.0 + case_id}),
                f"hash-{case_id}",
            )
    return path


def _seed_artifacts(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "case_0").mkdir(exist_ok=True)
    (root / "case_0" / "deck.inp").write_text("TITLE run\n", encoding="utf-8")
    (root / "case_0" / "out.csv").write_text("keff\n1.0001\n", encoding="utf-8")
    (root / "notes.txt").write_text("run notes\n", encoding="utf-8")
    return root


def _load_manifest(backup_dir):
    return json.loads((Path(backup_dir) / "manifest.json").read_text(encoding="utf-8"))


# --- create ------------------------------------------------------------------

def test_create_backup_snapshots_state_and_artifacts(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    artifacts = _seed_artifacts(tmp_path / "runs")
    dest = tmp_path / "backup_1"

    result = create_backup(dest, state_path=state, artifacts=[artifacts])

    assert result == dest and dest.is_dir()
    manifest = _load_manifest(dest)
    assert manifest["format"] == "labeeb-backup"
    assert manifest["version"] == 1
    assert manifest["created_at"]

    paths = {entry["path"] for entry in manifest["files"]}
    assert any(p.startswith("sqlite/state.sqlite") for p in paths)
    assert "artifacts/runs/case_0/deck.inp" in paths
    assert "artifacts/runs/case_0/out.csv" in paths
    assert "artifacts/runs/notes.txt" in paths
    assert all(entry["sha256"] for entry in manifest["files"])
    # no staging leftovers
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".labeeb-backup-staging-")]


def test_backup_state_is_consistent_sqlite_snapshot(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "backup_db"
    create_backup(dest, state_path=state)

    backup_db = dest / "sqlite" / "state.sqlite"
    with sqlite3.connect(str(backup_db)) as connection:
        rows = connection.execute("SELECT case_id, status FROM campaign_cases ORDER BY case_id").fetchall()
    assert [row[0] for row in rows] == [0, 1, 2]
    assert all(row[1] == "SUCCESS" for row in rows)


def test_create_backup_refuses_occupied_destination(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "junk.txt").write_text("junk", encoding="utf-8")
    with pytest.raises(BackupError, match="exists and is not empty"):
        create_backup(dest, state_path=state)


def test_create_backup_empty_dest_requires_overwrite_flag(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "empty_dir"
    dest.mkdir()
    with pytest.raises(BackupError, match="already exists"):
        create_backup(dest, state_path=state)
    # overwrite=True publishes into the empty existing directory
    result = create_backup(dest, state_path=state, overwrite=True)
    assert (result / "manifest.json").is_file()


def test_create_backup_validates_inputs(tmp_path):
    with pytest.raises(BackupError, match="does not exist"):
        create_backup(tmp_path / "b1", state_path=tmp_path / "missing.sqlite")
    state = _seed_state(tmp_path / "state.sqlite")
    with pytest.raises(BackupError, match="does not exist"):
        create_backup(tmp_path / "b2", state_path=state, artifacts=[tmp_path / "nope"])


# --- shared-memory policy ------------------------------------------------------

def test_memory_is_never_backed_up_implicitly(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "bk_no_mem"
    create_backup(dest, state_path=state)  # no memory_snapshot passed

    manifest = _load_manifest(dest)
    assert manifest["shared_memory"]["included"] is False
    assert manifest["shared_memory"]["policy"] == "explicit-opt-in"
    assert not (dest / "shared_memory.json").exists()


def test_explicit_memory_snapshot_is_exported(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    snapshot = {"case_0": {"keff": 1.0}, "online": {"count": 1}}
    dest = tmp_path / "bk_mem"
    create_backup(dest, state_path=state, memory_snapshot=snapshot)

    manifest = _load_manifest(dest)
    assert manifest["shared_memory"]["included"] is True
    stored = json.loads((dest / "shared_memory.json").read_text(encoding="utf-8"))
    assert stored == snapshot
    entry = next(e for e in manifest["files"] if e["path"] == "shared_memory.json")
    assert entry["sha256"]


# --- validate ------------------------------------------------------------------

def test_validate_backup_detects_tampering(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    artifacts = _seed_artifacts(tmp_path / "runs")
    dest = tmp_path / "backup_t"
    create_backup(dest, state_path=state, artifacts=[artifacts])

    assert validate_backup(dest)  # clean validation passes

    target = dest / "artifacts" / "runs" / "notes.txt"
    target.write_text("run noteZ\n", encoding="utf-8")  # same length -> checksum failure
    with pytest.raises(BackupError, match="checksum does not match"):
        validate_backup(dest)


def test_validate_backup_detects_missing_file_and_bad_version(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "backup_v"
    create_backup(dest, state_path=state)

    # Missing listed file
    hidden = dest / "sqlite" / "state.sqlite.hidden"
    (dest / "sqlite" / "state.sqlite").rename(hidden)
    with pytest.raises(BackupError, match="listed in manifest is missing"):
        validate_backup(dest)
    hidden.rename(dest / "sqlite" / "state.sqlite")

    # Unsupported future version
    manifest_path = dest / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = 99
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError, match="Unsupported backup manifest version"):
        validate_backup(dest)


def test_validate_backup_rejects_non_backup_directory(tmp_path):
    other = tmp_path / "not_a_backup"
    other.mkdir()
    with pytest.raises(BackupError, match="missing manifest"):
        validate_backup(other)


def test_validate_backup_checks_sqlite_integrity(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "backup_i"
    create_backup(dest, state_path=state)

    # Corrupt the backed-up database page so quick_check fails
    db = dest / "sqlite" / "state.sqlite"
    data = bytearray(db.read_bytes())
    data[100:104] = b"\xff\xff\xff\xff"
    db.write_bytes(bytes(data))
    with pytest.raises(BackupError, match="integrity|checksum"):
        validate_backup(dest)


# --- restore --------------------------------------------------------------------

def test_restore_state_and_artifacts(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    artifacts = _seed_artifacts(tmp_path / "runs")
    dest = tmp_path / "backup_r"
    create_backup(dest, state_path=state, artifacts=[artifacts])

    restored_state = tmp_path / "restored" / "state.sqlite"
    restored_artifacts = tmp_path / "restored_runs"
    manifest = restore_backup(dest, state_path=restored_state, artifacts_root=restored_artifacts)

    assert manifest.version == 1
    with CampaignStateStore(restored_state) as reopened:
        assert reopened.case_ids() == [0, 1, 2]
        row = reopened.get(2)
        assert row is not None and row["status"] == "SUCCESS"
    assert (restored_artifacts / "runs" / "case_0" / "deck.inp").read_text(encoding="utf-8") == "TITLE run\n"
    assert (restored_artifacts / "runs" / "notes.txt").is_file()


def test_restore_requires_state_entry_when_requested(tmp_path):
    dest = tmp_path / "bk_no_state"
    create_backup(dest, artifacts=[_seed_artifacts(tmp_path / "runs")])
    with pytest.raises(BackupError, match="no campaign state database"):
        restore_backup(dest, state_path=tmp_path / "x.sqlite")
    # artifacts-only restore works
    manifest = restore_backup(dest, artifacts_root=tmp_path / "out_artifacts")
    assert manifest.files


def test_restore_refuses_tampered_backup(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "backup_t2"
    create_backup(dest, state_path=state)
    (dest / "sqlite" / "state.sqlite").write_bytes(b"corrupted-not-sqlite" * 10)
    with pytest.raises(BackupError):
        restore_backup(dest, state_path=tmp_path / "never.sqlite")
    assert not (tmp_path / "never.sqlite").exists()


def test_restore_is_atomic_on_target(tmp_path):
    state = _seed_state(tmp_path / "state.sqlite")
    dest = tmp_path / "backup_a"
    create_backup(dest, state_path=state)

    target = tmp_path / "live.sqlite"
    with CampaignStateStore(target) as store:  # pre-existing live database
        store.save(CaseResult(9, {"x": 1}, "SUCCESS", 0, 0.1), "h9")
    restore_backup(dest, state_path=target)
    with CampaignStateStore(target) as reopened:
        assert reopened.case_ids() == [0, 1, 2]  # replaced, not merged

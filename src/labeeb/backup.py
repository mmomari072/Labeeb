"""API-first backup and restore for campaign state, run artifacts, and (on
explicit request) shared-memory snapshots (DATABASE-BACKUP-01).

Backup semantics:

* SQLite files (``CampaignStateStore`` state databases) are captured with the
  sqlite3 online-backup API (``connection.backup()``) from a read-only
  connection — never by copying the live file — giving a consistent snapshot
  even if another process is writing.
* Artifacts (run directories/files) are copied byte-for-byte.
* Every backup carries a ``manifest.json`` with format/version metadata,
  creation time, per-file SHA-256 checksums, and an explicit shared-memory
  policy record.
* Backups are staged in the destination's parent directory and atomically
  published with ``os.replace``; an existing non-empty destination is never
  overwritten.
* ``validate_backup`` re-checksums every file and runs SQLite ``quick_check``
  on the state database before any restore.
* Shared-memory snapshots are NEVER included implicitly: only an explicitly
  provided ``memory_snapshot`` mapping is exported (as ``shared_memory.json``);
  otherwise the manifest records that memory was deliberately excluded.
"""

import hashlib
import json
import os
import sqlite3
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .exceptions import BackupError

MANIFEST_FORMAT = "labeeb-backup"
MANIFEST_VERSION = 1
_MANIFEST_NAME = "manifest.json"
_SQLITE_DIR = "sqlite"
_ARTIFACTS_DIR = "artifacts"
_MEMORY_NAME = "shared_memory.json"
_STAGING_PREFIX = ".labeeb-backup-staging-"


@dataclass
class BackupManifest:
    """Metadata describing one finished backup directory."""

    version: int = MANIFEST_VERSION
    created_at: str = ""
    source: Dict[str, Any] = field(default_factory=dict)
    files: List[Dict[str, Any]] = field(default_factory=list)
    shared_memory: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible mapping (with the format marker)."""
        return {
            "format": MANIFEST_FORMAT,
            "version": self.version,
            "created_at": self.created_at,
            "source": dict(self.source),
            "files": [dict(entry) for entry in self.files],
            "shared_memory": dict(self.shared_memory),
        }

    @classmethod
    def from_dict(cls, record: Dict[str, Any]) -> "BackupManifest":
        """Rebuild a manifest from a parsed mapping, validating format/version."""
        if record.get("format") != MANIFEST_FORMAT:
            raise BackupError(
                f"Not a labeeb backup manifest (format={record.get('format')!r})"
            )
        version = int(record.get("version", 0))
        if version != MANIFEST_VERSION:
            raise BackupError(
                f"Unsupported backup manifest version {version} "
                f"(supported: {MANIFEST_VERSION})"
            )
        return cls(
            version=version,
            created_at=str(record.get("created_at", "")),
            source=dict(record.get("source", {})),
            files=[dict(entry) for entry in record.get("files", [])],
            shared_memory=dict(record.get("shared_memory", {})),
        )


# -- helpers ---------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel_entries(root: Path) -> List[Path]:
    """Return every file under ``root`` as a path relative to it."""
    if root.is_file():
        return [Path(root.name)]
    return [path.relative_to(root) for path in sorted(root.rglob("*")) if path.is_file()]


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst_root: Path) -> None:
    dst_root.mkdir(parents=True, exist_ok=True)
    for rel in _rel_entries(src):
        _copy_file(src / rel, dst_root / rel)


def _backup_sqlite(source: Path, destination: Path) -> None:
    """Snapshot a SQLite file with the online-backup API (read-only source)."""
    if not source.is_file():
        raise BackupError(f"SQLite state file '{source}' does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"Failed to open SQLite state '{source}': {exc}") from exc
    try:
        target_connection = sqlite3.connect(str(destination))
        try:
            last_error: Optional[Exception] = None
            for _ in range(3):
                try:
                    source_connection.backup(target_connection)
                    break
                except sqlite3.OperationalError as exc:  # busy writer
                    last_error = exc
            else:
                raise BackupError(
                    f"SQLite backup of '{source}' stayed busy; close writer handles and retry"
                ) from last_error
        finally:
            target_connection.close()
    finally:
        source_connection.close()


def _quick_check(path: Path) -> str:
    """Return the result of SQLite ``PRAGMA quick_check`` on a file."""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"Failed to open SQLite file '{path}': {exc}") from exc
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
        if row is None or row[0] != "ok":
            raise BackupError(f"SQLite integrity check failed for '{path}': {row}")
        return str(row[0])
    finally:
        connection.close()


def _restore_file_atomic(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` via a sibling temp file + atomic replace."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    staging = dst.parent / f".{dst.name}.restore-{uuid.uuid4().hex}"
    shutil.copy2(src, staging)
    os.replace(staging, dst)


# -- public API ---------------------------------------------------------------


def create_backup(
    destination: Union[str, Path],
    *,
    state_path: Optional[Union[str, Path]] = None,
    artifacts: Sequence[Union[str, Path]] = (),
    memory_snapshot: Optional[Dict[str, Any]] = None,
    overwrite: bool = False,
) -> Path:
    """Create a validated, atomic backup directory and return its path.

    Args:
        destination: Final backup directory. It must not exist (or must be an
            existing empty directory when ``overwrite=True``); the backup is
            staged next to it and atomically renamed into place.
        state_path: Optional SQLite campaign state file (e.g. a
            :class:`~labeeb.results.CampaignStateStore` database) captured with
            sqlite-safe online backup semantics.
        artifacts: Optional files or directories (run outputs) copied verbatim
            into ``<backup>/artifacts/``.
        memory_snapshot: Optional explicit shared-memory snapshot mapping
            (e.g. ``CampaignMemory.snapshot()``). Shared memory is NEVER backed
            up implicitly; pass this mapping to opt in. When omitted the
            manifest records the exclusion explicitly.
        overwrite: Allow publishing over an existing *empty* destination
            directory. Non-empty destinations are never overwritten.

    Returns:
        The finalized backup directory containing ``manifest.json``.

    Raises:
        BackupError: On invalid inputs, busy SQLite sources, or an occupied
            destination.
    """
    destination = Path(destination)
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise BackupError(
                f"Backup destination '{destination}' exists and is not empty; "
                f"choose a new destination"
            )
        if not overwrite:
            raise BackupError(
                f"Backup destination '{destination}' already exists (use overwrite=True "
                f"to replace an empty directory)"
            )

    staging = parent / f"{_STAGING_PREFIX}{uuid.uuid4().hex}"
    staging.mkdir()
    source_entries: List[Dict[str, Any]] = []
    try:
        # 1. SQLite state via the online-backup API
        if state_path is not None:
            state = Path(state_path)
            if not state.is_file():
                raise BackupError(f"State path '{state}' does not exist")
            db_file = staging / _SQLITE_DIR / state.name
            _backup_sqlite(state, db_file)
            source_entries.append(
                {
                    "role": "campaign_state",
                    "original": state.name,
                    "path": f"{_SQLITE_DIR}/{state.name}",
                }
            )

        # 2. Run artifacts (byte-for-byte copy)
        artifact_names: List[str] = []
        for artifact in artifacts:
            source = Path(artifact)
            if not source.exists():
                raise BackupError(f"Artifact '{source}' does not exist")
            target = staging / _ARTIFACTS_DIR / source.name
            if source.is_dir():
                _copy_tree(source, target)
            else:
                _copy_file(source, target)
            artifact_names.append(source.name)

        # 3. Optional explicit shared-memory snapshot export
        memory_record: Dict[str, Any] = {
            "policy": "explicit-opt-in",
            "included": memory_snapshot is not None,
            "note": "shared memory is derived/volatile and is only exported when "
            "memory_snapshot is explicitly provided",
        }
        if memory_snapshot is not None:
            memory_path = staging / _MEMORY_NAME
            memory_path.write_text(
                json.dumps(memory_snapshot, sort_keys=True, default=str),
                encoding="utf-8",
            )
            memory_record["file"] = _MEMORY_NAME
            memory_record["entries"] = len(memory_snapshot)

        # 4. Manifest with per-file checksums
        files: List[Dict[str, Any]] = []
        for path in sorted(staging.rglob("*")):
            if path.is_file() and path.name != _MANIFEST_NAME:
                files.append(
                    {
                        "path": path.relative_to(staging).as_posix(),
                        "size": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                )
        manifest = BackupManifest(
            created_at=_now(),
            source={
                "state_path": str(state_path) if state_path is not None else None,
                "artifacts": artifact_names,
                "tool": "labeeb DATABASE-BACKUP-01",
            },
            files=files,
            shared_memory=memory_record,
        )
        manifest_target = staging / _MANIFEST_NAME
        _atomic_write_text(manifest_target, json.dumps(manifest.to_dict(), indent=2, sort_keys=True))

        # 5. Atomic publish
        try:
            os.replace(staging, destination)
        except OSError as exc:
            raise BackupError(
                f"Failed to atomically publish backup at '{destination}': {exc}"
            ) from exc
        return destination
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def validate_backup(backup_dir: Union[str, Path]) -> BackupManifest:
    """Verify a backup directory: manifest format/version, every checksum, and
    SQLite integrity of any contained state database.

    Raises:
        BackupError: On any mismatch or integrity failure.
    """
    root = Path(backup_dir)
    manifest_path = root / _MANIFEST_NAME
    if not manifest_path.is_file():
        raise BackupError(f"'{root}' is not a labeeb backup (missing manifest.json)")
    try:
        manifest = BackupManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise BackupError(f"Backup manifest is not valid JSON: {exc}") from exc

    seen: set = set()
    for entry in manifest.files:
        rel = entry.get("path")
        if not rel or rel in seen:
            raise BackupError(f"Backup manifest has invalid or duplicate file entry: {entry!r}")
        seen.add(rel)
        target = root / rel
        if not target.is_file():
            raise BackupError(f"Backup file '{rel}' listed in manifest is missing")
        if target.stat().st_size != int(entry.get("size", -1)):
            raise BackupError(f"Backup file '{rel}' size does not match manifest")
        if _sha256(target) != entry.get("sha256"):
            raise BackupError(f"Backup file '{rel}' checksum does not match manifest")

    state_entries = [e for e in manifest.files if e.get("path", "").startswith(f"{_SQLITE_DIR}/")]
    for entry in state_entries:
        _quick_check(root / entry["path"])
    return manifest


def restore_backup(
    backup_dir: Union[str, Path],
    *,
    state_path: Optional[Union[str, Path]] = None,
    artifacts_root: Optional[Union[str, Path]] = None,
) -> BackupManifest:
    """Validate a backup and restore its contents.

    Args:
        backup_dir: The backup directory (as returned by :func:`create_backup`).
        state_path: Destination for the campaign state database. The restored
            database is written to a sibling temp file and atomically moved into
            place. Close any open handles on the target before restoring.
        artifacts_root: Destination directory receiving the backup's
            ``artifacts/`` tree (files are restored via atomic per-file
            replacement).

    Returns:
        The validated manifest describing what was restored.

    Raises:
        BackupError: If validation fails, no state database exists when
            ``state_path`` is requested, or the artifacts tree is empty when
            ``artifacts_root`` is requested.
    """
    root = Path(backup_dir)
    manifest = validate_backup(root)

    if state_path is not None:
        state_entries = [e for e in manifest.files if e.get("path", "").startswith(f"{_SQLITE_DIR}/")]
        if not state_entries:
            raise BackupError("Backup contains no campaign state database to restore")
        db_entry = state_entries[0]
        target = Path(state_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_db = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}"
        try:
            _backup_sqlite(root / db_entry["path"], temp_db)
            _quick_check(temp_db)
            os.replace(temp_db, target)
        except Exception:
            if temp_db.exists():
                temp_db.unlink()
            raise

    if artifacts_root is not None:
        artifacts_src = root / _ARTIFACTS_DIR
        if not artifacts_src.is_dir():
            raise BackupError("Backup contains no artifacts tree to restore")
        target_root = Path(artifacts_root)
        for rel in _rel_entries(artifacts_src):
            _restore_file_atomic(artifacts_src / rel, target_root / rel)

    return manifest


def _atomic_write_text(path: Path, content: str) -> None:
    staging = path.parent / f".{path.name}.{uuid.uuid4().hex}"
    staging.write_text(content, encoding="utf-8")
    os.replace(staging, path)

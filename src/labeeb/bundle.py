"""
Exportable, reproducible Analysis Bundles for simulation campaigns.
Supports redacted JSON and ZIP archive packaging with manifests, provenance,
results, execution events, opt-in artifacts, and replay/import validation.
"""

import copy
import json
import logging
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .exceptions import LabeebError

logger = logging.getLogger(__name__)


class BundleError(LabeebError):
    """Raised when analysis bundle creation, validation, or loading fails."""


def _redact_data(data: Any, redact_keys: set) -> Any:
    """Recursively redact keys matching redact_keys."""
    if not redact_keys:
        return data
    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            if k in redact_keys:
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = _redact_data(v, redact_keys)
        return redacted
    elif isinstance(data, list):
        return [_redact_data(item, redact_keys) for item in data]
    return data


class AnalysisBundle:
    """
    Encapsulates a self-contained, reproducible simulation campaign export bundle.
    """

    SCHEMA_VERSION = "1.0.0"

    def __init__(
        self,
        manifest: Dict[str, Any],
        provenance: Dict[str, Any],
        results: List[Dict[str, Any]],
        events: Optional[List[Dict[str, Any]]] = None,
        artifacts: Optional[Dict[str, Any]] = None,
        redact_keys: Optional[Sequence[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.manifest: Dict[str, Any] = copy.deepcopy(manifest)
        self.provenance: Dict[str, Any] = copy.deepcopy(provenance)
        self.results: List[Dict[str, Any]] = copy.deepcopy(results)
        self.events: List[Dict[str, Any]] = copy.deepcopy(events) if events else []
        self.artifacts: Dict[str, Any] = copy.deepcopy(artifacts) if artifacts else {}
        self.redact_keys: set = set(redact_keys) if redact_keys else set()
        self.metadata: Dict[str, Any] = copy.deepcopy(metadata) if metadata else {
            "schema_version": self.SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "python_version": sys.version,
            "platform": platform.platform(),
        }

    @classmethod
    def from_campaign(
        cls,
        campaign: Any,
        results: Optional[Sequence[Any]] = None,
        publisher: Optional[Any] = None,
        artifacts: Optional[Dict[str, Union[str, Path]]] = None,
        redact_keys: Optional[Sequence[str]] = None,
    ) -> "AnalysisBundle":
        """Build an AnalysisBundle from an executed Campaign instance."""
        manifest_data = getattr(campaign.manifest, "to_dict", lambda: dict(campaign.manifest))() if hasattr(campaign, "manifest") else {}
        provenance_data = campaign.manifest.provenance() if hasattr(campaign.manifest, "provenance") else {}

        # Collect results
        raw_results: List[Dict[str, Any]] = []
        if results is not None:
            for r in results:
                if hasattr(r, "to_record") and callable(r.to_record):
                    raw_results.append(r.to_record())
                elif hasattr(r, "to_dict") and callable(r.to_dict):
                    raw_results.append(r.to_dict())
                elif isinstance(r, dict):
                    raw_results.append(r)

        # Collect events
        events_list: List[Dict[str, Any]] = []
        pub = publisher or getattr(campaign, "publisher", None)
        if pub is not None and hasattr(pub, "get_buffered_events"):
            events_list = pub.get_buffered_events()

        # Collect artifact references
        artifact_refs: Dict[str, Any] = {}
        if artifacts:
            for key, path in artifacts.items():
                p = Path(path)
                artifact_refs[key] = {
                    "path": str(p),
                    "exists": p.exists(),
                    "size_bytes": p.stat().st_size if p.exists() else 0,
                }

        return cls(
            manifest=manifest_data,
            provenance=provenance_data,
            results=raw_results,
            events=events_list,
            artifacts=artifact_refs,
            redact_keys=redact_keys,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize bundle payload to a redacted dictionary."""
        payload = {
            "metadata": self.metadata,
            "manifest": self.manifest,
            "provenance": self.provenance,
            "results": self.results,
            "events": self.events,
            "artifacts": self.artifacts,
        }
        if self.redact_keys:
            return _redact_data(payload, self.redact_keys)
        return payload

    def to_json(self, path: Union[str, Path]) -> Path:
        """Export bundle payload as formatted JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return target

    def to_zip(self, path: Union[str, Path]) -> Path:
        """Export bundle payload and referenced artifact files as a ZIP archive."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle_dict = self.to_dict()

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bundle.json", json.dumps(bundle_dict, indent=2, sort_keys=True))
            # Include artifacts in archive
            for key, art_info in self.artifacts.items():
                if isinstance(art_info, dict) and "path" in art_info:
                    art_path = Path(art_info["path"])
                    if art_path.exists() and art_path.is_file():
                        zf.write(art_path, arcname=f"artifacts/{art_path.name}")

        return target

    @classmethod
    def load(cls, path: Union[str, Path]) -> "AnalysisBundle":
        """Load and validate an AnalysisBundle from a JSON or ZIP file."""
        p = Path(path)
        if not p.exists():
            raise BundleError(f"Bundle file '{path}' does not exist")

        try:
            if zipfile.is_zipfile(p):
                with zipfile.ZipFile(p, "r") as zf:
                    if "bundle.json" not in zf.namelist():
                        raise BundleError(f"Corrupt bundle archive: 'bundle.json' missing from '{path}'")
                    content = zf.read("bundle.json").decode("utf-8")
                    data = json.loads(content)
            else:
                data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BundleError(f"Failed to load bundle from '{path}': {exc}") from exc

        if not isinstance(data, dict) or "manifest" not in data or "results" not in data:
            raise BundleError(f"Invalid bundle schema in '{path}': manifest or results missing")

        return cls(
            manifest=data.get("manifest", {}),
            provenance=data.get("provenance", {}),
            results=data.get("results", []),
            events=data.get("events", []),
            artifacts=data.get("artifacts", {}),
            metadata=data.get("metadata", {}),
        )

    def replay_memory(self, memory: Any) -> None:
        """Replay bundle results into a CampaignMemory instance."""
        for res in self.results:
            case_id = res.get("case_id", 0)
            record = copy.deepcopy(res)
            memory.record_case(case_id, record)

    def replay_events(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """Replay bundle events to an event callback or observer."""
        for evt in self.events:
            try:
                callback(copy.deepcopy(evt))
            except Exception as exc:
                logger.warning("Bundle event replay callback failed: %s", exc)


def export_analysis_bundle(
    campaign: Any,
    path: Union[str, Path],
    results: Optional[Sequence[Any]] = None,
    artifacts: Optional[Dict[str, Union[str, Path]]] = None,
    redact_keys: Optional[Sequence[str]] = None,
) -> AnalysisBundle:
    """Convenience functional helper to export campaign analysis bundle."""
    bundle = AnalysisBundle.from_campaign(
        campaign=campaign,
        results=results,
        artifacts=artifacts,
        redact_keys=redact_keys,
    )
    p = Path(path)
    if p.suffix.lower() == ".zip":
        bundle.to_zip(p)
    else:
        bundle.to_json(p)
    return bundle


def load_analysis_bundle(path: Union[str, Path]) -> AnalysisBundle:
    """Convenience helper to load and validate an analysis bundle."""
    return AnalysisBundle.load(path)

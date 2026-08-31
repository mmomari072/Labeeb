"""Validated campaign manifests and reproducibility metadata."""

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .exceptions import LabeebError


class CampaignError(LabeebError):
    """Raised when a campaign manifest is invalid or unreadable."""


@dataclass
class CampaignManifest:
    """Execution-agnostic, validated campaign configuration."""

    name: str
    parameters: Dict[str, List[Any]]
    templates: List[str]
    commands: List[str]
    seed: Optional[int] = None
    execution: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CampaignManifest":
        if not isinstance(payload, dict):
            raise CampaignError("Campaign manifest must be a mapping")

        required = ("name", "parameters", "templates", "commands")
        missing = [key for key in required if key not in payload]
        if missing:
            raise CampaignError("Campaign manifest is missing: " + ", ".join(missing))

        name = payload["name"]
        parameters = payload["parameters"]
        templates = payload["templates"]
        commands = payload["commands"]
        if not isinstance(name, str) or not name.strip():
            raise CampaignError("Campaign name must be a non-empty string")
        if not isinstance(parameters, dict) or not parameters:
            raise CampaignError("Campaign parameters must be a non-empty mapping")
        if any(not isinstance(key, str) or not key for key in parameters):
            raise CampaignError("Campaign parameter names must be non-empty strings")
        if any(not isinstance(values, list) or not values for values in parameters.values()):
            raise CampaignError("Each campaign parameter must contain a non-empty list")
        if not isinstance(templates, list) or not templates or not all(isinstance(item, str) for item in templates):
            raise CampaignError("Campaign templates must be a non-empty list of strings")
        if not isinstance(commands, list) or not commands or not all(isinstance(item, str) for item in commands):
            raise CampaignError("Campaign commands must be a non-empty list of strings")

        seed = payload.get("seed")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise CampaignError("Campaign seed must be an integer")
        execution = payload.get("execution", {})
        if not isinstance(execution, dict):
            raise CampaignError("Campaign execution settings must be a mapping")
        return cls(name, parameters, templates, commands, seed, dict(execution))

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "parameters": self.parameters,
            "templates": self.templates,
            "commands": self.commands,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.execution:
            payload["execution"] = self.execution
        return payload

    def provenance(self) -> Dict[str, Any]:
        """Return deterministic manifest and template provenance metadata."""
        manifest_bytes = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        template_metadata: Dict[str, Dict[str, Any]] = {}
        for template in self.templates:
            path = Path(template)
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                template_metadata[template] = {"exists": True, "sha256": digest}
            else:
                template_metadata[template] = {"exists": False, "sha256": None}
        return {
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "templates": template_metadata,
            "commands": [
                {"command": command, "executable": shutil.which(command.split()[0]) if command.split() else None}
                for command in self.commands
            ],
        }


def load_manifest(path: Union[str, Path]) -> CampaignManifest:
    """Load and validate a JSON or YAML campaign manifest."""
    manifest_path = Path(path)
    try:
        if manifest_path.suffix.lower() == ".json":
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        elif manifest_path.suffix.lower() in {".yml", ".yaml"}:
            import yaml

            payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        else:
            raise CampaignError("Manifest format must be .json, .yml, or .yaml")
    except CampaignError:
        raise
    except Exception as exc:
        raise CampaignError(f"Failed to load campaign manifest '{manifest_path}': {exc}") from exc
    return CampaignManifest.from_dict(payload)

"""Validated campaign manifests and reproducibility metadata."""

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from .exceptions import LabeebError

if TYPE_CHECKING:
    from .case import Case
    from .results import CaseResult


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


class Campaign:
    """Python API for building and executing a manifest-backed case study.

    A campaign is intentionally usable from a case-study Python file.  The
    command-line interface is only a thin adapter around this class.
    """

    def __init__(self, manifest: CampaignManifest, state_path: Optional[Union[str, Path]] = None) -> None:
        if not isinstance(manifest, CampaignManifest):
            raise CampaignError("Campaign requires a validated CampaignManifest")
        self.manifest = manifest
        self.state_path = Path(state_path) if state_path is not None else None

    @classmethod
    def from_manifest(cls, path: Union[str, Path], state_path: Optional[Union[str, Path]] = None) -> "Campaign":
        """Load a manifest and return an executable campaign object."""
        return cls(load_manifest(path), state_path=state_path)

    def build_case(self) -> "Case":
        """Build a configured :class:`Case` for this campaign."""
        from .case import Case
        from .database import Database
        from .utils.file_io import File

        case = Case(name=self.manifest.name, output_files={})
        case.database = Database(data=self.manifest.parameters)
        case.FlagsMap = {f"#{name}#": name for name in self.manifest.parameters}
        for template in self.manifest.templates:
            case.add_file(File(file_path=template))
        execution = self.manifest.execution
        case.main_dir = str(execution.get("main_dir", Path.cwd()))
        case.run_case_main_dir = str(execution.get("run_dir", f"{self.manifest.name}_runs"))
        case.run_type = "new"
        case.exe_cmd = list(self.manifest.commands)
        if "timeout" in execution:
            case.timeout = execution["timeout"]
        if "log_file" in execution:
            case.log_file = execution["log_file"]
        return case

    def _input_hash(self, case_id: int, parameters: Dict[str, Any]) -> str:
        payload = {
            "manifest": self.manifest.provenance()["manifest_sha256"],
            "case_id": case_id,
            "parameters": parameters,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def status(self) -> Dict[str, int]:
        """Return persisted status counts, or an empty status for new runs."""
        if self.state_path is None:
            return {}
        with self._state() as state:
            return state.summary()

    def _state(self):
        from .results import CampaignStateStore

        return CampaignStateStore(self.state_path)  # type: ignore[arg-type]

    def run(self, resume: bool = True, max_retries: int = 3) -> List["CaseResult"]:
        """Execute all cases and return ordered :class:`CaseResult` records."""
        from .exceptions import CaseExecutionError
        from .results import CaseResult

        case = self.build_case()
        run_root = Path(case.main_dir) / case.run_case_main_dir
        if not run_root.exists():
            run_root.mkdir(parents=True, exist_ok=True)

        state_context = self._state() if self.state_path is not None else None
        state = state_context.__enter__() if state_context is not None else None
        results: List[CaseResult] = []
        try:
            for case_id in range(len(case.database)):
                parameters = case.database.get_row(case_id)
                input_hash = self._input_hash(case_id, parameters)
                persisted = state.get(case_id) if state is not None else None
                if resume and state is not None and state.should_reuse(case_id, input_hash):
                    results.append(CaseResult.from_record(persisted["result"]))
                    continue
                if state is not None and persisted is not None and not state.retry_allowed(case_id, max_retries):
                    results.append(CaseResult.from_record(persisted["result"]))
                    continue

                started = time.monotonic()
                case.case_id = case_id
                try:
                    case.launch_case(case_id)
                    result = CaseResult(case_id, parameters, "SUCCESS", 0, time.monotonic() - started)
                except CaseExecutionError as exc:
                    result = CaseResult(
                        case_id, parameters, "FAILED", None, time.monotonic() - started, failure=str(exc)
                    )
                if state is not None:
                    state.save(result, input_hash)
                results.append(result)
        finally:
            if state_context is not None:
                state_context.__exit__(None, None, None)
        return results

"""Validated campaign manifests and reproducibility metadata."""

import hashlib
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING, Union

from .exceptions import LabeebError

if TYPE_CHECKING:
    from .case import Case
    from .results import CaseResult

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        manifest: CampaignManifest,
        state_path: Optional[Union[str, Path]] = None,
        status_registry: Optional[Any] = None,
        memory: Optional[Any] = None,
        publisher: Optional[Any] = None,
        output_catalog: Optional[Union[str, Path]] = None,
        live_plot: Optional[Any] = None,
    ) -> None:
        if not isinstance(manifest, CampaignManifest):
            raise CampaignError("Campaign requires a validated CampaignManifest")
        lengths = {len(values) for values in manifest.parameters.values()}
        if len(lengths) != 1:
            raise CampaignError("Campaign parameters must contain the same number of values")
        self.manifest = manifest
        self.state_path = Path(state_path) if state_path is not None else None
        self.output_catalog: Optional[Path] = (
            Path(output_catalog) if output_catalog is not None else None
        )
        self.live_plot = self._coerce_live_plot(live_plot)
        from .results import StatusRegistry
        from .shared_memory import CampaignMemory

        self.status_registry = status_registry if status_registry is not None else StatusRegistry()
        self.memory: CampaignMemory = memory if memory is not None else CampaignMemory()
        self.publisher = publisher

    @classmethod
    def from_manifest(
        cls,
        path: Union[str, Path],
        state_path: Optional[Union[str, Path]] = None,
        memory: Optional[Any] = None,
        publisher: Optional[Any] = None,
        output_catalog: Optional[Union[str, Path]] = None,
        live_plot: Optional[Any] = None,
    ) -> "Campaign":
        """Load a manifest and return an executable campaign object."""
        return cls(
            load_manifest(path),
            state_path=state_path,
            memory=memory,
            publisher=publisher,
            output_catalog=output_catalog,
            live_plot=live_plot,
        )

    @staticmethod
    def _coerce_live_plot(live_plot: Any) -> Optional[Any]:
        """Normalize the live_plot argument into a PlotObserver instance.

        Accepts a ``PlotObserver``/``LivePlot`` instance or a plain mapping of
        its configuration keys (``metrics``, ``output_path``, ``enabled``,
        ``update_interval_seconds``, ``title``, ``xlabel``, ``ylabel``).
        """
        if live_plot is None:
            return None
        from .plot import LivePlot, PlotObserver

        if isinstance(live_plot, (PlotObserver, LivePlot)):
            return live_plot
        if isinstance(live_plot, dict):
            from .plot import PlotObserver

            allowed = {
                "metrics", "extract_fn", "output_path", "enabled",
                "update_interval_seconds", "title", "xlabel", "ylabel",
            }
            unknown = sorted(set(live_plot) - allowed)
            if unknown:
                logger.warning(
                    "live_plot config keys ignored (unsupported): %s", ", ".join(unknown)
                )
            config = {key: value for key, value in live_plot.items() if key in allowed}
            return PlotObserver(**config)
        raise CampaignError(
            "live_plot must be a PlotObserver/LivePlot instance or a configuration mapping"
        )

    def _resolve_live_plot(self) -> Optional[Any]:
        """Return the live plot observer for this run, if any."""
        if self.live_plot is not None:
            return self.live_plot
        manifest_plot = self.manifest.execution.get("live_plot")
        if manifest_plot is None:
            return None
        return self._coerce_live_plot(manifest_plot)

    def export_status(self, path: Union[str, Path]) -> Any:
        """Export the campaign's status registry to CSV, JSON, or Parquet."""
        return self.status_registry.export(path)

    def export_bundle(
        self,
        path: Union[str, Path],
        results: Optional[Sequence[Any]] = None,
        artifacts: Optional[Dict[str, Union[str, Path]]] = None,
        redact_keys: Optional[Sequence[str]] = None,
    ) -> Any:
        """Export an AnalysisBundle from this campaign to JSON or ZIP."""
        from .bundle import export_analysis_bundle

        return export_analysis_bundle(
            self,
            path=path,
            results=results,
            artifacts=artifacts,
            redact_keys=redact_keys,
        )

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
        case.capture_output = bool(execution.get("capture_output", False))
        case.shell = bool(execution.get("shell", False))
        if "command_failure_policy" in execution:
            case.command_failure_policy = execution["command_failure_policy"]
        if "harvest_failure_policy" in execution:
            case.harvest_failure_policy = execution["harvest_failure_policy"]
        if "max_attempts" in execution:
            case.max_attempts = int(execution["max_attempts"])
        case._validate_failure_policies()
        return case

    def _append_lifecycle_event(
        self, event_type: str, cwd: Union[str, Path], case_id: Optional[int] = None,
        attempt: int = 0, status: str = "INFO", message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        from .execution import ExecutionEvent, append_execution_event

        now = datetime.now(timezone.utc).isoformat()
        event = ExecutionEvent(
            command="", cwd=str(cwd), status=status, returncode=0 if status != "FAILED" else 1,
            duration_seconds=0.0, started_at=now, ended_at=now, case_id=case_id,
            unit=self.manifest.name, attempt=attempt, event_type=event_type, message=message,
        )
        if self.publisher is not None:
            try:
                payload = {**event.to_dict(), **(details or {})}
                self.publisher.publish(payload)
            except Exception:
                pass

        events_file = self.manifest.execution.get("events_file")
        if not events_file:
            return

        event_path = Path(events_file)
        if not event_path.is_absolute():
            event_path = Path(cwd).parent / event_path
        append_execution_event(event, event_path)

    def _input_hash(self, case_id: int, parameters: Dict[str, Any]) -> str:
        payload = {
            "manifest": self.manifest.provenance()["manifest_sha256"],
            "case_id": case_id,
            "parameters": parameters,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def status(self) -> Dict[str, int]:
        """Return status counts from the in-memory registry or persisted state."""
        if len(self.status_registry) > 0:
            return self.status_registry.summary()
        if self.state_path is None:
            return {}
        with self._state() as state:
            return state.summary()

    def _state(self):
        from .results import CampaignStateStore

        return CampaignStateStore(self.state_path)  # type: ignore[arg-type]

    def _open_output_catalog(self) -> Optional[Any]:
        """Open the optional OutputCatalog for this run (constructor path or
        manifest ``execution.output_catalog``), or None when disabled."""
        configured = self.output_catalog or self.manifest.execution.get("output_catalog")
        if not configured:
            return None
        from .outputs import OutputCatalog

        return OutputCatalog(Path(configured))

    @staticmethod
    def _record_catalog_attempt(
        catalog: Any,
        case: "Case",
        result: "CaseResult",
        case_id: int,
        attempt: int,
        output_lens: Dict[str, int],
    ) -> None:
        """Record one executed attempt into the output catalog.

        Links case/attempt to status, command, timing, stdout/stderr artifacts
        (when ``capture_output`` wrote them), and the harvested outputs produced
        by this attempt (identified as the per-output append delta since
        ``output_lens`` was captured before launch).
        """
        from .outputs import OutputRecord

        history = getattr(case, "execution_history", None) or []
        entry = history[-1] if history else {}
        event = entry.get("execution_event") or {}
        case_dir = Path(getattr(case, "current_case_dir", None) or ".")
        stdout_file = case_dir / "stdout.log"
        stderr_file = case_dir / "stderr.log"

        metrics: Dict[str, Any] = {}
        outputs = getattr(case, "outputs", {})
        for key, values in outputs.items():
            new_values = list(values[output_lens.get(key, 0):])
            if new_values:
                metrics[key] = new_values[-1]

        record = OutputRecord(
            case_id=case_id,
            status=result.status,
            attempt=attempt,
            unit=entry.get("unit") or getattr(case, "name", None),
            command=event.get("command") or entry.get("command"),
            exit_code=event.get("returncode") if event else result.exit_code,
            duration_seconds=result.duration_seconds or event.get("duration_seconds"),
            metrics=metrics,
            artifacts={},
            stdout_path=str(stdout_file) if stdout_file.is_file() else None,
            stderr_path=str(stderr_file) if stderr_file.is_file() else None,
            stdout_bytes=int(event.get("stdout_bytes", 0) or 0),
            stderr_bytes=int(event.get("stderr_bytes", 0) or 0),
            message=event.get("message") or result.failure,
            started_at=event.get("started_at"),
            ended_at=event.get("ended_at"),
        )
        catalog.record(record)

    def _attach_live_plot(self, live_plot: Optional[Any]) -> bool:
        """Attach the live plot observer to the campaign publisher (safe).

        Returns True when attached. Attachment failures never raise: they are
        logged and the campaign continues without live plotting.
        """
        if live_plot is None:
            return False
        if self.publisher is None:
            logger.warning(
                "live_plot configured but campaign has no publisher; "
                "events will not reach the plot"
            )
            return False
        try:
            self.publisher.add_observer(live_plot)
            return True
        except Exception as exc:
            logger.warning("Failed to attach live plot observer: %s", exc)
            return False

    def _shutdown_live_plot(self, live_plot: Optional[Any], attached: bool) -> None:
        """Detach and close the live plot observer without ever raising."""
        if live_plot is None:
            return
        if attached and self.publisher is not None:
            try:
                self.publisher.remove_observer(live_plot)
            except Exception as exc:
                logger.warning("Failed to detach live plot observer: %s", exc)
        try:
            live_plot.close()
        except Exception as exc:
            logger.warning("Failed to close live plot observer: %s", exc)

    def run(self, resume: bool = True, max_retries: int = 3) -> List["CaseResult"]:
        """Execute all cases and return ordered :class:`CaseResult` records.

        When a live plot observer is configured (``live_plot=`` or manifest
        ``execution.live_plot``) and the campaign has a publisher, the observer
        is attached before the first event and detached + closed afterwards —
        including when execution raises — so a plotting error can never leak
        into the run.
        """
        from .exceptions import CaseExecutionError
        from .results import CaseResult

        case = self.build_case()
        run_root = Path(case.main_dir) / case.run_case_main_dir
        if not run_root.exists():
            run_root.mkdir(parents=True, exist_ok=True)

        state_context = self._state() if self.state_path is not None else None
        state = state_context.__enter__() if state_context is not None else None
        results: List[CaseResult] = []
        campaign_status = "SUCCESS"
        catalog_context = self._open_output_catalog()
        catalog = catalog_context.__enter__() if catalog_context is not None else None
        live_plot = self._resolve_live_plot()
        plot_attached = self._attach_live_plot(live_plot) if live_plot is not None else False
        self._append_lifecycle_event("campaign_start", run_root)
        try:
            try:
                for case_id in range(len(case.database)):
                    parameters = case.database.get_row(case_id)
                    input_hash = self._input_hash(case_id, parameters)
                    persisted = state.get(case_id) if state is not None else None
                    if resume and state is not None and state.should_reuse(case_id, input_hash):
                        self._append_lifecycle_event("case_cache_hit", run_root, case_id=case_id, status="SKIPPED")
                        cached_result = CaseResult.from_record(persisted["result"])
                        self.status_registry.record_result(cached_result)
                        self.memory.record_case(
                            case_id,
                            {**cached_result.parameters, "status": cached_result.status, "duration": cached_result.duration_seconds, "exit_code": cached_result.exit_code, "cached": True},
                        )
                        results.append(cached_result)
                        continue
                    if state is not None and persisted is not None and not state.retry_allowed(case_id, max_retries):
                        persisted_result = CaseResult.from_record(persisted["result"])
                        self.status_registry.record_result(persisted_result)
                        self.memory.record_case(
                            case_id,
                            {**persisted_result.parameters, "status": persisted_result.status, "duration": persisted_result.duration_seconds, "exit_code": persisted_result.exit_code, "failure": persisted_result.failure},
                        )
                        results.append(persisted_result)
                        continue

                    started = time.monotonic()
                    case.case_id = case_id
                    attempt = persisted["attempts"] if persisted is not None else 0
                    output_lens = {key: len(values) for key, values in case.outputs.items()}
                    self._append_lifecycle_event("case_start", run_root, case_id=case_id, attempt=attempt, status="STARTED")
                    try:
                        case.launch_case(case_id, _attempt=attempt)
                        if getattr(case, "_case_failed", False):
                            result = CaseResult(
                                case_id, parameters, "FAILED", None, time.monotonic() - started,
                                failure=case.failure or "Case failed (continue policy)",
                            )
                        else:
                            result = CaseResult(case_id, parameters, "SUCCESS", 0, time.monotonic() - started)
                    except CaseExecutionError as exc:
                        result = CaseResult(
                            case_id, parameters, "FAILED", None, time.monotonic() - started, failure=str(exc)
                        )
                    if case.execution_history:
                        event_record = case.execution_history[-1].get("execution_event")
                        if event_record:
                            from .execution import ExecutionEvent, append_execution_event
                            if self.publisher is not None:
                                try:
                                    self.publisher.publish(ExecutionEvent.from_dict(event_record))
                                except Exception:
                                    pass
                            events_file = self.manifest.execution.get("events_file")
                            if events_file:
                                event_path = Path(events_file)
                                if not event_path.is_absolute():
                                    event_path = Path(case.main_dir) / event_path
                                append_execution_event(ExecutionEvent.from_dict(event_record), event_path)
                    self._append_lifecycle_event(
                        "case_complete" if result.status == "SUCCESS" else "case_failure",
                        run_root, case_id=case_id, attempt=attempt, status=result.status, message=result.failure,
                        details={**parameters, "duration": result.duration_seconds},
                    )
                    if result.status != "SUCCESS":
                        campaign_status = "FAILED"
                    self.status_registry.record_result(result)
                    self.memory.record_case(
                        case_id,
                        {**parameters, "status": result.status, "duration": result.duration_seconds, "exit_code": result.exit_code, "failure": result.failure},
                    )
                    if catalog is not None:
                        try:
                            self._record_catalog_attempt(catalog, case, result, case_id, attempt, output_lens)
                        except Exception as exc:
                            logger.warning("Failed to record output catalog attempt for case %s: %s", case_id, exc)
                    if state is not None:
                        state.save(result, input_hash)
                    results.append(result)
            finally:
                if catalog_context is not None:
                    try:
                        catalog_context.__exit__(None, None, None)
                    except Exception as exc:
                        logger.warning("Failed to close output catalog cleanly: %s", exc)
                if state_context is not None:
                    state_context.__exit__(None, None, None)
            self._append_lifecycle_event("campaign_complete", run_root, status=campaign_status)
        finally:
            self._shutdown_live_plot(live_plot, plot_attached)
        return results

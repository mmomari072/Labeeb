"""
Labeeb: Sensitivity and Uncertainty Analysis interface for text-based input deck codes.
Designed for simulation-code coupling and sensitivity analysis.
"""

import os
import logging

logging.getLogger("labeeb").addHandler(logging.NullHandler())

from .case import Case, Flag, FlagsMap
from .campaign import Campaign, CampaignError, CampaignManifest, load_manifest
from .coupler import Coupler
from .database import Attribute, Database
from .exceptions import (
    BackupError,
    CaseExecutionError,
    CouplingError,
    DatabaseError,
    LabeebError,
    OptimizationError,
    SamplingError,
    TemplateError,
)
from .execution import (
    ExecutionBackend,
    ExecutionEvent,
    ExecutionResult,
    LocalExecutionBackend,
    append_execution_event,
    export_execution_events,
)
from .analysis import AnalysisError, correlation_analysis, morris_screening, sobol_indices, wilks_sample_size
from .extractors import (
    CallableHarvester,
    CsvHarvester,
    ExcelHarvester,
    ExtractionError,
    Harvester,
    JsonHarvester,
    RegexHarvester,
    extract_csv,
    extract_excel,
    extract_json,
    extract_regex,
    run_extractor,
)
from .sampler import (
    DiscreteSampling,
    FOATConstructor,
    OATConstructor,
    correlated_normal_sample,
    halton_sample,
    latin_hypercube_sample,
    normal_sample,
    product,
    sample,
    uniform_sample,
    truncated_normal_sample,
)
from .shared_memory import (
    CampaignMemory,
    InMemorySharedBackend,
    SharedMemoryBackend,
    SharedMemoryError,
)
from .publisher import (
    CompositeEventPublisher,
    EventPublisher,
    JsonlEventPublisher,
    LiveObserver,
    NullEventPublisher,
    PublisherError,
    RedisStreamEventPublisher,
    WebSocketEventPublisher,
)
from .plot import LivePlot, PlotObserver
from .bundle import (
    AnalysisBundle,
    BundleError,
    export_analysis_bundle,
    load_analysis_bundle,
)
from .results import CaseResult, CampaignStateStore, ExecutionStatusRegistry, StatusRegistry, export_case_results
from .outputs import OutputCatalog, OutputRecord
from .backup import BackupManifest, create_backup, restore_backup, validate_backup
from .optimizer import Constraint, EvaluationRecord, OptimizeResult, Optimizer, export_optimization_history
from .ai import (
    BoTorchGPSurrogate,
    NeuralMLPSurrogate,
    SurrogateModel,
    optimize_optuna,
    optimize_scipy,
    rank_candidates,
)
from .report import write_html_report
from .logging_config import CaseLoggerAdapter, configure_logging
from .utils.file_io import File, evaluate_expression, format_value

__version__ = "1.24.0"
__author__ = "Mohammed Omari"

__all__ = [
    "AnalysisBundle", "AnalysisError", "Attribute", "BackupError", "BackupManifest", "BoTorchGPSurrogate", "BundleError", "CallableHarvester", "Campaign", "CampaignError", "CampaignManifest",
    "CampaignMemory", "CampaignStateStore", "Case", "CaseExecutionError", "CaseResult", "CompositeEventPublisher", "Constraint", "Coupler",
    "CsvHarvester", "StatusRegistry", "ExecutionStatusRegistry", "EventPublisher", "EvaluationRecord", "ExcelHarvester", "OptimizeResult", "Optimizer", "OptimizationError", "NeuralMLPSurrogate",
    "CouplingError", "Database", "DatabaseError", "DiscreteSampling", "ExecutionBackend",
    "ExecutionEvent", "ExecutionResult", "ExtractionError", "FOATConstructor", "OATConstructor", "File", "Flag", "FlagsMap",
    "Harvester", "InMemorySharedBackend", "JsonHarvester", "JsonlEventPublisher", "LabeebError", "LiveObserver", "LivePlot", "LocalExecutionBackend", "NullEventPublisher", "OutputCatalog", "OutputRecord", "PlotObserver", "PublisherError", "RedisStreamEventPublisher", "RegexHarvester", "SamplingError", "SharedMemoryBackend", "SharedMemoryError", "TemplateError", "WebSocketEventPublisher", "correlation_analysis",
    "append_execution_event", "create_backup", "evaluate_expression", "export_analysis_bundle", "export_case_results", "export_execution_events", "export_optimization_history", "extract_csv", "extract_excel", "extract_json", "extract_regex", "format_value", "halton_sample",
    "latin_hypercube_sample", "load_analysis_bundle", "load_manifest", "morris_screening", "normal_sample", "product",
    "restore_backup", "run_extractor", "sample", "sobol_indices", "uniform_sample", "wilks_sample_size", "SurrogateModel", "optimize_scipy", "optimize_optuna", "rank_candidates",
    "validate_backup", "write_html_report", "print_banner", "CaseLoggerAdapter", "configure_logging",
    "correlated_normal_sample", "truncated_normal_sample",
]

def print_banner() -> None:
    """Print the optional package identification banner."""
    print("*" * 80)
    print(
        """  _           _               _
 | |         | |             | |    
 | |     __ _| |__   ___  ___| |__  
 | |    / _` | '_ \\ / _ \\/ _ \\ '_ \\ 
 | |___| (_| | |_) |  __/  __/ |_) |
 |______\\__,_|_.__/ \\___|\\___|_.__/ 
"""
    )
    print("----------------------------------------------------")
    print("CREATED BY : Eng. Mohammad OMARI")
    print(f"VERSION    : {__version__}")
    print("DATE       : Aug 2026")
    print("*" * 80)


if os.environ.get("LABEEB_SHOW_BANNER", "").strip().lower() in {"1", "true", "yes", "on"}:
    print_banner()

"""
Labeeb: Sensitivity and Uncertainty Analysis interface for text-based input deck codes.
Developed for nuclear reactor code coupling and sensitivity analysis (MCNP, RELAP5, etc.).
"""

import os
import logging

logging.getLogger("labeeb").addHandler(logging.NullHandler())

from .case import Case, Flag, FlagsMap
from .campaign import Campaign, CampaignError, CampaignManifest, load_manifest
from .coupler import Coupler
from .database import Attribute, Database
from .exceptions import (
    CaseExecutionError,
    CouplingError,
    DatabaseError,
    LabeebError,
    SamplingError,
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
from .extractors import ExtractionError, extract_csv, extract_json, extract_regex, run_extractor
from .sampler import (
    DiscreteSampling,
    FOATConstructor,
    halton_sample,
    latin_hypercube_sample,
    normal_sample,
    product,
    sample,
    uniform_sample,
)
from .results import CaseResult, CampaignStateStore, export_case_results
from .report import write_html_report
from .logging_config import CaseLoggerAdapter, configure_logging
from .utils.file_io import File

__version__ = "1.4.0"
__author__ = "Mohammed Omari"

__all__ = [
    "AnalysisError", "Attribute", "Campaign", "CampaignError", "CampaignManifest",
    "CampaignStateStore", "Case", "CaseExecutionError", "CaseResult", "Coupler",
    "CouplingError", "Database", "DatabaseError", "DiscreteSampling", "ExecutionBackend",
    "ExecutionEvent", "ExecutionResult", "ExtractionError", "FOATConstructor", "File", "Flag", "FlagsMap",
    "LabeebError", "LocalExecutionBackend", "SamplingError", "correlation_analysis",
    "append_execution_event", "export_case_results", "export_execution_events", "extract_csv", "extract_json", "extract_regex", "halton_sample",
    "latin_hypercube_sample", "load_manifest", "morris_screening", "normal_sample", "product",
    "run_extractor", "sample", "sobol_indices", "uniform_sample", "wilks_sample_size",
    "write_html_report", "print_banner", "CaseLoggerAdapter", "configure_logging",
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
    print("INSTITUTE  : Jordan Research and Training Reactor")
    print(f"VERSION    : {__version__}")
    print("DATE       : Aug 2026")
    print("*" * 80)


if os.environ.get("LABEEB_SHOW_BANNER", "").strip().lower() in {"1", "true", "yes", "on"}:
    print_banner()

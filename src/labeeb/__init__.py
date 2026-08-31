"""
Labeeb: Sensitivity and Uncertainty Analysis interface for text-based input deck codes.
Developed for nuclear reactor code coupling and sensitivity analysis (MCNP, RELAP5, etc.).
"""

from .case import Case, Flag, FlagsMap
from .campaign import CampaignError, CampaignManifest, load_manifest
from .coupler import Coupler
from .database import Attribute, Database
from .exceptions import (
    CaseExecutionError,
    CouplingError,
    DatabaseError,
    LabeebError,
    SamplingError,
)
from .sampler import (
    DiscreteSampling,
    FOATConstructor,
    normal_sample,
    sample,
    uniform_sample,
)
from .utils.file_io import File

__version__ = "0.2.2"
__author__ = "Mohammed Omari"

# Print nice banner on import
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
print(f"----------------------------------------------------")
print(f"CREATED BY : Eng. Mohammad OMARI")
print(f"INSTITUTE  : Jordan Research and Training Reactor")
print(f"VERSION    : {__version__}")
print(f"DATE       : Aug 2026")
print("*" * 80)

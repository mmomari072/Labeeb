"""
Custom exceptions for the Labeeb package.
Helps users of the API catch specific errors during simulation runs.
"""


class LabeebError(Exception):
    """Base exception for all Labeeb errors."""

    pass


class DatabaseError(LabeebError):
    """Raised when an error occurs during database or attribute operations."""

    pass


class SamplingError(LabeebError):
    """Raised when configuration or validation of samplers fails."""

    pass


class CaseExecutionError(LabeebError):
    """Raised when input deck template compilation or code execution fails."""

    pass


class TemplateError(CaseExecutionError):
    """Raised when template compilation, variable substitution, or expression evaluation fails."""

    pass


class CouplingError(LabeebError):
    """Raised when errors occur during multi-code coupling runs."""

    pass


class BackupError(LabeebError):
    """Raised when backup creation, validation, or restore fails."""

    pass


class OptimizationError(LabeebError):
    """Raised for invalid optimizer configuration or optimization failures."""

    pass

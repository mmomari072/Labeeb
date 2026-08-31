"""Application-owned logging configuration and execution context helpers."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, Union


_HANDLER_MARKER = "_labeeb_handler"
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class CaseLoggerAdapter(logging.LoggerAdapter):
    """Attach stable campaign, case, unit, and attempt fields to log records."""

    def process(self, message: Any, kwargs: Dict[str, Any]):
        extra = dict(self.extra)
        extra.update(kwargs.get("extra", {}))
        kwargs["extra"] = extra
        prefix = (
            f"[case_id={extra.get('case_id', '-')} "
            f"unit={extra.get('unit', '-')} attempt={extra.get('attempt', 0)}]"
        )
        return f"{prefix} {message}", kwargs


def configure_logging(
    level: Union[int, str] = logging.INFO,
    log_file: Optional[Union[str, Path]] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 3,
    stream: bool = True,
) -> logging.Logger:
    """Configure Labeeb handlers without modifying the application's root logger."""
    if max_bytes < 1 or backup_count < 0:
        raise ValueError("max_bytes must be positive and backup_count cannot be negative")
    resolved_level = logging.getLevelName(level) if isinstance(level, str) else level
    if not isinstance(resolved_level, int):
        raise ValueError(f"Unknown logging level: {level}")

    logger = logging.getLogger("labeeb")
    logger.setLevel(resolved_level)
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_FORMAT)
    if stream:
        handler = logging.StreamHandler()
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    if log_file is not None:
        target = Path(log_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(target, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

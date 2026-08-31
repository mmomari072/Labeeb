"""
OS Operations utility functions for the Labeeb package.
Provides wrapped and robust functions for directory and file manipulations.
"""

import glob
import logging
import os
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def rmdir(directory: str) -> int:
    """
    Recursively remove a directory.

    Args:
        directory: Path to the directory.

    Returns:
        0 on success, 1 on failure.
    """
    try:
        if os.path.exists(directory):
            shutil.rmtree(directory)
        return 0
    except Exception as e:
        logger.error(f"Failed to remove directory {directory}: {e}")
        return 1


def mkdir(path: str) -> int:
    """
    Create a directory if it does not exist.

    Args:
        path: Path to create.

    Returns:
        0 on success, -123 on failure/already exists.
    """
    try:
        os.makedirs(path, exist_ok=True)
        return 0
    except Exception as e:
        logger.warning(f"Folder {path} creation failed or exists: {e}")
        return -123


def chdir(path: str) -> int:
    """
    Change the current working directory.

    Args:
        path: Destination path.

    Returns:
        0 on success, 1 on failure.
    """
    try:
        os.chdir(path)
        return 0
    except Exception as e:
        logger.error(f"Failed to change directory to {path}: {e}")
        return 1


def cpdir(src: str, dst: str) -> None:
    """
    Copy a directory tree.

    Args:
        src: Source directory path.
        dst: Destination directory path.
    """
    if os.path.isdir(src):
        _, tail = os.path.split(src)
        shutil.copytree(src, os.path.join(dst, tail), dirs_exist_ok=True)


def cpfile(src: str, dst: str) -> int:
    """
    Copy a single file.

    Args:
        src: Source file path.
        dst: Destination directory.

    Returns:
        0 on success.
    """
    if os.path.isfile(src):
        _, tail = os.path.split(src)
        shutil.copy(src, set_fullpath(dst, tail))
        return 0
    return 1


def cp(src: str, dst: str) -> int:
    """
    Copy a file or folder, supports glob patterns.

    Args:
        src: Source path or pattern.
        dst: Destination folder.

    Returns:
        0 on success, 1 on failure.
    """
    _, tail = os.path.split(src)
    if isfile(src):
        return cpfile(src, dst)
    elif isdir(src):
        cpdir(src, dst)
        return 0
    elif "*" in tail or "?" in tail:
        flist = glob.glob(src)
        for f in flist:
            cp(f, dst)
        return 0
    else:
        logger.error(f"Copying {src} object is not supported. Path type: {path_type(src)}")
        return 1


def isfile(path: str) -> bool:
    """Check if path is a file."""
    return os.path.isfile(path)


def isdir(path: str) -> bool:
    """Check if path is a directory."""
    return os.path.isdir(path)


def path_type(path: str) -> Optional[str]:
    """
    Return type of path ('file', 'dir', or None).
    """
    if isdir(path):
        return "dir"
    elif isfile(path):
        return "file"
    return None


def set_fullpath(directory: str, file: str, *args: str) -> str:
    """
    Combine paths safely.
    """
    return os.path.join(directory, file, *args)


def pwd() -> str:
    """Return current working directory."""
    return os.getcwd()


def execute(
    command: str,
    wkdir: Optional[str] = None,
    timeout: Optional[float] = None,
    log_file: Optional[str] = None,
) -> int:
    """
    Execute a shell command with timeout, optional directory change, and logging support.

    Args:
        command: Command to execute.
        wkdir: Directory to run the command in.
        timeout: Timeout in seconds before raising TimeoutExpired.
        log_file: File path to redirect command standard outputs/errors.

    Returns:
        Command return code (0 for success, -999 on timeout).
    """
    from ..execution import LocalExecutionBackend

    result = LocalExecutionBackend().run(
        command,
        cwd=wkdir or pwd(),
        timeout=timeout,
        log_file=log_file,
    )
    return result.returncode

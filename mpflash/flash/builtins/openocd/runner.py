"""Locate and run the Infineon build of OpenOCD.

Stock OpenOCD has no PSoC Edge target, so only Infineon's customised build
(version string ``0.12.0+dev-<major>.<minor>.<patch>.<build>``) is accepted.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence, Tuple

from mpflash.errors import MPFlashError
from mpflash.logger import log

ENV_VAR = "MPFLASH_OPENOCD"
"""Environment variable holding the path to an Infineon OpenOCD executable."""

MIN_VERSION: Tuple[int, int, int] = (5, 8, 0)
"""Oldest Infineon OpenOCD release that supports PSoC Edge (per the MicroPython port)."""

_VERSION_RE = re.compile(r"\+dev-(\d+)\.(\d+)\.(\d+)")


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    """Return the Infineon release triple from ``openocd --version`` output, or None for other builds."""
    if match := _VERSION_RE.search(text):
        return int(match[1]), int(match[2]), int(match[3])
    return None


@lru_cache(maxsize=None)
def _probe_version(exe: str) -> Optional[Tuple[int, int, int]]:
    try:
        # OpenOCD prints its banner on stderr.
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        log.debug(f"Could not run {exe} --version: {error}")
        return None
    return parse_version(f"{result.stdout}\n{result.stderr}")


def is_suitable(exe: Path | str) -> bool:
    """True when ``exe`` is an Infineon OpenOCD of at least :data:`MIN_VERSION`."""
    version = _probe_version(str(exe))
    return version is not None and version >= MIN_VERSION


def find_openocd() -> Optional[Path]:
    """Find a suitable OpenOCD via ``MPFLASH_OPENOCD`` first, then ``PATH``.

    Raises:
        MPFlashError: ``MPFLASH_OPENOCD`` is set but does not point at a suitable build.
    """
    if configured := os.environ.get(ENV_VAR):
        if not is_suitable(configured):
            minimum = ".".join(map(str, MIN_VERSION))
            raise MPFlashError(
                f"{ENV_VAR}={configured!r} is not an Infineon OpenOCD >= {minimum} (stock OpenOCD does not support PSoC Edge)."
            )
        return Path(configured)

    if found := shutil.which("openocd"):
        if is_suitable(found):
            return Path(found)
        log.info(f"Ignoring {found}: not an Infineon OpenOCD >= {'.'.join(map(str, MIN_VERSION))}")
    return None


def scripts_dir(exe: Path) -> Optional[Path]:
    """The ``scripts`` directory that ships next to ``bin/openocd`` in Infineon packages."""
    candidate = exe.resolve().parent.parent / "scripts"
    return candidate if candidate.is_dir() else None


def run_openocd(exe: Path, args: Sequence[str], *, timeout: int = 180) -> str:
    """Run OpenOCD with ``args`` (no shell) and return its combined output.

    Raises:
        MPFlashError: on timeout, launch failure or a non-zero exit status.
    """
    cmd = [str(exe), *args]
    log.debug(f"Running OpenOCD: {cmd}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise MPFlashError(f"OpenOCD timed out after {timeout}s") from error
    except OSError as error:
        raise MPFlashError(f"Could not start OpenOCD ({exe}): {error}") from error

    output = f"{result.stdout}{result.stderr}"
    log.trace(output)
    if result.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-15:])
        raise MPFlashError(f"OpenOCD failed with exit code {result.returncode}. Is the board connected?\n{tail}")
    return output

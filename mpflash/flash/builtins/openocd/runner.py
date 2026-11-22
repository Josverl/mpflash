"""Locate and run the Infineon build of OpenOCD.

Stock OpenOCD has no PSOC Edge target, so only Infineon's customised build
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

from .udev import RULES_DIR, RULES_FILE

ENV_VAR = "MPFLASH_OPENOCD"
"""Environment variable holding the path to an Infineon OpenOCD executable."""

MIN_VERSION: Tuple[int, int, int] = (5, 8, 0)
"""Oldest Infineon OpenOCD release that supports PSOC Edge (per the MicroPython port)."""

_VERSION_RE = re.compile(r"\+dev-(\d+)\.(\d+)\.(\d+)")

KITPROG3_ID = "04b4:f155"
"""USB ``vendor:product`` of the KitProg3 probe on Infineon kits."""

_NO_PROBE = "unable to find a matching CMSIS-DAP device"


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
                f"{ENV_VAR}={configured!r} is not an Infineon OpenOCD >= {minimum} (stock OpenOCD does not support PSOC Edge)."
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


def _kitprog_unreadable(sysfs: Path = Path("/sys/bus/usb/devices"), devnodes: Path = Path("/dev/bus/usb")) -> bool:
    """True if a KitProg3 is attached but user cannot open its USB node (Linux only)."""
    for device in sysfs.glob("*"):
        try:
            if f"{(device / 'idVendor').read_text().strip()}:{(device / 'idProduct').read_text().strip()}" != KITPROG3_ID:
                continue
            bus, number = int((device / "busnum").read_text()), int((device / "devnum").read_text())
        except (OSError, ValueError):
            continue
        if not os.access(devnodes / f"{bus:03d}" / f"{number:03d}", os.R_OK | os.W_OK):
            return True
    return False


class ProbeAccessError(MPFlashError):
    """The KitProg3 probe is connected, but user is not allowed to open it (missing udev rule)."""


def _failure_hint(output: str, access_denied: bool) -> str:
    """Explain the common 'probe not found' failure; a generic hint for any other error."""
    if _NO_PROBE not in output:
        return "Is the board connected?"
    if access_denied:
        return (
            f"The KitProg3 USB probe ({KITPROG3_ID}) is connected, but cannot open it (missing udev rule).\n"
            "Install the rule, then unplug and reconnect the board:\n"
            f"  sudo cp -f {RULES_FILE} {RULES_DIR}/\n"
            "  sudo udevadm control --reload-rules\n"
            "Unless your desktop session grants USB access, your user must also be in the 'plugdev' group:\n"
            "  sudo usermod -aG plugdev $USER   (then log out and in)"
        )
    return f"No KitProg3 USB probe ({KITPROG3_ID}) was found. Connect the board's debug USB port and check the cable."


def run_openocd(exe: Path, args: Sequence[str], *, timeout: int = 180) -> str:
    """Run OpenOCD with ``args`` (no shell) and return its combined output.

    Raises:
        ProbeAccessError: the probe is attached but its USB node is not accessible.
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
        access_denied = _NO_PROBE in output and _kitprog_unreadable()
        error_type = ProbeAccessError if access_denied else MPFlashError
        raise error_type(f"OpenOCD failed with exit code {result.returncode}.\n{_failure_hint(output, access_denied)}\n{tail}")
    return output

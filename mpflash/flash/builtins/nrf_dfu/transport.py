"""Subprocess adapter for Adafruit's legacy Nordic Serial DFU protocol."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from mpflash.errors import MPFlashError
from mpflash.logger import log


@dataclass(frozen=True)
class SerialDfuResult:
    """Captured output from a successful Serial DFU transfer."""

    command: tuple[str, ...]
    stdout: str
    stderr: str


def is_nrfutil_available() -> bool:
    """Return whether the optional Adafruit nrfutil package is installed."""
    return importlib.util.find_spec("nordicsemi") is not None


def serial_dfu_command(package: Path, port: str) -> tuple[str, ...]:
    """Build the isolated legacy Serial DFU command."""
    return (
        sys.executable,
        "-m",
        "nordicsemi",
        "--verbose",
        "dfu",
        "serial",
        "--package",
        str(package),
        "--port",
        port,
        "--baudrate",
        "115200",
        "--singlebank",
    )


def flash_serial_dfu(
    package: Path,
    port: str,
    *,
    timeout: float = 180,
    command: Sequence[str] | None = None,
) -> SerialDfuResult:
    """Transfer one validated SoftDevice+bootloader package to one CDC port."""
    if not port:
        raise MPFlashError("nRF Serial DFU requires an explicitly matched bootloader CDC port")
    if not package.is_file():
        raise MPFlashError(f"nRF Serial DFU package does not exist: {package}")
    if command is None and not is_nrfutil_available():
        raise MPFlashError(
            "Adafruit nrfutil is required for nRF SoftDevice migration. Install MPFlash with the nrf extra: uv sync --extra nrf"
        )

    argv = tuple(command) if command is not None else serial_dfu_command(package, port)
    log.info(f"Transferring {package.name} to {port} with Adafruit Serial DFU")
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise MPFlashError(
            f"nRF Serial DFU timed out after {timeout:g} seconds on {port}. "
            "The board may still be in its bootloader; inspect the mounted UF2 volume before retrying."
        ) from exc
    except OSError as exc:
        raise MPFlashError(f"Could not start nRF Serial DFU on {port}: {exc}") from exc

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode:
        details = (stderr.strip() or stdout.strip() or "no diagnostic output").splitlines()[-1]
        raise MPFlashError(
            f"nRF Serial DFU failed on {port} with exit code {completed.returncode}: {details}. "
            "Do not retry against a different port; inspect the board's current UF2 identity first."
        )
    log.success(f"Completed nRF SoftDevice+bootloader transfer on {port}")
    return SerialDfuResult(command=argv, stdout=stdout, stderr=stderr)

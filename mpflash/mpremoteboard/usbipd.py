"""Discover and reattach USB devices to WSL2 with usbipd."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from mpflash.logger import log

_INSTANCE_ID = re.compile(
    r"^USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})(?:&[^\\]+)*\\(.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UsbipdDevice:
    """A currently connected USB device reported by usbipd."""

    bus_id: str
    vid: int
    pid: int
    serial_number: str
    description: str
    attached: bool


def find_usbipd() -> Optional[str]:
    """Return the usbipd executable available through WSL interop."""
    return shutil.which("usbipd.exe") or shutil.which("usbipd")


def parse_usbipd_state(output: str) -> list[UsbipdDevice]:
    """Parse connected devices from ``usbipd state`` JSON output."""
    try:
        state = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(state, dict) or not isinstance(state.get("Devices"), list):
        return []

    devices = []
    for item in state["Devices"]:
        if not isinstance(item, dict):
            continue
        bus_id = str(item.get("BusId") or "")
        match = _INSTANCE_ID.match(str(item.get("InstanceId") or ""))
        if not bus_id or match is None:
            continue
        devices.append(
            UsbipdDevice(
                bus_id=bus_id,
                vid=int(match.group(1), 16),
                pid=int(match.group(2), 16),
                serial_number=match.group(3),
                description=str(item.get("Description") or "USB device"),
                attached=bool(item.get("ClientIPAddress")),
            )
        )
    return devices


def select_usbipd_device(
    devices: list[UsbipdDevice],
    *,
    vid: int,
    pid: int,
    serial_number: str,
) -> Optional[UsbipdDevice]:
    """Select one physical device without guessing between identical boards."""
    candidates = [device for device in devices if device.vid == vid and device.pid == pid]
    if serial_number:
        serial_matches = [device for device in candidates if device.serial_number.casefold() == serial_number.casefold()]
        return serial_matches[0] if len(serial_matches) == 1 else None
    return candidates[0] if len(candidates) == 1 else None


def _run_usbipd(executable: str, *args: str) -> Optional[subprocess.CompletedProcess[str]]:
    try:
        return subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug(f"Could not run usbipd: {exc}")
        return None


def _find_current_device(
    executable: str,
    *,
    vid: int,
    pid: int,
    serial_number: str,
) -> Optional[UsbipdDevice]:
    state = _run_usbipd(executable, "state")
    if state is None or state.returncode != 0:
        return None
    return select_usbipd_device(
        parse_usbipd_state(state.stdout),
        vid=vid,
        pid=pid,
        serial_number=serial_number,
    )


def reattach_usbipd_device(
    *,
    vid: int,
    pid: int,
    serial_number: str,
    executable: Optional[str] = None,
) -> Optional[bool]:
    """Reattach one USB device to WSL2.

    Returns ``True`` when the device is attached, ``False`` when an attach was
    attempted and failed, and ``None`` when usbipd or a unique device is not
    currently available.
    """
    executable = executable or find_usbipd()
    if executable is None:
        return None
    device = _find_current_device(
        executable,
        vid=vid,
        pid=pid,
        serial_number=serial_number,
    )
    if device is None:
        return None
    if device.attached:
        return True

    result = _run_usbipd(
        executable,
        "attach",
        "--wsl",
        "--busid",
        device.bus_id,
    )
    if result is not None and result.returncode == 0:
        log.info(f"Reattached {device.description} ({device.bus_id}) to WSL2 with usbipd")
        return True

    attached_device = _find_current_device(
        executable,
        vid=vid,
        pid=pid,
        serial_number=serial_number,
    )
    if attached_device is not None and attached_device.attached:
        log.info(f"Reattached {attached_device.description} ({attached_device.bus_id}) to WSL2 with usbipd")
        return True

    detail = "usbipd did not return a result"
    if result is not None:
        detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
    log.warning(
        f"Could not reattach {device.description} ({device.bus_id}) to WSL2: {detail}. Run: usbipd attach --wsl --busid {device.bus_id}"
    )
    return False

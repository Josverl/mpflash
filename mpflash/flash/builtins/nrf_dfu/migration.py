"""Stateful, offline nRF SoftDevice+bootloader migration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from serial.tools import list_ports

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.uf2 import copy_firmware_to_uf2
from mpflash.flash.builtins.uf2.boardid import Uf2BoardInfo, read_uf2_board_info
from mpflash.flash.builtins.uf2.nrf import enter_nrf_uf2_bootloader
from mpflash.flash.builtins.uf2.volume import mounted_uf2_volumes
from mpflash.logger import log
from mpflash.mpremoteboard import MPRemoteBoard

from .artifacts import inspect_application_uf2, inspect_dfu_package
from .profiles import NrfDfuProfile, get_profiles, profile_package_path
from .transport import flash_serial_dfu

ConfirmMigration = Callable[[str], bool]


class MigrationStage(str, Enum):
    """Observable stages used in failure diagnostics."""

    PREFLIGHT = "preflight"
    SERIAL_DFU = "SoftDevice+bootloader Serial DFU"
    TARGET_BOOTLOADER = "target bootloader verification"
    APPLICATION = "matching application UF2 transfer"
    RUNTIME = "runtime verification"


@dataclass(frozen=True)
class BootloaderPort:
    """USB identity for one serial CDC bootloader interface."""

    device: str
    vid: Optional[int]
    pid: Optional[int]
    serial_number: Optional[str]
    location: Optional[str]

    @property
    def usb_id(self) -> tuple[Optional[int], Optional[int]]:
        return self.vid, self.pid


@dataclass(frozen=True)
class BootloaderTarget:
    """One conservatively matched UF2 volume and CDC interface."""

    volume: Path
    port: BootloaderPort
    info: Uf2BoardInfo


def snapshot_bootloader_ports() -> Dict[str, BootloaderPort]:
    """Snapshot serial ports, keyed case-insensitively by device name."""
    return {
        port.device.casefold(): BootloaderPort(
            device=port.device,
            vid=port.vid,
            pid=port.pid,
            serial_number=port.serial_number,
            location=port.location,
        )
        for port in list_ports.comports()
    }


def _known_usb_ids() -> set[tuple[int, int]]:
    return {profile.usb_id for profile in get_profiles().values()}


def _is_changed_port(port: BootloaderPort, previous: Dict[str, BootloaderPort]) -> bool:
    old = previous.get(port.device.casefold())
    return old is None or old.usb_id != port.usb_id or old.serial_number != port.serial_number


def wait_for_bootloader_port(
    previous: Dict[str, BootloaderPort],
    *,
    preferred_port: str = "",
    expected_usb_id: Optional[tuple[int, int]] = None,
    expected_location: str = "",
    timeout: float = 10,
    poll_interval: float = 0.25,
) -> BootloaderPort:
    """Wait for exactly one allowlisted Adafruit-derived bootloader CDC port."""
    deadline = time.monotonic() + timeout
    preferred = preferred_port.casefold()
    while time.monotonic() < deadline:
        ports = snapshot_bootloader_ports()
        candidates = [
            port
            for port in ports.values()
            if port.usb_id in _known_usb_ids() and (expected_usb_id is None or port.usb_id == expected_usb_id)
        ]
        if expected_location:
            candidates = [port for port in candidates if port.location == expected_location]
        if preferred:
            preferred_matches = [port for port in candidates if port.device.casefold() == preferred]
            if len(preferred_matches) == 1:
                return preferred_matches[0]

        changed = [port for port in candidates if _is_changed_port(port, previous)]
        if len(changed) == 1:
            return changed[0]
        if len(changed) > 1:
            devices = ", ".join(sorted(port.device for port in changed))
            raise MPFlashError(f"Multiple new nRF bootloader CDC ports appeared: {devices}")
        time.sleep(poll_interval)

    raise MPFlashError(
        "No new or explicitly selected allowlisted nRF bootloader CDC port appeared; "
        "for an already-mounted UF2 volume, also specify its CDC port with --serial"
    )


def wait_for_runtime_port(
    previous: Dict[str, BootloaderPort],
    bootloader: BootloaderPort,
    *,
    timeout: float = 20,
    poll_interval: float = 0.25,
) -> BootloaderPort:
    """Wait for the application CDC port replacing one bootloader port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ports = snapshot_bootloader_ports()
        candidates = [port for port in ports.values() if port.usb_id not in _known_usb_ids() and _is_changed_port(port, previous)]
        if bootloader.location:
            location_matches = [port for port in candidates if port.location == bootloader.location]
            if len(location_matches) == 1:
                return location_matches[0]
            if len(location_matches) > 1:
                devices = ", ".join(sorted(port.device for port in location_matches))
                raise MPFlashError(f"Multiple runtime CDC ports appeared at the bootloader USB location: {devices}")
        else:
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                devices = ", ".join(sorted(port.device for port in candidates))
                raise MPFlashError(f"Multiple new runtime CDC ports appeared: {devices}")
        time.sleep(poll_interval)

    raise MPFlashError("No unambiguous runtime CDC port appeared after the application UF2 transfer")


def _volume_fingerprints(volumes: Iterable[Path]) -> dict[str, Uf2BoardInfo]:
    return {str(volume).casefold(): read_uf2_board_info(volume) for volume in volumes}


def _matches_profile(info: Uf2BoardInfo, profile: NrfDfuProfile, *, exact_bootloader: bool) -> bool:
    if info.board_id.casefold() != profile.board_id.casefold():
        return False
    if (info.softdevice or "").casefold() != profile.softdevice.casefold():
        return False
    return not exact_bootloader or info.bootloader_version == profile.bootloader_version


def _source_profile(info: Uf2BoardInfo, port: BootloaderPort) -> NrfDfuProfile:
    matches = [
        profile
        for profile in get_profiles().values()
        if _matches_profile(info, profile, exact_bootloader=False)
        and info.bootloader_version in profile.source_bootloader_versions
        and port.usb_id == profile.usb_id
    ]
    if len(matches) != 1:
        raise MPFlashError(
            "The current bootloader is not an allowlisted nice!nano/SuperMini profile: "
            f"Board-ID={info.board_id!r}, bootloader={info.bootloader_version!r}, SoftDevice={info.softdevice!r}, "
            f"USB={port.vid or 0:04X}:{port.pid or 0:04X}"
        )
    return matches[0]


def _validate_explicit_bootloader_pair(
    volume: Path,
    preferred_port: str,
    volumes: Iterable[Path],
    ports: Dict[str, BootloaderPort],
) -> None:
    """Require a unique allowlisted volume and CDC interface for destructive DFU."""
    if not preferred_port:
        raise MPFlashError("An already-mounted nRF UF2 volume requires its CDC interface through --serial")

    candidates = [port for port in ports.values() if port.usb_id in _known_usb_ids()]
    preferred = [port for port in candidates if port.device.casefold() == preferred_port.casefold()]
    if len(candidates) != 1 or len(preferred) != 1:
        devices = ", ".join(sorted(port.device for port in candidates)) or "none"
        raise MPFlashError(
            f"Cannot safely pair the selected UF2 volume with one bootloader CDC interface; allowlisted CDC candidates: {devices}"
        )

    allowlisted_volumes: list[Path] = []
    for mounted in volumes:
        info = read_uf2_board_info(mounted)
        if any(
            _matches_profile(info, profile, exact_bootloader=False) and info.bootloader_version in profile.source_bootloader_versions
            for profile in get_profiles().values()
        ):
            allowlisted_volumes.append(mounted)
    selected = str(volume).casefold()
    if len(allowlisted_volumes) != 1 or str(allowlisted_volumes[0]).casefold() != selected:
        paths = ", ".join(sorted(str(path) for path in allowlisted_volumes)) or "none"
        raise MPFlashError(f"Cannot safely pair the selected CDC interface with one allowlisted UF2 volume; allowlisted volumes: {paths}")


def wait_for_profile_volume(
    profile: NrfDfuProfile,
    previous: dict[str, Uf2BoardInfo],
    *,
    timeout: float = 20,
    poll_interval: float = 0.25,
) -> Path:
    """Wait for one new or changed volume reporting the target profile."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches: list[Path] = []
        for volume in mounted_uf2_volumes():
            info = read_uf2_board_info(volume)
            if not _matches_profile(info, profile, exact_bootloader=True):
                continue
            old = previous.get(str(volume).casefold())
            if old is None or old != info:
                matches.append(volume)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            paths = ", ".join(sorted(str(path) for path in matches))
            raise MPFlashError(f"Multiple target nRF UF2 volumes appeared: {paths}")
        time.sleep(poll_interval)
    raise MPFlashError(f"The target bootloader did not appear as {profile.board_id} with {profile.softdevice}")


def _explicit_volume(mcu: MPRemoteBoard) -> Optional[Path]:
    for value in (getattr(mcu, "path", None), getattr(mcu, "serialport", "")):
        if not value:
            continue
        candidate = Path(str(value))
        try:
            if candidate.is_dir() and (candidate / "INFO_UF2.TXT").is_file():
                return candidate
        except OSError:
            continue
    return None


def _confirmation(
    current: NrfDfuProfile,
    target: NrfDfuProfile,
    application: Path,
    *,
    force_repair: bool,
) -> str:
    if force_repair and current.name == target.name:
        return (
            f"Force-repair {target.board_id} by reinstalling {target.softdevice} and "
            f"bootloader {target.bootloader_version}, then flash {application.name}?\n"
            "UF2 metadata can report the expected version even when the SoftDevice is corrupted. "
            "This erases the current application and filesystem. There is no automatic rollback; "
            "a failed bootloader transfer may require SWD recovery."
        )
    return (
        f"Migrate {current.board_id} from {current.softdevice} to {target.softdevice} and "
        f"{target.board_id} bootloader {target.bootloader_version}, then flash {application.name}?\n"
        "This erases the current application and filesystem. There is no automatic rollback; "
        "a failed bootloader transfer may require SWD recovery."
    )


def migrate_nrf(
    mcu: MPRemoteBoard,
    application: Path,
    target: NrfDfuProfile,
    *,
    confirm: ConfirmMigration,
    bootloader_port: str = "",
    force_repair: bool = False,
    timeout: float = 20,
) -> MPRemoteBoard:
    """Migrate one allowlisted nRF board and install its matching application."""
    stage = MigrationStage.PREFLIGHT
    state = "the original application or bootloader should still be available"
    original_serial = mcu.serialport
    try:
        inspect_application_uf2(application, target)
        volumes_before = mounted_uf2_volumes()
        ports_before = snapshot_bootloader_ports()
        runtime_port_before = ports_before.get(original_serial.casefold())
        explicit_volume = _explicit_volume(mcu)
        volume = explicit_volume
        if explicit_volume is not None:
            _validate_explicit_bootloader_pair(explicit_volume, bootloader_port, volumes_before, ports_before)
        else:
            if mcu.family == "unknown":
                mcu.get_mcu_info()
            volume = enter_nrf_uf2_bootloader(mcu, timeout=int(timeout), existing_volumes=volumes_before)
        assert volume is not None
        info = read_uf2_board_info(volume)
        port = wait_for_bootloader_port(
            ports_before,
            preferred_port=bootloader_port or (original_serial if original_serial.upper().startswith("COM") else ""),
            expected_location="" if explicit_volume is not None or runtime_port_before is None else runtime_port_before.location or "",
            timeout=timeout,
        )
        current = _source_profile(info, port)
        current_target = BootloaderTarget(volume=volume, port=port, info=info)
        already_target = current.name == target.name and _matches_profile(info, target, exact_bootloader=True)

        if force_repair or not already_target:
            if not confirm(_confirmation(current, target, application, force_repair=force_repair)):
                raise MPFlashError("nRF SoftDevice migration cancelled before any writes")
            stage = MigrationStage.SERIAL_DFU
            state = "inspect the mounted UF2 volume before retrying; SWD recovery may be required"
            previous_volumes = _volume_fingerprints(mounted_uf2_volumes())
            if force_repair and already_target:
                previous_volumes.pop(str(volume).casefold(), None)
                log.warning(
                    f"Force-reinstalling {target.softdevice} and bootloader {target.bootloader_version}; "
                    "matching UF2 metadata does not prove SoftDevice integrity"
                )
            target_ports_before = snapshot_bootloader_ports()
            with profile_package_path(target) as package:
                inspect_dfu_package(package, target)
                flash_serial_dfu(package, current_target.port.device, timeout=max(timeout, 180))

            stage = MigrationStage.TARGET_BOOTLOADER
            state = "the target bootloader may be installed without an application"
            volume = wait_for_profile_volume(target, previous_volumes, timeout=timeout)
            port = wait_for_bootloader_port(
                target_ports_before,
                preferred_port=current_target.port.device,
                expected_usb_id=target.usb_id,
                expected_location=current_target.port.location or "",
                timeout=timeout,
            )
            if port.usb_id != target.usb_id:
                raise MPFlashError(
                    f"Target bootloader CDC identity is {port.vid or 0:04X}:{port.pid or 0:04X}, "
                    f"expected {target.usb_vid:04X}:{target.usb_pid:04X}"
                )
        else:
            log.info(f"{target.board_id} already has bootloader {target.bootloader_version} and {target.softdevice}; skipping Serial DFU")

        stage = MigrationStage.APPLICATION
        state = "the target bootloader is installed and can accept a matching application UF2"
        runtime_ports_before = snapshot_bootloader_ports()
        try:
            copy_firmware_to_uf2(application, volume)
        except OSError as exc:
            raise MPFlashError(f"Could not copy {application.name} to {volume}: {exc}") from exc

        stage = MigrationStage.RUNTIME
        state = "the matching application was copied; reset the board and verify its runtime manually"
        runtime_port = wait_for_runtime_port(runtime_ports_before, port, timeout=timeout)
        mcu.serialport = runtime_port.device
        mcu.vid = runtime_port.vid or 0
        mcu.pid = runtime_port.pid or 0
        mcu.serial_number = runtime_port.serial_number or ""
        mcu.location = runtime_port.location or ""
        if not mcu.wait_for_restart(timeout=int(timeout)):
            raise MPFlashError("The migrated board did not reconnect after the application UF2 transfer")
        mcu.softdevice = target.softdevice
        log.success(f"Migrated {target.board_id} to {target.softdevice} and restored its MicroPython application")
        return mcu
    except MPFlashError as exc:
        raise MPFlashError(f"nRF migration failed during {stage.value}: {exc}. Current state: {state}.") from exc

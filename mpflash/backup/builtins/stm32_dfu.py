"""Raw STM32 main-flash backup and restore through dfu-util's DfuSe support."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from mpflash.backup.base import BackupContext, BackupOutput, BackupProvider
from mpflash.backup.bundle import Bundle, sha256_file
from mpflash.backup.models import Artifact, ArtifactRole, ComponentKind, Exactness, ProviderCapability
from mpflash.backup.registry import register
from mpflash.errors import MPFlashError

FLASH_NAME = "flash.bin"
FLASH_BASE = 0x08000000
DFU_DEVICE = ",0483:df11"
DFU_TIMEOUT = 300
RESTART_TIMEOUT = 20

_DEVICE_RE = re.compile(r'Found DFU: \[0483:df11\].*?\balt=(\d+), name="([^"]*)"')
_LAYOUT_RE = re.compile(r"^@Internal Flash /(?P<address>0[xX][0-9a-fA-F]+)/(?P<segments>[^/]+)$")
_SEGMENT_RE = re.compile(r"(?P<count>[0-9]+)\*(?P<size>[0-9]+)(?P<unit>[BKMG])(?P<access>[a-g])")

EXCLUSIONS = (
    "Only the advertised, readable, erasable and writable internal main-flash range is included.",
    "ROM system memory/bootloader, option bytes, OTP, RAM, and read-protected regions are excluded; any "
    "bootloader stored inside the advertised main-flash range is included.",
)
COVERS = (ComponentKind.VFS,)


@dataclass(frozen=True)
class DfuFlashRange:
    """One unambiguous, writable DfuSe internal-flash range."""

    alternate: int
    address: int
    length: int


BootloaderEntry = Callable[[Any], None]


def _enter_dfu(mcu: Any) -> None:
    """Use MPFlash's existing STM32 bootloader activation and readiness checks."""
    from mpflash.common import BootloaderMethod
    from mpflash.flash.registry import get_backend
    from mpflash.flash.services import default_services

    backend = get_backend("dfu")
    if backend is None:
        raise MPFlashError("The STM32 DFU flash backend is not registered")
    if not default_services.enter_bootloader(mcu, BootloaderMethod.AUTO, backend=backend):
        raise MPFlashError(f"Could not put {mcu.serialport} into STM32 DFU mode")


def _tool_path(configured: Optional[str] = None) -> str:
    tool = configured or shutil.which("dfu-util")
    if not tool:
        raise MPFlashError("STM32 raw flash backup requires dfu-util 0.11 or newer on PATH")
    return tool


def _run_dfu_util(tool: str, arguments: Sequence[str], *, timeout: int = DFU_TIMEOUT) -> str:
    command = [tool, *arguments]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MPFlashError(f"dfu-util timed out after {timeout} seconds") from exc
    except OSError as exc:
        raise MPFlashError(f"Could not run dfu-util: {exc}") from exc

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode:
        detail = f": {output}" if output else ""
        raise MPFlashError(f"dfu-util failed with exit code {result.returncode}{detail}")
    return output


def parse_flash_range(output: str) -> DfuFlashRange:
    """Parse exactly one fully accessible DfuSe internal-flash range from ``dfu-util -l -v``."""
    candidates: list[DfuFlashRange] = []
    internal_flash_ranges = 0
    unsupported_base: Optional[int] = None
    for match in _DEVICE_RE.finditer(output):
        alternate, name = int(match.group(1)), match.group(2)
        if name.startswith("@Internal Flash"):
            internal_flash_ranges += 1
        layout = _LAYOUT_RE.fullmatch(name)
        if not layout:
            if name.startswith("@Internal Flash"):
                raise MPFlashError(f"Ambiguous STM32 internal-flash layout: {name!r}")
            continue

        address = int(layout.group("address"), 16)
        if address != FLASH_BASE:
            if name.startswith("@Internal Flash"):
                unsupported_base = address
            continue

        length = 0
        for raw_segment in layout.group("segments").split(","):
            segment = _SEGMENT_RE.fullmatch(raw_segment)
            if segment is None:
                raise MPFlashError(f"Invalid STM32 DfuSe memory segment: {raw_segment!r}")
            count = int(segment.group("count"))
            page_size = int(segment.group("size"))
            access = segment.group("access")
            if count <= 0 or page_size <= 0:
                raise MPFlashError(f"Invalid STM32 DfuSe memory segment: {raw_segment!r}")
            if access != "g":
                raise MPFlashError(f"STM32 internal-flash segment {raw_segment!r} is not advertised as readable, erasable, and writable")
            multiplier = {"B": 1, "K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024}[segment.group("unit")]
            length += count * page_size * multiplier

        if length <= 0 or length > 0xFFFFFFFF or address + length > 0x100000000:
            raise MPFlashError(f"Invalid STM32 internal-flash range length {length}")
        candidates.append(DfuFlashRange(alternate=alternate, address=address, length=length))

    if internal_flash_ranges > 1:
        raise MPFlashError("dfu-util advertised multiple STM32 internal-flash ranges; refusing an ambiguous layout")
    if not candidates and unsupported_base is not None:
        raise MPFlashError(f"Unsupported STM32 internal-flash base address {unsupported_base:#010x}")
    if len(candidates) != 1:
        if not candidates:
            raise MPFlashError("dfu-util did not advertise one readable, erasable, writable internal flash range at 0x08000000")
        raise MPFlashError("dfu-util advertised multiple STM32 internal-flash ranges; refusing an ambiguous layout")
    return candidates[0]


def _flash_artifact(artifacts: Sequence[Artifact]) -> Artifact:
    raw = [item for item in artifacts if item.component is ComponentKind.FLASH and item.role is ArtifactRole.DEVICE_READ]
    if len(raw) != 1 or len(artifacts) != 1:
        raise MPFlashError("The bundle must contain exactly one raw STM32 flash image to restore")
    artifact = raw[0]
    if artifact.address != FLASH_BASE or artifact.length is None or artifact.length <= 0:
        raise MPFlashError("Only a raw STM32 main-flash image starting at 0x08000000 can be restored")
    return artifact


class STM32DfuProvider(BackupProvider):
    """Back up and restore advertised STM32 internal main flash through dfu-util."""

    name = "stm32-dfu-flash"
    priority = 10

    def __init__(self, tool: Optional[str] = None, enter_dfu: BootloaderEntry = _enter_dfu):
        self._configured_tool = tool
        self._enter_dfu = enter_dfu

    def is_available(self) -> bool:
        return bool(self._configured_tool or shutil.which("dfu-util"))

    def capabilities(self, mcu: Any) -> Sequence[ProviderCapability]:
        if not getattr(mcu, "connected", False) or getattr(mcu, "family", "") != "micropython" or getattr(mcu, "port", "") != "stm32":
            return ()
        return (
            ProviderCapability(
                component=ComponentKind.FLASH,
                can_backup=True,
                can_restore=True,
                exactness=Exactness.EXACT,
                covers=COVERS,
                exclusions=EXCLUSIONS,
            ),
        )

    def _layout(self, mcu: Any, tool: str) -> DfuFlashRange:
        self._enter_dfu(mcu)
        output = _run_dfu_util(tool, ["--device", DFU_DEVICE, "--list", "--verbose"])
        if not _DEVICE_RE.search(output):
            raise MPFlashError("dfu-util found no STM32 DFU device; enter the STM32 system bootloader and check the USB driver")
        return parse_flash_range(output)

    @staticmethod
    def _transfer_arguments(layout: DfuFlashRange, operation: str, path: Path) -> list[str]:
        return [
            "--device",
            DFU_DEVICE,
            "--alt",
            str(layout.alternate),
            "--dfuse-address",
            f"{layout.address:#010x}:{layout.length}:leave",
            operation,
            str(path),
        ]

    @staticmethod
    def _wait_for_restart(mcu: Any, operation: str) -> None:
        mcu.connected = False
        if not mcu.wait_for_restart(timeout=RESTART_TIMEOUT):
            raise MPFlashError(f"{mcu.serialport} did not reconnect after STM32 DFU {operation}")

    def _read_and_leave(self, mcu: Any, tool: str, layout: DfuFlashRange, path: Path, length: int) -> None:
        prefix = DfuFlashRange(alternate=layout.alternate, address=layout.address, length=length)
        _run_dfu_util(tool, self._transfer_arguments(prefix, "--upload", path))
        if not path.is_file() or path.stat().st_size != length:
            actual = path.stat().st_size if path.is_file() else 0
            raise MPFlashError(f"dfu-util uploaded {actual} bytes, expected {length}")
        self._wait_for_restart(mcu, "read")

    def backup(self, mcu: Any, component: ComponentKind, ctx: BackupContext) -> BackupOutput:
        if component is not ComponentKind.FLASH:
            raise MPFlashError(f"STM32 DfuSe cannot back up {component.value}")
        tool = _tool_path(self._configured_tool)
        layout = self._layout(mcu, tool)
        target = ctx.writer.artifact_path(FLASH_NAME)
        _run_dfu_util(tool, self._transfer_arguments(layout, "--upload", target))
        if not target.is_file() or target.stat().st_size != layout.length:
            actual = target.stat().st_size if target.is_file() else 0
            raise MPFlashError(f"dfu-util uploaded {actual} bytes, expected {layout.length}")
        self._wait_for_restart(mcu, "backup")
        ctx.writer.register_artifact(
            FLASH_NAME,
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider=self.name,
            address=layout.address,
            length=layout.length,
            covers=COVERS,
            exclusions=EXCLUSIONS,
        )
        return BackupOutput(notes=(f"Read {layout.length} bytes of STM32 main flash through DfuSe.",))

    def describe_restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> Sequence[str]:
        bundle.verify()
        artifact = _flash_artifact(artifacts)
        assert artifact.length is not None
        tool = _tool_path(self._configured_tool)
        layout = self._layout(mcu, tool)
        with tempfile.TemporaryDirectory(prefix="mpflash-stm32-inspect-") as temporary:
            self._read_and_leave(mcu, tool, layout, Path(temporary) / "readable.bin", 1)
        self._check_layout(layout, artifact)
        return [
            f"erase and rewrite {layout.length} bytes of advertised STM32 main flash at {layout.address:#010x}",
            "exclude ROM system memory/bootloader, option bytes, OTP, and read-protected regions; include any "
            "bootloader stored inside main flash",
            "read the flash back through DfuSe, verify SHA-256, and return the board to MicroPython",
        ]

    def restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> None:
        artifact = _flash_artifact(artifacts)
        assert artifact.length is not None
        tool = _tool_path(self._configured_tool)
        source = bundle.artifact_path(artifact)
        expected_hash = sha256_file(source)
        if expected_hash != artifact.sha256:
            raise MPFlashError("The STM32 flash image changed after the bundle was validated; refusing to restore it")
        layout = self._layout(mcu, tool)
        if layout.address != artifact.address or layout.length != artifact.length:
            with tempfile.TemporaryDirectory(prefix="mpflash-stm32-inspect-") as temporary:
                self._read_and_leave(mcu, tool, layout, Path(temporary) / "readable.bin", 1)
            self._check_layout(layout, artifact)

        _run_dfu_util(tool, self._transfer_arguments(layout, "--download", source))
        self._wait_for_restart(mcu, "restore")

        verified_layout = self._layout(mcu, tool)
        if verified_layout.address != artifact.address or verified_layout.length != artifact.length:
            with tempfile.TemporaryDirectory(prefix="mpflash-stm32-inspect-") as temporary:
                self._read_and_leave(mcu, tool, verified_layout, Path(temporary) / "readable.bin", 1)
            self._check_layout(verified_layout, artifact)
        with tempfile.TemporaryDirectory(prefix="mpflash-stm32-verify-") as temporary:
            readback = Path(temporary) / FLASH_NAME
            _run_dfu_util(tool, self._transfer_arguments(verified_layout, "--upload", readback))
            if not readback.is_file() or readback.stat().st_size != layout.length:
                actual = readback.stat().st_size if readback.is_file() else 0
                raise MPFlashError(f"dfu-util verified {actual} bytes, expected {layout.length}")
            actual_hash = sha256_file(readback)
        self._wait_for_restart(mcu, "restore verification")
        if actual_hash != expected_hash:
            raise MPFlashError("The STM32 main-flash readback does not match the backup after restoring it")

    @staticmethod
    def _check_layout(layout: DfuFlashRange, artifact: Artifact) -> None:
        if layout.address != artifact.address or layout.length != artifact.length:
            raise MPFlashError(
                f"The bundle covers {artifact.length} bytes at {artifact.address:#010x}, but this STM32 advertises "
                f"{layout.length} bytes at {layout.address:#010x}"
            )


register(STM32DfuProvider())

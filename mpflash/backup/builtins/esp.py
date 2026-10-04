"""Raw main-flash backup and restore for ESP32 and ESP8266 through esptool.

A backup is a byte-exact read of the whole attached SPI flash from address 0, so it includes the
bootloader, partition table, firmware *and* the filesystem. Restore rewrites the entire flash and
verifies it with an independent MD5 of the device against the file.

This is not a whole-device clone: eFuses/OTP (MAC address, keys, security configuration) are not
part of flash and are never read or written. Devices that use flash encryption, secure boot or
secure download mode are refused, because their flash cannot be read or rewritten faithfully.

``esptool`` is imported lazily so that importing mpflash stays fast.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Generator, List, Optional, Protocol, Sequence

from mpflash.backup.base import BackupContext, BackupOutput, BackupProvider
from mpflash.backup.bundle import Bundle
from mpflash.backup.models import Artifact, ArtifactRole, ComponentKind, Exactness, ProviderCapability
from mpflash.backup.registry import register
from mpflash.errors import MPFlashError
from mpflash.logger import log

FLASH_NAME = "flash.bin"
#: Espressif's USB VID. Boards on it use the chip's own USB, which has no DTR/RTS lines for esptool to reset with.
ESPRESSIF_USB_VID = 0x303A
#: The built-in USB-Serial/JTAG peripheral (ESP32-C3/C6/H2, and the S3 when it uses it). esptool resets
#: it into the bootloader itself, verified on an ESP32-C3. Other Espressif USB IDs, such as the TinyUSB
#: CDC of an ESP32-S2/S3 running MicroPython (0x4001), need machine.bootloader() and a re-enumeration
#: that is not implemented, so they are not offered.
USB_SERIAL_JTAG_PID = 0x1001
_FALLBACK_BAUD = 115_200
_USB_JTAG_FRAME = 2048
_DISK_MARGIN = 16 * 1024 * 1024
_BOARD_BACK_TIMEOUT = 20

EXCLUSIONS = (
    "eFuses/OTP (MAC address, keys and security configuration) are not part of flash and are not included.",
    "Only the SPI flash contents are included; RAM, RTC memory and PSRAM are not.",
)
#: A raw image contains the filesystem and ROMFS partitions, so restoring it replaces both.
COVERS = (ComponentKind.VFS, ComponentKind.ROMFS)


class EspDevice(Protocol):
    """What the provider needs from a connected ESP chip in its ROM bootloader."""

    chip: str

    def flash_size(self) -> int:
        """Return the size in bytes of the attached SPI flash."""
        ...

    def security_problems(self) -> List[str]:
        """Return why raw read/restore is unsafe, or an empty list."""
        ...

    def read_flash(self, path: Path, size: int) -> None: ...

    def write_flash(self, path: Path) -> None: ...

    def flash_md5(self, size: int) -> str: ...

    def hard_reset(self) -> None: ...


Connector = Callable[..., "Any"]  # (port, cpu) -> context manager yielding an EspDevice


class _EsptoolDevice:
    """:class:`EspDevice` implemented with the esptool >= 5 Python API."""

    def __init__(self, esp: Any, cmds: Any):
        self._esp = esp
        self._cmds = cmds
        self.chip = str(esp.CHIP_NAME)

    def flash_size(self) -> int:
        from esptool.util import flash_size_bytes

        try:
            size = flash_size_bytes(self._cmds.detect_flash_size(self._esp))
        except Exception as error:  # noqa: BLE001 - esptool raises FatalError and others
            raise MPFlashError(f"Could not detect the flash size of the {self.chip}: {error}") from error
        if not size:
            raise MPFlashError(f"Could not detect the flash size of the {self.chip}")
        return size

    def security_problems(self) -> List[str]:
        if getattr(self._esp, "secure_download_mode", False):
            return ["the chip is in secure download mode"]
        problems = []
        for description, check in (
            ("flash encryption is enabled", self._esp.get_flash_encryption_enabled),
            ("secure boot is enabled", self._esp.get_secure_boot_enabled),
        ):
            try:
                if check():
                    problems.append(description)
            except Exception as error:  # noqa: BLE001 - not knowing is not safe
                problems.append(f"it could not be determined whether {description.rsplit(' is ', 1)[0]} is enabled ({error})")
        return problems

    def read_flash(self, path: Path, size: int) -> None:
        if self._uses_usb_jtag():
            self._read_in_small_frames(path, size)
            return
        self._cmds.read_flash(self._esp, 0, size, output=str(path), flash_size="keep")

    def _uses_usb_jtag(self) -> bool:
        try:
            return bool(self._esp.uses_usb_jtag_serial())
        except Exception:  # noqa: BLE001 - not knowing means the standard path
            return False

    def _read_in_small_frames(self, path: Path, size: int) -> None:
        """Read the flash with the stub's frame size lowered to 2 KiB.

        With esptool 5.3.0 the stub's 4 KiB frames stall the built-in USB-Serial/JTAG of an ESP32-C3 on some
        flash content (deterministic at 0x108000 of one board; esptool 5.4.0 reads it). 2 KiB frames read
        the same bytes reliably on both. This is esptool's own ``read_flash`` with a different frame size.
        """
        esp = self._esp
        esp.check_command("read flash", esp.ESP_CMDS["READ_FLASH"], struct.pack("<IIII", 0, size, _USB_JTAG_FRAME, 64))
        md5 = hashlib.md5(usedforsecurity=False)
        received = 0
        with path.open("wb") as stream:
            while received < size:
                esp._port.timeout = 3
                frame = esp.read()
                stream.write(frame)
                md5.update(frame)
                received += len(frame)
                esp.write(struct.pack("<I", received))
        if received != size or esp.read().hex() != md5.hexdigest():
            raise MPFlashError(f"The flash read from the {self.chip} did not match its checksum")

    def write_flash(self, path: Path) -> None:
        # All "keep": the image is written exactly as stored. No force: esptool's guards stay active.
        self._cmds.write_flash(
            self._esp,
            [(0, str(path))],
            flash_mode="keep",
            flash_freq="keep",
            flash_size="keep",
            compress=True,
        )

    def flash_md5(self, size: int) -> str:
        return str(self._esp.flash_md5sum(0, size)).lower()

    def hard_reset(self) -> None:
        self._cmds.reset_chip(self._esp, "hard-reset")


@contextmanager
def connect_esptool(serialport: str, cpu: str) -> Generator[EspDevice, None, None]:
    """Connect to ``serialport`` in the ROM bootloader, load the flasher stub and raise the baud rate.

    Falls back to 115200 baud when the faster rate fails. UART bridges enter the bootloader through
    esptool's automatic DTR/RTS reset.
    """
    import esptool.cmds as cmds
    from mpflash.flash.builtins.esp import _chip_params

    _, _, baud = _chip_params(cpu or "esp32")
    attempts: List[Optional[int]] = [baud, None]  # None = stay at the default baud rate
    last_error: Optional[Exception] = None
    for attempt in attempts:
        connected = False
        try:
            with cmds.detect_chip(port=serialport) as esp:
                esp = cmds.run_stub(esp)
                if attempt:
                    esp.change_baud(attempt)
                connected = True
                yield _EsptoolDevice(esp, cmds)
                return
        except MPFlashError:
            raise
        except GeneratorExit:  # pragma: no cover - the caller left the block
            raise
        except Exception as error:  # noqa: BLE001 - esptool raises FatalError, serial and OS errors
            if connected:
                raise  # a failure inside the caller's block is not a connection failure
            if attempt is None:
                raise MPFlashError(f"Could not connect to the ESP bootloader on {serialport}: {error}") from error
            last_error = error
            log.warning(f"Could not connect to {serialport} at {attempt} baud ({error}); retrying at {_FALLBACK_BAUD}")
    raise MPFlashError(f"Could not connect to the ESP bootloader on {serialport}: {last_error}")  # pragma: no cover


def _normalise(chip: str) -> str:
    return chip.replace("-", "").replace("_", "").casefold()


def _file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _flash_artifact(artifacts: Sequence[Artifact]) -> Artifact:
    raw = [a for a in artifacts if a.component is ComponentKind.FLASH and a.role is ArtifactRole.DEVICE_READ]
    if len(raw) != 1 or len(artifacts) != 1:
        raise MPFlashError("The bundle must contain exactly one raw flash image to restore")
    artifact = raw[0]
    if artifact.address != 0 or artifact.length is None:
        raise MPFlashError("Only a raw flash image that starts at address 0 can be restored")
    return artifact


class EspFlashProvider(BackupProvider):
    """Back up and restore the entire SPI flash of a UART-connected ESP32/ESP8266."""

    name = "esptool-flash"
    priority = 10

    def __init__(self, connector: Connector = connect_esptool):
        self._connect = connector

    def capabilities(self, mcu: Any) -> Sequence[ProviderCapability]:
        if not getattr(mcu, "connected", False) or getattr(mcu, "port", "") not in ("esp32", "esp8266"):
            return ()
        if str(getattr(mcu, "board", "")).startswith("ARDUINO_"):
            return ()
        if getattr(mcu, "vid", 0) == ESPRESSIF_USB_VID and getattr(mcu, "pid", 0) != USB_SERIAL_JTAG_PID:
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

    # -- backup ------------------------------------------------------------

    def backup(self, mcu: Any, component: ComponentKind, ctx: BackupContext) -> BackupOutput:
        writer = ctx.writer
        target = writer.artifact_path(FLASH_NAME)
        with self._connect(mcu.serialport, mcu.cpu) as device:
            self._require_safe(device, "back up")
            size = device.flash_size()
            free = shutil.disk_usage(target.parent).free
            if free < size + _DISK_MARGIN:
                raise MPFlashError(f"Not enough disk space: the {size}-byte flash image needs more than the {free} bytes free")
            log.info(f"Reading {size} bytes of flash from the {device.chip} on {mcu.serialport}")
            device.read_flash(target, size)
            if not target.is_file() or target.stat().st_size != size:
                raise MPFlashError(f"The flash read produced {target.stat().st_size if target.is_file() else 0} bytes, expected {size}")
            chip = device.chip
            device.hard_reset()
        self._wait_for_board(mcu, "reading the flash")
        writer.register_artifact(
            FLASH_NAME,
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider=self.name,
            address=0,
            length=size,
            covers=COVERS,
            exclusions=EXCLUSIONS,
        )
        return BackupOutput(notes=(f"Flash: {size} bytes read from the {chip} through esptool; it includes the filesystem.",))

    # -- restore -----------------------------------------------------------

    def describe_restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> Sequence[str]:
        artifact = _flash_artifact(artifacts)
        with self._connect(mcu.serialport, mcu.cpu) as device:
            self._check_target(device, bundle, artifact)
            device.hard_reset()
        self._wait_for_board(mcu, "checking the board")
        assert artifact.length is not None
        return [
            f"ERASE and rewrite the ENTIRE flash: {artifact.length} bytes at 0x{artifact.address:08X} of the {bundle.manifest.device.cpu}",
            "this replaces the bootloader, partition table, firmware and the filesystem (and ROMFS)",
            "the result is verified against the image by MD5; eFuses and keys are not touched",
            "checking the board briefly resets it",
        ]

    def restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> None:
        artifact = _flash_artifact(artifacts)
        assert artifact.length is not None
        image = bundle.artifact_path(artifact)
        with self._connect(mcu.serialport, mcu.cpu) as device:
            self._check_target(device, bundle, artifact)
            log.info(f"Writing {artifact.length} bytes of flash to the {device.chip} on {mcu.serialport}")
            device.write_flash(image)
            written = device.flash_md5(artifact.length)
            expected = _file_md5(image)
            if written != expected:
                raise MPFlashError(
                    f"The flash did not verify after writing (device MD5 {written}, image MD5 {expected}). "
                    "The board may not boot; restore again or reflash firmware with `mpflash flash`."
                )
            device.hard_reset()
        self._wait_for_board(mcu, "restoring the flash", fatal=False)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _require_safe(device: EspDevice, action: str) -> None:
        problems = device.security_problems()
        if problems:
            raise MPFlashError(
                f"Cannot {action} the flash of this {device.chip}: {'; '.join(problems)}. Raw flash backup does not support secured chips."
            )

    def _check_target(self, device: EspDevice, bundle: Bundle, artifact: Artifact) -> None:
        self._require_safe(device, "restore")
        wanted = bundle.manifest.device.cpu
        if not wanted:
            raise MPFlashError("The bundle does not record which chip it was made from, so a raw restore cannot be checked")
        if _normalise(device.chip) != _normalise(wanted):
            raise MPFlashError(f"The bundle was made from an {wanted} but this board has an {device.chip}")
        size = device.flash_size()
        if size != artifact.length:
            raise MPFlashError(f"The image is {artifact.length} bytes but this board has {size} bytes of flash; they must be identical")

    @staticmethod
    def _wait_for_board(mcu: Any, after: str, *, fatal: bool = True) -> None:
        mcu.connected = False
        if mcu.wait_for_restart(timeout=_BOARD_BACK_TIMEOUT):
            return
        message = f"{mcu.serialport} did not come back after {after}"
        if fatal:
            raise MPFlashError(message)
        log.warning(f"{message}; the flash was verified before the reset")


register(EspFlashProvider())

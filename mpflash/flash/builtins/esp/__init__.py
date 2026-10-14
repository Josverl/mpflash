"""Flash ESP32 and ESP8266 via the esptool Python API (esptool ≥ 5.0).

This module uses ``esptool.cmds`` functions directly instead of building
CLI argument lists and routing them through ``esptool.main()``.

Upgrade rationale (esptool ≥ 5.0 vs. esptool.main())
------------------------------------------------------
Pros
~~~~
* No ``sys.exit()`` risk — all errors surface as typed Python exceptions.
* Clean, stable function signatures instead of argparse ``Namespace`` objects.
* A single serial connection is opened, reused for erase + write, then closed
  automatically via the context-manager protocol.
* Compression is enabled for **all** chips (ESP32 and ESP8266) because the
  flasher stub supports it; esptool also auto-falls back internally when
  compressed data is larger than uncompressed.
* Easier to add progress callbacks or other programmatic control in future.

Cons
~~~~
* Requires esptool ≥ 5.0 (API stabilised in that release).
* Slightly more explicit than a single ``esptool.main()`` call.

The equivalent ``esptool`` CLI commands are always logged so that users can
copy-paste them for manual flashing or troubleshooting.
"""

import struct
import time
from pathlib import Path
from typing import Literal, Optional, Tuple

import esptool.cmds as espcmds
from esptool import FatalError
from esptool.bin_image import ESP32FirmwareImage, LoadFirmwareImage
from esptool.targets import CHIP_DEFS
from loguru import logger as log

from mpflash.errors import MPFlashError
from mpflash.mpboard_id import find_known_board
from mpflash.mpremoteboard import MPRemoteBoard

FlashMode = Literal["keep", "qio", "qout", "dio", "dout"]

# Baud rates per chip key — the only thing not exposed by esptool ROM classes.
_BAUD_FOR: dict = {
    "esp8266": 460_800,
    "esp32s2": 460_800,
    "esp32c6": 460_800,
}
_DEFAULT_BAUD = 921_600
_RETRY_BAUD = 115_200
_DND_AFTER_FLASH = 1  # ESP32 Magic reset time needed - give the board a moment to reset before trying to reconnect


def _chip_params(cpu: str) -> Tuple[str, str, int]:
    """Return ``(chip_key, start_addr_hex, baud_rate)`` for a CPU string.

    Flash start addresses are read directly from the esptool ROM class
    (``CHIP_DEFS[chip_key].BOOTLOADER_FLASH_OFFSET``) so they stay correct
    for any chip esptool supports without duplication.

    Args:
        cpu: CPU identifier, e.g. ``"ESP32"``, ``"ESP32S3"``, ``"ESP32P4"``.

    Returns:
        A tuple of ``(esptool chip key, flash start address hex, baud rate)``.

    Raises:
        MPFlashError: The CPU is not supported by the installed esptool.
    """
    # Normalise: "ESP32-P4" or "ESP32P4" → "esp32p4"
    chip_key = cpu.lower().replace("-", "")
    rom_cls = CHIP_DEFS.get(chip_key)
    if rom_cls is None:
        raise MPFlashError(f"Unknown CPU {cpu!r}; refusing to assume ESP32 flash parameters")
    start_addr = hex(rom_cls.BOOTLOADER_FLASH_OFFSET)
    baud = _BAUD_FOR.get(chip_key, _DEFAULT_BAUD)
    return chip_key, start_addr, baud


def _log_esptool_cmd(
    chip: str,
    serialport: str,
    baud_rate: int,
    start_addr: str,
    fw_file: Path,
    flash_mode: str,
    flash_size: str,
    *,
    compress: bool,
    erase: bool,
) -> None:
    """Log the esptool CLI equivalents so users can flash manually.

    Args:
        chip: esptool chip name.
        serialport: Serial port path.
        baud_rate: Flashing baud rate.
        start_addr: Hex flash start address string.
        fw_file: Firmware file path.
        flash_mode: SPI flash mode.
        flash_size: Flash size specifier.
        compress: Whether to show ``--compress`` or ``--no-compress``.
        erase: Whether to include ``--erase-all`` in the write command.
    """
    erase_flag = " --erase-all" if erase else ""
    compress_flag = "--compress" if compress else "--no-compress"
    log.info(
        f"  esptool --chip {chip} --port {serialport} -b {baud_rate}"
        f" write_flash{erase_flag} --flash_mode {flash_mode} --flash_size {flash_size}"
        f" {compress_flag} {start_addr} {fw_file}"
    )


def _attempt_flash(
    mcu: MPRemoteBoard,
    chip: str,
    start_addr: str,
    baud_rate: int,
    fw_file: Path,
    flash_mode: str,
    flash_size: str,
    *,
    erase: bool,
) -> None:
    """Perform a single flash attempt over a fresh serial connection.

    Validates the firmware and detected chip before any erase or write.
    esptool performs its revision and security checks before an optional
    full erase. If compressed writing fails, retry without compression.

    Args:
        mcu: Board to flash.
        chip: esptool chip key (e.g. ``"esp32"``).
        start_addr: Hex flash start address string.
        baud_rate: Baud rate for the flash operation.
        fw_file: Path to the firmware file.
        flash_mode: SPI flash mode written into the image header.
        flash_size: Flash size specifier.
        erase: Whether to erase all flash before writing.

    Raises:
        Exception: Any esptool error that occurs during the flash operation.
    """
    _log_esptool_cmd(chip, mcu.serialport, baud_rate, start_addr, fw_file, flash_mode, flash_size, compress=True, erase=erase)

    try:
        image = LoadFirmwareImage(chip, str(fw_file))
    except (FatalError, OSError, RuntimeError, struct.error) as exc:
        raise MPFlashError(f"Invalid {chip} firmware {fw_file}: {exc}") from exc
    expected_rom = CHIP_DEFS[chip]
    if chip != "esp8266":
        if not isinstance(image, ESP32FirmwareImage):
            raise MPFlashError(f"Invalid {chip} firmware {fw_file}: expected an ESP32-family image")
        if image.chip_id != expected_rom.IMAGE_CHIP_ID:
            raise MPFlashError(f"Refusing firmware {fw_file}: image chip ID {image.chip_id} does not match {expected_rom.CHIP_NAME}")

    addr_data = [(int(start_addr, 16), str(fw_file))]
    write_kwargs = {"flash_mode": flash_mode, "flash_size": flash_size}

    with espcmds.detect_chip(port=mcu.serialport) as esp:
        if esp.CHIP_NAME != expected_rom.CHIP_NAME:
            raise MPFlashError(
                f"Refusing to flash {mcu.serialport}: detected {esp.CHIP_NAME}, but {mcu.board} firmware requires {expected_rom.CHIP_NAME}"
            )
        esp = espcmds.run_stub(esp)
        esp.change_baud(baud_rate)

        log.info("Writing flash (compressed)...")
        try:
            # Let esptool validate image/revision/security before a full erase.
            espcmds.write_flash(esp, addr_data, **write_kwargs, erase_all=erase, compress=True)  # type: ignore
        except FatalError as exc:
            log.warning(f"Compressed write failed ({exc}), retrying without compression...")
            _log_esptool_cmd(chip, mcu.serialport, baud_rate, start_addr, fw_file, flash_mode, flash_size, compress=False, erase=erase)
            espcmds.write_flash(esp, addr_data, **write_kwargs, erase_all=erase, no_compress=True)  # type: ignore

        espcmds.reset_chip(esp)


def flash_esp(
    mcu: MPRemoteBoard,
    fw_file: Path,
    *,
    erase: bool = True,
    flash_mode: FlashMode = "keep",
    flash_size: str = "detect",
    retry_on_error: bool = True,
    retry_baud: int = _RETRY_BAUD,
    retry_flash_mode: FlashMode = "dio",
) -> Optional[MPRemoteBoard]:
    """Flash ESP32/ESP8266 firmware using the esptool Python API.

    Validates the firmware and target chip, optionally erases flash, then writes the firmware
    with compression enabled for all chips.  If the compressed write raises a
    ``FatalError`` (e.g. stub not available), the write is retried without
    compression.  If the entire flash attempt fails and ``retry_on_error`` is
    ``True``, a second attempt is made at ``retry_baud`` with ``retry_flash_mode``.

    Args:
        mcu: Board to flash.
        fw_file: Path to the ``.bin`` firmware file.
        erase: Erase all flash before writing (default ``True``).
        flash_mode: SPI flash mode written into the image header.
        flash_size: Flash size (``"detect"`` auto-detects on the device).
        retry_on_error: Retry with lower baud / different flash mode on failure.
        retry_baud: Baud rate to use for the retry attempt (default 115200).
        retry_flash_mode: SPI flash mode for the retry attempt (default ``"dio"``).

    Returns:
        The updated ``MPRemoteBoard`` on success, ``None`` on failure.

    Raises:
        MPFlashError: Firmware or chip validation fails, or the board does
            not restart into MicroPython after the write.

    .. note::
        Internal implementation behind
        :class:`mpflash.flash.builtins.esptool_backend.EsptoolBackend`. Public
        callers should use :func:`mpflash.flash.flash_mcu` with
        ``method=FlashMethod.ESPTOOL``.
    """
    if mcu.port not in ["esp32", "esp8266"] or mcu.board.startswith("ARDUINO_"):
        log.error(f"esptool not supported for {mcu.port} {mcu.board} on {mcu.serialport}")
        return None

    log.info(f"Flashing {fw_file} on {mcu.board} on {mcu.serialport}")
    if not mcu.cpu:
        mcu.cpu = find_known_board(mcu.board).mcu

    chip, start_addr, baud_rate = _chip_params(str(mcu.cpu))

    try:
        _attempt_flash(mcu, chip, start_addr, baud_rate, fw_file, flash_mode, flash_size, erase=erase)
    except MPFlashError:
        raise
    except Exception as first_exc:
        log.error(f"Failed to flash {mcu.board} on {mcu.serialport}: {first_exc}")
        if not retry_on_error:
            return None
        log.warning(f"Retrying at {retry_baud} baud with flash_mode={retry_flash_mode!r}...")
        try:
            _attempt_flash(mcu, chip, start_addr, retry_baud, fw_file, retry_flash_mode, flash_size, erase=erase)
        except MPFlashError:
            raise
        except Exception as retry_exc:
            log.error(f"Retry also failed for {mcu.board} on {mcu.serialport}: {retry_exc}")
            return None

    log.info("Done flashing, board has been reset ...")
    time.sleep(_DND_AFTER_FLASH)  # Magic reset time needed - give the board a moment to reset before trying to reconnect
    if not mcu.wait_for_restart():
        raise MPFlashError(
            f"Firmware was written to {mcu.serialport}, but the board did not restart into MicroPython; "
            "flash success could not be confirmed"
        )
    log.success(f"Flashed {mcu.serialport} to {mcu.board} {mcu.version}")
    return mcu

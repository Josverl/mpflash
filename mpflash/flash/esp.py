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

from pathlib import Path
from typing import Literal, Optional, Tuple

import esptool.cmds as espcmds
from esptool import FatalError
from esptool.loader import ESPLoader
from loguru import logger as log

from mpflash.mpboard_id import find_known_board
from mpflash.mpremoteboard import MPRemoteBoard

FlashMode = Literal["keep", "qio", "qout", "dio", "dout"]


def _chip_params(cpu: str) -> Tuple[str, str, int]:
    """Return ``(chip_name, start_addr_hex, baud_rate)`` for a CPU string.

    Args:
        cpu: CPU identifier, e.g. ``"ESP32"``, ``"ESP32S3"``, ``"ESP8266"``.

    Returns:
        A tuple of ``(esptool chip name, flash start address, baud rate)``.
    """
    cpu_upper = cpu.upper()
    if cpu_upper == "ESP8266":
        return "esp8266", "0x0", 460_800
    # ESP32 family — check variants before the plain "ESP32" fallback
    if "C2" in cpu_upper:
        return "esp32c2", "0x0", 921_600
    if "S2" in cpu_upper:
        return "esp32s2", "0x1000", 460_800
    if "S3" in cpu_upper:
        return "esp32s3", "0x0", 921_600
    if "C3" in cpu_upper:
        return "esp32c3", "0x0", 921_600
    if "C6" in cpu_upper:
        return "esp32c6", "0x0", 460_800
    return "esp32", "0x1000", 921_600


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
        erase: Whether to show the erase command.
    """
    if erase:
        log.info(f"  esptool --chip {chip} --port {serialport} erase_flash")
    compress_flag = "--compress" if compress else "--no-compress"
    log.info(
        f"  esptool --chip {chip} --port {serialport} -b {baud_rate}"
        f" write_flash --flash_mode {flash_mode} --flash_size {flash_size}"
        f" {compress_flag} {start_addr} {fw_file}"
    )


def flash_esp(
    mcu: MPRemoteBoard,
    fw_file: Path,
    *,
    erase: bool = True,
    flash_mode: FlashMode = "keep",
    flash_size: str = "detect",
) -> Optional[MPRemoteBoard]:
    """Flash ESP32/ESP8266 firmware using the esptool Python API.

    Connects to the board, optionally erases flash, then writes the firmware
    with compression enabled for all chips.  If the compressed write raises a
    ``FatalError`` (e.g. stub not available), the write is retried without
    compression so the flash always completes when possible.

    Args:
        mcu: Board to flash.
        fw_file: Path to the ``.bin`` firmware file.
        erase: Erase all flash before writing (default ``True``).
        flash_mode: SPI flash mode written into the image header.
        flash_size: Flash size (``"detect"`` auto-detects on the device).

    Returns:
        The updated ``MPRemoteBoard`` on success, ``None`` on failure.
    """
    if mcu.port not in ["esp32", "esp8266"] or mcu.board.startswith("ARDUINO_"):
        log.error(f"esptool not supported for {mcu.port} {mcu.board} on {mcu.serialport}")
        return None

    log.info(f"Flashing {fw_file} on {mcu.board} on {mcu.serialport}")
    if not mcu.cpu:
        mcu.cpu = find_known_board(mcu.board).mcu

    chip, start_addr, baud_rate = _chip_params(mcu.cpu)

    # Always show the equivalent CLI commands for user reference
    _log_esptool_cmd(
        chip, mcu.serialport, baud_rate, start_addr, fw_file,
        flash_mode, flash_size, compress=True, erase=erase,
    )

    try:
        with espcmds.detect_chip(port=mcu.serialport) as esp:
            esp = espcmds.run_stub(esp)
            esp.change_baud(baud_rate)

            if erase:
                log.info("Erasing flash...")
                espcmds.erase_flash(esp)

            addr_data = [(int(start_addr, 16), str(fw_file))]
            write_kwargs = {"flash_mode": flash_mode, "flash_size": flash_size, "force": True}

            log.info("Writing flash (compressed)...")
            try:
                espcmds.write_flash(esp, addr_data, **write_kwargs, compress=True)
            except FatalError as exc:
                log.warning(f"Compressed write failed ({exc}), retrying without compression...")
                _log_esptool_cmd(
                    chip, mcu.serialport, baud_rate, start_addr, fw_file,
                    flash_mode, flash_size, compress=False, erase=False,
                )
                espcmds.write_flash(esp, addr_data, **write_kwargs, no_compress=True)
    except Exception as e:
        log.error(f"Failed to flash {mcu.board} on {mcu.serialport}: {e}")
        return None

    log.info("Done flashing, resetting the board...")
    mcu.wait_for_restart()
    log.success(f"Flashed {mcu.serialport} to {mcu.board} {mcu.version}")
    return mcu

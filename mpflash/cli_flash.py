from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List
from urllib.parse import unquote, urlparse
import re

import rich_click as click
from loguru import logger as log

from mpflash.cli_group import cli
from mpflash.common import BootloaderMethod, FlashParams, UF2_PORTS, filtered_comports
from mpflash.errors import MPFlashError
from mpflash.versions import clean_version

# #########################################################################################################
# CLI
# #########################################################################################################

DOWNLOAD_CHUNK_SIZE = 64 * 1024
DOWNLOAD_TIMEOUT = (10, 120)


@dataclass
class DirectFirmwareInfo:
    firmware_path: Path
    source_hint: str
    inferred_port: str
    inferred_board: str
    inferred_variant: str
    cleanup_path: Path | None = None


@cli.command(
    "flash",
    short_help="Flash one or all connected MicroPython boards with a specific firmware and version.",
)
@click.option(
    "--version",
    "-v",
    "version",  # single version
    default="stable",
    multiple=False,
    show_default=True,
    help="The version of MicroPython to flash.",
    metavar="SEMVER, 'stable', 'preview' or '?'",
)
@click.option(
    "--serial",
    "--serial-port",
    "-s",
    "serial",
    default=["*"],
    multiple=True,
    show_default=True,
    help="Which serial port(s) (or globs) to flash",
    metavar="SERIALPORT",
)
@click.option(
    "--volume",
    "volumes",
    multiple=True,
    default=[],
    show_default=True,
    help="Mounted UF2 boot volume path(s), e.g. D:\\, d:\\, or /Volumes/RPI-RP2 (Windows backslashes accepted)",
    metavar="PATH",
)
@click.option(
    "--ignore",
    "-i",
    is_eager=True,
    help="Serial port(s) to ignore. Defaults to MPFLASH_IGNORE.",
    multiple=True,
    default=[],
    envvar="MPFLASH_IGNORE",
    show_default=True,
    metavar="SERIALPORT",
)
@click.option(
    "--bluetooth/--no-bluetooth",
    "--bt/--no-bt",
    is_flag=True,
    default=False,
    show_default=True,
    help="""Include bluetooth ports in the list""",
)
@click.option(
    "--port",
    "-p",
    "ports",
    help="The MicroPython port to flash",
    metavar="PORT",
    default=[],
    multiple=True,
)
@click.option(
    "--board",
    "-b",
    "board",  # single board
    multiple=False,
    help="The MicroPython board ID to flash. If not specified will try to read the BOARD_ID from the connected MCU.",
    metavar="BOARD_ID or ?",
)
@click.option(
    "--variant",
    "--var",
    "variant",  # single board
    multiple=False,
    help="The board VARIANT to flash or '-'. If not specified will try to read the variant from the connected MCU.",
    metavar="VARIANT",
)
@click.option(
    "--cpu",
    "--chip",
    "cpu",
    help="The CPU type to flash. If not specified will try to read the CPU from the connected MCU.",
    metavar="CPU",
)
@click.option(
    "--erase/--no-erase",
    default=False,
    show_default=True,
    help="""Erase flash before writing new firmware.""",
)
@click.option(
    "--bootloader",
    "--bl",
    "bootloader",
    type=click.Choice([e.value for e in BootloaderMethod]),
    default="auto",
    show_default=True,
    help="""How to enter the (MicroPython) bootloader before flashing.""",
)
@click.option(
    "--file",
    "-f",
    "firmware_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    show_default=False,
    help="Flash directly from a local firmware file.",
    metavar="FIRMWARE_FILE",
)
@click.option(
    "--url",
    "-u",
    "firmware_url",
    default="",
    show_default=False,
    help="Flash directly from a firmware URL.",
    metavar="URL",
)
@click.option(
    "--force",
    "-F",
    default=False,
    is_flag=True,
    show_default=True,
    help="""Force download of firmware even if it already exists (no short flag; -f is used by --file).""",
)
@click.option(
    "--flash_mode",
    "--fm",
    type=click.Choice(["keep", "qio", "qout", "dio", "dout"]),
    default="keep",
    show_default=True,
    help="""Flash mode for ESP boards. (default: keep)""",
)
@click.option(
    "--retry/--no-retry",
    "retry_on_error",
    default=True,
    show_default=True,
    help="""Retry with lower baud rate and different flash mode on failure (ESP boards only).""",
)
@click.option(
    "--retry-baud",
    "retry_baud",
    type=int,
    default=115_200,
    show_default=True,
    help="""Baud rate used for the retry attempt (ESP boards only).""",
)
@click.option(
    "--retry-flash-mode",
    "--rfm",
    "retry_flash_mode",
    type=click.Choice(["qio", "qout", "dio", "dout"]),
    default="dio",
    show_default=True,
    help="""Flash mode used for the retry attempt (ESP boards only).""",
)
@click.option(
    "--custom",
    "-c",
    default=False,
    is_flag=True,
    show_default=True,
    help="""Flash a custom firmware""",
)
def cli_flash_board(**kwargs) -> int:
    import mpflash.download.jid as jid
    import mpflash.mpboard_id as mpboard_id
    from mpflash.ask_input import ask_missing_params
    from mpflash.connected import connected_ports_boards_variants
    from mpflash.list import show_mcus
    from mpflash.flash import flash_tasks
    from mpflash.flash.worklist import FlashTask, FlashTaskList, create_worklist
    from mpflash.mpremoteboard import MPRemoteBoard

    def _create_worklist_or_fail(*create_args, **create_kwargs) -> FlashTaskList:
        """Create a worklist and raise a user-friendly CLI error on invalid input."""
        try:
            return create_worklist(*create_args, **create_kwargs)
        except ValueError as exc:
            raise click.UsageError(
                "Invalid flash option combination. "
                f"{exc}. "
                "Try specifying both --board and --serial, or use '--serial *' to auto-detect ports."
            ) from None

    def _split_board_variant(board_id: str, port: str = "") -> tuple[str, str]:
        """Split board+variant identifiers where variant suffixes are expected."""
        if port != "esp32" or "-" not in board_id:
            return board_id, ""
        # ESP32 board IDs use board-variant naming in the upstream board database.
        board, variant = board_id.split("-", 1)
        return board, variant

    def _requires_board_prompt_for_direct_flash(inferred_port: str, inferred_board: str, inferred_variant: str) -> bool:
        """Return True when direct firmware inference is insufficient for safe flashing."""
        if not inferred_board:
            return True
        if inferred_port == "esp32" and not inferred_variant:
            return True
        return False

    def _infer_port_board_variant(source_hint: str) -> tuple[str, str, str]:
        """Infer (port, board, variant) from a firmware path or URL."""
        from mpflash.custom.naming import port_and_boardid_from_path

        parsed = urlparse(source_hint)
        inspect_path = unquote(parsed.path) if parsed.scheme in {"http", "https"} else source_hint
        normalized = inspect_path.replace("\\", "/")

        build_match = re.search(r"/ports/([^/]+)/build-([^/]+)/", normalized, re.IGNORECASE)
        if build_match:
            port = build_match.group(1).lower()
            board, variant = _split_board_variant(build_match.group(2), port=port)
            return port, board, variant

        detected_port, detected_board = port_and_boardid_from_path(Path(normalized))
        if not detected_port:
            return "", "", ""
        if detected_board:
            board, variant = _split_board_variant(detected_board, port=detected_port)
        else:
            board, variant = "", ""
        return detected_port, board, variant

    def _download_firmware_url(url: str) -> Path:
        """Download a firmware URL to a temporary file and return its path.

        Temporary files are cleaned by the caller in a finally block after flashing.
        """
        import requests

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise click.UsageError("Invalid --url. Only http:// or https:// URLs are supported.")

        suffix = Path(unquote(parsed.path)).suffix or ".bin"
        temp_file_path: Path | None = None
        try:
            # delete=False so we can pass a stable path into flash task creation.
            with NamedTemporaryFile(prefix="mpflash-fw-", suffix=suffix, delete=False) as temp_file:
                temp_file_path = Path(temp_file.name)
                response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        temp_file.write(chunk)
                return temp_file_path
        except requests.RequestException as exc:
            if temp_file_path and temp_file_path.exists():
                temp_file_path.unlink(missing_ok=True)
            raise click.UsageError(f"Failed to download firmware from URL: {exc}") from None

    def _prepare_direct_firmware(path: Path | None, url: str) -> DirectFirmwareInfo | None:
        """Prepare direct firmware source and inferred board metadata."""
        if not path and not url:
            return None
        if path and url:
            raise click.UsageError("Use either --file or --url, not both.")
        if path:
            local_path = path.expanduser().resolve()
            if not local_path.exists() or not local_path.is_file():
                raise click.UsageError(f"Firmware file not found: {local_path}")
            source_hint = local_path.as_posix()
            inferred_port, inferred_board, inferred_variant = _infer_port_board_variant(source_hint)
            return DirectFirmwareInfo(
                firmware_path=local_path,
                source_hint=source_hint,
                inferred_port=inferred_port,
                inferred_board=inferred_board,
                inferred_variant=inferred_variant,
            )
        downloaded = _download_firmware_url(url)
        inferred_port, inferred_board, inferred_variant = _infer_port_board_variant(url)
        return DirectFirmwareInfo(
            firmware_path=downloaded,
            source_hint=url,
            inferred_port=inferred_port,
            inferred_board=inferred_board,
            inferred_variant=inferred_variant,
            cleanup_path=downloaded,
        )

    def _attach_direct_firmware(
        tasks: FlashTaskList,
        firmware_path: Path,
        source: str,
        version: str,
        *,
        fallback_port: str = "",
        fallback_board: str = "",
    ) -> None:
        """Attach a direct firmware file to all tasks."""
        from mpflash.db.models import Firmware

        for task in tasks:
            if fallback_port and not task.board.port:
                task.board.port = fallback_port
            if fallback_board and not task.board.board_id:
                task.board.board_id = fallback_board

            board_id = task.board.board_id or task.board.board or firmware_path.stem
            task.firmware = Firmware(
                board_id=board_id,
                version=version,
                port=task.board.port or fallback_port,
                firmware_file=firmware_path.as_posix(),
                source=source,
                custom=False,
            )

    def _create_direct_firmware_tasks(params: FlashParams, detected_boards: List[MPRemoteBoard]) -> FlashTaskList:
        """Create flash tasks for direct firmware without requiring board DB lookup."""
        comports = filtered_comports(
            ignore=params.ignore,
            include=params.serial,
            bluetooth=params.bluetooth,
        )
        if not comports:
            serial_filter = ", ".join(params.serial)
            raise click.UsageError(
                f"No serial ports matched: {serial_filter}. Check the port name, or use '--serial *' to auto-detect."
            )

        by_serial = {board.serialport: board for board in detected_boards}
        tasks: FlashTaskList = []
        for serial in comports:
            board = by_serial.get(serial) or MPRemoteBoard(serial)
            if params.ports and not board.port:
                board.port = params.ports[0]
            if params.boards and not board.board_id:
                board.board_id = f"{params.boards[0]}-{params.variant}" if params.variant else params.boards[0]
            tasks.append(FlashTask(board=board, firmware=None))
        return tasks

    firmware_file = kwargs.pop("firmware_file", None)
    firmware_url = kwargs.pop("firmware_url", "")

    # version to versions, board to boards
    kwargs["versions"] = [kwargs.pop("version")] if kwargs["version"] is not None else []
    if kwargs["board"] is None:
        kwargs["boards"] = []
        kwargs.pop("board")
    else:
        kwargs["boards"] = [kwargs.pop("board")]

    params = FlashParams(**kwargs)
    params.versions = list(params.versions)
    params.ports = list(params.ports)
    params.boards = list(params.boards)
    params.serial = list(params.serial)
    params.ignore = list(params.ignore)
    params.volumes = list(params.volumes)
    params.bootloader = BootloaderMethod(params.bootloader)
    direct_firmware = _prepare_direct_firmware(firmware_file, firmware_url)
    try:
        if direct_firmware:
            params.custom = True
            if not params.ports and direct_firmware.inferred_port:
                params.ports = [direct_firmware.inferred_port]
            if not params.boards:
                if not _requires_board_prompt_for_direct_flash(
                    direct_firmware.inferred_port,
                    direct_firmware.inferred_board,
                    direct_firmware.inferred_variant,
                ):
                    params.boards = [direct_firmware.inferred_board]
                    if direct_firmware.inferred_variant and not params.variant:
                        params.variant = direct_firmware.inferred_variant

        # make it simple for the user to flash one board by asking for the serial port if not specified
        if params.boards == ["?"] or params.serial == "?":  #  or params.variant == "?":
            params.serial = ["?"]
            # if params.variant == "?":
            #     params.boards = ["?"]  # trigger full interactive board+variant flow
            if params.boards == ["*"]:
                # No board specified
                params.boards = ["?"]

        # Detect connected boards if not specified,
        # and ask for input if boards cannot be detected.
        # In direct firmware mode, avoid inferring board/port from current firmware;
        # ask for missing inputs explicitly instead.
        all_boards = []
        if not params.boards and not direct_firmware:
            # nothing specified - detect connected boards
            params.ports, params.boards, variants, all_boards = connected_ports_boards_variants(
                include=params.ports,
                ignore=params.ignore,
                bluetooth=params.bluetooth,
            )
            if variants and len(variants) >= 1:
                params.variant = variants[0]
            if params.boards == []:
                # No MicroPython boards detected, but it could be unflashed or in bootloader mode
                # Ask for serial port to flash. For direct firmware, board_id is optional.
                params.serial = ["?"]
                if not direct_firmware:
                    params.boards = ["?"]
                # assume manual mode if no board is detected
                params.bootloader = BootloaderMethod("manual")
        elif params.boards:
            mpboard_id.resolve_board_ids(params)

        # Ask for missing input if needed
        params = ask_missing_params(
            params,
            ask_board=not bool(direct_firmware),
            ask_for_port=bool(direct_firmware and not params.ports),
        )
        if not params:  # Cancelled by user
            return 2
        assert isinstance(params, FlashParams)

        if len(params.versions) > 1:
            log.error(f"Only one version can be flashed at a time, not {params.versions}")
            raise MPFlashError("Only one version can be flashed at a time")

        params.versions = [clean_version(v) for v in params.versions]
        tasks = []

        # Normalize volume paths: accept both Windows backslashes and POSIX forward slashes
        if params.volumes:
            params.volumes = [str(Path(v)) for v in params.volumes]

        if direct_firmware and not params.volumes:
            tasks = _create_direct_firmware_tasks(params, all_boards)
        elif params.volumes:
            # Explicit UF2 mount path(s) for boards already in bootloader mode.
            if not params.boards:
                raise click.UsageError("--volume requires --board so firmware can be selected")
            board_id = f"{params.boards[0]}-{params.variant}" if params.variant else params.boards[0]
            tasks = _create_worklist_or_fail(
                params.versions[0],
                serial_ports=params.volumes,
                board_id=board_id,
                custom_firmware=params.custom,
                port=params.ports[0] if params.ports else None,
            )
            if any(task.board.port not in UF2_PORTS for task in tasks):
                raise click.UsageError(f"--volume is only supported for UF2-capable ports ({', '.join(sorted(UF2_PORTS))})")
        elif len(params.versions) == 1 and len(params.boards) == 1 and params.serial == ["*"]:
            # One or more serial ports including the board / variant (auto-detect ports)
            comports = filtered_comports(
                ignore=params.ignore,
                include=params.serial,
                bluetooth=params.bluetooth,
            )
            board_id = f"{params.boards[0]}-{params.variant}" if params.variant else params.boards[0]
            log.info(f"Flashing {board_id} {params.versions[0]} to {len(comports)} serial ports")
            log.info(f"Target ports: {', '.join(comports)}")
            tasks = _create_worklist_or_fail(
                params.versions[0],
                serial_ports=comports,
                board_id=board_id,
                custom_firmware=params.custom,
                port=params.ports[0] if params.ports else None,
            )
        elif params.serial == ["*"] and params.boards:
            # Auto mode on detected boards with optional include/ignore filtering
            if not all_boards:
                log.trace("No boards detected yet, scanning for connected boards")
                _, _, _, all_boards = connected_ports_boards_variants(include=params.ports, ignore=params.ignore)
            if params.variant:
                for b in all_boards:
                    b.variant = params.variant if (params.variant.lower() not in {"-", "none"}) else ""
            tasks = _create_worklist_or_fail(
                params.versions[0],
                connected_comports=all_boards,
                include_ports=params.serial,
                ignore_ports=params.ignore,
            )
        elif params.versions[0] and params.boards and params.serial:
            # Manual specification of serial ports + board
            comports = filtered_comports(
                ignore=params.ignore,
                include=params.serial,
                bluetooth=params.bluetooth,
            )
            if not comports:
                serial_filter = ", ".join(params.serial)
                raise click.UsageError(f"No serial ports matched: {serial_filter}. Check the port name, or use '--serial *' to auto-detect.")
            board_id = f"{params.boards[0]}-{params.variant}" if params.variant else params.boards[0]
            tasks = _create_worklist_or_fail(
                params.versions[0],
                serial_ports=comports,
                board_id=board_id,
                port=params.ports[0] if params.ports else None,
            )
        else:
            # Single serial port auto-detection
            connected_comports = [MPRemoteBoard(params.serial[0])]
            tasks = _create_worklist_or_fail(
                params.versions[0],
                connected_comports=connected_comports,
            )
        if direct_firmware:
            _attach_direct_firmware(
                tasks,
                direct_firmware.firmware_path,
                direct_firmware.source_hint,
                params.versions[0],
                fallback_port=params.ports[0] if params.ports else "",
                fallback_board=params.boards[0] if params.boards else "",
            )
        elif not params.custom:
            jid.ensure_firmware_downloaded_tasks(tasks, version=params.versions[0], force=params.force)
        if flashed := flash_tasks(
            tasks,
            params.erase,
            params.bootloader,
            flash_mode=params.flash_mode,
            retry_on_error=params.retry_on_error,
            retry_baud=params.retry_baud,
            retry_flash_mode=params.retry_flash_mode,
        ):
            log.info(f"Flashed {len(flashed)} boards")
            show_mcus(flashed, title="Updated boards after flashing")
            return 0
        else:
            log.error("No boards were flashed")
            return 1
    finally:
        if direct_firmware and direct_firmware.cleanup_path and direct_firmware.cleanup_path.exists():
            direct_firmware.cleanup_path.unlink(missing_ok=True)

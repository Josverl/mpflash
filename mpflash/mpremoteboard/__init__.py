"""MPFlash compatibility facade over the standalone mpremoteboard package."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import List, Optional, Union

import mpremoteboard as _core
from mpremoteboard import (
    DEFAULT_TIMEOUT,
    ERROR,
    OK,
    MPRemoteBoard as _CoreMPRemoteBoard,
    MPRemoteBoardError,
)
from mpremoteboard.runner import run
from tenacity import retry, stop_after_attempt, wait_fixed

from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.mpboard_id.board_id import find_board_id_by_description
from mpflash.mpboard_id.known import best_matching_port

HERE = Path(_core.__file__).parent
RETRIES = 3
ON_WSL2 = bool(sys.platform == "linux" and Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower())

# Keep these module attributes available to existing callers and monkeypatches.
serial = _core.serial
time = _core.time


class MPRemoteBoard(_CoreMPRemoteBoard):
    """MPFlash-enriched board API, retaining the historical defaults."""

    _logger = log

    def _resolve_port(self, port: str, family: str) -> str:
        return best_matching_port(port, family) or port

    def _resolve_board_identity(self, info: dict) -> None:
        if info.get("board_id"):
            self.board_id = info["board_id"]
            return

        description = self.description
        position = description.rfind(" with")
        short_description = description[:position].strip() if position != -1 else ""
        self.board_id = f"{info['board']}-{info.get('variant', '')}"
        try:
            self.board_id = find_board_id_by_description(description, short_description, version=self.version) or "UNKNOWN_BOARD"
        except MPFlashError:
            log.warning(f"Could not resolve board_id for description: {description!r}")
            self.board_id = self.board_id or "UNKNOWN_BOARD"

    def _apply_board_info_toml(self) -> None:
        toml_board_id = self.toml.get("mpflash", {}).get("board_id", "")
        if toml_board_id:
            log.debug(f"Using board_id from board_info.toml: {toml_board_id!r}")
            self.board_id = toml_board_id

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(1), reraise=True)
    def get_mcu_info(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        *,
        log_errors: bool = True,
        resume: Optional[bool] = False,
    ) -> None:
        """Read firmware metadata, retaining MPFlash's legacy reset default."""
        super().get_mcu_info(timeout, log_errors=log_errors, resume=resume)

    def get_mcu_info_once(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        *,
        log_errors: bool = True,
        resume: Optional[bool] = True,
    ) -> None:
        """Probe firmware metadata exactly once without facade retries."""
        _CoreMPRemoteBoard.get_mcu_info(self, timeout, log_errors=log_errors, resume=resume)

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(0.2), reraise=True)
    def get_board_info_toml(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Read optional board metadata using the legacy reset behavior."""
        _CoreMPRemoteBoard.get_board_info_toml(self, timeout, resume=False)

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(2), reraise=True)
    def run_command(
        self,
        cmd: Union[str, List[str]],
        *,
        log_errors: bool = True,
        no_info: bool = False,
        timeout: int = 60,
        resume: Optional[bool] = None,
        **kwargs,
    ) -> tuple[int, list[str]]:
        """Run a command with the historical retry and reset behavior."""
        return super().run_command(
            cmd,
            log_errors=log_errors,
            no_info=no_info,
            timeout=timeout,
            resume=resume,
            **kwargs,
        )

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(1))
    def mip_install(self, name: str) -> bool:
        return super().mip_install(name)

    def _run(self, cmd: List[str], timeout: int, log_errors: bool, no_info: bool, **kwargs):
        """Keep the old module-level runner patch point working."""
        return run(cmd, timeout, log_errors, no_info, **kwargs)

    def set_board_info_toml(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        try:
            super().set_board_info_toml(timeout)
        except MPRemoteBoardError as exc:
            raise MPFlashError(str(exc)) from exc

    def wait_for_restart(self, timeout: int = 10) -> bool:
        """Wait for restart and preserve MPFlash's optional WSL2 reattachment."""
        usbipd_executable: Optional[str] = None
        usbipd_result: Optional[bool] = None
        if ON_WSL2:
            from mpflash.config import config

            if config.usbipd:
                from .usbipd import find_usbipd

                usbipd_executable = find_usbipd()
        for _ in range(timeout):
            time.sleep(1)
            port_available = self._refresh_serialport()
            if usbipd_executable and not port_available and usbipd_result is None:
                from .usbipd import reattach_usbipd_device

                usbipd_result = reattach_usbipd_device(
                    vid=self.vid,
                    pid=self.pid,
                    serial_number=self.serial_number,
                    executable=usbipd_executable,
                )
            with contextlib.suppress(ConnectionError, MPFlashError):
                self.get_mcu_info_once(log_errors=False, resume=True)
                return True
        if usbipd_executable and not self._refresh_serialport():
            identity = f"{self.vid:04x}:{self.pid:04x}"
            if self.serial_number:
                identity += f" serial {self.serial_number}"
            log.warning(f"USB device {identity} did not return to WSL2. Run 'usbipd list', then 'usbipd attach --wsl --busid <BUSID>'.")
        return False


__all__ = [
    "DEFAULT_TIMEOUT",
    "ERROR",
    "HERE",
    "OK",
    "ON_WSL2",
    "RETRIES",
    "MPRemoteBoard",
    "MPRemoteBoardError",
    "run",
]

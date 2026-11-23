"""MPFlash compatibility facade over the standalone mpremoteboard package."""

from __future__ import annotations

import contextlib
import inspect
import sys
import warnings
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


class _UnsetType:
    pass


_UNSET = _UnsetType()


def _resolve_soft_reset(
    *,
    soft_reset: Union[bool, _UnsetType],
    resume: Union[bool, None, _UnsetType],
    default: bool,
) -> bool:
    if not isinstance(resume, _UnsetType):
        if not isinstance(soft_reset, _UnsetType):
            raise TypeError("soft_reset and deprecated resume cannot be used together")
        frame = inspect.currentframe()
        stacklevel = 1
        while frame is not None:
            frame = frame.f_back
            stacklevel += 1
            if frame is None:
                break
            module_name = frame.f_globals.get("__name__", "")
            if module_name != __name__ and not module_name.startswith("tenacity"):
                break
        warnings.warn("resume is deprecated; use soft_reset instead", DeprecationWarning, stacklevel=stacklevel)
        return False if resume is None else not resume
    return default if isinstance(soft_reset, _UnsetType) else soft_reset


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
        soft_reset: Union[bool, _UnsetType] = _UNSET,
        resume: Union[bool, None, _UnsetType] = _UNSET,
    ) -> None:
        """Read firmware metadata, retaining MPFlash's legacy reset default."""
        resolved_soft_reset = _resolve_soft_reset(
            soft_reset=soft_reset,
            resume=resume,
            default=True,
        )
        super().get_mcu_info(timeout, log_errors=log_errors, soft_reset=resolved_soft_reset)

    def get_mcu_info_once(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        *,
        log_errors: bool = True,
        soft_reset: bool = False,
    ) -> None:
        """Probe firmware metadata exactly once without facade retries."""
        _CoreMPRemoteBoard.get_mcu_info(self, timeout, log_errors=log_errors, soft_reset=soft_reset)

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(0.2), reraise=True)
    def get_board_info_toml(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Read optional board metadata using the legacy reset behavior."""
        _CoreMPRemoteBoard.get_board_info_toml(self, timeout, soft_reset=True)

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(2), reraise=True)
    def run_command(
        self,
        cmd: Union[str, List[str]],
        *,
        log_errors: bool = True,
        no_info: bool = False,
        timeout: int = 60,
        soft_reset: Union[bool, _UnsetType] = _UNSET,
        resume: Union[bool, None, _UnsetType] = _UNSET,
        **kwargs,
    ):
        """Run a command with the historical retry and reset behavior."""
        resolved_soft_reset = _resolve_soft_reset(
            soft_reset=soft_reset,
            resume=resume,
            default=False,
        )
        return super().run_command(
            cmd,
            log_errors=log_errors,
            no_info=no_info,
            timeout=timeout,
            soft_reset=resolved_soft_reset,
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
                self.get_mcu_info_once(log_errors=False, soft_reset=False)
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

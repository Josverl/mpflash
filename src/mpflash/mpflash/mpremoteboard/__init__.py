"""
Module to run mpremote commands, and retry on failure or timeout
"""

import sys
import time
from pathlib import Path
from typing import List, Optional, Union

import serial.tools.list_ports
from loguru import logger as log
from rich.progress import track
from tenacity import retry, stop_after_attempt, wait_fixed

from mpflash.errors import MPFlashError
from mpflash.mpboard_id.board_id import find_board_id_by_description
from mpflash.mpremoteboard.runner import run

###############################################################################################
# TODO : make this a bit nicer
HERE = Path(__file__).parent

OK = 0
ERROR = -1
RETRIES = 3
###############################################################################################


class MPRemoteBoard:
    """Class to run mpremote commands"""

    def __init__(self, serialport: str = "", update: bool = False):
        """
        Initialize MPRemoteBoard object.

        Parameters:
        - serialport (str): The serial port to connect to. Default is an empty string.
        - update (bool): Whether to update the MCU information. Default is False.
        """
        self.serialport = serialport
        self.firmware = {}

        self.connected = False
        self.path: Optional[Path] = None
        self.family = "unknown"
        self.description = ""
        self.version = ""
        self.port = ""
        self.board = ""
        self.cpu = ""
        self.arch = ""
        self.mpy = ""
        self.build = ""
        if update:
            self.get_mcu_info()

    def __str__(self):
        """
        Return a string representation of the MPRemoteBoard object.

        Returns:
        - str: The string representation of the object.
        """
        return f"MPRemoteBoard({self.serialport}, {self.family} {self.port}, {self.board}, {self.version})"

    @staticmethod
    def connected_boards(bluetooth: bool = False, description: bool = False) -> List[str]:
        # TODO: rename to connected_comports
        """
        Get a list of connected comports.

        Parameters:
        - bluetooth (bool): Whether to include Bluetooth ports. Default is False.

        Returns:
        - List[str]: A list of connected board ports.
        """
        comports = serial.tools.list_ports.comports()

        if not bluetooth:
            # filter out bluetooth ports
            comports = [p for p in comports if "bluetooth" not in p.description.lower()]
            comports = [p for p in comports if "BTHENUM" not in p.hwid]
        if description:
            output = [
                f"{p.device} {(p.manufacturer + ' ') if p.manufacturer and not p.description.startswith(p.manufacturer) else ''}{p.description}"
                for p in comports
            ]
        else:
            output = [p.device for p in comports]

        if sys.platform == "win32":
            # Windows sort of comports by number - but fallback to device name
            return sorted(
                output, key=lambda x: int(x.split()[0][3:]) if x.split()[0][3:].isdigit() else x
            )
        # sort by device name
        return sorted(output)

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(1), reraise=True)  # type: ignore ## retry_error_cls=ConnectionError,
    def get_mcu_info(self, timeout: int = 2):
        """
        Get MCU information from the connected board.

        Parameters:
        - timeout (int): The timeout value in seconds. Default is 2.

        Raises:
        - ConnectionError: If failed to get mcu_info for the serial port.
        """
        rc, result = self.run_command(
            ["run", str(HERE / "mpy_fw_info.py")],
            no_info=True,
            timeout=timeout,
        )
        if rc != OK:
            raise ConnectionError(f"Failed to get mcu_info for {self.serialport}")
        # Ok we have the info, now parse it
        s = result[0].strip()
        if s.startswith("{") and s.endswith("}"):
            info = eval(s)
            self.family = info["family"]
            self.version = info["version"]
            self.build = info["build"]
            self.port = info["port"]
            self.cpu = info["cpu"]
            self.arch = info["arch"]
            self.mpy = info["mpy"]
            self.description = descr = info["board"]
            pos = descr.rfind(" with")
            short_descr = descr[:pos].strip() if pos != -1 else ""
            if board_name := find_board_id_by_description(
                descr, short_descr, version=self.version
            ):
                self.board = board_name
            else:
                self.board = "UNKNOWN_BOARD"

    def disconnect(self) -> bool:
        """
        Disconnect from a board.

        Returns:
        - bool: True if successfully disconnected, False otherwise.
        """
        if not self.connected:
            return True
        if not self.serialport:
            log.error("No port connected")
            self.connected = False
            return False
        log.info(f"Disconnecting from {self.serialport}")
        result = self.run_command(["disconnect"])[0] == OK
        self.connected = False
        return result

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(2), reraise=True)
    def run_command(
        self,
        cmd: Union[str, List[str]],
        *,
        log_errors: bool = True,
        no_info: bool = False,
        timeout: int = 60,
        **kwargs,
    ):
        """
        Run mpremote with the given command.

        Parameters:
        - cmd (Union[str, List[str]]): The command to run, either a string or a list of strings.
        - log_errors (bool): Whether to log errors. Default is True.
        - no_info (bool): Whether to skip printing info. Default is False.
        - timeout (int): The timeout value in seconds. Default is 60.

        Returns:
        - bool: True if the command succeeded, False otherwise.
        """
        if isinstance(cmd, str):
            cmd = cmd.split(" ")
        prefix = [sys.executable, "-m", "mpremote"]
        if self.serialport:
            prefix += ["connect", self.serialport]
        # if connected add resume to keep state between commands
        if self.connected:
            prefix += ["resume"]
        cmd = prefix + cmd
        log.debug(" ".join(cmd))
        result = run(cmd, timeout, log_errors, no_info, **kwargs)
        self.connected = result[0] == OK
        return result

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(1))
    def mip_install(self, name: str) -> bool:
        """
        Install a micropython package.

        Parameters:
        - name (str): The name of the package to install.

        Returns:
        - bool: True if the installation succeeded, False otherwise.
        """
        # install createstubs to the board
        cmd = ["mip", "install", name]
        result = self.run_command(cmd)[0] == OK
        self.connected = True
        return result

    def wait_for_restart(self, timeout: int = 10):
        """wait for the board to restart"""
        for _ in track(
            range(timeout),
            description="Waiting for the board to restart",
            transient=True,
            get_time=lambda: time.time(),
            show_speed=False,
            refresh_per_second=2,
            total=timeout,
        ):
            time.sleep(1)
            try:
                self.get_mcu_info()
                break
            except (ConnectionError, MPFlashError):
                pass

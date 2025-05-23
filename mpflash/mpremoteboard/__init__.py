"""
Module to run mpremote commands, and retry on failure or timeout
"""

import contextlib
import sys
import time
from pathlib import Path
from typing import List, Optional, Union

import serial.tools.list_ports
from rich.progress import track
from tenacity import retry, stop_after_attempt, wait_fixed

from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.mpboard_id.board_id import find_board_id_by_description
from mpflash.mpremoteboard.runner import run

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore
else:
    import tomli as tomllib  # type: ignore

###############################################################################################
HERE = Path(__file__).parent

OK = 0
ERROR = -1
RETRIES = 3
###############################################################################################


class MPRemoteBoard:
    """Class to run mpremote commands"""

    def __init__(
        self, serialport: str = "", update: bool = False, *, location: str = ""
    ):
        """
        Initialize MPRemoteBoard object.

        Parameters:
        - serialport (str): The serial port to connect to. Default is an empty string.
        - update (bool): Whether to update the MCU information. Default is False.
        """
        self._board_id = ""

        self.serialport: str = serialport
        self.firmware = {}

        self.connected = False
        self.path: Optional[Path] = None
        self.family = "unknown"
        self.description = ""
        self.version = ""
        self.port = ""
        self.cpu = ""
        self.arch = ""
        self.mpy = ""
        self.build = ""
        self.location = location  # USB location
        self.toml = {}
        if update:
            self.get_mcu_info()

    ###################################
    # board_id := board[-variant]
    @property
    def board_id(self) -> str:
        return self._board_id

    @board_id.setter
    def board_id(self, value: str) -> None:
        self._board_id = value.rstrip("-")

    @property
    def board(self) -> str:
        return self._board_id.split("-")[0]

    @board.setter
    def board(self, value: str) -> None:
        self.board_id = f"{value}-{self.variant}" if self.variant else value

    @property
    def variant(self) -> str:
        return self._board_id.split("-")[1] if "-" in self._board_id else ""

    @variant.setter
    def variant(self, value: str) -> None:
        self.board_id = f"{self.board}-{value}"

    ###################################
    def __str__(self):
        """
        Return a string representation of the MPRemoteBoard object.

        Returns:
        - str: A human readable representation of the MCU.
        """
        return f"MPRemoteBoard({self.serialport}, {self.family} {self.port}, {self.board}{f'-{self.variant}' if self.variant else ''}, {self.version})"

    @staticmethod
    def connected_boards(
        bluetooth: bool = False, description: bool = False
    ) -> List[str]:
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
                output,
                key=lambda x: int(x.split()[0][3:])
                if x.split()[0][3:].isdigit()
                else x,
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
            resume=False,  # Avoid restarts
        )
        if rc not in (0, 1):  ## WORKAROUND - SUDDEN RETURN OF 1 on success
            log.debug(f"rc: {rc}, result: {result}")
            raise ConnectionError(f"Failed to get mcu_info for {self.serialport}")
        # Ok we have the info, now parse it
        raw_info = result[0].strip() if result else ""
        if raw_info.startswith("{") and raw_info.endswith("}"):
            info = eval(raw_info)
            self.family = info["family"]
            self.version = info["version"]
            self.build = info["build"]
            self.port = info["port"]
            self.cpu = info["cpu"]
            self.arch = info["arch"]
            self.mpy = info["mpy"]
            self.description = descr = info["description"] if 'description' in info else info["board"]
            pos = descr.rfind(" with")
            short_descr = descr[:pos].strip() if pos != -1 else ""
            if info.get("board_id", None):
                # we have a board_id - so use that to get the board name
                self.board_id = info["board_id"]
            else:
                self.board_id = f"{info['board']}-{info.get('variant', '')}"
                board_name = find_board_id_by_description(
                    descr, short_descr, version=self.version
                )
                self.board_id = board_name or "UNKNOWN_BOARD"
                # TODO: Get the variant as well
            # get the board_info.toml
            self.get_board_info_toml()
            # TODO: get board_id from the toml file if it exists
        # now we know the board is connected
        self.connected = True

    @retry(stop=stop_after_attempt(RETRIES), wait=wait_fixed(0.2), reraise=True)  # type: ignore ## retry_error_cls=ConnectionError,
    def get_board_info_toml(self, timeout: int = 1):
        """
        Reads the content of the board_info.toml file from the connected board,
        and adds that to the board object.

        Parameters:
        - timeout (int): The timeout value in seconds.

        Raises:
        - ConnectionError: If failed to communicate with the serial port.
        """
        try:
            rc, result = self.run_command(
                ["cat", ":board_info.toml"],
                no_info=True,
                timeout=timeout,
                log_errors=False,
            )
        except Exception as e:
            raise ConnectionError(
                f"Failed to get board_info.toml for {self.serialport}:"
            ) from e
        # this is optional - so only parse if we got the file
        self.toml = {}
        if rc in [OK]:  # sometimes we get an -9 ???
            try:
                # Ok we have the info, now parse it
                self.toml = tomllib.loads("".join(result))
                log.debug(f"board_info.toml: {self.toml}")
            except Exception as e:
                log.error(f"Failed to parse board_info.toml: {e}")
        else:
            log.trace(f"Did not find a board_info.toml: {result}")

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
        resume: Optional[bool] = None,
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
        if (resume != False) and self.connected or resume:
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
            description=f"Waiting for the board to restart ({timeout}s)",
            transient=True,
            show_speed=False,
            refresh_per_second=1,
            total=timeout,
        ):
            time.sleep(1)
            with contextlib.suppress(ConnectionError, MPFlashError):
                self.get_mcu_info()
                break

    def to_dict(self) -> dict:
        """
        Serialize the MPRemoteBoard object to JSON, including all attributes and readable properties.

        Returns:
        - str: A JSON string representation of the object.
        """

        def get_properties(obj):
            """Helper function to get all readable properties."""
            return {
                name: getattr(obj, name)
                for name in dir(obj.__class__)
                if isinstance(getattr(obj.__class__, name, None), property)
            }

        # Combine instance attributes, readable properties, and private attributes
        data = {**self.__dict__, **get_properties(self)}

        # remove the path and firmware attibutes from the json output as they are always empty
        del data["_board_id"]  # dup of board_id
        del data["connected"]
        del data["path"]
        del data["firmware"]

        return data

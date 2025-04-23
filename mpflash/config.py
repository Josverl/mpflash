"""centralized configuration for mpflash"""

import os
from importlib.metadata import version
from pathlib import Path
from typing import List, Optional

import platformdirs


def get_version():
    name = __package__ or "mpflash"
    return version(name)


class MPFlashConfig:
    """Centralized configuration for mpflash"""

    quiet: bool = False
    verbose: bool = False
    usb: bool = False
    ignore_ports: List[str] = []
    _firmware_folder: Optional[Path] = None
    # test options specified on the commandline
    tests: List[str] = []
    _interactive: bool = True
    _gh_client = None

    @property
    def interactive(self):
        # No interactions in CI
        if os.getenv("GITHUB_ACTIONS") == "true":
            from mpflash.logger import log

            log.warning("Disabling interactive mode in CI")
            return False
        return self._interactive

    @interactive.setter
    def interactive(self, value: bool):
        self._interactive = value

    @property
    def firmware_folder(self) -> Path:
        """The folder where firmware files are stored"""
        if not self._firmware_folder:
            self._firmware_folder = platformdirs.user_downloads_path() / "firmware"
        return self._firmware_folder

    @property
    def db_path(self) -> Path:
        """The path to the database file"""
        return self.firmware_folder / "mpflash.db"

    @property
    def gh_client(self):
        """The gh client to use"""
        if not self._gh_client:
            from github import Auth, Github

            # Token with no permissions to avoid throttling
            # https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2022-11-28#getting-a-higher-rate-limit
            PAT_NO_ACCESS = "github_pat_" + "11AAHPVFQ0G4NTaQ73Bw5J" + "_fAp7K9sZ1qL8VFnI9g78eUlCdmOXHB3WzSdj2jtEYb4XF3N7PDJBl32qIxq"
            PAT = os.environ.get("GITHUB_TOKEN") or PAT_NO_ACCESS
            self._gh_client = Github(auth=Auth.Token(PAT))
        return self._gh_client


config = MPFlashConfig()
__version__ = get_version()

"""Install the KitProg3 udev rule on Linux so a normal user can open the Infineon debug probe."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from mpflash.logger import log

RULES_FILE = Path(__file__).resolve().parents[3] / "udev_rules" / "65-mpflash-infineon-kitprog3.rules"
"""The rule file shipped with mpflash."""

RULES_DIR = Path("/etc/udev/rules.d")


def install_commands() -> List[List[str]]:
    """The commands that install the rule and apply it to an already connected Infineon probe."""
    sudo = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
    return [
        [*sudo, "cp", "-f", str(RULES_FILE), str(RULES_DIR / RULES_FILE.name)],
        [*sudo, "udevadm", "control", "--reload-rules"],
        [*sudo, "udevadm", "trigger", "--subsystem-match=usb", "--attr-match=idVendor=04b4", "--action=add"],
    ]


def _can_prompt() -> bool:
    from mpflash.config import config

    return sys.platform == "linux" and config.interactive and sys.stdin.isatty()


def offer_install() -> bool:
    """Ask for confirmation, then install the rule with sudo. True only if it was installed.

    Never installs without an interactive confirmation; otherwise the caller shows the manual commands.
    """
    if not RULES_FILE.is_file() or not _can_prompt():
        return False
    if os.geteuid() != 0 and not shutil.which("sudo"):
        return False

    import click

    if not click.confirm(
        f"Install {RULES_FILE.name} into {RULES_DIR} so your user can open the KitProg3 probe? (uses sudo)",
        default=False,
    ):
        return False
    for command in install_commands():
        log.info(f"Running: {' '.join(command)}")
        try:
            subprocess.run(command, check=True)  # sudo may ask for a password on the terminal
        except (OSError, subprocess.CalledProcessError) as error:
            log.warning(f"Could not install the udev rule: {error}")
            return False
    log.success("Installed the udev rule")
    return True

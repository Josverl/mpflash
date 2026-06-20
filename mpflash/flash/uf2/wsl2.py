"""Compatibility shim — see :mod:`mpflash.flash.builtins.uf2.wsl2`."""

from mpflash.flash.builtins.uf2.wsl2 import *  # noqa: F401,F403
from mpflash.flash.builtins.uf2.wsl2 import (  # noqa: F401
    dismount_uf2_wsl2,
    wait_for_UF2_wsl2,
)

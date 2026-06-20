"""Compatibility shim — see :mod:`mpflash.flash.builtins.uf2.linux`."""

from mpflash.flash.builtins.uf2.linux import *  # noqa: F401,F403
from mpflash.flash.builtins.uf2.linux import (  # noqa: F401
    dismount_uf2_linux,
    get_uf2_drives,
    pmount,
    pumount,
    wait_for_UF2_linux,
)

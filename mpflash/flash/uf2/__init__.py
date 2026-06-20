"""Compatibility shim package — the implementation moved to :mod:`mpflash.flash.builtins.uf2`.

Each submodule re-exports the same names from the canonical location, so
external imports like ``from mpflash.flash.uf2 import flash_uf2`` and
``from mpflash.flash.uf2.windows import wait_for_UF2_windows`` keep working.
"""

from mpflash.flash.builtins.uf2 import *  # noqa: F401,F403
from mpflash.flash.builtins.uf2 import (  # noqa: F401
    copy_firmware_to_uf2,
    flash_uf2,
    waitfor_uf2,
)

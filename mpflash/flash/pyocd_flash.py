"""Compatibility shim — the implementation moved to :mod:`mpflash.flash.builtins.pyocd.flash`."""

from mpflash.flash.builtins.pyocd.flash import *  # noqa: F401,F403
from mpflash.flash.builtins.pyocd.flash import (  # noqa: F401
    PyOCDFlash,
    PyOCDProbe,
    flash_pyocd,
    list_pyocd_probes,
    pyocd_info,
)

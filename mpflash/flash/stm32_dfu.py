"""Compatibility shim — the implementation moved to :mod:`mpflash.flash.builtins.dfu.stm32_dfu`."""

from mpflash.flash.builtins.dfu.stm32_dfu import *  # noqa: F401,F403
from mpflash.flash.builtins.dfu.stm32_dfu import dfu_init, flash_stm32_dfu  # noqa: F401

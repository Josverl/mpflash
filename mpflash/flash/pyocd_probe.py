"""PyOCD probe re-export for backwards compatibility.

``PyOCDProbe`` is defined in ``pyocd_flash`` alongside the flash logic.
This module re-exports it so that tests and external code can import from
the more descriptive path ``mpflash.flash.pyocd_probe``.

This is an AI fixup - may be removed in the future.
"""

from mpflash.flash.pyocd_flash import PyOCDProbe

__all__ = ["PyOCDProbe"]

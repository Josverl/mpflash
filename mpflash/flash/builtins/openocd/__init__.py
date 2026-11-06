"""OpenOCD based flashing (currently PSOC Edge).

This is the internal implementation behind
:class:`mpflash.flash.builtins.openocd_backend.OpenOCDBackend`. Public callers
should use :func:`mpflash.flash.flash_mcu` with ``method=FlashMethod.OPENOCD``.
"""

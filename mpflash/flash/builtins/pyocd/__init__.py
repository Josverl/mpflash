"""pyOCD-specific bits owned by the pyOCD flash backend.

This sub-package keeps debug-probe abstractions out of ``mpflash.flash``
core. ``mpflash`` itself never imports ``probes`` — only the pyOCD backend
(and the legacy ``mpflash.flash.debug_probe`` shim) does.
"""

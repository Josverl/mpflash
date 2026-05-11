"""Compatibility module for pyOCD probe discovery.

Historically tests patched symbols in ``mpflash.flash.pyocd_probe``.
The implementation now lives in ``pyocd_flash``; this module keeps the
patch points stable.
"""

from typing import List

from mpflash.errors import MPFlashError
from mpflash.flash.pyocd_flash import PyOCDProbe as _PyOCDProbe
from mpflash.flash.pyocd_flash import _ensure_pyocd as _flash_ensure_pyocd


def _ensure_pyocd():
    """Patchable proxy to pyocd_flash._ensure_pyocd."""
    return _flash_ensure_pyocd()


class PyOCDProbe(_PyOCDProbe):
    """Compatibility wrapper that preserves test patch points."""

    @classmethod
    def is_implementation_available(cls) -> bool:
        try:
            _ensure_pyocd()
            return True
        except MPFlashError:
            return False

    @classmethod
    def discover(cls) -> List["PyOCDProbe"]:
        try:
            modules = _ensure_pyocd()
            connect_helper = modules["ConnectHelper"]
            pyocd_probes = connect_helper.get_all_connected_probes(blocking=False)
            return [
                cls(
                    unique_id=pyocd_probe.unique_id,
                    description=pyocd_probe.description,
                    pyocd_probe_obj=pyocd_probe,
                )
                for pyocd_probe in pyocd_probes
            ]
        except Exception:
            return []


__all__ = ["PyOCDProbe", "_ensure_pyocd"]

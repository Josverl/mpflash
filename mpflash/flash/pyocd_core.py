"""Compatibility shim — the implementation moved to :mod:`mpflash.flash.builtins.pyocd.core`."""

from mpflash.flash.builtins.pyocd.core import *  # noqa: F401,F403
from mpflash.flash.builtins.pyocd.core import (  # noqa: F401
    MCUIdentifier,
    auto_install_pack_for_target,
    detect_pyocd_target,
    get_pyocd_targets,
    get_unsupported_reason,
    is_pyocd_available,
    is_pyocd_supported,
)

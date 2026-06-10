"""Compatibility shim — see :mod:`mpflash.flash.builtins.uf2.volume`."""

from mpflash.flash.builtins.uf2.volume import *  # noqa: F401,F403
from mpflash.flash.builtins.uf2.volume import (  # noqa: F401
    dismount,
    resolve_explicit_volume,
    translate_volume_path,
    wait_for_volume,
)

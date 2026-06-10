"""Deprecated location for the debug-probe abstraction.

The real definitions now live in :mod:`mpflash.flash.builtins.pyocd.probes`.
This module is kept only for backwards compatibility with external code that
imported from the old path. It emits :class:`DeprecationWarning` on import
and will be removed in a future release.
"""

from __future__ import annotations

import warnings

from mpflash.flash.builtins.pyocd.probes import (  # noqa: F401
    DebugProbe,
    _probe_implementations,
    find_debug_probe,
    get_debug_probes,
    is_debug_programming_available,
    register_probe_implementation,
)

warnings.warn(
    "mpflash.flash.debug_probe is deprecated; import from "
    "mpflash.flash.builtins.pyocd.probes instead.",
    DeprecationWarning,
    stacklevel=2,
)

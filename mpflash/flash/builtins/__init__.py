"""Built-in flash backends. Importing this module registers them.

Each backend module imports :func:`mpflash.flash.registry.register` and calls
it at module load. Optional-dependency backends (pyOCD) swallow ImportError so
``mpflash`` still works without them.
"""

# Order matters only for tie-breaking equal-priority registrations; the
# registry sorts by ``priority`` for selection.
from . import uf2_backend  # noqa: F401
from . import dfu_backend  # noqa: F401
from . import esptool_backend  # noqa: F401

# pyOCD is optional — its backend module guards its own imports.
try:
    from . import pyocd_backend  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency missing entirely
    pass

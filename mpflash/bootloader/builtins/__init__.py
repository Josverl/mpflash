"""Built-in bootloader activators. Importing this module registers them.

Each submodule imports :func:`mpflash.bootloader.registry.register` and calls
it at module load.
"""

# Order matters for fallback dedupe only; all three are independent.
from . import mpy  # noqa: F401
from . import touch1200  # noqa: F401
from . import manual  # noqa: F401

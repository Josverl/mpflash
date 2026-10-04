"""Built-in backup providers; importing this package registers them.

Each provider module calls :func:`mpflash.backup.registry.register` at import
time and is imported here.
"""

from . import esp, romfs, rp2, vfs  # noqa: F401

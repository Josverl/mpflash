"""Abstract base class for pluggable bootloader activators.

An *activator* knows one way to put a board into firmware-update / bootloader
mode (e.g. send ``machine.bootloader()``, open the port at 1200 baud, or ask
the user to press a button). Built-ins live in
``mpflash.bootloader.builtins`` and register themselves at import time;
third-party flash plugins can call :func:`mpflash.bootloader.registry.register`
to contribute additional activators.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard


class BootloaderActivator(ABC):
    """Contract every bootloader activator must implement.

    Subclasses are typically singletons; the registry instantiates each
    activator once. The ``name`` attribute must match the corresponding
    :class:`mpflash.common.BootloaderMethod` enum *value* for the built-in
    activators (``"mpy"``, ``"touch1200"``, ``"manual"``); plugin-supplied
    activators may use any unique string.
    """

    #: Short identifier (matches ``BootloaderMethod.value`` for built-ins).
    name: str = ""

    def is_available(self, mcu: "MPRemoteBoard") -> bool:
        """Runtime availability check for this MCU.

        Default returns ``True``. Activators with environmental
        prerequisites (USB drivers, GUI prompts on a headless host, …)
        should override.
        """
        return True

    @abstractmethod
    def activate(self, mcu: "MPRemoteBoard", *, timeout: int = 10) -> bool:
        """Attempt to put ``mcu`` into bootloader mode.

        Returns ``True`` if the activator believes the attempt succeeded;
        the caller is responsible for confirming readiness afterwards.
        """
        raise NotImplementedError

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"

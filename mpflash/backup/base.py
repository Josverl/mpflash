"""Provider contract for backing up and restoring one or more device components.

Unlike :class:`mpflash.flash.base.FlashBackend`, which only writes firmware,
a provider can *read* device data, so it declares read and write capability
separately per component and per connected device.

Providers are discovered like flash backends: built-ins register themselves
when ``mpflash.backup.builtins`` is imported, and third parties use the
``mpflash.backup_plugins`` entry-point group.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from .models import Artifact, ComponentKind, ProviderCapability

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard

    from .bundle import Bundle, BundleWriter


@dataclass(frozen=True)
class BackupContext:
    """Per-backup inputs shared with every provider."""

    writer: "BundleWriter"


@dataclass(frozen=True)
class BackupOutput:
    """Extra information a provider returns beside the artifacts it staged."""

    tree_text: str = ""
    notes: tuple[str, ...] = ()


class BackupProvider(ABC):
    """Contract every backup/restore provider implements.

    Providers stage their data through ``ctx.writer`` (which hashes and records
    each artifact) and must raise :class:`~mpflash.errors.MPFlashError` on any
    failure; returning normally means every requested artifact was written.
    """

    #: Short unique identifier recorded in each artifact.
    name: str = ""

    #: Higher wins when several providers can handle the same component.
    priority: int = 0

    def is_available(self) -> bool:
        """Return ``False`` when an optional dependency or tool is missing."""
        return True

    @abstractmethod
    def capabilities(self, mcu: "MPRemoteBoard") -> Sequence[ProviderCapability]:
        """Return what this provider can do for ``mcu``; empty when it does not apply."""

    @abstractmethod
    def backup(self, mcu: "MPRemoteBoard", component: ComponentKind, ctx: BackupContext) -> BackupOutput:
        """Read ``component`` from ``mcu`` and stage it through ``ctx.writer``."""

    @abstractmethod
    def describe_restore(self, mcu: "MPRemoteBoard", bundle: "Bundle", artifacts: Sequence[Artifact]) -> Sequence[str]:
        """Validate target compatibility and list every erase/write that :meth:`restore` will perform.

        Must not modify the device. Raise ``MPFlashError`` if the bundle does not fit ``mcu``.
        """

    @abstractmethod
    def restore(self, mcu: "MPRemoteBoard", bundle: "Bundle", artifacts: Sequence[Artifact]) -> None:
        """Write ``artifacts`` to ``mcu`` and verify them.

        Leave ``mcu`` connected and usable so later components can be restored.
        """

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} priority={self.priority}>"

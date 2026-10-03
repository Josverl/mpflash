"""Registry and capability negotiation for backup providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Type

from mpflash.logger import log

from .base import BackupProvider
from .models import ComponentKind, ProviderCapability

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard

ENTRY_POINT_GROUP = "mpflash.backup_plugins"

_providers: Dict[str, BackupProvider] = {}
_entry_points_loaded = False


def register(provider: BackupProvider | Type[BackupProvider]) -> BackupProvider:
    """Register a provider instance (or class); re-registering a name replaces it."""
    instance = provider() if isinstance(provider, type) else provider
    if not instance.name:
        raise ValueError(f"BackupProvider {instance!r} has no 'name' attribute")
    _providers[instance.name] = instance
    log.debug(f"Registered backup provider: {instance!r}")
    return instance


def unregister(name: str) -> None:
    """Remove a provider; used by tests to avoid cross-test pollution."""
    _providers.pop(name, None)


def discover_entry_points() -> None:
    """Load third-party providers advertised through ``mpflash.backup_plugins`` (best effort)."""
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True

    from importlib.metadata import entry_points

    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            register(entry.load())
        except Exception as exc:  # noqa: BLE001 - a broken plugin must not break backups
            log.warning(f"Ignoring backup plugin {entry.name!r}: {exc}")


def get_providers() -> List[BackupProvider]:
    """Return all registered providers (built-ins and plugins)."""
    import mpflash.backup.builtins  # noqa: F401 - built-ins register on import

    discover_entry_points()
    return list(_providers.values())


def capabilities_for(mcu: "MPRemoteBoard") -> List[Tuple[BackupProvider, ProviderCapability]]:
    """Return every ``(provider, capability)`` available for ``mcu``, best provider first."""
    found: List[Tuple[BackupProvider, ProviderCapability]] = []
    for provider in get_providers():
        if not provider.is_available():
            continue
        try:
            found.extend((provider, capability) for capability in provider.capabilities(mcu))
        except Exception as exc:  # noqa: BLE001 - one failing provider must not hide the others
            log.warning(f"Backup provider {provider.name!r} could not inspect {mcu.serialport}: {exc}")
    found.sort(key=lambda item: item[0].priority, reverse=True)
    return found


def choose(
    available: Sequence[Tuple[BackupProvider, ProviderCapability]],
    component: ComponentKind,
    *,
    restore: bool,
    prefer: str = "",
) -> Optional[Tuple[BackupProvider, ProviderCapability]]:
    """Pick the best entry able to back up (or restore) ``component``, or ``None``.

    ``available`` is the list returned by :func:`capabilities_for`, so a device
    is probed once per command. A provider named ``prefer`` (for example the one
    that created a bundle) wins over priority.
    """
    matches = [
        (provider, capability)
        for provider, capability in available
        if capability.component is component and (capability.can_restore if restore else capability.can_backup)
    ]
    for provider, capability in matches:
        if prefer and provider.name == prefer:
            return provider, capability
    return matches[0] if matches else None

"""Registry for pluggable bootloader activators.

Built-ins in ``mpflash.bootloader.builtins`` register themselves at import
time. Flash plugins that contribute their own activators should call
:func:`register` during their module import (the flash registry triggers
that import on first use).

This registry is *internal* — there is no separate
``mpflash.bootloader_plugins`` entry-point group. Plugins distribute
activators alongside their flash backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Optional, Sequence, Type

from mpflash.logger import log

if TYPE_CHECKING:
    from mpflash.bootloader.base import BootloaderActivator

# Map of name -> activator instance. Insertion order is preserved.
_activators: "dict[str, BootloaderActivator]" = {}


def register(activator) -> "BootloaderActivator":
    """Register an activator instance (or class — auto-instantiated).

    Re-registering the same ``name`` replaces the existing entry; this lets a
    plugin override a built-in by registering after import.
    """
    from mpflash.bootloader.base import BootloaderActivator

    instance = activator() if isinstance(activator, type) else activator
    if not isinstance(instance, BootloaderActivator):
        raise TypeError(f"{instance!r} is not a BootloaderActivator")
    if not instance.name:
        raise ValueError(f"BootloaderActivator {instance!r} has no 'name' attribute")
    _activators[instance.name] = instance
    log.debug(f"Registered bootloader activator: {instance!r}")
    return instance


def unregister(name: str) -> None:
    """Remove an activator; used by tests to avoid cross-test pollution."""
    _activators.pop(name, None)


def _ensure_builtins() -> None:
    """Import the built-in activators so they register themselves."""
    import mpflash.bootloader.builtins  # noqa: F401


def get_activator(name: str) -> Optional["BootloaderActivator"]:
    """Look up an activator by name; returns ``None`` if unknown."""
    if not _activators:
        _ensure_builtins()
    return _activators.get(name)


def get_activators() -> List["BootloaderActivator"]:
    """Return every registered activator."""
    _ensure_builtins()
    return list(_activators.values())


def resolve_methods(
    requested: str,
    preferred: Optional[Sequence[str]] = None,
) -> List[str]:
    """Build the ordered list of activator names to try.

    * ``requested == "none"`` → ``[]`` (no activation needed).
    * ``requested == "auto"`` → use ``preferred`` if supplied, else fall back
      to a generic ``[mpy, manual]`` ladder. ``"manual"`` is always appended
      as a last-resort fallback when not already present.
    * Any other value → ``[requested, *preferred, "manual"]``, deduped.
    """
    _ensure_builtins()
    requested = (requested or "").lower()

    if requested == "none":
        return []

    seq: List[str]
    if requested == "auto":
        seq = list(preferred) if preferred else ["mpy", "manual"]
    else:
        seq = [requested]
        if preferred:
            seq.extend(preferred)

    if "manual" not in seq and "manual" in _activators:
        seq.append("manual")

    # Dedupe while preserving order, and drop names without a registered activator.
    seen: set[str] = set()
    result: List[str] = []
    for name in seq:
        if name in seen:
            continue
        seen.add(name)
        if name in _activators:
            result.append(name)
        else:
            log.debug(f"Skipping unknown bootloader activator: {name!r}")
    return result


def iter_activators_for(names: Iterable[str]) -> Iterable["BootloaderActivator"]:
    """Yield activator instances for each name (skipping unknown names)."""
    for name in names:
        activator = get_activator(name)
        if activator is not None:
            yield activator

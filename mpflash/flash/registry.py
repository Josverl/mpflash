"""Registry and selection logic for pluggable flash backends.

Backends are registered in two ways:

* In-tree built-ins import themselves from ``mpflash.flash.builtins``.
* Third-party plugins are discovered lazily via the
  ``mpflash.flash_plugins`` entry-point group.

Both routes use :func:`register`. Selection is driven by metadata declared on
each backend (port, file format, host platform, availability, priority) — no
hardcoded ``if mcu.port == "esp32"`` ladders.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Type

from mpflash.errors import MPFlashError
from mpflash.flash.base import FlashBackend
from mpflash.flash.context import Reason
from mpflash.flash.services import default_services
from mpflash.logger import log
from mpflash.mpremoteboard import MPRemoteBoard

# Map of name -> backend instance. Insertion order is preserved.
_backends: "dict[str, FlashBackend]" = {}

# Tracks whether entry-point discovery has run.
_entry_points_loaded = False


def register(backend: FlashBackend | Type[FlashBackend]) -> FlashBackend:
    """Register a backend instance (or class — auto-instantiated).

    Re-registering the same ``name`` replaces the existing entry; this lets a
    plugin override a built-in by registering after import.
    """
    instance = backend() if isinstance(backend, type) else backend
    if not instance.name:
        raise ValueError(f"FlashBackend {instance!r} has no 'name' attribute")
    _backends[instance.name] = instance
    log.debug(f"Registered flash backend: {instance!r}")
    return instance


def unregister(name: str) -> None:
    """Remove a backend; used by tests to avoid cross-test pollution."""
    _backends.pop(name, None)


def discover_entry_points() -> None:
    """Load any third-party backends advertised via ``mpflash.flash_plugins``.

    Called lazily by :func:`get_backends` so a normal CLI invocation does not
    pay the cost of importing ``importlib.metadata`` unless we actually need
    to enumerate plugins.
    """
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True

    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - Python <3.10 not supported
        return

    try:
        eps = entry_points(group="mpflash.flash_plugins")
    except TypeError:
        # Older importlib.metadata API — returns a dict-like.
        eps = entry_points().get("mpflash.flash_plugins", [])  # type: ignore[assignment]

    for ep in eps:
        try:
            loaded = ep.load()
        except Exception as exc:  # noqa: BLE001 - plugin loading is best-effort
            log.debug(f"Failed to load flash plugin {ep.name!r}: {exc}")
            continue
        try:
            register(loaded)
        except Exception as exc:  # noqa: BLE001
            log.debug(f"Failed to register flash plugin {ep.name!r}: {exc}")


def get_backends() -> List[FlashBackend]:
    """Return all registered backends (built-ins + plugins)."""
    # Ensure built-ins are imported (they register on import).
    import mpflash.flash.builtins  # noqa: F401

    discover_entry_points()
    return list(_backends.values())


def get_backend(name: str) -> Optional[FlashBackend]:
    """Look up a backend by name; returns ``None`` if unknown."""
    if not _backends:
        get_backends()
    return _backends.get(name)


def select_backend(
    mcu: MPRemoteBoard,
    fw_file: Path,
    requested_name: Optional[str] = None,
) -> FlashBackend:
    """Pick the right backend for ``mcu`` + ``fw_file``.

    When ``requested_name`` is provided, validate that backend supports the
    request and use it (or raise). When it is ``None`` (auto), pick the
    highest-priority backend whose ``supports()`` returns ``None``.

    Raises:
        MPFlashError: If the request cannot be satisfied; the message lists
            each backend's rejection :class:`Reason` so the user can see why.
    """
    backends = get_backends()
    platform = default_services.current_platform()

    if requested_name:
        backend = get_backend(requested_name)
        if backend is None:
            available = ", ".join(sorted(b.name for b in backends)) or "<none>"
            raise MPFlashError(
                f"Unknown flash method {requested_name!r}. "
                f"Available: {available}"
            )
        reason = backend.supports(mcu, fw_file, platform)
        if reason is not None:
            raise MPFlashError(
                f"Backend {backend.name!r} cannot flash {mcu.board_id or mcu.port!r} "
                f"with {fw_file.name}: {reason}"
            )
        return backend

    # Auto-select: filter by supports(), then sort by priority desc.
    candidates: List[tuple[FlashBackend, Optional[Reason]]] = [
        (b, b.supports(mcu, fw_file, platform)) for b in backends
    ]
    matching = [b for b, r in candidates if r is None]
    if matching:
        matching.sort(key=lambda b: b.priority, reverse=True)
        return matching[0]

    # Nothing matched — build a helpful diagnostic.
    rejections = "\n  ".join(
        f"{b.name}: {r}" for b, r in candidates if r is not None
    ) or "<no backends registered>"
    raise MPFlashError(
        f"No flash backend can handle {mcu.port or '<unknown port>'} "
        f"{mcu.board_id or mcu.board} with {fw_file.name}.\n"
        f"  {rejections}"
    )

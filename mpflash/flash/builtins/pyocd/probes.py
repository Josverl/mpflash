"""Debug-probe abstraction owned by the pyOCD flash backend.

The :class:`DebugProbe` ABC and the probe-implementation registry used to live
in ``mpflash.flash.debug_probe``; that location is now a deprecation shim that
re-exports the names defined here.

Third parties that want to add a new probe implementation (OpenOCD, J-Link, …)
should register through this module — but importantly, *probes are an
internal concern of the pyOCD backend*, not a separate ``mpflash`` extension
point.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from mpflash.errors import MPFlashError
from mpflash.logger import log


class DebugProbe(ABC):
    """Abstract base class for debug probe implementations."""

    def __init__(self, unique_id: str, description: str):
        self.unique_id = unique_id
        self.description = description
        self.target_type: Optional[str] = None

    @abstractmethod
    def program_flash(self, firmware_path: Path, target_type: str, **options) -> bool:
        """Program flash memory via the debug probe."""

    @classmethod
    @abstractmethod
    def is_implementation_available(cls) -> bool:
        """Check if this probe implementation is available."""

    @classmethod
    @abstractmethod
    def discover(cls) -> List["DebugProbe"]:
        """Discover all probes of this type."""

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.unique_id})"


# Registry for probe implementations
_probe_implementations: "dict[str, type]" = {}


def _ensure_builtin_registrations() -> None:
    """Lazily register built-in probe implementations.

    Avoids import-order side effects and circular-import noise during module
    import while keeping the legacy probe registry functional.
    """
    if "pyocd" in _probe_implementations:
        return
    try:
        from mpflash.flash.builtins.pyocd.flash import PyOCDProbe

        register_probe_implementation("pyocd", PyOCDProbe)
    except Exception:
        # Best-effort only: pyOCD backend may be unavailable in this env.
        pass


def register_probe_implementation(name: str, probe_class: type) -> None:
    """Register a probe implementation for discovery."""
    if not issubclass(probe_class, DebugProbe):
        raise ValueError("Probe class must inherit from DebugProbe")
    _probe_implementations[name] = probe_class
    log.debug(f"Registered {name} probe implementation")


def get_debug_probes() -> List[DebugProbe]:
    """Discover all available debug probes across all implementations."""
    _ensure_builtin_registrations()
    probes: List[DebugProbe] = []
    for name, probe_class in _probe_implementations.items():
        try:
            if probe_class.is_implementation_available():
                discovered = probe_class.discover()
                probes.extend(discovered)
                log.debug(f"Found {len(discovered)} {name} probes")
        except Exception as e:  # noqa: BLE001 - discovery is best-effort
            log.debug(f"Failed to discover {name} probes: {e}")
    return probes


def find_debug_probe(probe_id: Optional[str] = None) -> Optional[DebugProbe]:
    """Find a debug probe by ID (supports partial matching), or return the first available."""
    probes = get_debug_probes()
    if not probes:
        return None
    if not probe_id:
        return probes[0]
    for probe in probes:
        if probe.unique_id == probe_id:
            return probe
    matches = [p for p in probes if probe_id in p.unique_id]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise MPFlashError(
            f"Ambiguous probe ID '{probe_id}' matches multiple probes: "
            f"{[p.unique_id for p in matches]}"
        )
    return None


def is_debug_programming_available() -> bool:
    """Check if any registered debug probe implementation is usable."""
    _ensure_builtin_registrations()
    return any(impl.is_implementation_available() for impl in _probe_implementations.values())

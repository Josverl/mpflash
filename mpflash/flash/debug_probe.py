"""
Debug probe abstraction for MPFlash.

Provides extensible interface for debug probe implementations (pyOCD, OpenOCD, J-Link, etc.).
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from pathlib import Path

from mpflash.logger import log
from mpflash.errors import MPFlashError


class DebugProbe(ABC):
    """Abstract base class for debug probe implementations."""
    
    def __init__(self, unique_id: str, description: str):
        self.unique_id = unique_id
        self.description = description
        self.target_type: Optional[str] = None
    
    @abstractmethod
    def program_flash(self, firmware_path: Path, target_type: str, **options) -> bool:
        """Program flash memory via the debug probe."""
        pass
    
    @classmethod
    @abstractmethod
    def is_implementation_available(cls) -> bool:
        """Check if this probe implementation is available."""
        pass
    
    @classmethod
    @abstractmethod
    def discover(cls) -> List['DebugProbe']:
        """Discover all probes of this type."""
        pass
    
    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.unique_id})"


# Registry for probe implementations
_probe_implementations = {}


def register_probe_implementation(name: str, probe_class: type):
    """Register a probe implementation for discovery."""
    if not issubclass(probe_class, DebugProbe):
        raise ValueError("Probe class must inherit from DebugProbe")
    _probe_implementations[name] = probe_class
    log.debug(f"Registered {name} probe implementation")


def get_debug_probes() -> List[DebugProbe]:
    """Discover all available debug probes across all implementations."""
    probes = []
    
    for name, probe_class in _probe_implementations.items():
        try:
            if probe_class.is_implementation_available():
                discovered = probe_class.discover()
                probes.extend(discovered)
                log.debug(f"Found {len(discovered)} {name} probes")
        except Exception as e:
            log.debug(f"Failed to discover {name} probes: {e}")
    
    return probes


def find_debug_probe(probe_id: Optional[str] = None) -> Optional[DebugProbe]:
    """Find a debug probe by ID (supports partial matching), or return first available."""
    probes = get_debug_probes()
    
    if not probes:
        return None
    
    if not probe_id:
        return probes[0]
    
    # Exact match first
    for probe in probes:
        if probe.unique_id == probe_id:
            return probe
    
    # Partial match
    matches = [p for p in probes if probe_id in p.unique_id]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise MPFlashError(
            f"Ambiguous probe ID '{probe_id}' matches multiple probes: "
            f"{[p.unique_id for p in matches]}"
        )
    
    return None


def is_debug_programming_available() -> bool:
    """Check if any debug probe programming is available."""
    return any(
        impl.is_implementation_available() 
        for impl in _probe_implementations.values()
    )


# Auto-register pyOCD if available
try:
    from .pyocd_flash import PyOCDProbe
    register_probe_implementation("pyocd", PyOCDProbe)
except ImportError:
    log.debug("pyOCD probe implementation not available")
"""
PyOCD flash programming implementation for MPFlash.

This module provides SWD/JTAG flash programming using pyOCD as an alternative
to serial bootloader methods. Includes probe discovery, target detection,
and flash programming operations.
"""

from typing import List, Optional, Dict, Any
from pathlib import Path

from mpflash.logger import log
from mpflash.errors import MPFlashError
from mpflash.mpremoteboard import MPRemoteBoard
from .debug_probe import DebugProbe
from .pyocd_core import (
    detect_pyocd_target, 
    is_pyocd_supported, 
    get_unsupported_reason,
    is_pyocd_available
)


# Lazy import pyOCD to handle optional dependency
_pyocd_available = None
_pyocd_modules = {}


def _ensure_pyocd():
    """Ensure pyOCD modules are imported and available."""
    global _pyocd_available, _pyocd_modules
    
    if _pyocd_available is None:
        try:
            from pyocd.core.helpers import ConnectHelper
            from pyocd.flash.file_programmer import FileProgrammer
            from pyocd.core.exceptions import Error as PyOCDError
            
            _pyocd_modules.update({
                'ConnectHelper': ConnectHelper,
                'FileProgrammer': FileProgrammer,
                'PyOCDError': PyOCDError
            })
            _pyocd_available = True
            log.debug("pyOCD modules loaded successfully")
            
        except ImportError as e:
            _pyocd_available = False
            log.debug(f"pyOCD not available: {e}")
    
    if not _pyocd_available:
        raise MPFlashError("pyOCD is not installed. Install with: uv sync --extra pyocd")
    
    return _pyocd_modules


# =============================================================================
# PyOCD Probe Implementation
# =============================================================================

class PyOCDProbe(DebugProbe):
    """PyOCD debug probe implementation."""
    
    def __init__(self, unique_id: str, description: str, pyocd_probe_obj=None):
        super().__init__(unique_id, description)
        self._pyocd_probe = pyocd_probe_obj
        self._session = None
        self._connected = False
    
    @classmethod
    def is_implementation_available(cls) -> bool:
        """Check if pyOCD implementation is available."""
        try:
            _ensure_pyocd()
            return True
        except MPFlashError:
            return False
    
    @classmethod
    def discover(cls) -> List['PyOCDProbe']:
        """Discover all connected pyOCD probes."""
        try:
            modules = _ensure_pyocd()
            ConnectHelper = modules['ConnectHelper']
            
            pyocd_probes = ConnectHelper.get_all_connected_probes(blocking=False)
            probes = []
            
            for pyocd_probe in pyocd_probes:
                probe = cls(
                    unique_id=pyocd_probe.unique_id,
                    description=pyocd_probe.description,
                    pyocd_probe_obj=pyocd_probe
                )
                probes.append(probe)
            
            log.debug(f"Discovered {len(probes)} pyOCD probes")
            return probes
            
        except Exception as e:
            log.debug(f"Failed to discover pyOCD probes: {e}")
            return []
    
    def connect(self) -> bool:
        """Connect to the pyOCD probe."""
        if self._connected:
            return True
        
        try:
            modules = _ensure_pyocd()
            ConnectHelper = modules['ConnectHelper']
            
            self._session = ConnectHelper.session_with_chosen_probe(
                unique_id=self.unique_id,
                options={"halt_on_connect": False, "auto_unlock": True}
            )
            
            if self._session:
                self._connected = True
                log.debug(f"Connected to pyOCD probe {self.unique_id}")
                return True
            else:
                raise MPFlashError(f"Failed to create session with probe {self.unique_id}")
                
        except Exception as e:
            self._connected = False
            log.error(f"Failed to connect to pyOCD probe {self.unique_id}: {e}")
            raise MPFlashError(
                f"Cannot connect to probe {self.unique_id}. "
                f"Ensure the target is powered and SWD/JTAG pins are connected. "
                f"Error: {e}"
            )
    
    def disconnect(self) -> None:
        """Disconnect from the pyOCD probe."""
        if self._session:
            try:
                self._session.close()
                log.debug(f"Disconnected from pyOCD probe {self.unique_id}")
            except Exception as e:
                log.debug(f"Error during disconnect: {e}")
            finally:
                self._session = None
                self._connected = False
    
    def program_flash(self, firmware_path: Path, target_type: str, **options) -> bool:
        """
        Program flash memory using pyOCD.
        
        Args:
            firmware_path: Path to firmware file (.bin, .hex, .elf)
            target_type: pyOCD target type string
            **options: Programming options (erase, frequency, etc.)
            
        Returns:
            True if programming succeeded
            
        Raises:
            MPFlashError: If programming fails
        """
        if not firmware_path.exists():
            raise MPFlashError(f"Firmware file not found: {firmware_path}")
        
        # Connect if not already connected
        if not self._connected:
            self.connect()
        
        try:
            modules = _ensure_pyocd()
            FileProgrammer = modules['FileProgrammer']
            
            # Extract programming options
            erase_option = "chip" if options.get("erase", False) else "sector"
            frequency = options.get("frequency", 4000000)
            
            # Create programmer with session
            programmer = FileProgrammer(self._session)
            
            log.info(f"Programming {firmware_path.name} to {target_type} via {self.description}")
            log.debug(f"Options: erase={erase_option}, frequency={frequency}Hz")
            
            # Program the firmware
            programmer.program(
                str(firmware_path),
                file_format=None,  # Auto-detect format
                erase=erase_option,
                reset=True,
                verify=True
            )
            
            log.info(f"Successfully programmed {firmware_path.name}")
            return True
            
        except Exception as e:
            error_msg = f"Flash programming failed: {e}"
            log.error(error_msg)
            raise MPFlashError(error_msg)
    
    def detect_target(self) -> Optional[str]:
        """Detect the target type connected to the probe."""
        try:
            if not self._connected:
                self.connect()
            
            if self._session and self._session.target:
                target_name = self._session.target.part_number.lower()
                log.info(f"Detected target: {target_name}")
                return target_name
                
        except Exception as e:
            log.debug(f"Target detection failed: {e}")
        
        return None
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        try:
            self.disconnect()
        except Exception:
            pass  # Don't raise in __exit__
        return False  # Don't suppress original exception


# =============================================================================
# Flash Programming Interface
# =============================================================================

class PyOCDFlash:
    """High-level pyOCD flash programming interface."""
    
    def __init__(self, mcu: MPRemoteBoard, probe_id: Optional[str] = None, auto_install_packs: bool = True):
        """
        Initialize PyOCD flash programmer.
        
        Args:
            mcu: MPRemoteBoard instance with board information
            probe_id: Specific probe unique ID to use (optional)
            auto_install_packs: Automatically install missing CMSIS packs
        """
        self.mcu = mcu
        self.probe_id = probe_id
        
        # Detect target type using core functionality
        self.target_type = detect_pyocd_target(mcu, auto_install_packs=auto_install_packs)
        
        if not is_pyocd_available():
            raise MPFlashError("No debug probe support available. Install with: uv sync --extra pyocd")
            
        if not self.target_type:
            reason = get_unsupported_reason(mcu)
            raise MPFlashError(f"Board {mcu.board_id} ({mcu.cpu}) not supported by pyOCD: {reason}")
    
    def flash_firmware(self, fw_file: Path, erase: bool = False, **kwargs) -> bool:
        """
        Flash firmware using pyOCD.
        
        Args:
            fw_file: Path to firmware file (.bin, .hex, .elf)
            erase: Whether to perform chip erase before programming
            **kwargs: Additional options passed to pyOCD
            
        Returns:
            True if flashing succeeded
            
        Raises:
            MPFlashError: If flashing fails
        """
        if not fw_file.exists():
            raise MPFlashError(f"Firmware file not found: {fw_file}")
            
        # Find appropriate probe
        probe = find_pyocd_probe(self.probe_id)
        if not probe:
            if self.probe_id:
                raise MPFlashError(
                    f"PyOCD probe '{self.probe_id}' not found. "
                    f"Use 'mpflash list-probes' to see available probes."
                )
            else:
                raise MPFlashError(
                    "No PyOCD debug probes available. "
                    "Connect a debug probe and ensure pyOCD can detect it."
                )
        
        log.info(f"Flashing {fw_file.name} to {self.mcu.board_id} via pyOCD SWD/JTAG")
        log.debug(f"Target type: {self.target_type}, Probe: {probe.description}")
        
        # Build programming options
        options = {
            "erase": erase,
            "frequency": kwargs.get("frequency", 4000000),
            "pyocd_options": kwargs.get("pyocd_options", {})
        }
        
        # Program using the probe
        return probe.program_flash(fw_file, self.target_type, **options)


# =============================================================================
# Probe Discovery Functions
# =============================================================================

def list_pyocd_probes() -> List[PyOCDProbe]:
    """
    Discover all connected pyOCD debug probes.
    
    Returns:
        List of PyOCDProbe instances
    """
    return PyOCDProbe.discover()


def find_pyocd_probe(probe_id: Optional[str] = None) -> Optional[PyOCDProbe]:
    """
    Find a pyOCD debug probe by ID, or handle multi-probe selection.
    
    Args:
        probe_id: Specific probe ID to find (supports partial matching)
        
    Returns:
        PyOCDProbe instance or None if not found
        
    Raises:
        MPFlashError: When multiple probes are available but no specific probe_id provided
    """
    from loguru import logger as log
    from mpflash.exceptions import MPFlashError
    
    probes = list_pyocd_probes()
    
    if not probes:
        return None
    
    if not probe_id:
        if len(probes) == 1:
            return probes[0]
        else:
            # Multiple probes available - user must specify which one
            log.error(f"Multiple debug probes detected ({len(probes)}). Please specify which probe to use with --probe <ID>:")
            for i, probe in enumerate(probes, 1):
                log.error(f"  {i}. {probe.description} (ID: {probe.unique_id})")
            raise MPFlashError(
                f"Multiple debug probes found. Use --probe <ID> to specify which probe to use.\n"
                f"Available probes: {', '.join(p.unique_id for p in probes)}"
            )
    
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
            f"{[p.unique_id for p in matches]}. "
            f"Use a more specific ID or the full unique ID."
        )
    
    return None


# =============================================================================
# Main Public API
# =============================================================================

def flash_pyocd(mcu: MPRemoteBoard, fw_file: Path, erase: bool = False, 
                probe_id: Optional[str] = None, auto_install_packs: bool = True, **kwargs) -> bool:
    """
    Flash MCU using pyOCD SWD/JTAG interface.
    
    Args:
        mcu: MPRemoteBoard instance with board information
        fw_file: Path to firmware file
        erase: Whether to erase flash before programming  
        probe_id: Specific debug probe ID to use (optional)
        auto_install_packs: Automatically install missing CMSIS packs
        **kwargs: Additional options
        
    Returns:
        True if flashing succeeded
        
    Raises:
        MPFlashError: If flashing fails
    """
    if not is_pyocd_supported(mcu):
        reason = get_unsupported_reason(mcu)
        raise MPFlashError(f"PyOCD flash not supported: {reason}")
        
    # Create flasher and program
    flasher = PyOCDFlash(mcu, probe_id=probe_id, auto_install_packs=auto_install_packs)
    return flasher.flash_firmware(fw_file, erase=erase, **kwargs)


def pyocd_info() -> Dict[str, Any]:
    """
    Get information about pyOCD installation and available probes.
    
    Returns:
        Dictionary with pyOCD status information
    """
    info = {
        "available": is_pyocd_available(),
        "probes": [],
        "version": None
    }
    
    if info["available"]:
        try:
            import pyocd
            info["version"] = pyocd.__version__
        except ImportError:
            pass
            
        info["probes"] = [
            {
                "unique_id": probe.unique_id,
                "description": probe.description,
                "vendor": getattr(probe, 'vendor_name', 'Unknown'),
                "product": getattr(probe, 'product_name', 'Unknown'),
                "target_type": probe.target_type
            }
            for probe in list_pyocd_probes()
        ]
    
    return info


# =============================================================================
# Compatibility Functions (for migration)
# =============================================================================

def find_probe_for_target(target_type: str, probe_id: Optional[str] = None) -> Optional[PyOCDProbe]:
    """
    Find a suitable debug probe for the target type.
    
    Args:
        target_type: pyOCD target type string
        probe_id: Specific probe ID to find (optional)
        
    Returns:
        PyOCDProbe instance or None if not found
    """
    return find_pyocd_probe(probe_id)  # target_type not needed for probe selection
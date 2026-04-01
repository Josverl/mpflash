"""
Core pyOCD functionality for MPFlash.

This module contains the essential pyOCD integration logic including
target detection, fuzzy matching, and CMSIS pack management.
"""

import re
import subprocess
from typing import Optional, Dict, List, Tuple
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

from mpflash.logger import log
from mpflash.errors import MPFlashError
from mpflash.mpremoteboard import MPRemoteBoard


# =============================================================================
# Secure Subprocess Utilities
# =============================================================================

def _run_pyocd_command(args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """
    Run pyOCD command with security validation and error handling.
    
    Args:
        args: List of command arguments (excluding 'pyocd')
        timeout: Timeout in seconds
        
    Returns:
        subprocess.CompletedProcess object
        
    Raises:
        MPFlashError: If command execution fails or times out
    """
    # Validate arguments - should be safe for pyOCD commands
    for arg in args:
        if not isinstance(arg, str):
            raise MPFlashError(f"Invalid argument type: {type(arg)}")
        # Allow alphanumeric, dashes, dots, and common pyOCD options
        if not re.match(r'^[a-zA-Z0-9._-]+$', arg):
            raise MPFlashError(f"Invalid argument format: {arg}")
    
    cmd = ['pyocd'] + args
    
    try:
        log.debug(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False  # Don't raise on non-zero exit
        )
        return result
        
    except subprocess.TimeoutExpired:
        raise MPFlashError(f"Command timed out after {timeout}s: {' '.join(cmd)}")
    except FileNotFoundError:
        raise MPFlashError(
            "pyOCD command not found. Ensure pyOCD is installed and in PATH: "
            "uv sync --extra pyocd"
        )
    except Exception as e:
        raise MPFlashError(f"Command execution failed: {e}")


# Lazy import for pyOCD to handle optional dependency
_pyocd_available = None
_pyocd_modules = {}


def _ensure_pyocd():
    """Ensure pyOCD modules are imported and available."""
    global _pyocd_available, _pyocd_modules
    
    if _pyocd_available is None:
        try:
            import pyocd
            _pyocd_modules['pyocd_version'] = pyocd.__version__
            _pyocd_available = True
            log.debug(f"pyOCD {pyocd.__version__} available")
        except ImportError as e:
            _pyocd_available = False
            log.debug(f"pyOCD not available: {e}")
    
    if not _pyocd_available:
        raise MPFlashError("pyOCD is not installed. Install with: uv sync --extra pyocd")
    
    return _pyocd_modules


def is_pyocd_available() -> bool:
    """Check if pyOCD is available for use."""
    try:
        _ensure_pyocd()
        return True
    except MPFlashError:
        return False


# =============================================================================
# MCU Information Parsing
# =============================================================================

def parse_mcu_info(mcu: MPRemoteBoard) -> Dict[str, str]:
    """
    Parse MCU information from connected device.
    
    Args:
        mcu: Connected MPRemoteBoard instance
        
    Returns:
        Dictionary with parsed MCU information:
        - chip_family: e.g., "STM32WB55", "RP2040", "SAMD51"
        - chip_variant: e.g., "RGV6", "P19A"  
        - board_name: e.g., "NUCLEO-WB55", "RPI_PICO"
        - full_description: Complete description string
        
    Examples:
        "NUCLEO-WB55 with STM32WB55RGV6" -> {
            "chip_family": "STM32WB55",
            "chip_variant": "RGV6", 
            "board_name": "NUCLEO-WB55",
            "full_description": "NUCLEO-WB55 with STM32WB55RGV6"
        }
    """
    info = {
        "chip_family": "",
        "chip_variant": "",
        "board_name": "",
        "full_description": mcu.description,
        "cpu": mcu.cpu,
        "port": mcu.port
    }
    
    # Parse description field (sys.implementation._machine)
    description = mcu.description.strip()
    
    # Pattern 1: "BOARD_NAME with CHIP_FAMILY_VARIANT"
    # Example: "NUCLEO-WB55 with STM32WB55RGV6"
    match = re.match(r"^(.+?)\s+with\s+(.+)$", description, re.IGNORECASE)
    if match:
        info["board_name"] = match.group(1).strip()
        chip_full = match.group(2).strip()
        
        # Extract family and variant from chip name
        # Pattern for STM32 chips: STM32[FAMILY][VARIANT]
        # Examples: STM32F429ZI -> STM32F429 + ZI, STM32WB55RGV6 -> STM32WB55 + RGV6
        chip_match = re.match(r"^(STM32[A-Z]+\d+)([A-Z0-9]*)$", chip_full, re.IGNORECASE)
        if chip_match:
            info["chip_family"] = chip_match.group(1).upper()
            info["chip_variant"] = chip_match.group(2).upper()
        else:
            info["chip_family"] = chip_full.upper()
        
        log.debug(f"Parsed MCU info: {info}")
        return info
    
    # Pattern 2: Direct chip name (RP2040, SAMD51, etc.)
    # Example: "RP2040", "SAMD51P19A"
    if description.upper().startswith("RP20"):
        info["chip_family"] = "RP2040" if "2040" in description else "RP2350"
        info["board_name"] = mcu.board_id or "RP2040_BOARD"
        log.debug(f"Parsed RP2040 info: {info}")
        return info
    
    # Pattern 3: SAMD chips
    samd_match = re.match(r"^(SAMD\d+)([A-Z]\d+[A-Z]?).*$", description, re.IGNORECASE)
    if samd_match:
        info["chip_family"] = samd_match.group(1).upper()
        info["chip_variant"] = samd_match.group(2).upper()
        info["board_name"] = mcu.board_id or "SAMD_BOARD"
        log.debug(f"Parsed SAMD info: {info}")
        return info
    
    # Fallback: Use CPU and port information
    if mcu.cpu:
        cpu_upper = mcu.cpu.upper()
        if cpu_upper.startswith("STM32"):
            info["chip_family"] = cpu_upper
        elif "RP2040" in cpu_upper:
            info["chip_family"] = "RP2040"
        elif "SAMD" in cpu_upper:
            info["chip_family"] = cpu_upper
        else:
            info["chip_family"] = cpu_upper
    
    info["board_name"] = mcu.board_id or "UNKNOWN_BOARD"
    
    log.debug(f"Fallback MCU info: {info}")
    return info


# =============================================================================
# pyOCD Target Discovery
# =============================================================================

@lru_cache(maxsize=1)
def get_pyocd_targets() -> Dict[str, Dict[str, str]]:
    """
    Get all available pyOCD targets using comprehensive discovery.
    
    Returns:
        Dictionary mapping target_name -> {vendor, part_number, source}
        
    Raises:
        MPFlashError: If pyOCD is not available or discovery fails
    """
    _ensure_pyocd()
    targets = {}
    
    # Try API-based approach first (fast, but may miss pack targets)
    try:
        from pyocd.target import BUILTIN_TARGETS as TARGET_CLASSES
        
        for target_name, target_class in TARGET_CLASSES.items():
            try:
                if hasattr(target_class, 'VENDOR'):
                    vendor = getattr(target_class, 'VENDOR', 'Unknown')
                    part_number = getattr(target_class, '__name__', target_name)
                else:
                    vendor = getattr(target_class, 'vendor', 'Unknown')
                    part_number = getattr(target_class, 'part_number', target_name)
                
                targets[target_name] = {
                    "vendor": vendor,
                    "part_number": part_number,
                    "source": 'builtin'
                }
            except Exception as e:
                log.debug(f"Skipped target {target_name}: {e}")
                continue
        
        log.debug(f"API method loaded {len(targets)} built-in targets")
        
    except Exception as api_error:
        log.debug(f"API-based target discovery failed: {api_error}")
    
    # Use subprocess to get complete target list including pack targets
    # This is more reliable for getting all available targets
    try:
        result = _run_pyocd_command(['list', '--targets'], timeout=30)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            subprocess_targets = {}
            
            # Parse the table output (skip header and separator)
            for line in lines[2:]:
                line = line.strip()
                if not line:
                    continue
                
                # Split on multiple spaces to handle table format
                parts = re.split(r'\s{2,}', line)
                if len(parts) >= 5:
                    target_name = parts[0].strip()
                    vendor = parts[1].strip()
                    part_number = parts[2].strip()
                    source = parts[4].strip()
                    
                    subprocess_targets[target_name] = {
                        "vendor": vendor,
                        "part_number": part_number,
                        "source": source
                    }
            
            # Merge subprocess results (subprocess is authoritative)
            if len(subprocess_targets) > len(targets):
                targets = subprocess_targets
                log.debug(f"Subprocess method loaded {len(targets)} total targets")
            else:
                # Supplement API results with any pack targets from subprocess
                pack_targets = {k: v for k, v in subprocess_targets.items() 
                              if v['source'] == 'pack' and k not in targets}
                targets.update(pack_targets)
                log.debug(f"Added {len(pack_targets)} pack targets from subprocess")
        
    except Exception as subprocess_error:
        log.debug(f"Subprocess target discovery failed: {subprocess_error}")
    
    log.debug(f"Loaded {len(targets)} pyOCD targets total")
    return targets


# =============================================================================
# Fuzzy Target Matching
# =============================================================================

def fuzzy_match_target(mcu_info: Dict[str, str], pyocd_targets: Dict[str, Dict[str, str]]) -> Optional[str]:
    """
    Find the best matching pyOCD target using fuzzy string matching.
    
    Args:
        mcu_info: Parsed MCU information
        pyocd_targets: Available pyOCD targets
        
    Returns:
        Best matching pyOCD target name or None
    """
    from difflib import SequenceMatcher
    
    chip_family = mcu_info.get("chip_family", "").upper()
    chip_variant = mcu_info.get("chip_variant", "").upper()
    port = mcu_info.get("port", "").lower()
    
    if not chip_family:
        log.debug("No chip family found for fuzzy matching")
        return None
    
    log.debug(f"Fuzzy matching for chip: {chip_family}{chip_variant}, port: {port}")
    
    best_match = None
    best_score = 0.0
    matches = []
    
    for target_name, target_info in pyocd_targets.items():
        target_lower = target_name.lower()
        part_number = target_info.get("part_number", "").upper()
        
        # Calculate similarity scores
        scores = []
        
        # 1. Direct chip family match
        if chip_family.lower() in target_lower:
            family_score = 1.0
        else:
            family_score = SequenceMatcher(None, chip_family.lower(), target_lower).ratio()
        scores.append(("family", family_score * 0.5))
        
        # 2. Part number match (if available)
        if part_number and chip_family in part_number:
            part_score = 1.0
        elif part_number:
            part_score = SequenceMatcher(None, chip_family, part_number).ratio()
        else:
            part_score = 0.0
        scores.append(("part", part_score * 0.3))
        
        # 3. Port/platform match
        port_score = 0.0
        if port == "stm32" and target_lower.startswith("stm32"):
            port_score = 0.2
        elif port == "rp2" and "rp20" in target_lower:
            port_score = 0.2
        elif port == "samd" and "samd" in target_lower:
            port_score = 0.2
        scores.append(("port", port_score))
        
        # Calculate total score
        total_score = sum(score for _, score in scores)
        
        if total_score > 0.6:  # Minimum threshold for reliable matches
            matches.append((target_name, total_score, scores))
            
            if total_score > best_score:
                best_score = total_score
                best_match = target_name
    
    # Log matching results for debugging
    if matches:
        log.debug("Target matching results:")
        for target, score, detailed_scores in sorted(matches, key=lambda x: x[1], reverse=True)[:5]:
            detail_str = ", ".join(f"{name}:{score:.2f}" for name, score in detailed_scores)
            log.debug(f"  {target}: {score:.3f} ({detail_str})")
    
    if best_match:
        log.info(f"Best target match: {best_match} (score: {best_score:.3f})")
    else:
        log.debug("No suitable target match found")
    
    return best_match


# =============================================================================
# CMSIS Pack Management
# =============================================================================

def auto_install_pack_for_target(chip_family: str) -> bool:
    """
    Automatically find and install CMSIS pack for a missing target.
    
    Args:
        chip_family: The chip family to search for (e.g., "STM32H563", "STM32F429")
        
    Returns:
        True if a pack was found and installed, False otherwise
    """
    try:
        log.info(f"Searching for CMSIS pack containing {chip_family}")
        
        # Basic validation: chip_family should be alphanumeric
        if not chip_family or not re.match(r'^[A-Z0-9]+$', chip_family, re.IGNORECASE):
            log.warning(f"Invalid chip family format: {chip_family}")
            return False
        
        # Search for packs containing the target
        result = _run_pyocd_command(['pack', 'find', chip_family], timeout=60)
        
        if result.returncode != 0:
            log.debug(f"Pack search failed: {result.stderr}")
            return False
        
        # Parse the output to find suitable packs
        lines = result.stdout.strip().split('\n')
        packs_to_install = set()
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('Part') or line.startswith('-'):
                continue
            
            # Parse pack info line
            parts = re.split(r'\s{2,}', line)
            if len(parts) >= 4:
                part_number = parts[0].strip()
                vendor = parts[1].strip()
                pack_name = parts[2].strip()
                installed = parts[4].strip().lower() if len(parts) > 4 else 'false'
                
                # Check if this part matches our chip family and isn't installed
                if (chip_family.upper() in part_number.upper() and 
                    installed == 'false' and 
                    pack_name not in packs_to_install):
                    packs_to_install.add(pack_name)
        
        if not packs_to_install:
            log.debug(f"No uninstalled packs found for {chip_family}")
            return False
        
        # Install the first suitable pack (usually the most relevant)
        pack_to_install = list(packs_to_install)[0]
        log.info(f"Installing CMSIS pack: {pack_to_install}")
        
        install_result = _run_pyocd_command(['pack', 'install', chip_family], timeout=300)
        
        if install_result.returncode == 0:
            log.info(f"Successfully installed pack for {chip_family}")
            
            # Clear the target cache so new targets are discovered
            if hasattr(get_pyocd_targets, 'cache_clear'):
                get_pyocd_targets.cache_clear()
                log.debug("Cleared target cache after pack installation")
            
            return True
        else:
            log.debug(f"Pack installation failed: {install_result.stderr}")
            return False
        
    except subprocess.TimeoutExpired:
        log.warning(f"Pack installation for {chip_family} timed out")
        return False
    except Exception as e:
        log.debug(f"Auto pack installation failed: {e}")
        return False


# =============================================================================
# Main Target Detection API
# =============================================================================

# Simple cache to avoid redundant target detection for the same board
_target_cache = {}

def detect_pyocd_target(mcu: MPRemoteBoard, auto_install_packs: bool = True) -> Optional[str]:
    """
    Detect pyOCD target type for a connected MCU with automatic pack installation.
    
    Args:
        mcu: Connected MPRemoteBoard instance
        auto_install_packs: If True, automatically install missing CMSIS packs
        
    Returns:
        pyOCD target type string or None if no match found
        
    Examples:
        >>> mcu.description = "NUCLEO-WB55 with STM32WB55RGV6"
        >>> detect_pyocd_target(mcu)
        'stm32wb55xg'
    """
    # Create cache key from board_id and chip info
    cache_key = f"{mcu.board_id}_{mcu.cpu}_{getattr(mcu, 'port', '')}"
    
    # Check cache first
    if cache_key in _target_cache:
        log.debug(f"Using cached target for {mcu.board_id}: {_target_cache[cache_key]}")
        return _target_cache[cache_key]
    
    try:
        # Parse MCU information for fuzzy matching
        mcu_info = parse_mcu_info(mcu)
        chip_family = mcu_info.get('chip_family', '')
        
        # Get available targets and try fuzzy matching
        pyocd_targets = get_pyocd_targets()
        target = fuzzy_match_target(mcu_info, pyocd_targets)
        
        if target:
            log.debug(f"Target detection: {mcu.board_id} -> {target}")
            _target_cache[cache_key] = target
            return target
        
        # No target found - try automatic pack installation if enabled
        if auto_install_packs and chip_family:
            log.info(f"No pyOCD target found for {chip_family}, attempting automatic pack installation")
            
            pack_installed = auto_install_pack_for_target(chip_family)
            if pack_installed:
                # Retry target detection with updated pack targets
                log.info("Retrying target detection after pack installation")
                pyocd_targets = get_pyocd_targets()  # Refresh target list
                target = fuzzy_match_target(mcu_info, pyocd_targets)
                
                if target:
                    log.info(f"Target found after pack installation: {mcu.board_id} -> {target}")
                    _target_cache[cache_key] = target
                    return target
                else:
                    log.warning(f"Still no target found for {chip_family} after pack installation")
            else:
                log.debug(f"Automatic pack installation failed for {chip_family}")
        
        log.debug(f"No target found for {mcu.board_id} ({chip_family})")
        _target_cache[cache_key] = None
        return None
        
    except Exception as e:
        log.debug(f"Target detection failed: {e}")
        _target_cache[cache_key] = None
        return None


def is_pyocd_supported(mcu: MPRemoteBoard) -> bool:
    """
    Check if MCU is supported by pyOCD.
    
    Args:
        mcu: MPRemoteBoard instance
        
    Returns:
        True if pyOCD can program this MCU
    """
    return detect_pyocd_target(mcu, auto_install_packs=False) is not None


def get_unsupported_reason(mcu: MPRemoteBoard) -> str:
    """
    Get actionable reason why MCU is not supported by pyOCD.
    
    Args:
        mcu: MPRemoteBoard instance
        
    Returns:
        Human-readable reason string with suggested actions
    """
    mcu_info = parse_mcu_info(mcu)
    chip_family = mcu_info.get("chip_family", "Unknown")
    port = mcu_info.get("port", "unknown")
    
    if port in ["esp32", "esp8266"]:
        return (
            f"ESP32/ESP8266 use Xtensa/RISC-V cores, not Cortex-M. "
            f"Use 'mpflash flash --method esptool' instead of pyOCD."
        )
    elif chip_family.startswith("STM32"):
        return (
            f"STM32 variant {chip_family} not found in pyOCD targets. "
            f"Try: 1) Enable pack installation with --auto-install-packs, "
            f"2) Run 'pyocd pack find {chip_family}' to search for CMSIS packs, "
            f"3) Check pyOCD version with 'pyocd --version'."
        )
    elif chip_family.startswith("SAMD"):
        return (
            f"SAMD variant {chip_family} not found in pyOCD targets. "
            f"Try: 1) Enable pack installation with --auto-install-packs, "
            f"2) Run 'pyocd pack find {chip_family}' to search for CMSIS packs, "
            f"3) Check if Microchip CMSIS packs are available."
        )
    elif chip_family.startswith("RP20"):
        return (
            f"RP2040/RP2350 not supported. "
            f"Try: 1) Update pyOCD to latest version, "
            f"2) Use UF2 bootloader instead: 'mpflash flash --method uf2', "
            f"3) Check if target is in bootloader mode."
        )
    else:
        return (
            f"MCU {chip_family} ({port}) not supported by pyOCD. "
            f"Supported architectures: ARM Cortex-M (STM32, SAMD, LPC, etc.). "
            f"Run 'pyocd list --targets' to see all supported targets."
        )


# =============================================================================
# Cache Management
# =============================================================================

@dataclass(frozen=True)
class MCUIdentifier:
    """Immutable MCU identifier for caching target lookups."""
    board_id: str
    cpu: str
    description: str
    port: str
    
    @classmethod
    def from_mcu(cls, mcu: MPRemoteBoard) -> 'MCUIdentifier':
        """Create identifier from MPRemoteBoard instance."""
        return cls(
            board_id=mcu.board_id or "unknown",
            cpu=mcu.cpu or "unknown", 
            description=mcu.description or "unknown",
            port=mcu.port or "unknown"
        )


@lru_cache(maxsize=128)
def cached_target_lookup(mcu_id: MCUIdentifier) -> Optional[str]:
    """Cached version of target lookup for performance."""
    # Create minimal MCU-like object for parsing
    class MCUProxy:
        def __init__(self, mcu_id: MCUIdentifier):
            self.board_id = mcu_id.board_id
            self.cpu = mcu_id.cpu
            self.description = mcu_id.description
            self.port = mcu_id.port
    
    proxy = MCUProxy(mcu_id)
    return detect_pyocd_target(proxy, auto_install_packs=False)
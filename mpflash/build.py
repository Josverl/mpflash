"""
MicroPython build integration for mpflash.

This module provides integration with mpbuild to build MicroPython firmware
locally, generating all required formats (.dfu, .hex, .bin, .elf) for any
flash method.
"""

import hashlib
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any
import tempfile
import shutil

from loguru import logger as log

from mpflash.config import config
from mpflash.errors import MPFlashError
from mpflash.db.core import Session
from mpflash.db.models import Board, Firmware


class BuildManager:
    """Manages MicroPython firmware builds with caching."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize BuildManager with cache directory.
        
        Args:
            cache_dir: Directory for build cache. Defaults to config.firmware_folder/builds
        """
        self.cache_dir = cache_dir or (config.firmware_folder / "builds")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def get_or_build(self, board: str, version: str = "latest", force: bool = False) -> List[Path]:
        """
        Get firmware files for board, building if necessary.
        
        Args:
            board: Board name (e.g., "NUCLEO_H563ZI", "RPI_PICO")
            version: MicroPython version to build (default: "latest")
            force: Force rebuild even if cached version exists
            
        Returns:
            List of paths to generated firmware files
            
        Raises:
            MPFlashError: If mpbuild not available, Docker issues, or build fails
        """
        log.info(f"Getting firmware for {board} version {version}")
        
        # Check cache first
        if not force:
            cached_files = self._find_cached(board, version)
            if cached_files:
                log.info(f"Using cached build for {board} ({len(cached_files)} files)")
                return cached_files
        
        # Validate dependencies
        self._ensure_mpbuild_available()
        self._check_docker_available()
        
        # Build firmware
        log.info(f"Building MicroPython firmware for {board} (this may take 5-30 minutes)")
        return self._build_firmware(board, version)
    
    def _find_cached(self, board: str, version: str) -> List[Path]:
        """Find cached firmware files for board and version."""
        cache_key = self._cache_key(board, version)
        cache_path = self.cache_dir / cache_key
        
        if not cache_path.exists():
            return []
        
        # Find all firmware files in cache directory
        firmware_files = []
        for pattern in ["*.dfu", "*.hex", "*.bin", "*.elf"]:
            firmware_files.extend(cache_path.glob(pattern))
        
        if firmware_files:
            log.debug(f"Found {len(firmware_files)} cached firmware files for {board}")
            return firmware_files
        
        return []
    
    def _cache_key(self, board: str, version: str) -> str:
        """Generate cache key for board and version."""
        # Use board and version to create deterministic cache key
        key_data = f"{board}_{version}".encode()
        return hashlib.md5(key_data).hexdigest()[:12]
    
    def _ensure_mpbuild_available(self) -> None:
        """Ensure mpbuild is available as a dependency."""
        try:
            import mpbuild
            log.debug(f"mpbuild available: {mpbuild.__version__ if hasattr(mpbuild, '__version__') else 'unknown version'}")
        except ImportError:
            raise MPFlashError(
                "mpbuild is not installed. Install with: uv sync --extra build\n"
                "Note: mpbuild requires Docker to build MicroPython firmware."
            )
        except TypeError as e:
            if "unsupported operand type(s) for |" in str(e):
                raise MPFlashError(
                    "mpbuild requires Python 3.10 or newer (current: Python 3.9).\n"
                    "The --build flag is not available on this Python version."
                )
            else:
                raise MPFlashError(f"Error importing mpbuild: {e}")
    
    def _check_docker_available(self) -> None:
        """Check if Docker is available and running."""
        try:
            result = subprocess.run(
                ["docker", "--version"], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            if result.returncode != 0:
                raise MPFlashError("Docker command failed. Please ensure Docker is installed and running.")
                
            log.debug(f"Docker available: {result.stdout.strip()}")
            
        except FileNotFoundError:
            raise MPFlashError(
                "Docker not found. mpbuild requires Docker to build MicroPython firmware.\n"
                "Install Docker: https://docs.docker.com/get-docker/"
            )
        except subprocess.TimeoutExpired:
            raise MPFlashError("Docker command timed out. Please check Docker installation.")
    
    def _build_firmware(self, board: str, version: str) -> List[Path]:
        """Build firmware using mpbuild and cache results."""
        from mpbuild.build import build_board
        from mpbuild import find_mpy_root
        
        # Create temporary directory for build
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            try:
                # Call mpbuild to build firmware
                log.info(f"Starting mpbuild for {board}...")
                
                # mpbuild.build_board() builds firmware and writes to build dir
                # We need to find or clone a MicroPython repo first
                try:
                    mpy_root, _ = find_mpy_root()
                    log.debug(f"Using MicroPython repository at {mpy_root}")
                except Exception as e:
                    raise MPFlashError(f"Could not find MicroPython repository: {e}")
                
                # Build the firmware - this modifies the source tree
                log.info(f"Building {board} firmware (this may take several minutes)...")
                build_board(board, mpy_dir=mpy_root)
                
                # Find build output in the MicroPython repository
                build_output = self._find_build_output_in_repo(mpy_root, board)
                
                # Scan for firmware files
                firmware_files = self._scan_build_output(build_output, board)
                
                if not firmware_files:
                    raise MPFlashError(f"No firmware files generated for {board}")
                
                # Cache the results
                cached_files = self._cache_build_output(firmware_files, board, version)
                
                log.info(f"Build complete! Generated {len(cached_files)} firmware files")
                return cached_files
                
            except Exception as e:
                if isinstance(e, MPFlashError):
                    raise
                raise MPFlashError(f"Build failed for {board}: {e}")
    
    def _find_build_output(self, search_dir: Path, board: str) -> Path:
        """Find build output directory when mpbuild doesn't return it directly."""
        # Common MicroPython build output locations
        possible_paths = [
            search_dir / "build",
            search_dir / f"build-{board}",
            search_dir / "ports" / "stm32" / "build",
            search_dir / "ports" / "rp2" / "build",
        ]
        
        for path in possible_paths:
            if path.exists():
                return path
        
        # Fallback: search for any firmware files recursively
        for pattern in ["*.dfu", "*.hex", "*.bin", "*.elf"]:
            files = list(search_dir.glob(f"**/{pattern}"))
            if files:
                return files[0].parent
        
        raise MPFlashError(f"Could not locate build output for {board}")
    
    def _find_build_output_in_repo(self, mpy_root: Path, board: str) -> Path:
        """Find build output directory in MicroPython repository after build."""
        # Common MicroPython build output locations based on port
        possible_paths = [
            mpy_root / "ports" / "stm32" / "build" / f"BOARD_{board}",
            mpy_root / "ports" / "stm32" / "build" / board,
            mpy_root / "ports" / "rp2" / "build" / f"BOARD_{board}",
            mpy_root / "ports" / "rp2" / "build" / board,
            mpy_root / "ports" / "esp32" / "build" / board,
            mpy_root / "ports" / "esp8266" / "build" / board,
            mpy_root / "ports" / "samd" / "build" / board,
        ]
        
        for path in possible_paths:
            if path.exists():
                log.debug(f"Found build output at {path}")
                return path
        
        # Fallback: search for any firmware files recursively in ports
        ports_dir = mpy_root / "ports"
        for pattern in ["*.dfu", "*.hex", "*.bin", "*.elf"]:
            files = list(ports_dir.glob(f"**/build*/**/{pattern}"))
            if files:
                log.debug(f"Found firmware files at {files[0].parent}")
                return files[0].parent
        
        raise MPFlashError(f"Could not locate build output for {board} in {mpy_root}")
    
    def _scan_build_output(self, build_output, board: str) -> List[Path]:
        """Scan build output for firmware files."""
        firmware_files = []
        
        if isinstance(build_output, list):
            # Direct list of files
            firmware_files = [Path(f) for f in build_output if Path(f).suffix in ['.dfu', '.hex', '.bin', '.elf']]
        else:
            # Directory to scan
            build_dir = Path(build_output)
            for pattern in ["*.dfu", "*.hex", "*.bin", "*.elf"]:
                firmware_files.extend(build_dir.glob(f"**/{pattern}"))
        
        # Filter to likely firmware files (exclude intermediate build artifacts)
        valid_files = []
        for file_path in firmware_files:
            # Skip obvious intermediate files
            if any(skip in file_path.name.lower() for skip in ['test', 'debug', 'bootloader']):
                continue
            # Include likely firmware files
            if any(include in file_path.name.lower() for include in [board.lower(), 'firmware', 'micropython']):
                valid_files.append(file_path)
        
        return valid_files or firmware_files  # Fallback to all if filtering removes everything
    
    def _cache_build_output(self, firmware_files: List[Path], board: str, version: str) -> List[Path]:
        """Copy build output to cache and return cached file paths."""
        cache_key = self._cache_key(board, version)
        cache_path = self.cache_dir / cache_key
        cache_path.mkdir(parents=True, exist_ok=True)
        
        cached_files = []
        for firmware_file in firmware_files:
            # Generate descriptive filename for cache
            suffix = firmware_file.suffix
            cached_name = f"{board}-{version}{suffix}"
            cached_file = cache_path / cached_name
            
            # Copy to cache
            shutil.copy2(firmware_file, cached_file)
            cached_files.append(cached_file)
            log.debug(f"Cached {firmware_file.name} as {cached_file}")
        
        return cached_files


def is_build_available() -> bool:
    """Check if build functionality is available (mpbuild + Docker)."""
    try:
        BuildManager()._ensure_mpbuild_available()
        BuildManager()._check_docker_available()
        return True
    except MPFlashError:
        return False


def get_build_unavailable_reason() -> str:
    """Get the specific reason why build functionality is unavailable."""
    try:
        BuildManager()._ensure_mpbuild_available()
        BuildManager()._check_docker_available()
        return ""  # Build is available
    except MPFlashError as e:
        return str(e)


def build_firmware(board: str, version: str = "latest", force: bool = False) -> List[Path]:
    """
    Convenience function to build firmware for a board.
    
    Args:
        board: Board name (e.g., "NUCLEO_H563ZI")
        version: MicroPython version (default: "latest")
        force: Force rebuild even if cached
        
    Returns:
        List of paths to generated firmware files
    """
    build_manager = BuildManager()
    return build_manager.get_or_build(board, version, force)


def import_firmware_to_database(firmware_files: List[Path], board_id: str, version: str, port: str = "") -> int:
    """
    Import built firmware files into mpflash database.
    
    Args:
        firmware_files: List of firmware file paths to import
        board_id: Board identifier (e.g., "NUCLEO_H563ZI")
        version: Firmware version (e.g., "v1.26.0", "latest")
        port: Board port type (e.g., "stm32", "rp2") - auto-detected if not provided
        
    Returns:
        Number of firmware files imported
        
    Raises:
        MPFlashError: If database operations fail
    """
    if not firmware_files:
        return 0
    
    log.debug(f"Importing {len(firmware_files)} firmware files for {board_id} into database")
    
    # Auto-detect port from board_id if not provided
    if not port:
        port = _detect_port_from_board_id(board_id)
    
    imported_count = 0
    
    try:
        with Session() as session:
            # Ensure board exists in database
            board = Board(
                board_id=board_id,
                version=version,
                board_name=board_id,  # Use board_id as name for built firmware
                mcu="Unknown",  # Will be detected when flashed
                variant="",
                port=port,
                path="built",  # Mark as built locally
                description=f"Locally built MicroPython firmware for {board_id}",
                family="micropython",
                custom=True,  # Mark as custom since it's locally built
            )
            session.merge(board)
            
            # Add firmware entries
            for fw_file in firmware_files:
                # Make path relative to firmware folder for storage
                try:
                    relative_path = fw_file.relative_to(config.firmware_folder)
                except ValueError:
                    # If file is not under firmware folder, use absolute path
                    relative_path = fw_file
                
                firmware = Firmware(
                    board_id=board_id,
                    version=version,
                    firmware_file=str(relative_path),
                    source="mpbuild",  # Mark source as mpbuild
                    build=0,  # No build number for local builds
                    custom=True,  # Mark as custom
                    port=port,
                    description=f"Built locally with mpbuild ({fw_file.suffix})",
                )
                session.merge(firmware)
                imported_count += 1
                log.debug(f"Imported firmware: {fw_file.name} -> {relative_path}")
            
            session.commit()
            
    except Exception as e:
        raise MPFlashError(f"Failed to import firmware to database: {e}")
    
    log.info(f"Successfully imported {imported_count} firmware files for {board_id}")
    return imported_count


def _detect_port_from_board_id(board_id: str) -> str:
    """
    Auto-detect port type from board ID.
    
    Args:
        board_id: Board identifier
        
    Returns:
        Detected port type
    """
    board_lower = board_id.lower()
    
    if any(prefix in board_lower for prefix in ["stm32", "nucleo", "disco", "eval"]):
        return "stm32"
    elif any(prefix in board_lower for prefix in ["rpi_pico", "pico", "rp2040", "rp2350"]):
        return "rp2"
    elif any(prefix in board_lower for prefix in ["esp32", "esp8266"]):
        return "esp32" if "esp32" in board_lower else "esp8266"
    elif any(prefix in board_lower for prefix in ["samd", "metro", "feather"]):
        return "samd"
    else:
        log.warning(f"Could not detect port for board {board_id}, using 'unknown'")
        return "unknown"
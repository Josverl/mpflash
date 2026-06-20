"""
MicroPython build integration for mpflash.

This module provides integration with mpbuild to build MicroPython firmware
locally, generating all required formats (.dfu, .hex, .bin, .elf) for any
flash method.
"""

import hashlib
import peewee
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Set

from loguru import logger as log

from mpflash.config import config
from mpflash.errors import MPFlashError
from mpflash.db.models import Board, Firmware, database


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

    def get_or_build(
        self,
        board: str,
        version: str = "latest",
        force: bool = False,
        preferred_suffixes: Optional[Set[str]] = None,
    ) -> List[Path]:
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
            cached_files = self._find_cached(board, version, preferred_suffixes)
            if cached_files:
                log.info(f"Using cached build for {board} ({len(cached_files)} files)")
                return cached_files

        # Validate dependencies
        self._ensure_mpbuild_available()
        self._check_docker_available()

        # Build firmware
        log.info(f"Building MicroPython firmware for {board} (this may take 5-30 minutes)")
        return self._build_firmware(board, version, preferred_suffixes)

    def _find_cached(
        self,
        board: str,
        version: str,
        preferred_suffixes: Optional[Set[str]] = None,
    ) -> List[Path]:
        """Find cached firmware files for board and version."""
        cache_key = self._cache_key(board, version)
        cache_path = self.cache_dir / cache_key

        if not cache_path.exists():
            return []

        # Find all firmware files in cache directory
        firmware_files = []
        for pattern in ["*.dfu", "*.hex", "*.bin", "*.elf"]:
            firmware_files.extend(cache_path.glob(pattern))

        if preferred_suffixes:
            allowed = {s.lower() for s in preferred_suffixes}
            firmware_files = [f for f in firmware_files if f.suffix.lower() in allowed]

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
            result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=10)
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

    def _build_firmware(
        self,
        board: str,
        version: str,
        preferred_suffixes: Optional[Set[str]] = None,
    ) -> List[Path]:
        """Build firmware using mpbuild and cache results."""
        from mpbuild.build import build_board
        from mpbuild.find_boards import find_mpy_root

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
                except SystemExit:
                    raise MPFlashError(
                        "Could not find a MicroPython repository. Set MICROPY_DIR or run mpbuild from within a MicroPython checkout."
                    )
                except Exception as e:
                    raise MPFlashError(f"Could not find MicroPython repository: {e}")

                build_board_name, build_variant = _split_board_variant(board)

                # Build the firmware - this modifies the source tree
                log.info(f"Building {board} firmware (this may take several minutes)...")
                build_board(build_board_name, variant=build_variant, mpy_dir=mpy_root)

                # Find build output in the MicroPython repository.
                board_port = _detect_port_from_board_id(board)
                lookup_port = board_port if board_port != "unknown" else None

                # Determine fallback extension order if preferred_suffixes not specified
                fallback_suffixes = preferred_suffixes or get_port_preferred_suffixes(board_port) or {""}

                firmware_files = self._find_firmware_files_in_repo(
                    mpy_root,
                    build_board_name,
                    build_variant,
                    port=lookup_port,
                    preferred_suffixes=fallback_suffixes,
                )
                log.debug(f"Found {len(firmware_files)} firmware files: {[f.name for f in firmware_files]}")

                if not firmware_files:
                    raise MPFlashError(f"No firmware files generated for {board}")

                # Filter by backend/port-required formats before caching/importing.
                if preferred_suffixes:
                    allowed = {s.lower() for s in preferred_suffixes}
                    filtered_files = [f for f in firmware_files if f.suffix.lower() in allowed]
                    if filtered_files:
                        firmware_files = filtered_files
                        log.debug(f"Filtered build output for {board} to {len(firmware_files)} file(s) with suffixes {sorted(allowed)}")

                repo_relative_files = []
                for fw in firmware_files:
                    try:
                        repo_relative_files.append(str(fw.relative_to(mpy_root)))
                    except ValueError:
                        repo_relative_files.append(str(fw))

                if repo_relative_files:
                    log.info(
                        "Build output firmware file(s): "
                        + ", ".join(sorted(repo_relative_files))
                    )

                # Cache the results
                cached_files = self._cache_build_output(
                    firmware_files,
                    board,
                    version,
                    preferred_suffixes,
                )

                log.info(f"Build complete! Generated {len(cached_files)} firmware files")
                return cached_files

            except Exception as e:
                if isinstance(e, MPFlashError):
                    raise
                raise MPFlashError(f"Build failed for {board}: {e}")

    def clean(self, board: str) -> None:
        """Clean a board build directory using mpbuild clean."""
        from mpbuild.build import clean_board
        from mpbuild.find_boards import find_mpy_root

        self._ensure_mpbuild_available()
        self._check_docker_available()

        try:
            try:
                mpy_root, _ = find_mpy_root()
                log.debug(f"Using MicroPython repository at {mpy_root}")
            except SystemExit:
                raise MPFlashError(
                    "Could not find a MicroPython repository. Set MICROPY_DIR or run mpbuild from within a MicroPython checkout."
                )

            board_name, variant = _split_board_variant(board)
            log.info(f"Cleaning firmware build tree for {board}")
            clean_board(board_name, variant=variant, mpy_dir=str(mpy_root))
        except Exception as e:
            if isinstance(e, MPFlashError):
                raise
            raise MPFlashError(f"Build clean failed for {board}: {e}")

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

        raise MPFlashError(f"Could not locate build output for {board}")

    def _find_firmware_files_in_repo(
        self,
        mpy_root: Path,
        board: str,
        variant: Optional[str] = None,
        port: Optional[str] = None,
        preferred_suffixes: Optional[Set[str]] = None,
    ) -> List[Path]:
        """Find firmware files in MicroPython repository build output with precision.

        Builds deterministic path from port/board/variant, searches for preferred
        extensions in order, with minimal fallback only if primary location is missing.

        Args:
            mpy_root: Root of MicroPython repository
            board: Board name (e.g., "RPI_PICO2")
            variant: Optional variant suffix (e.g., "RISCV")
            port: MicroPython port (e.g., "rp2")
            preferred_suffixes: Set of preferred file extensions (e.g., {".uf2", ".bin"})

        Returns:
            List of firmware file paths found

        Raises:
            MPFlashError: If no firmware files found
        """
        if not port or port == "unknown":
            raise MPFlashError(f"Cannot determine build path: port '{port}' is not specific enough")

        ports_root = mpy_root / "ports"

        # Build canonical path from port, board, and variant
        board_variant_id = f"{board}-{variant}" if variant else board
        canonical_path = ports_root / port / f"build-{board_variant_id}"

        log.debug(f"Looking for firmware in: {canonical_path}")

        # Search for files with preferred extensions in canonical location
        firmware_files = []
        if canonical_path.exists():
            # Prefer ordered extensions: define canonical priority order
            # (more specific/common formats first)
            extension_priority = [".uf2", ".bin", ".dfu", ".hex", ".elf"]
            if preferred_suffixes:
                # Filter priority list to only preferred suffixes
                ordered_suffixes = [ext for ext in extension_priority if ext.lower() in {s.lower() for s in preferred_suffixes}]
                # Search in priority order
                for suffix in ordered_suffixes:
                    found = list(canonical_path.glob(f"*{suffix}"))
                    # Deduplicate and filter to actual files with matching suffix
                    valid = list(set(f for f in found if f.is_file() and f.suffix.lower() == suffix.lower()))
                    if valid:
                        firmware_files.extend(valid)
                        break

            # Fallback: any firmware fil   e in canonical path
            if not firmware_files:
                for pattern in ["*.uf2", "*.bin", "*.dfu", "*.hex", "*.elf"]:
                    found = list(canonical_path.glob(pattern))
                    firmware_files.extend([f for f in found if f.is_file()])
                    if firmware_files:
                        break

            if firmware_files:
                log.debug(f"Found {len(firmware_files)} firmware file(s) at {canonical_path}")
                return firmware_files

        # Minimal fallback: check alternative paths only if canonical doesn't exist
        # Try without variant
        if variant:
            fallback_path = ports_root / port / f"build-{board}"
            if fallback_path.exists():
                log.debug(f"Canonical path not found, trying fallback: {fallback_path}")
                for pattern in ["*.uf2", "*.bin", "*.dfu", "*.hex", "*.elf"]:
                    found = list(fallback_path.glob(pattern))
                    if found:
                        return found

        # Try ports/{port}/build/{board} layout
        alt_path = ports_root / port / "build" / board_variant_id
        if alt_path.exists():
            log.debug(f"Trying alternative path: {alt_path}")
            for pattern in ["*.uf2", "*.bin", "*.dfu", "*.hex", "*.elf"]:
                found = list(alt_path.glob(pattern))
                if found:
                    return found

        raise MPFlashError(f"Could not locate firmware files for {board_variant_id} in {port} port at {mpy_root}")

    def _cache_build_output(
        self,
        firmware_files: List[Path],
        board: str,
        version: str,
        preferred_suffixes: Optional[Set[str]] = None,
    ) -> List[Path]:
        """Copy build output to cache and return cached file paths."""
        cache_key = self._cache_key(board, version)
        cache_path = self.cache_dir / cache_key
        cache_path.mkdir(parents=True, exist_ok=True)

        cached_files = []
        allowed = {s.lower() for s in preferred_suffixes} if preferred_suffixes else None
        for firmware_file in firmware_files:
            if allowed and firmware_file.suffix.lower() not in allowed:
                continue
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


def build_firmware(
    board: str,
    version: str = "latest",
    force: bool = False,
    preferred_suffixes: Optional[Set[str]] = None,
) -> List[Path]:
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
    return build_manager.get_or_build(board, version, force, preferred_suffixes=preferred_suffixes)


def clean_firmware(board: str) -> None:
    """Convenience function to clean a board build directory."""
    build_manager = BuildManager()
    build_manager.clean(board)


def get_port_preferred_suffixes(port: str) -> Set[str]:
    """Return default firmware suffixes preferred for a target port."""
    return {
        "esp32": {".bin"},
        "esp8266": {".bin"},
        "rp2": {".uf2"},
        "samd": {".uf2"},
        "nrf": {".uf2"},
        "stm32": {".dfu", ".bin"},
    }.get(port, set())


def detect_port_from_board_id(board_id: str) -> str:
    """Public helper to detect MicroPython port from board ID."""
    return _detect_port_from_board_id(board_id)


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
        if database.is_closed():
            database.connect()

        with database.atomic():
            # Ensure board exists in database.
            board_data = {
                "board_id": board_id,
                "version": version,
                "board_name": board_id,
                "mcu": "Unknown",
                "variant": "",
                "port": port,
                "path": "built",
                "description": f"Locally built MicroPython firmware for {board_id}",
                "family": "micropython",
                "custom": True,
            }
            Board.insert(**board_data).on_conflict(
                conflict_target=[Board.board_id, Board.version],
                update=board_data,
            ).execute()

            for fw_file in firmware_files:
                # Store paths relative to the configured firmware folder when possible.
                try:
                    firmware_path = str(fw_file.relative_to(config.firmware_folder))
                except ValueError:
                    firmware_path = str(fw_file)

                firmware_data = {
                    "board_id": board_id,
                    "version": version,
                    "firmware_file": firmware_path,
                    "source": "mpbuild",
                    "build": 0,
                    "custom": True,
                    "port": port,
                    "description": f"Built locally with mpbuild ({fw_file.suffix})",
                }
                Firmware.insert(**firmware_data).on_conflict(
                    conflict_target=[Firmware.board_id, Firmware.version, Firmware.firmware_file],
                    update={
                        "source": firmware_data["source"],
                        "build": firmware_data["build"],
                        "custom": firmware_data["custom"],
                        "port": firmware_data["port"],
                        "description": firmware_data["description"],
                    },
                ).execute()
                imported_count += 1
                log.debug(f"Imported firmware: {fw_file.name} -> {firmware_path}")

    except peewee.PeeweeException as e:
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
    elif any(prefix in board_lower for prefix in ["samd", "metro", "feather", "wio", "seeed"]):
        return "samd"
    else:
        log.warning(f"Could not detect port for board {board_id}, using 'unknown'")
        return "unknown"


def _split_board_variant(board_id: str) -> tuple[str, Optional[str]]:
    """Split board_id into board and optional variant parts."""
    if "-" not in board_id:
        return board_id, None
    board_name, variant = board_id.split("-", 1)
    return board_name, variant or None

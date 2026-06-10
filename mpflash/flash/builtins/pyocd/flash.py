"""
PyOCD flash programming implementation for MPFlash.

This module provides SWD/JTAG flash programming using pyOCD as an alternative
to serial bootloader methods. Includes probe discovery, target detection,
and flash programming operations.

.. note::
    Internal implementation behind
    :class:`mpflash.flash.builtins.pyocd_backend.PyOCDBackend`. Public callers
    should use :func:`mpflash.flash.flash_mcu` with
    ``method=FlashMethod.PYOCD``.
"""

from typing import List, Optional, Dict, Any
from pathlib import Path
import traceback
import sys

from mpflash.common import udev_rules_error_message
from mpflash.logger import log
from mpflash.errors import MPFlashError
from mpflash.mpremoteboard import MPRemoteBoard
from mpflash.flash.builtins.pyocd.probes import DebugProbe
from .core import (
    detect_pyocd_target,
    get_unsupported_reason,
    is_pyocd_available,
    is_pyocd_supported,
)


# Lazy import pyOCD to handle optional dependency
_pyocd_available = None
_pyocd_modules = {}
SUPPORTED_PYOCD_FILE_SUFFIXES = {".bin", ".hex", ".elf", ".axf"}
_last_probe_discovery_error: Optional[str] = None

# Some Renesas RA4M1 boards are unstable at pyOCD's higher default SWD rates.
# Use a conservative default that matches known-good manual pyocd CLI behaviour.
RA4M1_SAFE_SWD_FREQUENCY_HZ = 1_000_000


def _is_linux_usb_permission_error(message: str) -> bool:
    """Return True when an error message looks like Linux USB permission denial."""
    if not message:
        return False
    lower = message.lower()
    tags = (
        "permission denied",
        "access denied",
        "eacces",
        "libusb",
        "could not open usb",
        "usb access",
        "errno 13",
    )
    return any(tag in lower for tag in tags)


def _pyocd_linux_udev_message() -> str:
    """Common Linux udev guidance for pyOCD probe access."""
    return udev_rules_error_message(
        "mpflash.udev_rules",
        "50-cmsis-dap.rules",
        device_label="pyOCD debug probes over USB",
        next_step=(
            "If you use STLink, also copy the STLink rules from the same package "
            "directory (49-stlink*.rules), then reconnect the probe and try again."
        ),
    )


def _pyocd_no_probe_possible_causes() -> str:
    """Short troubleshooting hints when no pyOCD probes are found."""
    return (
        "Possible causes:\n"
        "- Probe is not connected or target is not powered\n"
        "- USB cable is charge-only (no data lines)\n"
        "- Another tool is holding the probe (IDE/debugger/openocd)\n"
        "- Probe firmware/driver is missing or outdated\n"
        "- pyOCD cannot auto-detect this probe/target"
    )


def _ensure_pyocd():
    """Ensure pyOCD modules are imported and available."""
    global _pyocd_available, _pyocd_modules

    if _pyocd_available is None:
        try:
            from pyocd.core.helpers import ConnectHelper
            from pyocd.flash.file_programmer import FileProgrammer
            from pyocd.core.exceptions import Error as PyOCDError
            from pyocd.core.exceptions import TransferError as PyOCDTransferError
            from pyocd.core.exceptions import CoreRegisterAccessError as PyOCDCoreRegisterAccessError

            _pyocd_modules.update(
                {
                    "ConnectHelper": ConnectHelper,
                    "FileProgrammer": FileProgrammer,
                    "PyOCDError": PyOCDError,
                    "PyOCDTransferError": PyOCDTransferError,
                    "PyOCDCoreRegisterAccessError": PyOCDCoreRegisterAccessError,
                }
            )
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
    def discover(cls) -> List["PyOCDProbe"]:
        """Discover all connected pyOCD probes."""
        global _last_probe_discovery_error
        try:
            modules = _ensure_pyocd()
            ConnectHelper = modules["ConnectHelper"]

            pyocd_probes = ConnectHelper.get_all_connected_probes(blocking=False)
            probes = []

            for pyocd_probe in pyocd_probes:
                probe = cls(unique_id=pyocd_probe.unique_id, description=pyocd_probe.description, pyocd_probe_obj=pyocd_probe)
                probes.append(probe)

            log.debug(f"Discovered {len(probes)} pyOCD probes")
            for probe in probes:
                log.debug(f"Probe: id={probe.unique_id}, description={probe.description}")
            _last_probe_discovery_error = None
            return probes

        except Exception as e:
            _last_probe_discovery_error = str(e)
            log.debug(f"Failed to discover pyOCD probes: {e}")
            return []

    def connect(
        self,
        target_type: Optional[str] = None,
        frequency: int = 4_000_000,
        connect_mode: Optional[str] = "under-reset",
    ) -> bool:
        """Connect to the pyOCD probe.

        connect_mode defaults to 'under-reset' which is required by most
        STM32 boards already running MicroPython firmware (otherwise the
        STLink fails to read IDCODE).
        """
        if self._connected:
            return True

        modules = _ensure_pyocd()
        ConnectHelper = modules["ConnectHelper"]

        modes = [connect_mode, "halt", "attach", "pre-reset"]
        attempted = []
        seen = set()
        last_error: Optional[Exception] = None

        for mode in modes:
            if mode in seen:
                continue
            seen.add(mode)
            attempted.append(mode)

            session_options: Dict[str, Any] = {"auto_unlock": True}
            if mode is not None:
                session_options["connect_mode"] = mode
            if target_type:
                session_options["target_override"] = target_type
            if frequency > 0:
                session_options["frequency"] = frequency

            try:
                log.debug(
                    f"Opening pyOCD session for probe {self.unique_id} with options: {session_options}"
                )
                self._session = ConnectHelper.session_with_chosen_probe(
                    unique_id=self.unique_id,
                    options=session_options,
                )
                if not self._session:
                    raise MPFlashError(
                        f"Failed to create session with probe {self.unique_id}"
                    )

                self._session.open()
                log.debug(f"pyOCD session opened for probe {self.unique_id}")
                self._connected = True
                log.debug(f"Connected to pyOCD probe {self.unique_id}")
                if hasattr(self._session, "options"):
                    log.debug(f"Session options: {self._session.options}")
                return True
            except Exception as e:
                last_error = e
                self._connected = False
                log.debug(
                    f"Failed to connect to probe {self.unique_id} with connect_mode={mode}: {e}"
                )
                if self._session:
                    try:
                        self._session.close()
                    except Exception:
                        pass
                    self._session = None

        e = last_error or Exception("unknown pyOCD connection failure")
        log.error(f"Failed to connect to pyOCD probe {self.unique_id}: {e}")
        if sys.platform.startswith("linux") and _is_linux_usb_permission_error(str(e)):
            raise MPFlashError(
                f"Cannot connect to probe {self.unique_id}.\n"
                f"{_pyocd_linux_udev_message()}\n"
                f"Details: {e}"
            )
        raise MPFlashError(
            f"Cannot connect to probe {self.unique_id}. "
            f"Tried connect_mode values: {attempted}. "
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

        Mirrors the behaviour of the ``pyocd flash`` CLI subcommand: builds a
        FileProgrammer with the requested erase mode, calls add_file()+commit(),
        then performs a separate reset, tolerating TransferError on the reset
        (as the CLI does) so the session can be closed cleanly.

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

        try:
            modules = _ensure_pyocd()
            FileProgrammer = modules["FileProgrammer"]
            PyOCDTransferError = modules["PyOCDTransferError"]
            PyOCDCoreRegisterAccessError = modules["PyOCDCoreRegisterAccessError"]

            # Extract programming options.
            # ``chip_erase`` must be one of {"auto", "sector", "chip"} and is
            # configured on the FileProgrammer constructor (NOT on program()).
            erase_option = "chip" if options.get("erase", False) else "sector"
            frequency = options.get("frequency", 4000000)
            connect_mode = options.get("connect_mode", "under-reset")

            suffix = firmware_path.suffix.lower()
            if suffix not in SUPPORTED_PYOCD_FILE_SUFFIXES:
                supported_formats = ", ".join(sorted(SUPPORTED_PYOCD_FILE_SUFFIXES))
                raise MPFlashError(
                    f"Unsupported firmware format for pyOCD: '{suffix or '<none>'}'. "
                    f"Supported formats: {supported_formats}. "
                    "Use --method dfu for .dfu files or provide a .bin/.hex/.elf image."
                )

            # Connect with explicit target configuration before programming.
            if not self._connected:
                self.connect(
                    target_type=target_type,
                    frequency=frequency,
                    connect_mode=connect_mode,
                )

            # Defensive: check session/target/core
            if not self._session:
                raise MPFlashError("pyOCD session was not created.")
            if not getattr(self._session, "target", None):
                raise MPFlashError("pyOCD session has no target. Check target_override and probe connection.")
            if not getattr(self._session.target, "selected_core", None):
                raise MPFlashError("pyOCD session target has no selected_core. Board may not be powered or supported.")

            log.info(f"Programming {firmware_path.name} to {target_type} via {self.description}")
            log.debug(f"Options: chip_erase={erase_option}, frequency={frequency}Hz, connect_mode={connect_mode}")
            log.debug(f"Firmware path: {firmware_path}")

            # Match pyOCD's load/flash subcommand default pre-reset behaviour.
            # For RA4M1 this reset-and-halt step is required before flash init.
            try:
                self._session.target.reset_and_halt()
            except Exception as reset_err:
                log.debug(f"Target reset_and_halt before programming failed: {reset_err}")

            # Build programmer + add file + commit (matches pyOCD CLI flow).
            programmer = FileProgrammer(self._session, chip_erase=erase_option)
            programmer.add_file(str(firmware_path), file_format=None)

            # Ensure the core is halted before invoking the flash algorithm.
            # Some targets connected in attach mode can remain running.
            try:
                self._session.target.halt()
            except Exception as halt_err:
                log.debug(f"Target halt before programming failed: {halt_err}")

            try:
                programmer.commit()
            except PyOCDCoreRegisterAccessError:
                # Retry once after forcing reset+halt to recover from
                # transient running-core states on certain targets/probes.
                log.debug("Retrying flash commit after CoreRegisterAccessError with reset_and_halt")
                try:
                    self._session.target.reset_and_halt()
                    programmer.commit()
                except PyOCDCoreRegisterAccessError:
                    raise

            log.info(f"Successfully programmed {firmware_path.name}")

            # Post-program reset (separate step, as pyOCD CLI does).
            # A TransferError here is expected on some targets because the
            # reset momentarily drops debug access. Tolerate it and tell pyOCD
            # to skip the DebugCoreStop / DebugPortStop sequences on close,
            # otherwise session.close() will fail with a DP error and leave
            # the SWD pins in a state that prevents the new firmware booting.
            try:
                log.debug("Resetting target to boot newly programmed firmware")
                self._session.target.reset()
            except PyOCDTransferError as err:
                log.debug(f"Tolerated transfer error during post-program reset: {err}")
                if not self._session.options.is_set("resume_on_disconnect"):
                    self._session.options.set("resume_on_disconnect", False)

            # Release the probe so the STLink/USB handle is freed and the
            # board's USB VCP becomes available for mpremote.
            self.disconnect()
            return True

        except MPFlashError as e:
            error_msg = f"Flash programming failed: {e}"
            log.error(error_msg)
            try:
                self.disconnect()
            except Exception:
                pass
            raise MPFlashError(error_msg) from e
        except Exception as e:
            error_msg = f"Flash programming failed: {e}"
            log.error(error_msg)
            log.debug(f"Flash programming traceback:\n{traceback.format_exc()}")
            try:
                self.disconnect()
            except Exception:
                pass
            raise MPFlashError(error_msg) from e

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

    def __init__(
        self,
        mcu: MPRemoteBoard,
        probe_id: Optional[str] = None,
        auto_install_packs: bool = True,
        target_override: Optional[str] = None,
    ):
        """
        Initialize PyOCD flash programmer.

        Args:
            mcu: MPRemoteBoard instance with board information
            probe_id: Specific probe unique ID to use (optional)
            auto_install_packs: Automatically install missing CMSIS packs
            target_override: Explicit pyOCD target name override (optional)
        """
        self.mcu = mcu
        self.probe_id = probe_id

        # Detect target type using core functionality unless explicitly overridden.
        self.target_type = target_override or detect_pyocd_target(
            mcu, auto_install_packs=auto_install_packs
        )
        if target_override:
            log.info(
                f"Using explicit pyOCD target override for {mcu.board_id}: {target_override}"
            )

        if not is_pyocd_available():
            raise MPFlashError("No debug probe support available. Install with: uv sync --extra pyocd")

        if not self.target_type:
            # Fallback for boards where serial metadata is unavailable:
            # ask the connected probe/target directly for part number.
            probe = find_pyocd_probe(self.probe_id)
            if probe:
                self.target_type = probe.detect_target()
                if self.target_type:
                    log.debug(
                        f"Detected pyOCD target via probe fallback: {self.target_type}"
                    )

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
                raise MPFlashError(f"PyOCD probe '{self.probe_id}' not found. Use 'mpflash list-probes' to see available probes.")
            else:
                if (
                    sys.platform.startswith("linux")
                    and _last_probe_discovery_error
                    and _is_linux_usb_permission_error(_last_probe_discovery_error)
                ):
                    raise MPFlashError(
                        f"No PyOCD debug probes available.\n"
                        f"{_pyocd_linux_udev_message()}\n"
                        f"Details: {_last_probe_discovery_error}"
                    )
                raise MPFlashError(
                    "No PyOCD debug probes available.\n"
                    f"{_pyocd_no_probe_possible_causes()}\n"
                    "Try: mpflash list-probes"
                )

        log.info(f"Flashing {fw_file.name} to {self.mcu.board_id} via pyOCD SWD/JTAG")
        log.debug(f"Target type: {self.target_type}, Probe: {probe.description}")

        # Build programming options.
        # Default RA4M1 targets to a safer SWD frequency unless explicitly set.
        requested_frequency = kwargs.get("frequency")
        if requested_frequency is None and self.target_type and "r7fa4m1" in self.target_type:
            requested_frequency = RA4M1_SAFE_SWD_FREQUENCY_HZ
            log.info(
                f"Using safe SWD frequency {requested_frequency}Hz for target {self.target_type}"
            )

        requested_connect_mode = kwargs.get("connect_mode")
        if requested_connect_mode is None and self.target_type and "r7fa4m1" in self.target_type:
            requested_connect_mode = "halt"
            log.info(
                f"Using pyOCD connect_mode={requested_connect_mode} for target {self.target_type}"
            )

        options = {
            "erase": erase,
            "frequency": requested_frequency if requested_frequency is not None else 4_000_000,
            "pyocd_options": kwargs.get("pyocd_options", {}),
        }
        if requested_connect_mode is not None:
            options["connect_mode"] = requested_connect_mode

        # Program using the probe
        assert self.target_type is not None , "Target type should have been detected in __init__"
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
    probes = list_pyocd_probes()
    log.debug(f"find_pyocd_probe(probe_id={probe_id!r}) found {len(probes)} connected probes")

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
            log.debug(f"Selected probe by exact id: {probe.unique_id}")
            return probe

    # Partial match
    matches = [p for p in probes if probe_id in p.unique_id]
    if len(matches) == 1:
        log.debug(f"Selected probe by partial id: {matches[0].unique_id}")
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


def flash_pyocd(
    mcu: MPRemoteBoard,
    fw_file: Path,
    erase: bool = False,
    probe_id: Optional[str] = None,
    auto_install_packs: bool = True,
    target_override: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    Flash MCU using pyOCD SWD/JTAG interface.

    Args:
        mcu: MPRemoteBoard instance with board information
        fw_file: Path to firmware file
        erase: Whether to erase flash before programming
        probe_id: Specific debug probe ID to use (optional)
        auto_install_packs: Automatically install missing CMSIS packs
        target_override: Explicit pyOCD target name override (optional)
        **kwargs: Additional options

    Returns:
        True if flashing succeeded

    Raises:
        MPFlashError: If flashing fails
    """
    if not target_override and not is_pyocd_supported(mcu):
        reason = get_unsupported_reason(mcu)
        raise MPFlashError(f"PyOCD flash not supported: {reason}")

    # Create flasher and program
    flasher = PyOCDFlash(
        mcu,
        probe_id=probe_id,
        auto_install_packs=auto_install_packs,
        target_override=target_override,
    )
    ok = flasher.flash_firmware(fw_file, erase=erase, **kwargs)
    if ok:
        # Give the board a moment to reset and re-enumerate over USB,
        # then wait for the MicroPython VCP to come back.
        log.info("Done flashing, board has been reset ...")
        mcu.wait_for_restart()
        log.success(f"Flashed {mcu.serialport} to {mcu.board} {mcu.version}")
    return ok


def pyocd_info() -> Dict[str, Any]:
    """
    Get information about pyOCD installation and available probes.

    Returns:
        Dictionary with pyOCD status information
    """
    info = {"available": is_pyocd_available(), "probes": [], "version": None}

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
                "vendor": getattr(probe, "vendor_name", "Unknown"),
                "product": getattr(probe, "product_name", "Unknown"),
                "target_type": probe.target_type,
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

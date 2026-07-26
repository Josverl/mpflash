"""
Additional unit tests to raise coverage of the pyOCD flash module.

These tests focus on the helper functions, the PyOCDProbe connect/program/
detect flows, PyOCDFlash fallbacks, probe discovery helpers and the public
convenience functions, all without requiring real hardware or pyOCD.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import mpflash.flash.builtins.pyocd.flash as flash_mod
from mpflash.flash.builtins.pyocd.flash import (
    PyOCDProbe,
    PyOCDFlash,
    _is_linux_usb_permission_error,
    _pyocd_linux_udev_message,
    _pyocd_no_probe_possible_causes,
    _ensure_pyocd,
    find_pyocd_probe,
    pyocd_info,
    find_probe_for_target,
)
from mpflash.errors import MPFlashError
from tests.fixtures.mock_pyocd_data import MOCK_MCUS


# Custom exception classes used to stand in for the pyOCD exception types.
class FakeTransferError(Exception):
    """Stand-in for pyocd TransferError."""


class FakeCoreRegisterAccessError(Exception):
    """Stand-in for pyocd CoreRegisterAccessError."""


def make_fake_modules(file_programmer=None):
    """Build a fake pyOCD modules dict suitable for _ensure_pyocd patching."""
    return {
        "ConnectHelper": Mock(),
        "FileProgrammer": file_programmer or Mock(),
        "PyOCDError": Exception,
        "PyOCDTransferError": FakeTransferError,
        "PyOCDCoreRegisterAccessError": FakeCoreRegisterAccessError,
    }


def make_probe_obj(unique_id, description="probe", target_type=None):
    """Create a lightweight stand-in probe object for discovery helpers."""
    return SimpleNamespace(
        unique_id=unique_id,
        description=description,
        vendor_name="Vendor",
        product_name="Product",
        target_type=target_type,
    )


# =============================================================================
# Helper functions
# =============================================================================


class TestHelperFunctions:
    """Test small pure helper functions."""

    def test_permission_error_empty(self):
        assert _is_linux_usb_permission_error("") is False

    def test_permission_error_none(self):
        assert _is_linux_usb_permission_error(None) is False  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "message",
        [
            "Permission denied",
            "Access denied to device",
            "EACCES while opening",
            "libusb error -3",
            "Could not open USB device",
            "USB access failure",
            "errno 13 occurred",
        ],
    )
    def test_permission_error_true(self, message):
        assert _is_linux_usb_permission_error(message) is True

    def test_permission_error_false(self):
        assert _is_linux_usb_permission_error("some unrelated failure") is False

    def test_udev_message_contains_rules(self):
        msg = _pyocd_linux_udev_message()
        assert "50-cmsis-dap.rules" in msg

    def test_no_probe_causes_text(self):
        text = _pyocd_no_probe_possible_causes()
        assert "Possible causes" in text
        assert "USB cable" in text


# =============================================================================
# _ensure_pyocd
# =============================================================================


class TestEnsurePyocd:
    """Test the lazy pyOCD import helper."""

    def teardown_method(self):
        # Reset the module-level cache so other tests are unaffected.
        flash_mod._pyocd_available = None
        flash_mod._pyocd_modules = {}

    def test_ensure_pyocd_import_failure(self):
        """ImportError during import should raise MPFlashError."""
        flash_mod._pyocd_available = None
        flash_mod._pyocd_modules = {}
        with patch.dict(sys.modules, {"pyocd.core.helpers": None}):
            with pytest.raises(MPFlashError, match="pyOCD is not installed"):
                _ensure_pyocd()

    def test_ensure_pyocd_cached_unavailable(self):
        """When previously marked unavailable, raises without re-import."""
        flash_mod._pyocd_available = False
        with pytest.raises(MPFlashError, match="pyOCD is not installed"):
            _ensure_pyocd()

    def test_ensure_pyocd_cached_available(self):
        """When already available, returns cached modules dict."""
        sentinel = {"ConnectHelper": Mock()}
        flash_mod._pyocd_available = True
        flash_mod._pyocd_modules = sentinel
        assert _ensure_pyocd() is sentinel


# =============================================================================
# PyOCDProbe.discover
# =============================================================================


class TestProbeDiscovery:
    """Test PyOCDProbe.discover error handling."""

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_discover_exception_records_error(self, mock_ensure):
        mock_ensure.side_effect = Exception("boom usb")
        flash_mod._last_probe_discovery_error = None

        probes = PyOCDProbe.discover()

        assert probes == []
        assert flash_mod._last_probe_discovery_error == "boom usb"


# =============================================================================
# PyOCDProbe.connect
# =============================================================================


class TestProbeConnect:
    """Test PyOCDProbe.connect flows."""

    def test_connect_already_connected(self):
        probe = PyOCDProbe("ID", "desc")
        probe._connected = True
        assert probe.connect() is True

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_connect_success_first_mode(self, mock_ensure):
        helper = Mock()
        session = Mock()
        helper.session_with_chosen_probe.return_value = session
        mock_ensure.return_value = {"ConnectHelper": helper}

        probe = PyOCDProbe("ID", "desc")
        assert probe.connect(target_type="stm32f429xi", frequency=2_000_000) is True
        session.open.assert_called_once()
        assert probe._connected is True

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_connect_session_none_raises(self, mock_ensure):
        helper = Mock()
        helper.session_with_chosen_probe.return_value = None
        mock_ensure.return_value = {"ConnectHelper": helper}

        probe = PyOCDProbe("ID", "desc")
        with pytest.raises(MPFlashError, match="Cannot connect to probe"):
            probe.connect(frequency=0)

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_connect_all_modes_fail(self, mock_ensure):
        helper = Mock()
        helper.session_with_chosen_probe.side_effect = Exception("no swd")
        mock_ensure.return_value = {"ConnectHelper": helper}

        probe = PyOCDProbe("ID", "desc")
        with pytest.raises(MPFlashError, match="Tried connect_mode values"):
            probe.connect()

    @patch("sys.platform", "linux")
    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_connect_linux_permission_error(self, mock_ensure):
        helper = Mock()
        helper.session_with_chosen_probe.side_effect = Exception("Permission denied: libusb")
        mock_ensure.return_value = {"ConnectHelper": helper}

        probe = PyOCDProbe("ID", "desc")
        with pytest.raises(MPFlashError, match="50-cmsis-dap.rules"):
            probe.connect()


# =============================================================================
# PyOCDProbe.program_flash
# =============================================================================


class TestProgramFlash:
    """Test PyOCDProbe.program_flash branches."""

    def _make_connected_probe(self, modules):
        probe = PyOCDProbe("ID", "desc")
        probe._connected = True
        session = Mock()
        session.target.selected_core = Mock()
        session.options.is_set.return_value = True
        probe._session = session
        return probe, session

    def test_program_flash_file_missing(self):
        probe = PyOCDProbe("ID", "desc")
        with pytest.raises(MPFlashError, match="Firmware file not found"):
            probe.program_flash(Path("/no/such/file.bin"), "stm32f429xi")

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_unsupported_suffix(self, mock_ensure, tmp_path):
        mock_ensure.return_value = make_fake_modules()
        fw = tmp_path / "fw.dfu"
        fw.write_bytes(b"x")

        probe = PyOCDProbe("ID", "desc")
        with pytest.raises(MPFlashError, match="Unsupported firmware format"):
            probe.program_flash(fw, "stm32f429xi")

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_success(self, mock_ensure, tmp_path):
        programmer = Mock()
        file_programmer_cls = Mock(return_value=programmer)
        mock_ensure.return_value = make_fake_modules(file_programmer_cls)

        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")

        probe, session = self._make_connected_probe(mock_ensure.return_value)
        result = probe.program_flash(fw, "stm32f429xi", erase=True)

        assert result is True
        file_programmer_cls.assert_called_once()
        # erase=True maps to chip erase mode
        assert file_programmer_cls.call_args.kwargs["chip_erase"] == "chip"
        programmer.add_file.assert_called_once()
        programmer.commit.assert_called()
        session.close.assert_called_once()

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_no_session(self, mock_ensure, tmp_path):
        mock_ensure.return_value = make_fake_modules()
        fw = tmp_path / "fw.hex"
        fw.write_bytes(b"x")

        probe = PyOCDProbe("ID", "desc")
        probe._connected = True
        probe._session = None
        with pytest.raises(MPFlashError, match="session was not created"):
            probe.program_flash(fw, "stm32f429xi")

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_no_target(self, mock_ensure, tmp_path):
        mock_ensure.return_value = make_fake_modules()
        fw = tmp_path / "fw.elf"
        fw.write_bytes(b"x")

        probe = PyOCDProbe("ID", "desc")
        probe._connected = True
        session = Mock()
        session.target = None
        probe._session = session
        with pytest.raises(MPFlashError, match="has no target"):
            probe.program_flash(fw, "stm32f429xi")

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_no_selected_core(self, mock_ensure, tmp_path):
        mock_ensure.return_value = make_fake_modules()
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")

        probe = PyOCDProbe("ID", "desc")
        probe._connected = True
        session = Mock()
        session.target.selected_core = None
        probe._session = session
        with pytest.raises(MPFlashError, match="no selected_core"):
            probe.program_flash(fw, "stm32f429xi")

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_core_register_retry(self, mock_ensure, tmp_path):
        programmer = Mock()
        # First commit raises, second (after reset_and_halt) succeeds.
        programmer.commit.side_effect = [FakeCoreRegisterAccessError(), None]
        file_programmer_cls = Mock(return_value=programmer)
        mock_ensure.return_value = make_fake_modules(file_programmer_cls)

        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")

        probe, session = self._make_connected_probe(mock_ensure.return_value)
        result = probe.program_flash(fw, "stm32f429xi")

        assert result is True
        assert programmer.commit.call_count == 2

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_post_reset_transfer_error_tolerated(self, mock_ensure, tmp_path):
        programmer = Mock()
        file_programmer_cls = Mock(return_value=programmer)
        mock_ensure.return_value = make_fake_modules(file_programmer_cls)

        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")

        probe, session = self._make_connected_probe(mock_ensure.return_value)
        session.target.reset.side_effect = FakeTransferError()
        session.options.is_set.return_value = False

        result = probe.program_flash(fw, "stm32f429xi")

        assert result is True
        session.options.set.assert_called_with("resume_on_disconnect", False)

    @patch("mpflash.flash.builtins.pyocd.flash._ensure_pyocd")
    def test_program_flash_calls_connect_when_disconnected(self, mock_ensure, tmp_path):
        programmer = Mock()
        file_programmer_cls = Mock(return_value=programmer)
        mock_ensure.return_value = make_fake_modules(file_programmer_cls)

        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")

        probe = PyOCDProbe("ID", "desc")
        probe._connected = False
        session = Mock()
        session.target.selected_core = Mock()
        session.options.is_set.return_value = True

        def fake_connect(**kwargs):
            probe._connected = True
            probe._session = session
            return True

        with patch.object(probe, "connect", side_effect=fake_connect) as mock_connect:
            result = probe.program_flash(fw, "stm32f429xi")

        assert result is True
        mock_connect.assert_called_once()


# =============================================================================
# PyOCDProbe.detect_target and context manager
# =============================================================================


class TestDetectTargetAndContext:
    """Test target detection and context manager behavior."""

    def test_detect_target_success(self):
        probe = PyOCDProbe("ID", "desc")
        probe._connected = True
        session = Mock()
        session.target.part_number = "STM32F429XI"
        probe._session = session

        assert probe.detect_target() == "stm32f429xi"

    def test_detect_target_failure(self):
        probe = PyOCDProbe("ID", "desc")
        probe._connected = True
        probe._session = None
        with patch.object(probe, "connect", side_effect=Exception("fail")):
            assert probe.detect_target() is None

    def test_context_manager(self):
        probe = PyOCDProbe("ID", "desc")
        with patch.object(probe, "connect") as mock_connect, patch.object(
            probe, "disconnect"
        ) as mock_disconnect:
            with probe as ctx:
                assert ctx is probe
            mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()

    def test_disconnect_handles_close_error(self):
        probe = PyOCDProbe("ID", "desc")
        session = Mock()
        session.close.side_effect = Exception("close fail")
        probe._session = session
        probe._connected = True
        # Should not raise
        probe.disconnect()
        assert probe._session is None
        assert probe._connected is False


# =============================================================================
# PyOCDFlash fallbacks
# =============================================================================


class TestPyOCDFlashInit:
    """Test PyOCDFlash __init__ override and fallback paths."""

    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    @patch("mpflash.flash.builtins.pyocd.flash.detect_pyocd_target")
    def test_target_override_used(self, mock_detect, mock_available):
        mock_available.return_value = True
        flasher = PyOCDFlash(MOCK_MCUS["stm32wb55"], target_override="stm32wb55xg")
        assert flasher.target_type == "stm32wb55xg"
        mock_detect.assert_not_called()

    @patch("mpflash.flash.builtins.pyocd.flash.find_pyocd_probe")
    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    @patch("mpflash.flash.builtins.pyocd.flash.detect_pyocd_target")
    def test_probe_fallback_detects_target(self, mock_detect, mock_available, mock_find):
        mock_available.return_value = True
        mock_detect.return_value = None
        probe = Mock()
        probe.detect_target.return_value = "stm32f429xi"
        mock_find.return_value = probe

        flasher = PyOCDFlash(MOCK_MCUS["stm32f429"])
        assert flasher.target_type == "stm32f429xi"
        probe.detect_target.assert_called_once()


# =============================================================================
# find_pyocd_probe
# =============================================================================


class TestFindPyocdProbe:
    """Test the probe-selection logic in find_pyocd_probe."""

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    def test_no_probes(self, mock_list):
        mock_list.return_value = []
        assert find_pyocd_probe() is None

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    def test_single_probe_no_id(self, mock_list):
        probe = make_probe_obj("ABC123")
        mock_list.return_value = [probe]
        assert find_pyocd_probe() is probe

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    def test_multiple_probes_no_id_raises(self, mock_list):
        mock_list.return_value = [make_probe_obj("AAA"), make_probe_obj("BBB")]
        with pytest.raises(MPFlashError, match="Multiple debug probes found"):
            find_pyocd_probe()

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    def test_exact_match(self, mock_list):
        p1, p2 = make_probe_obj("AAA111"), make_probe_obj("BBB222")
        mock_list.return_value = [p1, p2]
        assert find_pyocd_probe("BBB222") is p2

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    def test_partial_match_single(self, mock_list):
        p1, p2 = make_probe_obj("AAA111"), make_probe_obj("BBB222")
        mock_list.return_value = [p1, p2]
        assert find_pyocd_probe("BBB") is p2

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    def test_partial_match_ambiguous(self, mock_list):
        mock_list.return_value = [make_probe_obj("XX1"), make_probe_obj("XX2")]
        with pytest.raises(MPFlashError, match="Ambiguous probe ID"):
            find_pyocd_probe("XX")

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    def test_no_match(self, mock_list):
        mock_list.return_value = [make_probe_obj("AAA"), make_probe_obj("BBB")]
        assert find_pyocd_probe("ZZZ") is None


# =============================================================================
# flash_firmware no-probe variants
# =============================================================================


class TestFlashFirmwareNoProbe:
    """Cover the no-probe error branches in PyOCDFlash.flash_firmware."""

    def _make_flasher(self, mock_available, mock_detect):
        mock_available.return_value = True
        mock_detect.return_value = "stm32f429xi"
        return PyOCDFlash(MOCK_MCUS["stm32f429"])

    @patch("mpflash.flash.builtins.pyocd.flash.find_pyocd_probe")
    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    @patch("mpflash.flash.builtins.pyocd.flash.detect_pyocd_target")
    def test_no_probe_with_probe_id(self, mock_detect, mock_available, mock_find, tmp_path):
        flasher = self._make_flasher(mock_available, mock_detect)
        flasher.probe_id = "SOME_ID"
        mock_find.return_value = None
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")
        with pytest.raises(MPFlashError, match="not found"):
            flasher.flash_firmware(fw)

    @patch("sys.platform", "linux")
    @patch("mpflash.flash.builtins.pyocd.flash.find_pyocd_probe")
    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    @patch("mpflash.flash.builtins.pyocd.flash.detect_pyocd_target")
    def test_no_probe_linux_permission(self, mock_detect, mock_available, mock_find, tmp_path):
        flasher = self._make_flasher(mock_available, mock_detect)
        flasher.probe_id = None
        mock_find.return_value = None
        flash_mod._last_probe_discovery_error = "Permission denied: libusb"
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")
        with pytest.raises(MPFlashError, match="50-cmsis-dap.rules"):
            flasher.flash_firmware(fw)

    @patch("sys.platform", "win32")
    @patch("mpflash.flash.builtins.pyocd.flash.find_pyocd_probe")
    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    @patch("mpflash.flash.builtins.pyocd.flash.detect_pyocd_target")
    def test_no_probe_generic(self, mock_detect, mock_available, mock_find, tmp_path):
        flasher = self._make_flasher(mock_available, mock_detect)
        flasher.probe_id = None
        mock_find.return_value = None
        flash_mod._last_probe_discovery_error = None
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")
        with pytest.raises(MPFlashError, match="No PyOCD debug probes available"):
            flasher.flash_firmware(fw)

    @patch("mpflash.flash.builtins.pyocd.flash.find_pyocd_probe")
    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    @patch("mpflash.flash.builtins.pyocd.flash.detect_pyocd_target")
    def test_ra4m1_safe_defaults(self, mock_detect, mock_available, mock_find, tmp_path):
        mock_available.return_value = True
        mock_detect.return_value = "r7fa4m1ab"
        probe = Mock()
        probe.description = "probe"
        probe.program_flash.return_value = True
        mock_find.return_value = probe

        flasher = PyOCDFlash(MOCK_MCUS["ek_ra4m1"])
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"x")
        assert flasher.flash_firmware(fw) is True
        _, kwargs = probe.program_flash.call_args
        assert kwargs["frequency"] == flash_mod.RA4M1_SAFE_SWD_FREQUENCY_HZ
        assert kwargs["connect_mode"] == "halt"


# =============================================================================
# pyocd_info and find_probe_for_target
# =============================================================================


class TestPublicHelpers:
    """Test pyocd_info and find_probe_for_target."""

    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    def test_pyocd_info_unavailable(self, mock_available):
        mock_available.return_value = False
        info = pyocd_info()
        assert info["available"] is False
        assert info["probes"] == []

    @patch("mpflash.flash.builtins.pyocd.flash.list_pyocd_probes")
    @patch("mpflash.flash.builtins.pyocd.flash.is_pyocd_available")
    def test_pyocd_info_available(self, mock_available, mock_list):
        mock_available.return_value = True
        probe = make_probe_obj("ID1", target_type="stm32f429xi")
        mock_list.return_value = [probe]
        info = pyocd_info()
        assert info["available"] is True
        assert len(info["probes"]) == 1
        assert info["probes"][0]["unique_id"] == "ID1"
        assert info["probes"][0]["target_type"] == "stm32f429xi"

    @patch("mpflash.flash.builtins.pyocd.flash.find_pyocd_probe")
    def test_find_probe_for_target(self, mock_find):
        probe = make_probe_obj("ID1")
        mock_find.return_value = probe
        assert find_probe_for_target("stm32f429xi", "ID1") is probe


if __name__ == "__main__":
    pytest.main([__file__])

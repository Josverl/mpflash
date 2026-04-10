"""Tests for mpflash.flash.stm32_dfu - STM32 DFU flashing with .dfu and .bin support."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mpflash.mpremoteboard import MPRemoteBoard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_board(port="COM1"):
    board = MPRemoteBoard(port)
    board.board_id = "PYBD_SF2"
    board.port = "stm32"
    board.serialport = port
    return board


# ---------------------------------------------------------------------------
# dfu_init
# ---------------------------------------------------------------------------


class TestDfuInit:
    def test_no_pydfu(self):
        """dfu_init returns None gracefully when pydfu is not available."""
        with patch("mpflash.flash.stm32_dfu.pydfu", None):
            from mpflash.flash.stm32_dfu import dfu_init

            result = dfu_init()
            assert result is None

    @patch("platform.system", return_value="Linux")
    def test_linux_no_libusb_init(self, mock_platform):
        """On Linux, init_libusb_windows is NOT called."""
        mock_pydfu = MagicMock()
        with (
            patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu),
            patch("mpflash.flash.stm32_dfu.init_libusb_windows") as mock_init,
        ):
            from mpflash.flash.stm32_dfu import dfu_init

            dfu_init()
            mock_init.assert_not_called()

    @patch("platform.system", return_value="Windows")
    def test_windows_calls_libusb_init(self, mock_platform):
        """On Windows, init_libusb_windows is called."""
        mock_pydfu = MagicMock()
        with (
            patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu),
            patch("mpflash.flash.stm32_dfu.init_libusb_windows") as mock_init,
        ):
            from mpflash.flash.stm32_dfu import dfu_init

            dfu_init()
            mock_init.assert_called_once()


# ---------------------------------------------------------------------------
# flash_stm32_dfu – guard conditions
# ---------------------------------------------------------------------------


class TestFlashStm32DfuGuards:
    def test_no_pydfu_returns_none(self, tmp_path):
        """Returns None when pydfu module is unavailable."""
        fw = tmp_path / "fw.dfu"
        fw.touch()
        with patch("mpflash.flash.stm32_dfu.pydfu", None):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(_make_board(), fw)
            assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        """Returns None when firmware file does not exist."""
        fw = tmp_path / "missing.dfu"
        mock_pydfu = MagicMock()
        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(_make_board(), fw)
            assert result is None

    def test_invalid_extension_returns_none(self, tmp_path):
        """Returns None for unsupported file extensions."""
        fw = tmp_path / "firmware.hex"
        fw.touch()
        mock_pydfu = MagicMock()
        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(_make_board(), fw)
            assert result is None

    def test_usb_permission_error_returns_none(self, tmp_path):
        """Returns None on USB permission error (ValueError from list_dfu_devices)."""
        fw = tmp_path / "fw.dfu"
        fw.touch()
        mock_pydfu = MagicMock()
        mock_pydfu.list_dfu_devices.side_effect = ValueError("Permission denied")
        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(_make_board(), fw)
            assert result is None


# ---------------------------------------------------------------------------
# flash_stm32_dfu – .dfu file path
# ---------------------------------------------------------------------------


class TestFlashStm32DfuDfuFile:
    def _make_mock_pydfu(self, elements=None):
        m = MagicMock()
        m.read_dfu_file.return_value = elements if elements is not None else [{"data": b"\x00", "addr": 0x08000000, "size": 1, "num": 0}]
        return m

    def test_dfu_file_success(self, tmp_path):
        """Successfully flashes a .dfu file and returns the board."""
        fw = tmp_path / "fw.dfu"
        fw.touch()
        board = _make_board()
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(board, fw)

        assert result is board
        mock_pydfu.read_dfu_file.assert_called_once_with(fw)
        mock_pydfu.read_bin_file.assert_not_called()

    def test_dfu_file_calls_mass_erase_when_erase_true(self, tmp_path):
        """Mass erase is called when erase=True."""
        fw = tmp_path / "fw.dfu"
        fw.touch()
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw, erase=True)

        mock_pydfu.mass_erase.assert_called_once()

    def test_dfu_file_no_mass_erase_when_erase_false(self, tmp_path):
        """Mass erase is NOT called when erase=False."""
        fw = tmp_path / "fw.dfu"
        fw.touch()
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw, erase=False)

        mock_pydfu.mass_erase.assert_not_called()

    def test_dfu_file_empty_elements_returns_none(self, tmp_path):
        """Returns None when .dfu file yields no elements."""
        fw = tmp_path / "fw.dfu"
        fw.touch()
        mock_pydfu = self._make_mock_pydfu(elements=[])

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(_make_board(), fw)

        assert result is None

    def test_dfu_file_none_elements_returns_none(self, tmp_path):
        """Returns None when read_dfu_file returns None (parse error)."""
        fw = tmp_path / "fw.dfu"
        fw.touch()
        mock_pydfu = self._make_mock_pydfu(elements=None)
        mock_pydfu.read_dfu_file.return_value = None

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(_make_board(), fw)

        assert result is None


# ---------------------------------------------------------------------------
# flash_stm32_dfu – .bin file path (new functionality)
# ---------------------------------------------------------------------------


class TestFlashStm32DfuBinFile:
    def _make_mock_pydfu(self, elements=None):
        m = MagicMock()
        m.read_bin_file.return_value = (
            elements if elements is not None else [{"data": b"\x00" * 16, "addr": 0x08000000, "size": 16, "num": 0}]
        )
        return m

    def test_bin_file_success(self, tmp_path):
        """Successfully flashes a .bin file and returns the board."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 16)
        board = _make_board()
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(board, fw)

        assert result is board
        mock_pydfu.read_bin_file.assert_called_once_with(fw, 0x08000000)
        mock_pydfu.read_dfu_file.assert_not_called()

    def test_bin_file_uses_default_address(self, tmp_path):
        """Default address 0x08000000 is used for .bin files."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\xde\xad\xbe\xef")
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw)

        mock_pydfu.read_bin_file.assert_called_once_with(fw, 0x08000000)

    def test_bin_file_custom_address(self, tmp_path):
        """Custom address is passed to read_bin_file."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\xde\xad\xbe\xef")
        mock_pydfu = self._make_mock_pydfu()
        custom_addr = 0x08010000

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw, address=custom_addr)

        mock_pydfu.read_bin_file.assert_called_once_with(fw, custom_addr)

    def test_bin_file_calls_mass_erase_when_erase_true(self, tmp_path):
        """Mass erase is called when erase=True for .bin files."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 4)
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw, erase=True)

        mock_pydfu.mass_erase.assert_called_once()

    def test_bin_file_no_mass_erase_when_erase_false(self, tmp_path):
        """Mass erase is NOT called when erase=False for .bin files."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 4)
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw, erase=False)

        mock_pydfu.mass_erase.assert_not_called()

    def test_bin_file_empty_elements_returns_none(self, tmp_path):
        """Returns None when .bin file yields no elements."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 4)
        mock_pydfu = self._make_mock_pydfu(elements=[])

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            result = flash_stm32_dfu(_make_board(), fw)

        assert result is None

    def test_bin_file_calls_write_elements_and_exit_dfu(self, tmp_path):
        """write_elements and exit_dfu are called when flashing .bin succeeds."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 16)
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw)

        mock_pydfu.write_elements.assert_called_once()
        mock_pydfu.exit_dfu.assert_called_once()

    def test_bin_file_init_called_with_correct_kwargs(self, tmp_path):
        """init() is called with the STM32 vendor/product IDs."""
        fw = tmp_path / "fw.bin"
        fw.write_bytes(b"\x00" * 4)
        mock_pydfu = self._make_mock_pydfu()

        with patch("mpflash.flash.stm32_dfu.pydfu", mock_pydfu), patch("mpflash.flash.stm32_dfu.dfu_init", return_value=None):
            from mpflash.flash.stm32_dfu import flash_stm32_dfu

            flash_stm32_dfu(_make_board(), fw)

        mock_pydfu.init.assert_called_once_with(idVendor=0x0483, idProduct=0xDF11)


# ---------------------------------------------------------------------------
# common.py – PORT_FWTYPES includes .bin for stm32
# ---------------------------------------------------------------------------


class TestCommonPortFwtypes:
    def test_stm32_supports_bin(self):
        """stm32 firmware types include .bin."""
        from mpflash.common import PORT_FWTYPES

        assert ".bin" in PORT_FWTYPES["stm32"]

    def test_stm32_supports_dfu(self):
        """stm32 firmware types still include .dfu."""
        from mpflash.common import PORT_FWTYPES

        assert ".dfu" in PORT_FWTYPES["stm32"]

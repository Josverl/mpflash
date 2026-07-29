"""Tests for the ``mpflash erase`` command."""

from unittest.mock import PropertyMock

import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

# module under test :
from mpflash import cli_main
from mpflash.config import config
from mpflash.mpremoteboard import MPRemoteBoard

# mark all tests
pytestmark = pytest.mark.mpflash


def fakeboard(serialport="COM99", port="rp2", board_id="RPI_PICO"):
    fake = MPRemoteBoard(serialport)
    fake.connected = True
    fake.family = "micropython"
    fake.port = port
    fake.board_id = board_id
    fake.version = "1.22.0"
    return fake


def test_mpflash_erase_success(mocker: MockerFixture):
    """A supported connected board is erased with --yes."""
    fake = fakeboard(port="rp2")
    mocker.patch("mpflash.connected.list_mcus", return_value=[fake], autospec=True)
    mocker.patch("mpflash.list.show_mcus", return_value=None, autospec=True)
    m_erase = mocker.patch("mpflash.flash.builtins.uf2.erase.erase_filesystem", return_value=True, autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["erase", "--yes"], standalone_mode=True)

    assert result.exit_code == 0
    m_erase.assert_called_once_with(fake)


def test_mpflash_erase_no_boards_returns_one(mocker: MockerFixture):
    """Exit with code 1 when no boards are connected."""
    mocker.patch("mpflash.connected.list_mcus", return_value=[], autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["erase", "--yes"], standalone_mode=True)

    assert result.exit_code == 1


def test_mpflash_erase_unsupported_port_skipped(mocker: MockerFixture):
    """Boards on ports without a known block device are skipped."""
    fake = fakeboard(port="esp32")
    mocker.patch("mpflash.connected.list_mcus", return_value=[fake], autospec=True)
    m_erase = mocker.patch("mpflash.flash.builtins.uf2.erase.erase_filesystem", return_value=True, autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["erase", "--yes"], standalone_mode=True)

    assert result.exit_code == 1
    m_erase.assert_not_called()


def test_mpflash_erase_confirmation_declined(mocker: MockerFixture):
    """Declining the confirmation prompt aborts without erasing."""
    fake = fakeboard(port="rp2")
    mocker.patch("mpflash.connected.list_mcus", return_value=[fake], autospec=True)
    mocker.patch("mpflash.list.show_mcus", return_value=None, autospec=True)
    m_erase = mocker.patch("mpflash.flash.builtins.uf2.erase.erase_filesystem", return_value=True, autospec=True)
    mocker.patch.object(type(config), "interactive", new_callable=PropertyMock, return_value=True)
    mocker.patch("rich.prompt.Confirm.ask", return_value=False)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["erase"], standalone_mode=True)

    assert result.exit_code == 2
    m_erase.assert_not_called()


def test_mpflash_erase_respects_ignore_flag(mocker: MockerFixture):
    """Boards with the [mpflash] ignore flag are not erased."""
    fake = fakeboard(port="rp2")
    fake.toml = {"mpflash": {"ignore": True}}
    mocker.patch("mpflash.connected.list_mcus", return_value=[fake], autospec=True)
    m_erase = mocker.patch("mpflash.flash.builtins.uf2.erase.erase_filesystem", return_value=True, autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["erase", "--yes"], standalone_mode=True)

    assert result.exit_code == 1
    m_erase.assert_not_called()


def test_mpflash_erase_reports_failure(mocker: MockerFixture):
    """A board that cannot be erased returns exit code 1."""
    fake = fakeboard(port="rp2")
    mocker.patch("mpflash.connected.list_mcus", return_value=[fake], autospec=True)
    mocker.patch("mpflash.list.show_mcus", return_value=None, autospec=True)
    mocker.patch("mpflash.flash.builtins.uf2.erase.erase_filesystem", return_value=False, autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["erase", "--yes"], standalone_mode=True)

    assert result.exit_code == 1

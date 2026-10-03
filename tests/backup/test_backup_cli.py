"""The ``mpflash backup`` and ``mpflash restore`` commands."""

from unittest.mock import PropertyMock

import pytest
from backup_helpers import capability
from click.testing import CliRunner
from pytest_mock import MockerFixture

from mpflash import cli_main
from mpflash.backup.models import ComponentKind
from mpflash.config import config

pytestmark = pytest.mark.mpflash

FLASH, VFS = ComponentKind.FLASH, ComponentKind.VFS


@pytest.fixture
def board(mocker: MockerFixture, mcu):
    mocker.patch("mpflash.connected.list_mcus", return_value=[mcu], autospec=True)
    return mcu


def run(*args):
    return CliRunner().invoke(cli_main.cli, list(args), standalone_mode=True)


@pytest.fixture
def made_backup(board, full_provider, tmp_path):
    out = tmp_path / "backups"
    result = run("backup", "--serial", "COM9", "--output", str(out))
    assert result.exit_code == 0, result.output
    (folder,) = list(out.iterdir())
    full_provider.restored.clear()
    return folder


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def test_backup_creates_a_bundle_for_each_connected_board(board, full_provider, tmp_path):
    result = run("backup", "--output", str(tmp_path))

    assert result.exit_code == 0, result.output
    (folder,) = list(tmp_path.iterdir())
    assert (folder / "manifest.json").is_file() and (folder / "README.md").is_file()
    assert full_provider.backed_up == [FLASH, VFS, ComponentKind.ROMFS]


def test_backup_component_and_files_options_are_forwarded(board, full_provider, tmp_path):
    result = run("backup", "--output", str(tmp_path), "-c", "vfs", "--files")

    assert result.exit_code == 0, result.output
    assert full_provider.backed_up == [VFS]
    assert full_provider.contexts[0].include_files is True


def test_backup_without_boards_fails(mocker: MockerFixture, tmp_path):
    mocker.patch("mpflash.connected.list_mcus", return_value=[], autospec=True)

    assert run("backup", "--output", str(tmp_path)).exit_code == 1


def test_backup_unsupported_component_fails_without_creating_a_folder(board, isolated_registry, tmp_path):
    isolated_registry(capability(VFS))

    result = run("backup", "--output", str(tmp_path), "-c", "flash")

    assert result.exit_code == 1
    assert list(tmp_path.iterdir()) == []


def test_backup_ignores_boards_with_the_ignore_flag(board, full_provider, tmp_path):
    board.toml = {"mpflash": {"ignore": True}}

    assert run("backup", "--output", str(tmp_path)).exit_code == 1
    assert full_provider.backed_up == []


def test_backup_reports_failure_when_any_board_fails(board, isolated_registry, tmp_path):
    isolated_registry(capability(VFS), fail_backup=True)

    assert run("backup", "--output", str(tmp_path)).exit_code == 1


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def test_restore_dry_run_validates_and_changes_nothing(made_backup, full_provider):
    result = run("restore", str(made_backup), "--serial", "COM9", "--dry-run")

    assert result.exit_code == 0, result.output
    assert "[flash] write artifacts/flash.bin" in result.output
    assert full_provider.restored == []


def test_restore_with_yes_restores_in_order(made_backup, full_provider):
    result = run("restore", str(made_backup), "--serial", "COM9", "--yes")

    assert result.exit_code == 0, result.output
    assert full_provider.restored == [FLASH, VFS]


def test_restore_component_selection(made_backup, full_provider):
    result = run("restore", str(made_backup), "--serial", "COM9", "--yes", "-c", "vfs")

    assert result.exit_code == 0, result.output
    assert full_provider.restored == [VFS]


def test_restore_declined_confirmation_exits_with_two(made_backup, full_provider, mocker: MockerFixture):
    mocker.patch.object(type(config), "interactive", new_callable=PropertyMock, return_value=True)
    mocker.patch("rich.prompt.Confirm.ask", return_value=False)

    result = run("restore", str(made_backup), "--serial", "COM9")

    assert result.exit_code == 2
    assert full_provider.restored == []


def test_restore_non_interactive_requires_yes(made_backup, full_provider, mocker: MockerFixture):
    mocker.patch.object(type(config), "interactive", new_callable=PropertyMock, return_value=False)

    result = run("restore", str(made_backup), "--serial", "COM9")

    assert result.exit_code == 2
    assert "--yes" in result.output
    assert full_provider.restored == []


@pytest.mark.parametrize("serial", ["*", "COM?", "COM[1-3]"])
def test_restore_rejects_wildcard_serial(made_backup, serial):
    result = run("restore", str(made_backup), "--serial", serial, "--yes")

    assert result.exit_code == 2
    assert "exactly one serial port" in result.output


def test_restore_requires_serial_and_existing_folder(made_backup, tmp_path):
    assert run("restore", str(made_backup)).exit_code == 2
    assert run("restore", str(tmp_path / "missing"), "--serial", "COM9").exit_code == 2


def test_restore_requires_exactly_one_responsive_board(made_backup, full_provider, mocker: MockerFixture):
    mocker.patch("mpflash.connected.list_mcus", return_value=[], autospec=True)

    assert run("restore", str(made_backup), "--serial", "COM9", "--yes").exit_code == 1
    assert full_provider.restored == []


def test_restore_rejects_a_different_board_before_writing(made_backup, full_provider, mcu):
    mcu.board_id = "OTHER_BOARD"

    result = run("restore", str(made_backup), "--serial", "COM9", "--yes")

    assert result.exit_code == 1
    assert full_provider.restored == []


def test_restore_rejects_a_tampered_bundle(made_backup, full_provider):
    (made_backup / "artifacts" / "vfs.bin").write_bytes(b"EVIL!")

    result = run("restore", str(made_backup), "--serial", "COM9", "--yes")

    assert result.exit_code == 1
    assert full_provider.restored == []


def test_restore_failure_exits_nonzero(made_backup, full_provider):
    full_provider.fail_restore = VFS

    result = run("restore", str(made_backup), "--serial", "COM9", "--yes")

    assert result.exit_code == 1
    assert full_provider.restored == [FLASH]

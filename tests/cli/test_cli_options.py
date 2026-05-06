from typing import List

import pytest
from click.testing import CliRunner

# module under test :
import mpflash.cli_group as cli_group
import mpflash.cli_main as cli_main

# mark all tests
pytestmark = [pytest.mark.mpflash, pytest.mark.cli]


##########################################################################################
# --help


def test_mpflash_help():
    # check basic command line sanity check
    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["--help"])
    assert result.exit_code == 0
    expected = ["Usage:", "Options", "Commands", "--dir", "download", "flash", "list"]
    for word in expected:
        assert word in result.output


# FIXME
# Tests succedd in isolation but fail in batch
# @pytest.mark.parametrize(
#     "command",
#     [
#         ["--verbose"],
#         ["-V"],
#         ["-VV"],
#         ["-V", "-V"],
#     ],
# )
# def test_cli_verbose(command: List[str], mocker: MockerFixture):
#     # can turn on verbose mode
#     runner = CliRunner()
#     result = runner.invoke(cli_main.cli, command)
#     assert cli_group.config.verbose == True


@pytest.mark.parametrize(
    "params",
    [
        ["-q"],
        ["--quiet"],
        ["-q", "--verbose"],
        ["--quiet", "--verbose"],
    ],
)
def test_cli_quiet(params: List[str]):
    # can turn on verbose mode
    runner = CliRunner()
    result = runner.invoke(cli_main.cli, params)
    assert result
    assert cli_group.config.quiet == True
    assert cli_group.config.verbose == False


def test_global_dir_keeps_db_and_firmware_folder_aligned(mocker, tmp_path):
    """Global --dir should keep db path rooted in the selected firmware folder."""
    from mpflash.config import config

    mock_init_db = mocker.patch("mpflash.db.core._init_database")
    mock_migrate_db = mocker.patch("mpflash.db.core.migrate_database")

    old_folder = config._firmware_folder
    runner = CliRunner()
    try:
        result = runner.invoke(cli_main.cli, ["--dir", str(tmp_path), "--help"])
        assert result.exit_code == 0
        assert config.firmware_folder == tmp_path.resolve()
        assert config.db_path == tmp_path.resolve() / "mpflash.db"
        mock_init_db.assert_called_once_with(config.db_path)
        mock_migrate_db.assert_called_once_with(boards=True, firmwares=True)
    finally:
        config._firmware_folder = old_folder

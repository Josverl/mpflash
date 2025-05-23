from pathlib import Path

import pytest
from mock import MagicMock

from mpflash.db.gather_boards import package_repo


@pytest.mark.slow
def test_package_repo(mocker, pytestconfig, tmp_path):
    """
    Test the package_repo function.
    """
    # Mock the location
    mocker.patch("mpflash.db.gather_boards.HERE", tmp_path)
    # create empty database

    repo_path = pytestconfig.rootpath / "repos/micropython"
    if not repo_path.exists():
        pytest.skip(f"Repository {repo_path} not found")
    package_repo(repo_path)
    check_path = tmp_path / "micropython_boards.zip"
    assert check_path.is_file(), f"Failed to create {check_path}"

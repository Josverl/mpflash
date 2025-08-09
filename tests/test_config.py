"""Tests for mpflash.config module."""

import os
from pathlib import Path

import pytest

from mpflash.config import MPFlashConfig, get_version
from mpflash.errors import MPFlashError


def test_get_version_returns_string(mocker):
    """Test that get_version returns a version string."""
    mock_version = mocker.patch("mpflash.config.version", return_value="1.0.0")
    
    result = get_version()
    
    assert result == "1.0.0"
    mock_version.assert_called_once_with("mpflash")


def test_config_initialization():
    """Test default configuration values."""
    config = MPFlashConfig()
    
    assert config.quiet is False
    assert config.verbose is False
    assert config.usb is False
    assert config.ignore_ports == []
    assert config._firmware_folder is None
    assert config.tests == []
    assert config._interactive is True
    assert config._gh_client is None


def test_interactive_property_normal(mocker):
    """Test interactive property in normal environment."""
    config = MPFlashConfig()
    
    mocker.patch.dict(os.environ, {}, clear=True)
    assert config.interactive is True


def test_interactive_property_github_actions(mocker):
    """Test interactive property in GitHub Actions environment."""
    config = MPFlashConfig()
    mock_log = mocker.patch("mpflash.logger.log")
    
    mocker.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"})
    result = config.interactive
    
    assert result is False
    mock_log.warning.assert_called_once_with("Disabling interactive mode in CI")


@pytest.mark.parametrize("value,expected", [
    (False, False),
    (True, True),
])
def test_interactive_setter(value, expected):
    """Test interactive property setter."""
    config = MPFlashConfig()
    
    config.interactive = value
    assert config._interactive == expected


def test_firmware_folder_default(mocker):
    """Test firmware folder with default behavior."""
    config = MPFlashConfig()
    mock_log = mocker.patch("mpflash.logger.log")
    mock_downloads = mocker.patch("platformdirs.user_downloads_path")

    # Create a real Path object for downloads directory
    mock_downloads_path = Path("/mock/downloads")
    mock_downloads.return_value = mock_downloads_path

    # Mock the Path.exists and mkdir methods
    mock_exists = mocker.patch("pathlib.Path.exists", return_value=False)
    mock_is_dir = mocker.patch("pathlib.Path.is_dir", return_value=True)
    mock_mkdir = mocker.patch("pathlib.Path.mkdir")

    mocker.patch.dict("os.environ", {}, clear=True)
    result = config.firmware_folder

    expected_path = mock_downloads_path / "firmware"
    assert result == expected_path
    mock_log.info.assert_called_once()



def test_firmware_folder_invalid_environment_variable(mocker, tmp_path):
    """Test firmware folder with invalid environment variable."""
    config = MPFlashConfig()
    mock_log = mocker.patch("mpflash.logger.log")
    invalid_path = tmp_path / "non_existent"
    
    mock_downloads = mocker.patch("platformdirs.user_downloads_path")
    mock_downloads_path = Path("/mock/downloads")
    mock_downloads.return_value = mock_downloads_path

    # Mock Path operations
    mock_exists = mocker.patch("pathlib.Path.exists", return_value=False)
    mock_is_dir = mocker.patch("pathlib.Path.is_dir", return_value=True)
    mock_mkdir = mocker.patch("pathlib.Path.mkdir")

    mocker.patch.dict("os.environ", {"MPFLASH_FIRMWARE": str(invalid_path)})
    result = config.firmware_folder
    
    mock_log.warning.assert_called_once()
    assert "invalid directory" in mock_log.warning.call_args[0][0]


def test_firmware_folder_github_actions(mocker, tmp_path):
    """Test firmware folder in GitHub Actions environment."""
    config = MPFlashConfig()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    
    mocker.patch.dict(os.environ, {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKSPACE": str(workspace_dir)
    })
    mock_print = mocker.patch("builtins.print")
    
    result = config.firmware_folder
    
    expected_path = workspace_dir / "firmware"
    assert result == expected_path
    assert expected_path.exists()
    mock_print.assert_called_once()


def test_firmware_folder_not_directory_error(mocker, tmp_path):
    """Test firmware folder when path is not a directory."""
    config = MPFlashConfig()
    # Create a file instead of directory
    firmware_file = tmp_path / "firmware_file"
    firmware_file.write_text("test")
    
    mock_downloads = mocker.patch("platformdirs.user_downloads_path")
    mock_downloads.return_value = tmp_path
    
    mocker.patch.dict(os.environ, {}, clear=True)
    # Mock the path operations
    mock_truediv = mocker.patch.object(Path, "__truediv__")
    mock_firmware_path = mocker.Mock()
    mock_firmware_path.exists.return_value = True
    mock_firmware_path.is_dir.return_value = False
    mock_firmware_path.mkdir = mocker.Mock()
    mock_truediv.return_value = mock_firmware_path
    
    with pytest.raises(MPFlashError, match="is not a directory"):
        config.firmware_folder


@pytest.mark.parametrize("path_exists", [True, False])
def test_firmware_folder_setter_valid(tmp_path, path_exists):
    """Test firmware folder setter with valid directory."""
    config = MPFlashConfig()
    firmware_dir = tmp_path / "test_firmware"
    if path_exists:
        firmware_dir.mkdir()
        config.firmware_folder = firmware_dir
        assert config._firmware_folder == firmware_dir
    else:
        with pytest.raises(ValueError, match="Invalid firmware folder"):
            config.firmware_folder = firmware_dir


def test_db_path_property(tmp_path):
    """Test db_path property."""
    config = MPFlashConfig()
    firmware_dir = tmp_path / "firmware"
    firmware_dir.mkdir()
    config._firmware_folder = firmware_dir
    
    result = config.db_path
    
    assert result == firmware_dir / "mpflash.db"


def test_db_version_property():
    """Test db_version property."""
    config = MPFlashConfig()
    
    result = config.db_version
    
    assert result == "1.24.1"


@pytest.mark.parametrize("env_token,expected_token", [
    (None, None),  # Will use default PAT
    ("test_token", "test_token"),
])
def test_gh_client_property_tokens(mocker, env_token, expected_token):
    """Test gh_client property with different token sources."""
    config = MPFlashConfig()
    mock_github = mocker.patch("github.Github")
    mock_auth = mocker.patch("github.Auth")
    
    env_dict = {}
    if env_token:
        env_dict["GITHUB_TOKEN"] = env_token
    
    mocker.patch.dict(os.environ, env_dict, clear=True)
    result = config.gh_client
    
    mock_auth.Token.assert_called_once()
    if expected_token:
        mock_auth.Token.assert_called_with(expected_token)
    mock_github.assert_called_once()
    assert result == mock_github.return_value


def test_gh_client_property_cached(mocker):
    """Test that gh_client property is cached."""
    config = MPFlashConfig()
    mock_github = mocker.patch("github.Github")
    mock_auth = mocker.patch("github.Auth")
    
    # First access
    result1 = config.gh_client
    # Second access
    result2 = config.gh_client
    
    # Should only create client once
    assert mock_github.call_count == 1
    assert result1 == result2

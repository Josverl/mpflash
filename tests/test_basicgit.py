"""Tests for mpflash.basicgit module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from mpflash.basicgit import (
    _run_local_git,
    checkout_tag,
    clone,
    get_git_describe,
    get_local_tag,
    get_remote_tags,
)


class TestRunLocalGit:
    """Test cases for _run_local_git function."""

    def test_run_local_git_success(self, mocker):
        """Test successful git command execution."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = "success"

        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        result = _run_local_git(["git", "status"])

        assert result == mock_result
        mock_run.assert_called_once()

    def test_run_local_git_with_repo_path(self, mocker, tmp_path):
        """Test git command execution with repository path."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = "success"

        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        result = _run_local_git(["git", "status"], repo=tmp_path)

        assert result == mock_result
        mock_run.assert_called_once_with(
            ["git", "status"], capture_output=True, check=True, cwd=tmp_path.absolute().as_posix(), encoding="utf-8"
        )

    def test_run_local_git_not_a_directory_error(self, mocker):
        """Test handling of NotADirectoryError."""
        mock_log = mocker.patch("mpflash.basicgit.log")
        mocker.patch("subprocess.run", side_effect=NotADirectoryError("test error"))

        result = _run_local_git(["git", "status"])

        assert result is None
        mock_log.error.assert_called_once()

    def test_run_local_git_called_process_error(self, mocker):
        """Test handling of CalledProcessError."""
        mock_log = mocker.patch("mpflash.basicgit.log")
        error = subprocess.CalledProcessError(1, ["git", "status"])
        error.stdout = "stdout"
        error.stderr = "stderr"
        mocker.patch("subprocess.run", side_effect=error)

        result = _run_local_git(["git", "status"])

        assert result is None
        mock_log.error.assert_called_once()

    def test_run_local_git_with_stderr_warning(self, mocker):
        """Test handling of stderr with warnings."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = "warning: some warning"
        mock_result.stdout = "success"

        mock_log = mocker.patch("mpflash.basicgit.log")
        mocker.patch("subprocess.run", return_value=mock_result)

        result = _run_local_git(["git", "status"])

        assert result == mock_result
        mock_log.warning.assert_called_once()


class TestClone:
    """Test cases for clone function."""

    def test_clone_success(self, mocker, tmp_path):
        """Test successful repository cloning."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run_git.return_value = mock_result

        result = clone("https://github.com/user/repo.git", tmp_path)

        assert result is True
        mock_run_git.assert_called_once()

    def test_clone_with_shallow(self, mocker, tmp_path):
        """Test cloning with shallow option."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run_git.return_value = mock_result

        result = clone("https://github.com/user/repo.git", tmp_path, shallow=True)

        assert result is True
        # Check that --depth 1 was included in the command
        called_args = mock_run_git.call_args[0][0]
        assert "--depth" in called_args
        assert "1" in called_args

    def test_clone_with_tag(self, mocker, tmp_path):
        """Test cloning with specific tag."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run_git.return_value = mock_result

        result = clone("https://github.com/user/repo.git", tmp_path, tag="v1.0.0")

        assert result is True
        # Check that --branch tag was included in the command
        called_args = mock_run_git.call_args[0][0]
        assert "--branch" in called_args
        assert "v1.0.0" in called_args

    def test_clone_preview_tag_ignored(self, mocker, tmp_path):
        """Test that preview tags are ignored."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run_git.return_value = mock_result

        result = clone("https://github.com/user/repo.git", tmp_path, tag="preview")

        assert result is True
        # Check that --branch was not included for preview tag
        called_args = mock_run_git.call_args[0][0]
        assert "--branch" not in called_args

    def test_clone_failure(self, mocker, tmp_path):
        """Test failed repository cloning."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_run_git.return_value = None

        result = clone("https://github.com/user/repo.git", tmp_path)

        assert result is False


class TestGetLocalTag:
    """Test cases for get_local_tag function."""

    def test_get_local_tag_success(self, mocker):
        """Test successful tag retrieval."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.stdout = "v1.20.0"
        mock_run_git.return_value = mock_result

        result = get_local_tag()

        assert result == "v1.20.0"

    def test_get_local_tag_with_repo_path(self, mocker, tmp_path):
        """Test tag retrieval with specific repository path."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.stdout = "v1.20.0"
        mock_run_git.return_value = mock_result

        result = get_local_tag(tmp_path)

        assert result == "v1.20.0"
        # Check that the correct path was passed
        mock_run_git.assert_called_once()

    def test_get_local_tag_no_result(self, mocker):
        """Test tag retrieval when git command fails."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_run_git.return_value = None

        result = get_local_tag()

        assert result is None


class TestGetGitDescribe:
    """Test cases for get_git_describe function."""

    def test_get_git_describe_success(self, mocker):
        """Test successful git describe."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.stdout = "v1.20.0-10-gabcdef"
        mock_run_git.return_value = mock_result

        result = get_git_describe()

        assert result == "v1.20.0-10-gabcdef"

    def test_get_git_describe_with_repo(self, mocker, tmp_path):
        """Test git describe with repository path."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.stdout = "v1.20.0-10-gabcdef"
        mock_run_git.return_value = mock_result

        result = get_git_describe(tmp_path)

        assert result == "v1.20.0-10-gabcdef"

    def test_get_git_describe_failure(self, mocker):
        """Test git describe failure."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_run_git.return_value = None

        result = get_git_describe()

        assert result is None


class TestCheckoutTag:
    """Test cases for checkout_tag function."""

    def test_checkout_tag_success(self, mocker, tmp_path):
        """Test successful tag checkout."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run_git.return_value = mock_result

        result = checkout_tag("v1.20.0", tmp_path)

        assert result is True

    def test_checkout_tag_failure(self, mocker, tmp_path):
        """Test failed tag checkout."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_run_git.return_value = None

        result = checkout_tag("v1.20.0", tmp_path)

        assert result is False

    def test_checkout_tag_nonzero_return(self, mocker, tmp_path):
        """Test tag checkout with non-zero return code."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.returncode = 1
        mock_run_git.return_value = mock_result

        result = checkout_tag("v1.20.0", tmp_path)

        assert result is False


class TestGetRemoteTags:
    """Test cases for get_remote_tags function."""

    def test_get_remote_tags_success(self, mocker):
        """Test successful remote tags retrieval."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.stdout = "v1.19.0\nv1.20.0\nv1.21.0"
        mock_run_git.return_value = mock_result

        result = get_remote_tags("https://github.com/user/repo.git")

        expected = ["v1.19.0", "v1.20.0", "v1.21.0"]
        assert result == expected

    def test_get_remote_tags_empty_result(self, mocker):
        """Test remote tags with empty result."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.stdout = ""
        mock_run_git.return_value = mock_result

        result = get_remote_tags("https://github.com/user/repo.git")

        assert result == []

    def test_get_remote_tags_failure(self, mocker):
        """Test remote tags retrieval failure."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_run_git.return_value = None

        result = get_remote_tags("https://github.com/user/repo.git")

        assert result == []

    def test_get_remote_tags_with_whitespace(self, mocker):
        """Test remote tags with whitespace in output."""
        mock_run_git = mocker.patch("mpflash.basicgit._run_local_git")
        mock_result = Mock()
        mock_result.stdout = "  v1.19.0  \n  v1.20.0  \n  v1.21.0  "
        mock_run_git.return_value = mock_result

        result = get_remote_tags("https://github.com/user/repo.git")

        expected = ["v1.19.0", "v1.20.0", "v1.21.0"]
        assert result == expected

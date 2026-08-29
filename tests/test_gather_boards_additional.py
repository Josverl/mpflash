"""
Additional tests for gather_boards.py to improve coverage.

These tests focus on edge cases and functionality that may not be fully covered
by the existing tests.
"""

from unittest.mock import MagicMock, patch

import pytest

from mpflash.db.gather_boards import boardlist_from_repo, package_repo, write_hash_file


class TestWriteHashFile:
    """Test cases for write_hash_file function."""

    def test_write_hash_file_creates_correct_content(self, tmp_path):
        """Test that write_hash_file creates the correct file content."""
        boards_hash = "abc123"

        write_hash_file(boards_hash, tmp_path)

        hash_file = tmp_path / "boards_hash.txt"
        assert hash_file.exists(), "Hash file should be created"

        content = hash_file.read_text(encoding="utf-8")
        assert content == "abc123\n", "File should contain hash with newline"

    def test_write_hash_file_overwrites_existing(self, tmp_path):
        """Test that write_hash_file overwrites existing hash file."""
        hash_file = tmp_path / "boards_hash.txt"
        hash_file.write_text("old-hash\n")

        write_hash_file("new-hash", tmp_path)

        assert hash_file.read_text(encoding="utf-8") == "new-hash\n"

    def test_write_hash_file_handles_long_hash(self, tmp_path):
        """Test that write_hash_file preserves a full SHA-256 digest."""
        boards_hash = "a" * 64

        write_hash_file(boards_hash, tmp_path)

        hash_file = tmp_path / "boards_hash.txt"
        assert hash_file.read_text(encoding="utf-8") == boards_hash + "\n"


class TestPackageRepoErrorHandling:
    """Test error handling in package_repo function."""

    @patch("mpflash.db.gather_boards.micropython_versions")
    @patch("mpflash.db.gather_boards.log")
    def test_package_repo_no_versions_found(self, mock_log, mock_versions, tmp_path):
        """Test package_repo when no MicroPython versions are found."""
        mock_versions.return_value = []  # No versions found

        # Function should return early without processing
        package_repo(tmp_path)

        mock_log.error.assert_called_with("No Micropython versions found")

    @patch("mpflash.db.gather_boards.micropython_versions")
    @patch("mpflash.db.gather_boards.boardlist_from_repo")
    @patch("mpflash.db.gather_boards.create_zip_file")
    @patch("mpflash.db.gather_boards.write_hash_file")
    @patch("mpflash.db.gather_boards.HERE")
    @patch("mpflash.db.gather_boards.log")
    def test_package_repo_zip_file_creation_assertion(
        self, mock_log, mock_here, mock_write_hash, mock_create_zip, mock_boardlist, mock_versions, tmp_path
    ):
        """Test that package_repo assertion works when zip file creation fails."""
        mock_here.__truediv__ = lambda self, other: tmp_path / other
        mock_versions.return_value = ["v1.26.0"]
        mock_boardlist.return_value = [("v1.26", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        with pytest.raises(AssertionError, match="Failed to create"):
            package_repo(tmp_path)

    @patch("mpflash.db.gather_boards.micropython_versions")
    @patch("mpflash.db.gather_boards.boardlist_from_repo")
    @patch("mpflash.db.gather_boards.create_zip_file")
    @patch("mpflash.db.gather_boards.write_hash_file")
    @patch("mpflash.db.gather_boards.HERE")
    def test_package_repo_success_with_mocked_components(
        self, mock_here, mock_write_hash, mock_create_zip, mock_boardlist, mock_versions, tmp_path
    ):
        """Test successful package_repo execution with all components mocked."""
        mock_here.__truediv__ = lambda self, other: tmp_path / other
        mock_versions.return_value = ["v1.25.0", "v1.26.0"]
        mock_create_zip.return_value = "generated-hash"
        mock_boardlist.return_value = [
            ("v1.25", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython"),
            ("v1.26", "board2", "board2", "rp2", "", "rp2", "path2", "desc2", "micropython"),
        ]

        # Create the zip file to satisfy the assertion
        zip_file_path = tmp_path / "micropython_boards.zip"
        zip_file_path.touch()

        package_repo(tmp_path / "test_repo")

        # Verify function calls
        mock_versions.assert_called_once_with(minver="1.18")
        mock_boardlist.assert_called_once_with(versions=["v1.25.0", "v1.26.0"], mpy_dir=tmp_path / "test_repo")
        mock_create_zip.assert_called_once()
        mock_write_hash.assert_called_once_with("generated-hash", mock_here)


class TestBoardlistFromRepoEdgeCases:
    """Test edge cases for boardlist_from_repo function."""

    @patch("mpflash.db.gather_boards.git")
    @patch("mpflash.db.gather_boards.Database")
    @patch("mpflash.db.gather_boards.iter_boards")
    @patch("mpflash.db.gather_boards.log")
    def test_boardlist_from_repo_git_fetch_fails(self, mock_log, mock_iter_boards, mock_database_class, mock_git, tmp_path):
        """Test behavior when git fetch fails."""
        mock_git.fetch.side_effect = Exception("Git fetch failed")
        mock_git.pull.return_value = True
        mock_git.checkout_tag.return_value = True
        mock_git.get_git_describe.return_value = "v1.26.0"

        mock_db = MagicMock()
        mock_db.boards = {"board1": MagicMock()}
        mock_database_class.return_value = mock_db
        mock_iter_boards.return_value = [("v1.26", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        # Git fetch failure should propagate as an exception
        with pytest.raises(Exception, match="Git fetch failed"):
            boardlist_from_repo(["v1.26.0"], tmp_path)

    @patch("mpflash.db.gather_boards.git")
    @patch("mpflash.db.gather_boards.Database")
    @patch("mpflash.db.gather_boards.iter_boards")
    def test_boardlist_from_repo_multiple_versions_partial_failure(self, mock_iter_boards, mock_database_class, mock_git, tmp_path):
        """Test handling when some versions fail checkout but others succeed."""
        # First version fails, second succeeds
        mock_git.checkout_tag.side_effect = [False, True]
        mock_git.get_git_describe.return_value = "v1.26.0"

        mock_db = MagicMock()
        mock_db.boards = {"board1": MagicMock()}
        mock_database_class.return_value = mock_db
        mock_iter_boards.return_value = [("v1.26", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        result = boardlist_from_repo(["v1.25.0", "v1.26.0"], tmp_path)

        # Should have results only from the successful version
        assert len(result) == 1
        assert result[0][0] == "v1.26"

    @patch("mpflash.db.gather_boards.git")
    @patch("mpflash.db.gather_boards.Database")
    @patch("mpflash.db.gather_boards.iter_boards")
    def test_boardlist_from_repo_preview_version_with_describe_parsing(self, mock_iter_boards, mock_database_class, mock_git, tmp_path):
        """Test preview version handling with git describe parsing."""
        mock_git.checkout_tag.return_value = True
        mock_git.get_git_describe.return_value = "v1.26.0-preview-15-gabcdef123"

        mock_db = MagicMock()
        mock_db.boards = {"board1": MagicMock()}
        mock_database_class.return_value = mock_db
        mock_iter_boards.return_value = [("v1.26-preview", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        result = boardlist_from_repo(["v1.26.0-preview"], tmp_path)

        # Should checkout master for preview versions
        mock_git.checkout_tag.assert_called_with("master", tmp_path)
        assert len(result) == 1

    @patch("mpflash.db.gather_boards.git")
    @patch("mpflash.db.gather_boards.Database")
    @patch("mpflash.db.gather_boards.iter_boards")
    def test_boardlist_from_repo_database_initialization_error(self, mock_iter_boards, mock_database_class, mock_git, tmp_path):
        """Test handling when Database initialization fails."""
        mock_git.checkout_tag.return_value = True
        mock_git.get_git_describe.return_value = "v1.26.0"

        # Database initialization fails
        mock_database_class.side_effect = Exception("Database init failed")

        # Should handle the exception gracefully
        with pytest.raises(Exception, match="Database init failed"):
            boardlist_from_repo(["v1.26.0"], tmp_path)


class TestCreateZipFileEdgeCases:
    """Test edge cases for create_zip_file function."""

    def test_create_zip_file_with_unicode_content(self, tmp_path):
        """Test create_zip_file with unicode characters in board data."""
        from mpflash.db.gather_boards import create_zip_file

        zip_file = tmp_path / "unicode_test.zip"
        longlist = [
            ("v1.26", "board_ñ", "Board Ñoño", "esp32", "", "esp32", "path/ñ", "Descripción ñoño", "micropython"),
            ("v1.26", "board_中", "Board 中文", "rp2", "", "rp2", "path/中", "Description 中文", "micropython"),
        ]

        create_zip_file(longlist, zip_file)

        assert zip_file.exists()

        # Verify the ZIP file can be read and contains the unicode content
        import zipfile

        with zipfile.ZipFile(zip_file, "r") as zf:
            csv_content = zf.read("micropython_boards.csv").decode("utf-8")
            assert "board_ñ" in csv_content
            assert "Descripción ñoño" in csv_content
            assert "board_中" in csv_content
            assert "Description 中文" in csv_content

    def test_create_zip_file_large_dataset(self, tmp_path):
        """Test create_zip_file with a large number of boards."""
        from mpflash.db.gather_boards import create_zip_file

        zip_file = tmp_path / "large_test.zip"

        # Create a large dataset
        longlist = []
        for i in range(1000):
            longlist.append(
                (
                    f"v1.{i // 100}.{i % 100}",
                    f"board_{i}",
                    f"Board {i}",
                    "esp32",
                    f"variant_{i}" if i % 3 == 0 else "",
                    "esp32",
                    f"path/board_{i}",
                    f"Description for board {i}",
                    "micropython",
                )
            )

        create_zip_file(longlist, zip_file)

        assert zip_file.exists()

        # Verify the content
        import zipfile

        with zipfile.ZipFile(zip_file, "r") as zf:
            csv_content = zf.read("micropython_boards.csv").decode("utf-8")
            lines = csv_content.strip().split("\n")
            assert len(lines) == 1001  # header + 1000 data lines
            assert "board_999" in csv_content

    def test_create_zip_file_permission_error(self, tmp_path):
        """Test create_zip_file behavior when file cannot be written."""
        import os
        import sys

        from mpflash.db.gather_boards import create_zip_file

        # Create a directory and a file
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        zip_file = test_dir / "test.zip"

        longlist = [("v1.26", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        # On Windows, we need a different approach
        if sys.platform == "win32":
            # Create the file first and make it read-only
            zip_file.touch()
            # Set file as read-only
            import stat

            os.chmod(zip_file, stat.S_IREAD)

            try:
                # Should raise a permission error when trying to overwrite read-only file
                with pytest.raises(PermissionError):
                    create_zip_file(longlist, zip_file)
            finally:
                # Clean up - restore write permissions
                os.chmod(zip_file, stat.S_IWRITE | stat.S_IREAD)
        else:
            # On Unix-like systems, use directory permissions
            test_dir.chmod(0o444)  # Read-only directory

            try:
                # Should raise a permission error
                with pytest.raises(PermissionError):
                    create_zip_file(longlist, zip_file)
            finally:
                # Clean up - restore write permissions
                test_dir.chmod(0o755)

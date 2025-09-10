"""
Additional tests for gather_boards.py to improve coverage.

These tests focus on edge cases and functionality that may not be fully covered 
by the existing tests.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import tempfile

from mpflash.db.gather_boards import (
    write_version_file, 
    package_repo,
    boardlist_from_repo
)


class TestWriteVersionFile:
    """Test cases for write_version_file function."""
    
    def test_write_version_file_creates_correct_content(self, tmp_path):
        """Test that write_version_file creates the correct file content."""
        version = "v1.26.0"
        
        write_version_file(version, tmp_path)
        
        version_file = tmp_path / "boards_version.txt"
        assert version_file.exists(), "Version file should be created"
        
        content = version_file.read_text(encoding="utf-8")
        assert content == "v1.26.0\n", "File should contain version with newline"
    
    def test_write_version_file_overwrites_existing(self, tmp_path):
        """Test that write_version_file overwrites existing version file."""
        version_file = tmp_path / "boards_version.txt"
        version_file.write_text("old_version\n")
        
        new_version = "v1.27.0"
        write_version_file(new_version, tmp_path)
        
        content = version_file.read_text(encoding="utf-8")
        assert content == "v1.27.0\n", "File should be overwritten with new version"
    
    def test_write_version_file_handles_special_characters(self, tmp_path):
        """Test that write_version_file handles versions with special characters."""
        version = "v1.26.0-preview.123"
        
        write_version_file(version, tmp_path)
        
        version_file = tmp_path / "boards_version.txt"
        content = version_file.read_text(encoding="utf-8")
        assert content == "v1.26.0-preview.123\n"


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
    @patch("mpflash.db.gather_boards.write_version_file")
    @patch("mpflash.db.gather_boards.HERE")
    @patch("mpflash.db.gather_boards.log")
    def test_package_repo_zip_file_creation_assertion(
        self, mock_log, mock_here, mock_write_version, mock_create_zip, 
        mock_boardlist, mock_versions, tmp_path
    ):
        """Test that package_repo assertion works when zip file creation fails."""
        mock_here.__truediv__ = lambda self, other: tmp_path / other
        mock_versions.return_value = ["v1.26.0"]
        mock_boardlist.return_value = [("v1.26", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]
        
        # Don't actually create the zip file, so the assertion should fail
        zip_file_path = tmp_path / "micropython_boards.zip"
        
        with pytest.raises(AssertionError, match="Failed to create"):
            package_repo(tmp_path)
    
    @patch("mpflash.db.gather_boards.micropython_versions")
    @patch("mpflash.db.gather_boards.boardlist_from_repo")
    @patch("mpflash.db.gather_boards.create_zip_file")
    @patch("mpflash.db.gather_boards.write_version_file")
    @patch("mpflash.db.gather_boards.HERE")
    def test_package_repo_success_with_mocked_components(
        self, mock_here, mock_write_version, mock_create_zip, 
        mock_boardlist, mock_versions, tmp_path
    ):
        """Test successful package_repo execution with all components mocked."""
        mock_here.__truediv__ = lambda self, other: tmp_path / other
        mock_versions.return_value = ["v1.25.0", "v1.26.0"]
        mock_boardlist.return_value = [
            ("v1.25", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython"),
            ("v1.26", "board2", "board2", "rp2", "", "rp2", "path2", "desc2", "micropython")
        ]
        
        # Create the zip file to satisfy the assertion
        zip_file_path = tmp_path / "micropython_boards.zip"
        zip_file_path.touch()
        
        package_repo(tmp_path / "test_repo")
        
        # Verify function calls
        mock_versions.assert_called_once_with(minver="1.18")
        mock_boardlist.assert_called_once_with(
            versions=["v1.25.0", "v1.26.0"],
            mpy_dir=tmp_path / "test_repo"
        )
        mock_create_zip.assert_called_once()
        mock_write_version.assert_called_once_with("v1.26.0", mock_here)


class TestBoardlistFromRepoEdgeCases:
    """Test edge cases for boardlist_from_repo function."""
    
    @patch("mpflash.db.gather_boards.git")
    @patch("mpflash.db.gather_boards.Database")
    @patch("mpflash.db.gather_boards.iter_boards")
    @patch("mpflash.db.gather_boards.log")
    def test_boardlist_from_repo_git_fetch_fails(
        self, mock_log, mock_iter_boards, mock_database_class, mock_git, tmp_path
    ):
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
    def test_boardlist_from_repo_multiple_versions_partial_failure(
        self, mock_iter_boards, mock_database_class, mock_git, tmp_path
    ):
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
    def test_boardlist_from_repo_preview_version_with_describe_parsing(
        self, mock_iter_boards, mock_database_class, mock_git, tmp_path
    ):
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
    def test_boardlist_from_repo_database_initialization_error(
        self, mock_iter_boards, mock_database_class, mock_git, tmp_path
    ):
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
            ("v1.26", "board_中", "Board 中文", "rp2", "", "rp2", "path/中", "Description 中文", "micropython")
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
            longlist.append((
                f"v1.{i//100}.{i%100}", 
                f"board_{i}", 
                f"Board {i}", 
                "esp32", 
                f"variant_{i}" if i % 3 == 0 else "", 
                "esp32", 
                f"path/board_{i}", 
                f"Description for board {i}", 
                "micropython"
            ))
        
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
        from mpflash.db.gather_boards import create_zip_file
        
        # Create a read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only
        
        zip_file = readonly_dir / "test.zip"
        longlist = [("v1.26", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]
        
        # Should raise a permission error
        with pytest.raises(PermissionError):
            create_zip_file(longlist, zip_file)
        
        # Clean up - restore write permissions
        readonly_dir.chmod(0o755)
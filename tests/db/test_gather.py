import zipfile
from pathlib import Path

import pytest

from mpflash.db.gather_boards import boardlist_from_repo, create_zip_file, iter_boards, package_repo


@pytest.fixture
def mock_board(mocker):
    """Create a mock board for testing."""
    board = mocker.Mock()
    board.name = "test_board"
    board.mcu = "esp32"
    board.port = mocker.Mock()
    board.port.name = "esp32"
    board.path = "/path/to/micropython/ports/esp32/boards/test_board"
    board.description = "Test board description"
    board.variants = None
    return board


@pytest.fixture
def mock_database(mocker, mock_board):
    """Create a mock database with a test board."""
    db = mocker.Mock()
    db.boards = {"test_board": mock_board}
    return db


@pytest.fixture
def empty_mock_database(mocker):
    """Create an empty mock database."""
    db = mocker.Mock()
    db.boards = {}
    return db


class TestIterBoards:
    """Test cases for iter_boards function."""

    def test_iter_boards_empty_database(self, empty_mock_database):
        """Test iter_boards with empty database."""
        result = list(iter_boards(empty_mock_database, "v1.20"))
        assert result == []

    def test_iter_boards_single_board_no_variants(self, mock_database):
        """Test iter_boards with single board without variants."""
        result = list(iter_boards(mock_database, "v1.20"))
        expected = [
            (
                "v1.20",
                "test_board",
                "test_board",
                "esp32",
                "",
                "esp32",
                "ports/esp32/boards/test_board",
                "Test board description",
                "micropython",
            )
        ]
        assert result == expected

    def test_iter_boards_with_variants(self, mocker):
        """Test iter_boards with board having variants."""
        mock_variant = mocker.Mock()
        mock_variant.name = "variant1"
        mock_variant.description = "Variant 1 description"

        mock_board = mocker.Mock()
        mock_board.name = "test_board"
        mock_board.mcu = "esp32"
        mock_board.port = mocker.Mock()
        mock_board.port.name = "esp32"
        mock_board.path = "/path/to/micropython/ports/esp32/boards/test_board"
        mock_board.description = "Test board description"
        mock_board.variants = [mock_variant]

        mock_db = mocker.Mock()
        mock_db.boards = {"test_board": mock_board}

        result = list(iter_boards(mock_db, "v1.20"))

        assert len(result) == 2
        # Check base board
        assert result[0][1] == "test_board"
        assert result[0][4] == ""  # no variant
        # Check variant
        assert result[1][1] == "test_board-variant1"
        assert result[1][4] == "variant1"  # variant name

    def test_iter_boards_no_port(self, mocker):
        """Test iter_boards with board having no port."""
        mock_board = mocker.Mock()
        mock_board.name = "test_board"
        mock_board.mcu = "esp32"
        mock_board.port = None
        mock_board.path = "/path/to/micropython/ports/esp32/boards/test_board"
        mock_board.description = "Test board description"
        mock_board.variants = None

        mock_db = mocker.Mock()
        mock_db.boards = {"test_board": mock_board}

        result = list(iter_boards(mock_db, "v1.20"))
        assert result[0][5] == ""  # empty port name

    @pytest.mark.parametrize(
        "version_input,expected_version",
        [
            ("v1.20", "v1.20"),
            ("  v1.21  ", "v1.21"),
            ("\tv1.22\n", "v1.22"),
            ("", ""),
        ],
    )
    def test_iter_boards_version_handling(self, mock_database, version_input, expected_version):
        """Test that iter_boards handles version strings correctly."""
        result = list(iter_boards(mock_database, version_input))
        assert result[0][0] == expected_version


class TestBoardlistFromRepo:
    """Test cases for boardlist_from_repo function."""

    def test_boardlist_from_repo_nonexistent_dir(self, tmp_path, mocker):
        """Test boardlist_from_repo with non-existent directory."""
        mock_log = mocker.patch("mpflash.db.gather_boards.log")
        nonexistent_dir = tmp_path / "nonexistent"

        result = boardlist_from_repo(["v1.20"], nonexistent_dir)

        assert result == []
        mock_log.error.assert_called_once()

    def test_boardlist_from_repo_git_checkout_fails(self, tmp_path, mocker):
        """Test boardlist_from_repo when git checkout fails."""
        mock_git = mocker.patch("mpflash.db.gather_boards.git")
        mock_git.checkout_tag.return_value = False
        mock_log = mocker.patch("mpflash.db.gather_boards.log")

        result = boardlist_from_repo(["v1.20"], tmp_path)

        assert result == []
        mock_log.warning.assert_called_once()

    def test_boardlist_from_repo_success(self, tmp_path, mocker):
        """Test successful boardlist_from_repo execution."""
        # Mock git operations
        mock_git = mocker.patch("mpflash.db.gather_boards.git")
        mock_git.checkout_tag.return_value = True
        mock_git.get_git_describe.return_value = "v1.20.0-10-gabcdef"

        # Mock Database
        mock_database_class = mocker.patch("mpflash.db.gather_boards.Database")
        mock_db = mocker.Mock()
        mock_db.boards = {"board1": mocker.Mock(), "board2": mocker.Mock()}
        mock_database_class.return_value = mock_db

        # Mock iter_boards
        mock_iter_boards = mocker.patch("mpflash.db.gather_boards.iter_boards")
        mock_iter_boards.return_value = [("v1.20", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        mock_log = mocker.patch("mpflash.db.gather_boards.log")

        result = boardlist_from_repo(["v1.20"], tmp_path)

        assert len(result) == 1
        assert result[0][0] == "v1.20"
        mock_git.checkout_tag.assert_called_once_with("v1.20", tmp_path)

    def test_boardlist_from_repo_preview_version(self, tmp_path, mocker):
        """Test boardlist_from_repo with preview version."""
        mock_git = mocker.patch("mpflash.db.gather_boards.git")
        mock_git.checkout_tag.return_value = True
        mock_git.get_git_describe.return_value = "v1.21.0-preview-10-gabcdef"

        mock_database_class = mocker.patch("mpflash.db.gather_boards.Database")
        mock_db = mocker.Mock()
        mock_db.boards = {}
        mock_database_class.return_value = mock_db

        mock_iter_boards = mocker.patch("mpflash.db.gather_boards.iter_boards")
        mock_iter_boards.return_value = []

        boardlist_from_repo(["v1.21.0-preview"], tmp_path)

        # Should checkout master for preview versions
        mock_git.checkout_tag.assert_called_once_with("master", tmp_path)


class TestCreateZipFile:
    """Test cases for create_zip_file function."""

    def test_create_zip_file_success(self, tmp_path):
        """Test successful ZIP file creation."""
        zip_file = tmp_path / "test.zip"
        longlist = [("v1.20", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        create_zip_file(longlist, zip_file)

        assert zip_file.exists()

        # Verify ZIP contents
        with zipfile.ZipFile(zip_file, "r") as zf:
            assert "micropython_boards.csv" in zf.namelist()
            csv_content = zf.read("micropython_boards.csv").decode()
            assert "version,board_id,board_name,mcu,variant,port,path,description,family" in csv_content
            assert "v1.20,board1,board1,esp32,,esp32,path1,desc1,micropython" in csv_content

    def test_create_zip_file_empty_list(self, tmp_path):
        """Test create_zip_file with empty list."""
        zip_file = tmp_path / "empty.zip"

        create_zip_file([], zip_file)

        assert zip_file.exists()

        # Verify ZIP contains CSV header
        with zipfile.ZipFile(zip_file, "r") as zf:
            assert "micropython_boards.csv" in zf.namelist()
            csv_content = zf.read("micropython_boards.csv").decode()
            assert "version,board_id,board_name,mcu,variant,port,path,description,family" in csv_content

    def test_create_zip_file_multiple_boards(self, tmp_path):
        """Test create_zip_file with multiple boards."""
        zip_file = tmp_path / "multi.zip"
        longlist = [
            ("v1.20", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython"),
            ("v1.20", "board2", "board2", "rp2", "", "rp2", "path2", "desc2", "micropython"),
            ("v1.21", "board1-variant", "board1", "esp32", "variant", "esp32", "path1", "variant desc", "micropython"),
        ]

        create_zip_file(longlist, zip_file)

        assert zip_file.exists()

        # Verify ZIP contents
        with zipfile.ZipFile(zip_file, "r") as zf:
            csv_content = zf.read("micropython_boards.csv").decode()
            lines = csv_content.strip().split("\n")
            assert len(lines) == 4  # header + 3 data lines


class TestPackageRepo:
    """Test cases for package_repo function."""

    def test_package_repo_success(self, tmp_path, mocker):
        """Test successful package_repo execution."""
        # Mock HERE to use tmp_path
        mocker.patch("mpflash.db.gather_boards.HERE", tmp_path)

        # Mock dependencies
        mock_versions = mocker.patch("mpflash.db.gather_boards.micropython_versions")
        mock_versions.return_value = ["v1.20.0", "v1.21.0"]

        mock_boardlist = mocker.patch("mpflash.db.gather_boards.boardlist_from_repo")
        mock_boardlist.return_value = [("v1.20", "board1", "board1", "esp32", "", "esp32", "path1", "desc1", "micropython")]

        mock_create_zip = mocker.patch("mpflash.db.gather_boards.create_zip_file")

        mock_log = mocker.patch("mpflash.db.gather_boards.log")

        # Create the expected zip file for the assertion
        zip_file = tmp_path / "micropython_boards.zip"
        zip_file.touch()

        package_repo(tmp_path / "test_repo")

        mock_versions.assert_called_once_with(minver="1.18")
        mock_boardlist.assert_called_once()
        mock_create_zip.assert_called_once()

    def test_package_repo_with_default_path(self, tmp_path, mocker):
        """Test package_repo behavior with default path logic."""
        mocker.patch("mpflash.db.gather_boards.HERE", tmp_path)

        mock_versions = mocker.patch("mpflash.db.gather_boards.micropython_versions")
        mock_versions.return_value = ["1.26.0"]

        mock_boardlist = mocker.patch("mpflash.db.gather_boards.boardlist_from_repo")
        mock_boardlist.return_value = [tuple("v1.26 board1 board1 esp32  esp32 path1 desc1 micropython".split())]

        mock_create_zip = mocker.patch("mpflash.db.gather_boards.create_zip_file")

        # Create the expected zip file for the assertion
        zip_file = tmp_path / "micropython_boards.zip"
        zip_file.touch()

        # Test with a test path (the function handles None internally with 'or' operator)
        test_path = tmp_path / "test_repo"
        test_path.mkdir()
        package_repo(test_path)

        # Should call boardlist_from_repo with the provided path
        mock_boardlist.assert_called_once()

    def test_package_repo_zip_creation_fails(self, tmp_path, mocker):
        """Test package_repo when ZIP file creation fails."""
        mocker.patch("mpflash.db.gather_boards.HERE", tmp_path)

        mock_versions = mocker.patch("mpflash.db.gather_boards.micropython_versions")
        mock_versions.return_value = ["v1.20.0"]

        mock_boardlist = mocker.patch("mpflash.db.gather_boards.boardlist_from_repo")
        mock_boardlist.return_value = []

        mock_create_zip = mocker.patch("mpflash.db.gather_boards.create_zip_file")
        # Don't create the file to simulate failure

        with pytest.raises(AssertionError, match="Failed to create"):
            package_repo(tmp_path / "test_repo")


@pytest.mark.slow
def test_package_repo_integration(mocker, pytestconfig, tmp_path):
    """Integration test for the package_repo function."""
    # Mock the location
    mocker.patch("mpflash.db.gather_boards.HERE", tmp_path)

    repo_path = pytestconfig.rootpath / "repos/micropython"
    if not repo_path.exists():
        pytest.skip(f"Repository {repo_path} not found")

    package_repo(repo_path)
    check_path = tmp_path / "micropython_boards.zip"
    assert check_path.is_file(), f"Failed to create {check_path}"

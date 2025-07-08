# Contributing to MPFlash

Thank you for your interest in contributing to MPFlash! This guide will help you get started with contributing to the project.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Code Style Guidelines](#code-style-guidelines)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Adding Hardware Support](#adding-hardware-support)
- [Documentation](#documentation)
- [Release Process](#release-process)

## Getting Started

### Prerequisites

- Python 3.9.2 or later
- Poetry for dependency management
- Git for version control
- A MicroPython board for testing (optional but recommended)

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/your-username/mpflash.git
   cd mpflash
   ```

3. Add the original repository as upstream:
   ```bash
   git remote add upstream https://github.com/Josverl/mpflash.git
   ```

## Development Setup

### Install Dependencies

```bash
# Install development dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Environment Configuration

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Edit `.env` to set:
```bash
MPFLASH_FIRMWARE=./scratch    # Local firmware storage
PYTHONPATH=src                # For development
```

### Verify Installation

```bash
# Run MPFlash to verify installation
poetry run mpflash --help

# Run tests to ensure everything works
poetry run pytest
```

## Code Style Guidelines

### Python Conventions

MPFlash follows these coding standards:

#### Type Annotations
Always use type annotations for function parameters and return values:

```python
from typing import List, Optional, Dict, Any
from pathlib import Path

def download_firmware(
    board_ids: List[str],
    version: str = "stable",
    firmware_dir: Optional[Path] = None
) -> List[Path]:
    """Download firmware files for specified boards."""
    # Implementation here
    return []
```

#### Docstrings
Use concise docstrings (5-9 lines max) for modules and public methods:

```python
def flash_board(port: str, firmware_path: Path) -> bool:
    """Flash firmware to a MicroPython board.
    
    Args:
        port: Serial port of the target board
        firmware_path: Path to firmware file
        
    Returns:
        True if flashing succeeded, False otherwise
        
    Raises:
        MPFlashError: If flashing fails
    """
    # Implementation here
    return True
```

#### String Formatting
Use f-strings for string formatting:

```python
# Good
log.info(f"Flashing {board_name} on {port}")

# Avoid
log.info("Flashing {} on {}".format(board_name, port))
log.info("Flashing %s on %s" % (board_name, port))
```

#### Naming Conventions
- Variables and functions: `snake_case`
- Classes: `CamelCase`
- Constants: `UPPER_SNAKE_CASE`
- Private attributes: `_leading_underscore`

```python
class FirmwareManager:
    """Manages firmware operations."""
    
    DEFAULT_TIMEOUT = 30.0
    
    def __init__(self, firmware_dir: Path):
        self.firmware_dir = firmware_dir
        self._cache: Optional[Dict[str, Any]] = None
    
    def download_firmware(self, board_id: str) -> Path:
        """Download firmware for specified board."""
        # Implementation here
        return Path()
```

#### Error Handling
Use specific exception types and provide meaningful error messages:

```python
from mpflash.errors import MPFlashError

def validate_board_id(board_id: str) -> None:
    """Validate board identifier format."""
    if not board_id:
        raise MPFlashError("Board ID cannot be empty")
    
    if not board_id.replace("_", "").isalnum():
        raise MPFlashError(f"Invalid board ID format: {board_id}")
```

### Code Quality Tools

Use these tools to maintain code quality:

```bash
# Format code
poetry run black mpflash/

# Sort imports
poetry run isort mpflash/

# Remove unused imports
poetry run autoflake mpflash/ -r --in-place --remove-all-unused-imports

# Type checking
poetry run mypy mpflash/
```

## Testing

### Test Structure

MPFlash uses pytest for testing:

```
tests/
├── conftest.py              # Shared fixtures
├── test_*.py               # Unit tests
├── data/                   # Test data
├── cli/                    # CLI tests
├── db/                     # Database tests
├── flash/                  # Flash implementation tests
└── mpboard_id/             # Board ID tests
```

### Writing Tests

#### Unit Tests
Write focused unit tests for individual functions:

```python
import pytest
from pathlib import Path
from mpflash.download.fwinfo import FirmwareInfo

class TestFirmwareInfo:
    """Test firmware information handling."""
    
    def test_firmware_file_exists(self, tmp_path: Path):
        """Test firmware file existence check."""
        firmware_path = tmp_path / "test.bin"
        firmware_path.write_bytes(b"test firmware")
        
        info = FirmwareInfo(firmware_path)
        assert info.exists()
        assert info.size > 0
    
    def test_firmware_file_missing(self, tmp_path: Path):
        """Test handling of missing firmware file."""
        missing_path = tmp_path / "missing.bin"
        
        info = FirmwareInfo(missing_path)
        assert not info.exists()
        assert info.size == 0
```

#### Parameterized Tests
Use pytest.mark.parametrize for testing multiple inputs:

```python
@pytest.mark.parametrize("version,expected", [
    ("stable", True),
    ("preview", True),
    ("v1.25.0", True),
    ("1.25.0", True),
    ("invalid", False),
    ("", False),
])
def test_version_validation(version: str, expected: bool):
    """Test version string validation."""
    result = validate_version(version)
    assert result == expected
```

#### Database Tests
Use test database for database-related tests:

```python
@pytest.fixture
def test_db_session():
    """Provide test database session."""
    from mpflash.db.core import get_test_database_session
    
    with get_test_database_session() as session:
        yield session

def test_board_creation(test_db_session):
    """Test creating board record."""
    from mpflash.db.models import Board
    
    board = Board(
        board_id="TEST_BOARD",
        version="v1.25.0",
        board_name="Test Board",
        mcu="TestMCU",
        port="test",
        path="test/path",
        description="Test board"
    )
    
    test_db_session.add(board)
    test_db_session.commit()
    
    # Verify board was created
    retrieved = test_db_session.query(Board).filter_by(
        board_id="TEST_BOARD"
    ).first()
    assert retrieved is not None
    assert retrieved.board_name == "Test Board"
```

#### CLI Tests
Test CLI commands using Click's testing utilities:

```python
from click.testing import CliRunner
from mpflash.cli_list import cli_list_mcus

def test_list_command():
    """Test the list command."""
    runner = CliRunner()
    result = runner.invoke(cli_list_mcus, [])
    
    assert result.exit_code == 0
    assert "Connected boards" in result.output
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_download.py

# Run tests with coverage
poetry run pytest --cov=mpflash

# Run tests with verbose output
poetry run pytest -v

# Run tests excluding slow tests
poetry run pytest -m "not basicgit"

# Run tests for specific functionality
poetry run pytest -k "flash"
```

### Test Coverage

Maintain high test coverage:

```bash
# Generate coverage report
poetry run coverage run -m pytest
poetry run coverage html

# View coverage report
open htmlcov/index.html
```

## Submitting Changes

### Branch Naming

Use descriptive branch names:
- `feature/add-board-support-xyz` - New features
- `fix/resolve-flash-timeout` - Bug fixes
- `docs/update-api-reference` - Documentation updates
- `refactor/improve-database-layer` - Code refactoring

### Commit Messages

Write clear, descriptive commit messages:

```bash
# Good commit messages
git commit -m "Add support for STM32H7 boards"
git commit -m "Fix timeout issue in ESP32 flashing"
git commit -m "Update API documentation for board identification"

# Follow conventional commits format
git commit -m "feat: add support for custom firmware variants"
git commit -m "fix: resolve database migration issue"
git commit -m "docs: update contributing guidelines"
```

### Pull Request Process

1. **Update your fork:**
   ```bash
   git checkout main
   git pull upstream main
   git push origin main
   ```

2. **Create feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make changes and commit:**
   ```bash
   # Make your changes
   git add .
   git commit -m "feat: add your feature"
   ```

4. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create Pull Request:**
   - Go to GitHub and create a pull request
   - Fill out the PR template
   - Link any related issues

### Pull Request Checklist

Before submitting, ensure:

- [ ] Code follows style guidelines
- [ ] Tests are written and passing
- [ ] Documentation is updated
- [ ] Type annotations are added
- [ ] No unused imports or variables
- [ ] Commit messages are descriptive
- [ ] Branch is up to date with main

## Adding Hardware Support

### New Board Support

To add support for a new MicroPython board:

1. **Update board database:**
   ```python
   # In mpflash/db/gather_boards.py
   def add_custom_board():
       """Add new board to database."""
       board = Board(
           board_id="NEW_BOARD_ID",
           version="v1.25.0",
           board_name="New Board Name",
           mcu="NewMCU",
           port="newport",
           path="newport/NEW_BOARD",
           description="Description of new board"
       )
       # Add to database
   ```

2. **Add board identification:**
   ```python
   # In mpflash/mpboard_id/
   def identify_new_board(port: str) -> Optional[dict]:
       """Identify new board type."""
       # Implementation for board detection
       return {
           "board_id": "NEW_BOARD_ID",
           "mcu": "NewMCU",
           "port": "newport"
       }
   ```

3. **Write tests:**
   ```python
   def test_new_board_identification():
       """Test identification of new board."""
       # Test implementation
   ```

### New Platform Support

To add support for a new hardware platform:

1. **Create flash implementation:**
   ```python
   # In mpflash/flash/newplatform.py
   from .base import FlashBase
   
   class NewPlatformFlash(FlashBase):
       """Flash implementation for new platform."""
       
       def flash_firmware(self) -> bool:
           """Flash firmware to device."""
           # Platform-specific implementation
           return True
   ```

2. **Add bootloader support:**
   ```python
   # In mpflash/bootloader/newplatform.py
   from .base import BootloaderBase
   
   class NewPlatformBootloader(BootloaderBase):
       """Bootloader for new platform."""
       
       def activate(self) -> bool:
           """Activate bootloader mode."""
           # Implementation
           return True
   ```

3. **Register platform:**
   ```python
   # In mpflash/flash/__init__.py
   from .newplatform import NewPlatformFlash
   
   FLASH_IMPLEMENTATIONS = {
       "newplatform": NewPlatformFlash,
       # ... existing implementations
   }
   ```

4. **Add comprehensive tests:**
   ```python
   # In tests/flash/test_newplatform.py
   def test_new_platform_flash():
       """Test flashing on new platform."""
       # Test implementation
   ```

## Documentation

### Code Documentation

- Add docstrings to all public functions and classes
- Use type annotations consistently
- Include examples in docstrings where helpful
- Document any complex algorithms or business logic

### User Documentation

- Update README.md for user-facing changes
- Add examples to docs/mpflash_api_example.ipynb
- Update command help text for CLI changes

### Developer Documentation

- Update docs/developer.md for architecture changes
- Document new APIs in docs/api-reference.md
- Add troubleshooting sections for common issues

## Release Process

### Version Bumping

MPFlash uses semantic versioning:

```bash
# Patch version (bug fixes)
poetry version patch

# Minor version (new features)
poetry version minor

# Major version (breaking changes)
poetry version major
```

### Changelog

Update the changelog for releases:

```markdown
# Changelog

## [1.26.0] - 2025-01-15

### Added
- Support for new XYZ board family
- Custom firmware variant selection
- Improved error handling in flash operations

### Changed
- Updated database schema for better performance
- Improved board identification accuracy

### Fixed
- Fixed timeout issue with ESP32-S3 boards
- Resolved database migration edge cases
```

### Pre-release Checklist

Before releasing:

- [ ] All tests passing
- [ ] Documentation updated
- [ ] Version bumped appropriately
- [ ] Changelog updated
- [ ] No breaking changes without major version bump

## Getting Help

### Communication Channels

- **GitHub Issues:** For bug reports and feature requests
- **GitHub Discussions:** For questions and general discussion
- **Pull Requests:** For code contributions

### Development Questions

When asking for help:

1. Provide clear description of the issue
2. Include relevant code snippets
3. Mention your development environment
4. Include error messages if applicable
5. Link to relevant documentation

### Code Review

When reviewing code:

- Be constructive and helpful
- Focus on code quality and maintainability
- Test the changes locally when possible
- Provide specific feedback with examples
- Acknowledge good practices

## Recognition

Contributors are recognized in:

- README.md contributors section
- Release notes
- GitHub contributor statistics

Thank you for contributing to MPFlash! Your efforts help make MicroPython development more accessible and efficient for everyone.

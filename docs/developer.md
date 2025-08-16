# MPFlash Developer Documentation

## Overview

MPFlash is a CLI tool for downloading and flashing MicroPython firmware to various microcontrollers. It provides automated firmware management, board identification, and flashing capabilities for multiple hardware platforms.

## Architecture

### Core Components

```
mpflash/
├── cli_*.py          # CLI command implementations
├── db/               # Database models and operations
├── download/         # Firmware download functionality
├── flash/            # Board flashing implementations
├── bootloader/       # Bootloader activation methods
├── mpboard_id/       # Board identification utilities
├── mpremoteboard/    # Remote board communication
└── vendor/           # Third-party code integrations
```

### Key Modules

#### CLI Layer (`cli_*.py`)
- **cli_main.py**: Main entry point and command registration
- **cli_group.py**: Click group configuration and global options
- **cli_list.py**: Board listing functionality
- **cli_download.py**: Firmware download commands
- **cli_flash.py**: Board flashing commands

#### Database Layer (`db/`)
- **models.py**: SQLAlchemy models for boards and firmware
- **core.py**: Database initialization and migration
- **gather_boards.py**: Board data collection and management
- **loader.py**: Data loading utilities

#### Hardware Support
- **flash/**: Platform-specific flashing implementations
  - ESP32/ESP8266 via esptool
  - RP2040 via UF2 file copy
  - STM32 via DFU
  - SAMD via UF2 file copy
- **bootloader/**: Bootloader activation methods
  - Touch1200 for Arduino-compatible boards
  - MicroPython REPL-based activation
  - Manual intervention support

## Database Schema

The application uses SQLite with SQLAlchemy ORM:

### Board Table
```sql
CREATE TABLE boards (
    board_id VARCHAR(40) NOT NULL,
    version VARCHAR(12) NOT NULL,
    board_name VARCHAR NOT NULL,
    mcu VARCHAR NOT NULL,
    variant VARCHAR DEFAULT '',
    port VARCHAR(30) NOT NULL,
    path VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    family VARCHAR DEFAULT 'micropython',
    custom BOOLEAN DEFAULT false,
    PRIMARY KEY (board_id, version)
);
```

### Firmware Table
```sql
CREATE TABLE firmwares (
    board_id VARCHAR(40) NOT NULL,
    version VARCHAR(12) NOT NULL,
    firmware_file VARCHAR NOT NULL,
    port VARCHAR(20) DEFAULT '',
    description VARCHAR DEFAULT '',
    source VARCHAR NOT NULL,
    build INTEGER DEFAULT 0,
    custom BOOLEAN DEFAULT false,
    PRIMARY KEY (board_id, version, firmware_file),
    FOREIGN KEY (board_id, version) REFERENCES boards (board_id, version)
);
```

## Development Setup

### Prerequisites
- Python 3.9.2+
- uv for dependency management (or pip)
- Git for version control

### Installation
```bash
git clone https://github.com/Josverl/mpflash.git
cd mpflash
uv sync --all-extras
```

### Environment Variables
Set up your development environment:
```bash
# Copy and configure environment
cp .env.example .env

# Key variables:
MPFLASH_FIRMWARE=./scratch    # Firmware storage location
PYTHONPATH=src                # Test source path
```

### Running Tests
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=mpflash

# Run specific test categories
uv run pytest -m "not basicgit"
```

## Code Standards

### Python Style
- Use type annotations for all functions and methods
- Follow PEP 8 with 4-space indentation
- Use f-strings for string formatting
- Use snake_case for variables/functions, CamelCase for classes
- Add docstrings (5-9 lines max) for modules and public methods

### Example Code Style
```python
from typing import List, Optional
from pathlib import Path

class FirmwareManager:
    """Manages firmware download and storage operations."""
    
    def __init__(self, firmware_dir: Path) -> None:
        """Initialize firmware manager with storage directory."""
        self.firmware_dir = firmware_dir
        self._cache: Optional[dict] = None
    
    def download_firmware(
        self, 
        board_id: str, 
        version: str = "stable"
    ) -> Path:
        """Download firmware for specified board and version.
        
        Args:
            board_id: Target board identifier
            version: Firmware version (stable, preview, or x.y.z)
            
        Returns:
            Path to downloaded firmware file
            
        Raises:
            MPFlashError: If download fails or board not found
        """
        firmware_path = self.firmware_dir / f"{board_id}-{version}.bin"
        # Implementation here...
        return firmware_path
```

### Performance Considerations
- Use lazy loading for modules and heavy dependencies
- Implement generators for large datasets
- Cache database queries where appropriate
- Minimize startup time for CLI responsiveness

## Adding New Hardware Support

### 1. Flash Implementation
Create a new module in `mpflash/flash/`:

```python
from typing import Optional
from pathlib import Path
from .base import FlashBase

class NewPlatformFlash(FlashBase):
    """Flash support for new platform."""
    
    def __init__(self, port: str, firmware_path: Path):
        super().__init__(port, firmware_path)
        self.platform_name = "newplatform"
    
    def flash_firmware(self) -> bool:
        """Flash firmware to the device."""
        # Implementation specific to your platform
        return True
    
    def enter_bootloader(self) -> bool:
        """Enter bootloader mode."""
        # Platform-specific bootloader activation
        return True
```

### 2. Bootloader Support
Add bootloader activation in `mpflash/bootloader/`:

```python
from typing import Optional
from .base import BootloaderBase

class NewPlatformBootloader(BootloaderBase):
    """Bootloader activation for new platform."""
    
    def activate(self) -> bool:
        """Activate bootloader mode."""
        # Implementation here
        return True
```

### 3. Board Identification
Update board identification in `mpflash/mpboard_id/`:

```python
def identify_new_platform(port: str) -> Optional[dict]:
    """Identify new platform board."""
    # Board detection logic
    return {
        "board_id": "NEW_PLATFORM_BOARD",
        "port": "newplatform",
        "mcu": "NewMCU",
        "family": "micropython"
    }
```

### 4. Register Support
Update the main flash dispatcher to include your new platform:

```python
# In mpflash/flash/__init__.py
from .newplatform import NewPlatformFlash

FLASH_IMPLEMENTATIONS = {
    "newplatform": NewPlatformFlash,
    # ... existing implementations
}
```

## Testing

### Test Structure
```
tests/
├── conftest.py           # pytest configuration and fixtures
├── test_*.py            # Unit tests
├── data/                # Test data files
├── cli/                 # CLI command tests
├── db/                  # Database tests
├── flash/               # Flash implementation tests
└── mpboard_id/          # Board identification tests
```

### Writing Tests
```python
import pytest
from pathlib import Path
from mpflash.download.fwinfo import FirmwareInfo

class TestFirmwareInfo:
    """Test firmware information handling."""
    
    def test_firmware_parsing(self, tmp_path: Path):
        """Test firmware file parsing."""
        firmware_path = tmp_path / "test.bin"
        firmware_path.write_bytes(b"test firmware data")
        
        info = FirmwareInfo(firmware_path)
        assert info.exists()
        assert info.size > 0
    
    @pytest.mark.parametrize("version,expected", [
        ("stable", True),
        ("preview", True),
        ("1.25.0", True),
        ("invalid", False),
    ])
    def test_version_validation(self, version: str, expected: bool):
        """Test firmware version validation."""
        result = FirmwareInfo.validate_version(version)
        assert result == expected
```

### Test Database
Use the test database in `tests/data/` for database-related tests:

```python
@pytest.fixture
def test_db(tmp_path):
    """Provide test database."""
    db_path = tmp_path / "test.db"
    # Initialize test database
    return db_path
```

## Configuration Management

### Environment Variables
- `MPFLASH_FIRMWARE`: Custom firmware storage location
- `MPFLASH_IGNORE`: Space-separated list of ports to ignore
- `PYTHONPATH`: Source path for development

### Configuration Class
```python
from mpflash.config import config

# Access configuration
config.firmware_folder  # Path to firmware storage
config.verbose          # Debug logging enabled
config.interactive      # Interactive prompts enabled
```

## Debugging

### Logging
```python
from mpflash.logger import log

# Log levels: TRACE, DEBUG, INFO, WARNING, ERROR
log.debug("Debug information")
log.info("General information")
log.warning("Warning message")
log.error("Error occurred")
```

### VS Code Tasks
Use the configured tasks for development:
- `run createstubs`: Generate MicroPython stubs
- `coverage`: Run test coverage
- `coverage html`: Generate HTML coverage report

## Contributing

### Pull Request Process
1. Fork the repository
2. Create a feature branch
3. Implement changes with tests
4. Run full test suite
5. Submit pull request with clear description

### Code Review Checklist
- [ ] Type annotations added
- [ ] Tests written and passing
- [ ] Documentation updated
- [ ] Code follows style guidelines
- [ ] Performance impact considered
- [ ] Backward compatibility maintained

## Release Process

### Version Management
```bash
# Update version in pyproject.toml using either
uv version <new_version>  
uv version --bump patch 
# Build package
uv build

# Publish to PyPI
# set token in environment variable
export UV_PUBLISH_TOKEN="pypi-123456789abcdef"
# uv publish --index testpypi # optionally
uv publish #
```

### Documentation Updates
- Update README.md with new features
- Add changelog entries
- Update API documentation if needed

## Troubleshooting

### Common Issues

**Database Migration Errors**
- Check database file permissions
- Verify SQLite version compatibility
- Review migration scripts in `db/core.py`

**Board Detection Issues**
- Verify USB permissions (Linux)
- Check serial port availability
- Review board identification logic

**Firmware Download Failures**
- Check network connectivity
- Verify MicroPython repository availability
- Review download implementation

**Flash Operation Failures**
- Confirm bootloader activation
- Check firmware file integrity
- Verify platform-specific tools (esptool, etc.)

## Resources

- [MicroPython Downloads](https://micropython.org/download/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Click Documentation](https://click.palletsprojects.com/)
- [Rich Documentation](https://rich.readthedocs.io/)

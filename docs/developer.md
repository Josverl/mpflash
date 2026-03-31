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
- **models.py**: Peewee ORM models for boards, firmware, and metadata
- **core.py**: Database initialisation and connection management
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

## Database

The application uses **SQLite** via the **[Peewee](https://docs.peewee-orm.com/)** ORM. The database file location defaults to the OS user data directory and can be overridden with the `MPFLASH_FIRMWARE` environment variable.

### Peewee Models

Models are defined in `mpflash/db/models.py`. All models inherit from `BaseModel` which binds them to the shared `SqliteDatabase` instance initialised in `core.py`.

```python
import peewee

database = peewee.SqliteDatabase(None)  # path set at runtime by core.py

class BaseModel(peewee.Model):
    class Meta:
        database = database
```

### Schema

#### `metadata` table — key/value configuration store

| Column | Type | Notes |
|--------|------|-------|
| `name` | `VARCHAR` | Primary key |
| `value` | `TEXT` | |

#### `boards` table — all known MicroPython boards

| Column | Type | Notes |
|--------|------|-------|
| `board_id` | `VARCHAR(40)` | Composite PK with `version` |
| `version` | `VARCHAR(12)` | Composite PK with `board_id` |
| `board_name` | `TEXT` | |
| `mcu` | `TEXT` | |
| `variant` | `TEXT` | |
| `port` | `VARCHAR(30)` | e.g. `rp2`, `esp32` |
| `path` | `TEXT` | Path in micropython repo |
| `description` | `TEXT` | |
| `family` | `TEXT` | Default `micropython` |
| `custom` | `BOOLEAN` | `True` if user-added board |

#### `firmwares` table — downloaded firmware files

| Column | Type | Notes |
|--------|------|-------|
| `board_id` | `VARCHAR(40)` | Composite PK |
| `version` | `VARCHAR(12)` | Composite PK |
| `firmware_file` | `TEXT` | Composite PK; path to file |
| `port` | `VARCHAR(20)` | |
| `description` | `TEXT` | |
| `source` | `TEXT` | Download URL or `custom` |
| `build` | `INTEGER` | Preview build number |
| `custom` | `BOOLEAN` | `True` if user-provided |
| `custom_id` | `VARCHAR(40)` | Nullable; custom board ID |

### Database Initialisation

`core.py` initialises the shared database instance on module load:

```python
from mpflash.db.core import database  # SqliteDatabase instance

# Use the session context manager for transactions:
from mpflash.db.core import Session

with Session() as session:
    boards = Board.select().where(Board.port == "rp2")
```

The context manager opens the connection (if closed), wraps the block in an atomic transaction and commits on exit (or rolls back on exception).

## Development Setup

### Prerequisites
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) for dependency and environment management
- Git for version control

### Getting Started

Clone the repo and install all dependencies (including dev and test extras) into a local virtual environment:

```bash
git clone https://github.com/Josverl/mpflash.git
cd mpflash
uv sync --all-extras
```

This creates a `.venv` in the project directory. Activate it when running commands directly:

```bash
# Windows
.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate
```

Or prefix commands with `uv run` to use the venv automatically without activating it.

### Environment Variables

Optional overrides for local development:

```bash
MPFLASH_FIRMWARE=./scratch    # firmware storage location (instead of ~/Downloads/firmware)
PYTHONPATH=src                # needed when running pytest directly
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=mpflash

# Skip slow git-related tests
uv run pytest -m "not basicgit"

# Full coverage + HTML report
uv run coverage run -m pytest tests -m 'not basicgit'
uv run coverage html          # output in htmlcov/
```

### Building the Package

```bash
# Build wheel and sdist into dist/
uv build
```

The built files appear in `dist/`. To verify the package installs correctly:

```bash
uv tool install dist/mpflash-*.whl
mpflash --version
```

### Upgrading Dependencies

To upgrade all packages to the latest versions allowed by `pyproject.toml` version constraints and update `uv.lock`:

```bash
uv sync --upgrade
```

To upgrade a single package:

```bash
uv sync --upgrade-package <package-name>
```

After upgrading, run the tests to catch any regressions:

```bash
uv run pytest -m "not basicgit"
```

To check for known security vulnerabilities in the current lockfile:

```bash
uv audit
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

# Recommended: update the included boards & description information
uv run mpflash/db/gather_boards.py --mpy-path ../micropython

# Build package
uv build

# Publish to PyPI
# set token in environment variable

```pwsh
uv install keyring
$env:UV_PUBLISH_TOKEN=(python -m keyring get pypi uv_publish
del env:UV_PUBLISH_TOKEN
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
- [Peewee ORM Documentation](https://docs.peewee-orm.com/)
- [Click Documentation](https://click.palletsprojects.com/)
- [Rich Documentation](https://rich.readthedocs.io/)

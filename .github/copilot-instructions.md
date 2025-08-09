# GitHub Copilot Instructions for MPFlash

This document provides guidance for GitHub Copilot to maintain consistency with MPFlash's architecture and coding standards.

## Project Overview

MPFlash is a command-line tool and Python library for managing MicroPython firmware across multiple hardware platforms. The project follows a layered architecture with clear separation of concerns.

## AI Assistant rukes 
 - When running in shell , always make sure the activate the virtual environment after starting the shell 
 - when possible use MCP servers 

## Code Style and Standards

### Python Conventions
- Use Python type annotations throughout the code
- Follow snake_case for functions and variables
- Follow CamelCase for class names
- Use 4 spaces for indentation
- Use double quotes for strings
- Prefer f-strings for string formatting
- Maximum line length: 88 characters (Black formatter standard)
- Add comments, but not too much
- Add docstrings to modules and methods (5-9 lines maximum)
- Use double quotes for strings

# Speed and performance

- this is a CLI tool and loading speed is important
- Use lazy loading for modules and packages where possible
- Use generators for large data sets

# dependencies

- Use uv pip for package management
- the project is handled by poetry and all dependencies should be added to the pyproject.toml file
- minimize the number of dependencies
-

# Writing tests
- when asked to create an MVP - keep the number of tests to a minimum
- Use pytest for testing
- Use pytest fixtures for setup and teardown
- Use assert statements for testing
- all tests shouod be located in or under the `tests` directory
- Use descriptive names for test functions
- Use pytest.mark.parametrize for parameterized tests
- Use pytest.raises for testing exceptions
- for database related tests testsL
    - make use of the test database int tests/data
    - add fixtures for database setup and teardown
### Documentation
- Do not include type hints in docstrings
- Keep comments minimal but descriptive

### Example Function Style
```python
def flash_firmware(
    port: str,
    firmware_path: Path,
    timeout: float = 30.0
) -> bool:
    """Flash MicroPython firmware to a connected board.

    Args:
        port: Serial port identifier (e.g., 'COM3' or '/dev/ttyUSB0')
        firmware_path: Path to the firmware file
        timeout: Maximum time to wait for flashing (seconds)

    Returns:
        True if flashing succeeded, False otherwise

    Raises:
        FlashError: If flashing operation fails
    """
    # Implementation
```

## Project Structure Patterns

### CLI Commands
- Place in `mpflash/cli_*.py`
- Use Click decorators
- Include help text and type annotations
- Handle errors gracefully

### Core Components
- Follow interface-based design
- Use abstract base classes for common patterns
- Implement strategy pattern for varying behaviors

### Database Operations
- Use SQLAlchemy ORM
- Follow repository pattern
- Include proper error handling
- Use migrations for schema changes

## Common Patterns

### Hardware Abstraction
```python
class FlashBase(ABC):
    """Base class for flash implementations."""
    
    @abstractmethod
    def flash_firmware(self) -> bool:
        """Flash firmware to device."""
        pass
```

### Error Handling
```python
class MPFlashError(Exception):
    """Base exception for MPFlash operations."""
    pass

def safe_operation(func: Callable) -> Callable:
    """Decorator for safe operations with proper error handling."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except MPFlashError as e:
            log.error(f"Operation failed: {e}")
            return None
    return wrapper
```

### Configuration Management
```python
@dataclass
class Config:
    """Configuration dataclass with type hints."""
    firmware_dir: Path
    log_level: str = "INFO"
    timeout: float = 30.0
```

## Testing Conventions

### Test Structure
- Place tests in `tests/` directory
- Match test file names with implementation files
- Use pytest fixtures for setup
- Include unit, integration, and end-to-end tests

### Example Test Pattern
```python
def test_flash_firmware(mock_board, temp_firmware):
    """Test firmware flashing with mocked board."""
    result = flash_firmware(
        port=mock_board.port,
        firmware_path=temp_firmware
    )
    assert result is True
```

## Performance Considerations

### Lazy Loading
```python
class LazyLoader:
    """Lazy loading pattern for expensive imports."""
    def __init__(self):
        self._module = None

    @property
    def module(self):
        if self._module is None:
            import expensive_module
            self._module = expensive_module
        return self._module
```

### Caching
```python
@lru_cache(maxsize=100)
def get_board_info(board_id: str) -> dict:
    """Cached board information retrieval."""
    # Implementation
```

## Security Patterns

### Input Validation
```python
def validate_input(value: str, pattern: str) -> bool:
    """Validate input against security pattern."""
    import re
    return bool(re.match(pattern, value))
```

### Safe File Operations
```python
def safe_file_operation(path: Path) -> None:
    """Safe file operation pattern."""
    if not path.suffix in {'.bin', '.uf2', '.hex'}:
        raise SecurityError("Invalid file type")
    # Implementation
```

## Database Update Process

When working with the board database:
- Use `gather_boards.py` for updating board definitions
- Package updates in `micropython_boards.zip`
- Follow the repository pattern for database operations
- Maintain proper versioning and migrations

## Bootloader Operations

When implementing bootloader-related code:
- Use the BootloaderManager class
- Implement proper error handling
- Follow the strategy pattern for different bootloader types
- Include timeout mechanisms

Remember to maintain consistency with these patterns when suggesting code completions and implementations.

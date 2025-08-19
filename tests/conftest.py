"""Shared Pytest configuration and fixtures for mpflash tests."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Import test fixtures for pyOCD testing
try:
    from tests.fixtures.mock_pyocd_data import MOCK_MCUS, MOCK_PROBES, ALL_PYOCD_TARGETS
except ImportError:
    # Fallback if fixtures not available
    MOCK_MCUS = {}
    MOCK_PROBES = []
    ALL_PYOCD_TARGETS = {}


@pytest.fixture
def test_fw_path():
    """Return the path to the test firmware folder."""
    return Path(__file__).parent / "data" / "firmware"


# --------------------------------------
# https://docs.pytest.org/en/stable/example/markers.html#marking-platform-specific-tests-with-pytest
ALL_OS = set("win32 linux darwin".split())


def pytest_runtest_setup(item):
    supported_platforms = ALL_OS.intersection(mark.name for mark in item.iter_markers())
    platform = sys.platform
    if supported_platforms and platform not in supported_platforms:
        pytest.skip("cannot run on platform {}".format(platform))


from pathlib import Path

import pytest

# Constants for test
HERE = Path(__file__).parent

#############################################################
# Fixtures for database testing
#############################################################
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module")
def test_db():
    """
    Fixture to provide a test database.
    """
    yield HERE / "data/mpflash.db"


@pytest.fixture(scope="module")
def engine_fx(test_db):
    # engine = create_engine("sqlite:///:memory:")
    # engine = create_engine("sqlite:///D:/mypython/mpflash/mpflash.db")
    engine = create_engine(f"sqlite:///{test_db.as_posix()}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def connection_fx(engine_fx):
    connection = engine_fx.connect()
    yield connection
    connection.close()


@pytest.fixture(scope="function")
def session_fx(connection_fx):
    transaction = connection_fx.begin()
    testSession = sessionmaker(bind=connection_fx)
    yield testSession
    transaction.rollback()


# in memory database


@pytest.fixture(scope="module")
def engine_mem():
    engine = create_engine("sqlite:///:memory:")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def connection_mem(engine_mem):
    connection = engine_mem.connect()
    yield connection
    connection.close()


@pytest.fixture(scope="function")
def session_mem(connection_mem):
    transaction = connection_mem.begin()
    testSession = sessionmaker(bind=connection_fx)  # type: ignore
    yield testSession
    transaction.rollback()


#############################################################
# Fixtures for pyOCD testing  
#############################################################

@pytest.fixture
def mock_mcu():
    """Provide a mock MCU for testing."""
    if "stm32wb55" in MOCK_MCUS:
        return MOCK_MCUS["stm32wb55"]
    # Fallback mock
    class MockMCU:
        def __init__(self):
            self.board_id = "TEST_BOARD"
            self.cpu = "STM32WB55RGV6"
            self.description = "Test MCU with STM32WB55RGV6"
            self.port = "stm32"
    return MockMCU()


@pytest.fixture
def mock_esp32_mcu():
    """Provide an ESP32 mock MCU for testing unsupported scenarios."""
    if "esp32" in MOCK_MCUS:
        return MOCK_MCUS["esp32"]
    # Fallback mock
    class MockESP32:
        def __init__(self):
            self.board_id = "ESP32_DEV"
            self.cpu = "ESP32"
            self.description = "ESP32-DevKitC with ESP32-WROOM-32"
            self.port = "esp32"
    return MockESP32()


@pytest.fixture
def mock_pyocd_targets():
    """Provide mock pyOCD target data."""
    return ALL_PYOCD_TARGETS


@pytest.fixture
def mock_probes():
    """Provide mock probe data."""
    return MOCK_PROBES


@pytest.fixture
def temp_firmware_file(tmp_path):
    """Create a temporary firmware file for testing."""
    firmware_file = tmp_path / "test_firmware.bin"
    firmware_file.write_bytes(b"fake firmware content")
    return firmware_file


@pytest.fixture(autouse=True)
def reset_probe_registry():
    """Reset the probe registry before each test."""
    try:
        from mpflash.flash.debug_probe import _probe_implementations
        original_implementations = _probe_implementations.copy()
        _probe_implementations.clear()
        
        yield
        
        # Restore original implementations
        _probe_implementations.clear()
        _probe_implementations.update(original_implementations)
    except ImportError:
        # If debug_probe module not available, just yield
        yield


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for testing command execution."""
    with patch('subprocess.run') as mock_run:
        yield mock_run


# Test markers for categorizing tests
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "cli: mark test as a CLI test")
    config.addinivalue_line("markers", "pyocd: mark test as a pyOCD-related test")
    config.addinivalue_line("markers", "slow: mark test as slow running")

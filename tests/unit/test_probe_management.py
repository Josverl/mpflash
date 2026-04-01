"""
Unit tests for debug probe management and PyOCD probe implementation.

Tests probe discovery, connection handling, and flash programming
without requiring actual hardware.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path

# Import modules under test
from mpflash.flash.debug_probe import (
    DebugProbe,
    register_probe_implementation,
    get_debug_probes,
    find_debug_probe,
    is_debug_programming_available,
    _probe_implementations
)
from mpflash.flash.pyocd_probe import PyOCDProbe
from mpflash.flash.pyocd_flash import PyOCDFlash, flash_pyocd
from mpflash.errors import MPFlashError

# Import test fixtures
from tests.fixtures.mock_pyocd_data import (
    MOCK_PROBES,
    MOCK_MCUS,
    ERROR_SCENARIOS
)


class MockPyOCDProbe(DebugProbe):
    """Mock PyOCD probe for testing without pyOCD dependency."""
    
    def __init__(self, unique_id: str, description: str):
        super().__init__(unique_id, description)
        self.connected = False
        self.programming_success = True
    
    def program_flash(self, firmware_path: Path, target_type: str, **options) -> bool:
        if not self.connected:
            raise MPFlashError("Probe not connected")
        return self.programming_success
    
    @classmethod
    def is_implementation_available(cls) -> bool:
        return True
    
    @classmethod 
    def discover(cls) -> list:
        return [
            cls(probe["unique_id"], probe["description"]) 
            for probe in MOCK_PROBES
        ]


class TestDebugProbeRegistry:
    """Test the debug probe registration system."""
    
    def setup_method(self):
        """Clear registry before each test."""
        _probe_implementations.clear()
    
    def test_register_probe_implementation(self):
        """Test registering a probe implementation."""
        register_probe_implementation("mock", MockPyOCDProbe)
        
        assert "mock" in _probe_implementations
        assert _probe_implementations["mock"] == MockPyOCDProbe
    
    def test_register_invalid_probe_class(self):
        """Test error when registering invalid probe class."""
        class InvalidProbe:
            pass
        
        with pytest.raises(ValueError, match="must inherit from DebugProbe"):
            register_probe_implementation("invalid", InvalidProbe)
    
    def test_auto_registration_pyocd(self):
        """Test that pyOCD probe can be registered."""
        # Clear first
        _probe_implementations.clear()
        
        # Test direct registration (simpler than module reload)
        register_probe_implementation("pyocd", MockPyOCDProbe)
        
        assert "pyocd" in _probe_implementations
        assert _probe_implementations["pyocd"] == MockPyOCDProbe


class TestProbeDiscovery:
    """Test probe discovery functionality."""
    
    def setup_method(self):
        """Set up mock probe for testing."""
        _probe_implementations.clear()
        register_probe_implementation("mock", MockPyOCDProbe)
    
    def test_get_debug_probes_success(self):
        """Test successful probe discovery."""
        probes = get_debug_probes()
        
        assert len(probes) == 2  # From MOCK_PROBES
        assert all(isinstance(p, MockPyOCDProbe) for p in probes)
        assert probes[0].unique_id == "066CFF505750827567154312"
        assert probes[1].unique_id == "0D28C20417A04C1D"
    
    def test_get_debug_probes_no_implementations(self):
        """Test probe discovery with no implementations."""
        _probe_implementations.clear()
        
        probes = get_debug_probes()
        assert probes == []
    
    def test_get_debug_probes_implementation_unavailable(self):
        """Test probe discovery when implementation is unavailable."""
        class UnavailableProbe(DebugProbe):
            @classmethod
            def is_implementation_available(cls):
                return False
            
            @classmethod
            def discover(cls):
                return []
            
            def program_flash(self, firmware_path, target_type, **options):
                pass
        
        register_probe_implementation("unavailable", UnavailableProbe)
        probes = get_debug_probes()
        
        # Should only return mock probes, not unavailable ones
        assert len(probes) == 2
        assert all(isinstance(p, MockPyOCDProbe) for p in probes)
    
    def test_get_debug_probes_discovery_exception(self):
        """Test graceful handling of discovery exceptions."""
        class FaultyProbe(DebugProbe):
            @classmethod
            def is_implementation_available(cls):
                return True
            
            @classmethod
            def discover(cls):
                raise Exception("Discovery failed")
            
            def program_flash(self, firmware_path, target_type, **options):
                pass
        
        register_probe_implementation("faulty", FaultyProbe)
        probes = get_debug_probes()
        
        # Should return mock probes despite faulty probe throwing exception
        assert len(probes) == 2


class TestProbeFinding:
    """Test probe finding functionality."""
    
    def setup_method(self):
        _probe_implementations.clear()
        register_probe_implementation("mock", MockPyOCDProbe)
    
    def test_find_debug_probe_no_id(self):
        """Test finding first available probe when no ID specified."""
        probe = find_debug_probe()
        
        assert probe is not None
        assert isinstance(probe, MockPyOCDProbe)
        assert probe.unique_id == "066CFF505750827567154312"  # First probe
    
    def test_find_debug_probe_exact_match(self):
        """Test finding probe by exact ID match."""
        probe_id = "0D28C20417A04C1D"
        probe = find_debug_probe(probe_id)
        
        assert probe is not None
        assert probe.unique_id == probe_id
    
    def test_find_debug_probe_partial_match(self):
        """Test finding probe by partial ID match."""
        probe = find_debug_probe("066CFF")  # Partial match
        
        assert probe is not None
        assert probe.unique_id == "066CFF505750827567154312"
    
    def test_find_debug_probe_ambiguous_match(self):
        """Test error on ambiguous partial match."""
        # Both probes contain "D" - should be ambiguous
        with pytest.raises(MPFlashError, match="Ambiguous probe ID"):
            find_debug_probe("D")
    
    def test_find_debug_probe_no_match(self):
        """Test no match found."""
        probe = find_debug_probe("NONEXISTENT")
        assert probe is None
    
    def test_find_debug_probe_no_probes_available(self):
        """Test behavior when no probes are available."""
        _probe_implementations.clear()
        
        probe = find_debug_probe()
        assert probe is None


class TestPyOCDProbeIntegration:
    """Test PyOCD probe implementation details."""
    
    @patch('mpflash.flash.pyocd_probe._ensure_pyocd')
    def test_pyocd_probe_is_available(self, mock_ensure):
        """Test checking if pyOCD is available.""" 
        mock_ensure.return_value = {"ConnectHelper": Mock()}
        
        available = PyOCDProbe.is_implementation_available()
        assert available is True
    
    @patch('mpflash.flash.pyocd_probe._ensure_pyocd')
    def test_pyocd_probe_not_available(self, mock_ensure):
        """Test behavior when pyOCD is not available."""
        mock_ensure.side_effect = MPFlashError("pyOCD not installed")
        
        available = PyOCDProbe.is_implementation_available()
        assert available is False
    
    @patch('mpflash.flash.pyocd_probe._ensure_pyocd')
    def test_pyocd_probe_discovery(self, mock_ensure):
        """Test PyOCD probe discovery."""
        # Mock pyOCD ConnectHelper
        mock_helper = Mock()
        mock_probe_info = Mock()
        mock_probe_info.unique_id = "TEST123"
        mock_probe_info.description = "Test Probe"
        mock_helper.get_all_connected_probes.return_value = [mock_probe_info]
        
        mock_ensure.return_value = {"ConnectHelper": mock_helper}
        
        probes = PyOCDProbe.discover()
        
        assert len(probes) == 1
        assert probes[0].unique_id == "TEST123"
        assert probes[0].description == "Test Probe"


class TestPyOCDFlash:
    """Test PyOCDFlash class functionality."""
    
    def setup_method(self):
        """Set up mocks for testing."""
        self.mock_mcu = MOCK_MCUS["stm32wb55"]
        self.test_firmware = Path("/tmp/test_firmware.bin")
    
    @patch('mpflash.flash.pyocd_flash.get_pyocd_target_dynamic')
    @patch('mpflash.flash.pyocd_flash.is_debug_programming_available')
    def test_pyocd_flash_init_success(self, mock_available, mock_get_target):
        """Test successful PyOCDFlash initialization."""
        mock_available.return_value = True
        mock_get_target.return_value = "stm32wb55xg"
        
        flasher = PyOCDFlash(self.mock_mcu)
        
        assert flasher.mcu == self.mock_mcu
        assert flasher.target_type == "stm32wb55xg"
    
    @patch('mpflash.flash.pyocd_flash.get_pyocd_target_dynamic')
    @patch('mpflash.flash.pyocd_flash.is_debug_programming_available')
    def test_pyocd_flash_init_no_debug_support(self, mock_available, mock_get_target):
        """Test PyOCDFlash initialization when debug programming unavailable."""
        mock_available.return_value = False
        
        with pytest.raises(MPFlashError, match="No debug probe support available"):
            PyOCDFlash(self.mock_mcu)
    
    @patch('mpflash.flash.pyocd_flash.get_pyocd_target_dynamic')
    @patch('mpflash.flash.pyocd_flash.is_debug_programming_available')
    def test_pyocd_flash_init_unsupported_target(self, mock_available, mock_get_target):
        """Test PyOCDFlash initialization with unsupported target."""
        mock_available.return_value = True
        mock_get_target.return_value = None  # No target found
        
        with pytest.raises(MPFlashError, match="not supported by pyOCD"):
            PyOCDFlash(self.mock_mcu)
    
    @patch('mpflash.flash.pyocd_flash.get_pyocd_target_dynamic')
    @patch('mpflash.flash.pyocd_flash.is_debug_programming_available') 
    @patch('mpflash.flash.pyocd_flash.find_debug_probe')
    def test_flash_firmware_success(self, mock_find_probe, mock_available, mock_get_target):
        """Test successful firmware flashing."""
        # Setup mocks
        mock_available.return_value = True
        mock_get_target.return_value = "stm32wb55xg"
        
        mock_probe = Mock(spec=PyOCDProbe)
        mock_probe.program_flash.return_value = True
        mock_find_probe.return_value = mock_probe
        
        # Create temporary firmware file
        self.test_firmware.touch()
        
        try:
            flasher = PyOCDFlash(self.mock_mcu)
            result = flasher.flash_firmware(self.test_firmware)
            
            assert result is True
            mock_probe.program_flash.assert_called_once()
        finally:
            self.test_firmware.unlink(missing_ok=True)
    
    @patch('mpflash.flash.pyocd_flash.get_pyocd_target_dynamic')
    @patch('mpflash.flash.pyocd_flash.is_debug_programming_available')
    def test_flash_firmware_file_not_found(self, mock_available, mock_get_target):
        """Test error when firmware file doesn't exist."""
        mock_available.return_value = True
        mock_get_target.return_value = "stm32wb55xg"
        
        flasher = PyOCDFlash(self.mock_mcu)
        
        with pytest.raises(MPFlashError, match="Firmware file not found"):
            flasher.flash_firmware(Path("/nonexistent/firmware.bin"))
    
    @patch('mpflash.flash.pyocd_flash.get_pyocd_target_dynamic')
    @patch('mpflash.flash.pyocd_flash.is_debug_programming_available')
    @patch('mpflash.flash.pyocd_flash.find_debug_probe')
    def test_flash_firmware_no_probe(self, mock_find_probe, mock_available, mock_get_target):
        """Test error when no probe is found."""
        mock_available.return_value = True
        mock_get_target.return_value = "stm32wb55xg"
        mock_find_probe.return_value = None
        
        self.test_firmware.touch()
        
        try:
            flasher = PyOCDFlash(self.mock_mcu)
            
            with pytest.raises(MPFlashError, match="No PyOCD debug probes available"):
                flasher.flash_firmware(self.test_firmware)
        finally:
            self.test_firmware.unlink(missing_ok=True)


class TestFlashPyOCDFunction:
    """Test the flash_pyocd convenience function."""
    
    def setup_method(self):
        self.mock_mcu = MOCK_MCUS["stm32wb55"]
        self.test_firmware = Path("/tmp/test_firmware.bin")
    
    @patch('mpflash.flash.pyocd_flash.is_pyocd_supported_from_mcu')
    @patch('mpflash.flash.pyocd_flash.PyOCDFlash')
    def test_flash_pyocd_success(self, mock_flasher_class, mock_supported):
        """Test successful flash_pyocd function call."""
        mock_supported.return_value = True
        
        mock_flasher = Mock()
        mock_flasher.flash_firmware.return_value = True
        mock_flasher_class.return_value = mock_flasher
        
        self.test_firmware.touch()
        
        try:
            result = flash_pyocd(self.mock_mcu, self.test_firmware)
            
            assert result is True
            mock_flasher_class.assert_called_once()
            mock_flasher.flash_firmware.assert_called_once_with(
                self.test_firmware, erase=False
            )
        finally:
            self.test_firmware.unlink(missing_ok=True)
    
    @patch('mpflash.flash.pyocd_flash.is_pyocd_supported_from_mcu')
    def test_flash_pyocd_unsupported(self, mock_supported):
        """Test flash_pyocd with unsupported MCU."""
        mock_supported.return_value = False
        
        with patch('mpflash.flash.pyocd_flash.get_unsupported_reason_from_mcu') as mock_reason:
            mock_reason.return_value = "ESP32 not supported"
            
            with pytest.raises(MPFlashError, match="PyOCD flash not supported"):
                flash_pyocd(self.mock_mcu, self.test_firmware)
    
    @patch('mpflash.flash.pyocd_flash.is_pyocd_supported_from_mcu')
    @patch('mpflash.flash.pyocd_flash.get_pyocd_target_from_mcu')
    @patch('mpflash.flash.pyocd_flash.find_probe_for_target')
    def test_flash_pyocd_no_probe(self, mock_find_probe, mock_get_target, mock_supported):
        """Test flash_pyocd when no suitable probe found."""
        mock_supported.return_value = True
        mock_get_target.return_value = "stm32wb55xg"
        mock_find_probe.return_value = None
        
        with pytest.raises(MPFlashError, match="No suitable debug probe found"):
            flash_pyocd(self.mock_mcu, self.test_firmware)


class TestProbeAvailability:
    """Test availability checking functions."""
    
    def setup_method(self):
        _probe_implementations.clear()
    
    def test_is_debug_programming_available_true(self):
        """Test debug programming availability when probes available."""
        register_probe_implementation("mock", MockPyOCDProbe)
        
        assert is_debug_programming_available() is True
    
    def test_is_debug_programming_available_false(self):
        """Test debug programming availability when no probes available."""
        class UnavailableProbe(DebugProbe):
            @classmethod
            def is_implementation_available(cls):
                return False
            
            @classmethod
            def discover(cls):
                return []
            
            def program_flash(self, firmware_path, target_type, **options):
                pass
        
        register_probe_implementation("unavailable", UnavailableProbe)
        
        assert is_debug_programming_available() is False
    
    def test_is_debug_programming_available_no_implementations(self):
        """Test debug programming availability with no implementations."""
        assert is_debug_programming_available() is False


if __name__ == "__main__":
    pytest.main([__file__])
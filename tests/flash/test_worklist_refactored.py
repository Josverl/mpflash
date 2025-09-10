"""Tests for the refactored worklist module."""

import pytest
from unittest.mock import MagicMock

from mpflash.flash.worklist import (
    FlashTask,
    WorklistConfig,
    create_worklist,
    create_auto_worklist,
    create_manual_worklist,
    create_filtered_worklist,
    create_single_board_worklist,
    tasks_to_legacy_worklist,
    legacy_worklist_to_tasks,
    _create_flash_task,
    _find_firmware_for_board,
)
from mpflash.mpremoteboard import MPRemoteBoard
from mpflash.db.models import Firmware


class TestFlashTask:
    """Test the FlashTask dataclass."""
    
    def test_flash_task_creation(self):
        """Test creating a FlashTask."""
        board = MPRemoteBoard("COM1")
        board.board_id = "ESP32_GENERIC"
        firmware = Firmware(board_id="ESP32_GENERIC", version="1.22.0", port="esp32")
        
        task = FlashTask(board=board, firmware=firmware)
        
        assert task.board == board
        assert task.firmware == firmware
        assert task.is_valid is True
        assert task.board_id == "ESP32_GENERIC"
        assert task.firmware_version == "1.22.0"
    
    def test_flash_task_without_firmware(self):
        """Test FlashTask with no firmware."""
        board = MPRemoteBoard("COM1")
        board.board_id = "ESP32_GENERIC"
        
        task = FlashTask(board=board, firmware=None)
        
        assert task.board == board
        assert task.firmware is None
        assert task.is_valid is False
        assert task.board_id == "ESP32_GENERIC"
        assert task.firmware_version == "unknown"


class TestWorklistConfig:
    """Test the WorklistConfig dataclass."""
    
    def test_worklist_config_creation(self):
        """Test creating a WorklistConfig."""
        config = WorklistConfig(version="1.22.0")
        
        assert config.version == "1.22.0"
        assert config.include_ports == []
        assert config.ignore_ports == []
        assert config.board_id is None
        assert config.custom_firmware is False
    
    def test_worklist_config_with_parameters(self):
        """Test WorklistConfig with all parameters."""
        config = WorklistConfig(
            version="1.22.0",
            include_ports=["COM1", "COM2"],
            ignore_ports=["COM3"],
            board_id="ESP32_GENERIC",
            custom_firmware=True
        )
        
        assert config.version == "1.22.0"
        assert config.include_ports == ["COM1", "COM2"]
        assert config.ignore_ports == ["COM3"]
        assert config.board_id == "ESP32_GENERIC"
        assert config.custom_firmware is True


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_create_flash_task(self):
        """Test _create_flash_task utility."""
        board = MPRemoteBoard("COM1")
        firmware = Firmware(board_id="ESP32_GENERIC", version="1.22.0", port="esp32")
        
        task = _create_flash_task(board, firmware)
        
        assert isinstance(task, FlashTask)
        assert task.board == board
        assert task.firmware == firmware


class TestConversionFunctions:
    """Test conversion between new and legacy formats."""
    
    def test_tasks_to_legacy_worklist(self):
        """Test converting FlashTaskList to legacy WorkList."""
        board = MPRemoteBoard("COM1")
        firmware = Firmware(board_id="ESP32_GENERIC", version="1.22.0", port="esp32")
        task = FlashTask(board=board, firmware=firmware)
        
        worklist = tasks_to_legacy_worklist([task])
        
        assert len(worklist) == 1
        assert worklist[0] == (board, firmware)
    
    def test_legacy_worklist_to_tasks(self):
        """Test converting legacy WorkList to FlashTaskList."""
        board = MPRemoteBoard("COM1")
        firmware = Firmware(board_id="ESP32_GENERIC", version="1.22.0", port="esp32")
        worklist = [(board, firmware)]
        
        tasks = legacy_worklist_to_tasks(worklist)
        
        assert len(tasks) == 1
        assert isinstance(tasks[0], FlashTask)
        assert tasks[0].board == board
        assert tasks[0].firmware == firmware


class TestNewAPIFunctions:
    """Test the new API functions."""
    
    def test_create_manual_worklist_without_board_id(self):
        """Test that create_manual_worklist requires board_id."""
        config = WorklistConfig(version="1.22.0")  # No board_id
        
        with pytest.raises(ValueError, match="board_id must be specified"):
            create_manual_worklist(["COM1"], config)


class TestWorklistConfigClassMethods:
    """Test the WorklistConfig class methods."""
    
    def test_for_auto_detection(self):
        """Test WorklistConfig.for_auto_detection()."""
        config = WorklistConfig.for_auto_detection("1.22.0")
        
        assert config.version == "1.22.0"
        assert config.include_ports == []
        assert config.ignore_ports == []
        assert config.board_id is None
        assert config.custom_firmware is False
    
    def test_for_manual_boards(self):
        """Test WorklistConfig.for_manual_boards()."""
        config = WorklistConfig.for_manual_boards("1.22.0", "ESP32_GENERIC", custom_firmware=True)
        
        assert config.version == "1.22.0"
        assert config.board_id == "ESP32_GENERIC"
        assert config.custom_firmware is True
    
    def test_for_filtered_boards(self):
        """Test WorklistConfig.for_filtered_boards()."""
        config = WorklistConfig.for_filtered_boards(
            "1.22.0", 
            include_ports=["COM1"], 
            ignore_ports=["COM2"]
        )
        
        assert config.version == "1.22.0"
        assert config.include_ports == ["COM1"]
        assert config.ignore_ports == ["COM2"]


class TestHighLevelAPI:
    """Test the high-level create_worklist function."""
    
    def test_create_worklist_manual_mode(self):
        """Test create_worklist in manual mode."""
        # This would need more complex mocking to fully test
        # but we can test the parameter validation
        with pytest.raises(ValueError, match="board_id is required"):
            create_worklist("1.22.0", serial_ports=["COM1"])
    
    def test_create_worklist_no_parameters(self):
        """Test create_worklist with no boards or ports."""
        with pytest.raises(ValueError, match="Either connected_boards or serial_ports must be provided"):
            create_worklist("1.22.0")


def test_module_backward_compatibility():
    """Test that the module maintains backward compatibility."""
    # Test that all legacy functions are still available
    from mpflash.flash.worklist import (
        auto_update_worklist,
        manual_worklist,
        manual_board,
        single_auto_worklist,
        full_auto_worklist,
        filter_boards,
        WorkList,
        FlashItem,
    )
    
    # Test legacy type aliases
    assert WorkList is not None
    assert FlashItem is not None
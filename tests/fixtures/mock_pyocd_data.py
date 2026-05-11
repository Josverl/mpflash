"""
Mock data for pyOCD testing.

Contains sample target data, MCU descriptions, and command outputs
that mimic real pyOCD behavior for testing without hardware dependencies.
"""

from typing import Dict, List, Any

# Sample MCU descriptions from sys.implementation._machine
SAMPLE_MCU_DESCRIPTIONS = {
    "stm32wb55": "NUCLEO-WB55 with STM32WB55RGV6",
    "stm32f429": "NUCLEO-F429ZI with STM32F429ZI",
    "stm32h563": "NUCLEO-H563ZI with STM32H563ZI",
    "stm32f412": "NUCLEO-F412ZG with STM32F412ZG",
    "rp2040": "Raspberry Pi Pico with RP2040",
    "samd51": "Adafruit Metro M4 with SAMD51J19A",
    "esp32": "ESP32-DevKitC with ESP32-WROOM-32",
    "malformed": "Invalid Format",
    "empty": "",
}

# Sample pyOCD target data (built-in targets)
BUILTIN_PYOCD_TARGETS = {
    "stm32f429xi": {
        "vendor": "STMicroelectronics",
        "part_number": "STM32F429XI",
        "source": "builtin"
    },
    "stm32f412xg": {
        "vendor": "STMicroelectronics", 
        "part_number": "STM32F412XG",
        "source": "builtin"
    },
    "stm32wb55xg": {
        "vendor": "STMicroelectronics",
        "part_number": "STM32WB55XG", 
        "source": "builtin"
    },
    "rp2040": {
        "vendor": "Raspberry Pi",
        "part_number": "RP2040",
        "source": "builtin"
    },
    "samd51j19a": {
        "vendor": "Microchip",
        "part_number": "SAMD51J19A",
        "source": "builtin"
    }
}

# Sample pack targets (from CMSIS packs)
PACK_PYOCD_TARGETS = {
    "stm32h563zitx": {
        "vendor": "STMicroelectronics",
        "part_number": "STM32H563ZI",
        "source": "pack"
    },
    "stm32h503cbtx": {
        "vendor": "STMicroelectronics",
        "part_number": "STM32H503CB",
        "source": "pack"
    }
}

# Combined target data
ALL_PYOCD_TARGETS = {**BUILTIN_PYOCD_TARGETS, **PACK_PYOCD_TARGETS}

# Mock subprocess outputs
MOCK_SUBPROCESS_OUTPUTS = {
    "pyocd_list_targets": """
Name              Vendor               Part Number      Architecture     Source
----------------------------------------------------------------------
rp2040            Raspberry Pi         RP2040           ARMv6-M          builtin
stm32f412xg       STMicroelectronics   STM32F412XG      ARMv7E-M         builtin  
stm32f429xi       STMicroelectronics   STM32F429XI      ARMv7E-M         builtin
stm32wb55xg       STMicroelectronics   STM32WB55XG      ARMv7E-M         builtin
stm32h563zitx     STMicroelectronics   STM32H563ZI      ARMv8-M          pack
stm32h503cbtx     STMicroelectronics   STM32H503CB      ARMv8-M          pack
samd51j19a        Microchip            SAMD51J19A       ARMv7E-M         builtin
""",
    
    "pyocd_pack_find_stm32h563": """
Part Number         Vendor               Pack                           Installed
-------------------------------------------------------------------------------
STM32H563ZI         STMicroelectronics   Keil.STM32H5xx_DFP             false
STM32H563VE         STMicroelectronics   Keil.STM32H5xx_DFP             false  
STM32H563ZGT6       STMicroelectronics   Keil.STM32H5xx_DFP             false
""",
    
    "pyocd_pack_find_stm32h503": """
Part Number         Vendor               Pack                           Installed
-------------------------------------------------------------------------------
STM32H503CB         STMicroelectronics   Keil.STM32H5xx_DFP             false
STM32H503RB         STMicroelectronics   Keil.STM32H5xx_DFP             false
""",
    
    "pyocd_pack_install_success": "Successfully installed pack Keil.STM32H5xx_DFP\n",
    
    "pyocd_pack_install_failure": "Error: Failed to download pack from repository\n",
    
    "pyocd_list_probes": """
#   Probe/Board           Unique ID                                  Target Type
----------------------------------------------------------------------
0   ST-Link v3            066CFF505750827567154312               stm32h563zitx
1   CMSIS-DAP Probe       0D28C20417A04C1D                        <no target>
""",
    
    "empty_output": "",
    "command_not_found": "pyocd: command not found\n",
}

# Mock probe data
MOCK_PROBES = [
    {
        "unique_id": "066CFF505750827567154312",
        "description": "ST-Link v3",
        "vendor_name": "STMicroelectronics",
        "product_name": "ST-LINK/V3",
        "target_type": "stm32h563zitx"
    },
    {
        "unique_id": "0D28C20417A04C1D", 
        "description": "CMSIS-DAP Probe",
        "vendor_name": "ARM",
        "product_name": "DAPLink CMSIS-DAP",
        "target_type": None
    }
]

# Expected fuzzy matching results
EXPECTED_FUZZY_MATCHES = {
    "STM32WB55": "stm32wb55xg",
    "STM32F429": "stm32f429xi", 
    "STM32F412": "stm32f412xg",
    "STM32H563": "stm32h563zitx",  # From pack
    "RP2040": "rp2040",
    "SAMD51": "samd51j19a",
    "ESP32": None,  # Not supported by pyOCD
    "UNKNOWN": None,
}

# Test MCU objects (mock MPRemoteBoard)
class MockMCU:
    """Mock MPRemoteBoard for testing."""
    
    def __init__(self, board_id: str, cpu: str, description: str, port: str = "unknown"):
        self.board_id = board_id
        self.cpu = cpu  
        self.description = description
        self.port = port

MOCK_MCUS = {
    "stm32wb55": MockMCU("NUCLEO_WB55", "STM32WB55RGV6", "NUCLEO-WB55 with STM32WB55RGV6", "stm32"),
    "stm32f429": MockMCU("NUCLEO_F429ZI", "STM32F429ZI", "NUCLEO-F429ZI with STM32F429ZI", "stm32"),  
    "stm32h563": MockMCU("NUCLEO_H563ZI", "STM32H563ZI", "NUCLEO-H563ZI with STM32H563ZI", "stm32"),
    "rp2040": MockMCU("RPI_PICO", "RP2040", "Raspberry Pi Pico with RP2040", "rp2"),
    "samd51": MockMCU("METRO_M4", "SAMD51J19A", "Adafruit Metro M4 with SAMD51J19A", "samd"),
    "esp32": MockMCU("ESP32_DEV", "ESP32", "ESP32-DevKitC with ESP32-WROOM-32", "esp32"),
    "malformed": MockMCU("UNKNOWN", "UNKNOWN", "Invalid Format", "unknown"),
}

# Error scenarios for testing
ERROR_SCENARIOS = {
    "pyocd_not_installed": {
        "exception": ImportError("No module named 'pyocd'"),
        "expected_error": "pyOCD is not installed"
    },
    "no_probes_found": {
        "probes": [],
        "expected_error": "No debug probes available"
    },
    "probe_connection_failed": {
        "exception": Exception("Failed to connect to target"),
        "expected_error": "Cannot connect to probe"
    },
    "invalid_firmware_file": {
        "file_path": "/nonexistent/firmware.bin",
        "expected_error": "Firmware file not found"
    },
    "pack_install_timeout": {
        "exception": TimeoutError("Pack installation timed out"),
        "expected_error": "timed out"
    }
}
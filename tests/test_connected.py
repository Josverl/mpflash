import pytest
from pytest_mock import MockerFixture
from serial.tools.list_ports_common import ListPortInfo

from mpflash.connected import connected_ports_boards_variants, list_mcus
from mpflash.mpremoteboard import MPRemoteBoard


class TestConnectedPortsBoardsVariants:
    """Test connected_ports_boards_variants function."""

    def test_empty_connection_list(self, mocker: MockerFixture):
        """Test with no connected MCUs."""
        mocker.patch("mpflash.connected.list_mcus", return_value=[])

        ports, boards, variants, mcus = connected_ports_boards_variants(include=[], ignore=[], bluetooth=False)

        assert ports == []
        assert boards == []
        assert variants == []
        assert mcus == []

    def test_single_connected_mcu(self, mocker: MockerFixture):
        """Test with single connected MCU."""
        mock_mcu = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu.connected = True
        mock_mcu.port = "COM3"
        mock_mcu.board = "ESP32_GENERIC"
        mock_mcu.variant = "SPIRAM"
        mock_mcu.toml = {}

        mocker.patch("mpflash.connected.list_mcus", return_value=[mock_mcu])

        ports, boards, variants, mcus = connected_ports_boards_variants(include=[], ignore=[], bluetooth=False)

        assert ports == ["COM3"]
        assert boards == ["ESP32_GENERIC"]
        assert variants == ["SPIRAM"]
        assert mcus == [mock_mcu]

    def test_multiple_connected_mcus_unique_ports(self, mocker: MockerFixture):
        """Test with multiple MCUs on different ports."""
        mock_mcu1 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu1.connected = True
        mock_mcu1.port = "COM3"
        mock_mcu1.board = "ESP32_GENERIC"
        mock_mcu1.variant = "SPIRAM"
        mock_mcu1.toml = {}

        mock_mcu2 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu2.connected = True
        mock_mcu2.port = "COM4"
        mock_mcu2.board = "PICO"
        mock_mcu2.variant = "W"
        mock_mcu2.toml = {}

        mocker.patch("mpflash.connected.list_mcus", return_value=[mock_mcu1, mock_mcu2])

        ports, boards, variants, mcus = connected_ports_boards_variants(include=[], ignore=[], bluetooth=False)

        assert sorted(ports) == ["COM3", "COM4"]
        assert sorted(boards) == ["ESP32_GENERIC", "PICO"]
        assert sorted(variants) == ["SPIRAM", "W"]
        assert len(mcus) == 2

    def test_duplicate_ports_boards_variants(self, mocker: MockerFixture):
        """Test deduplication of ports, boards, and variants."""
        mock_mcu1 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu1.connected = True
        mock_mcu1.port = "COM3"
        mock_mcu1.board = "ESP32_GENERIC"
        mock_mcu1.variant = "SPIRAM"
        mock_mcu1.toml = {}

        mock_mcu2 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu2.connected = True
        mock_mcu2.port = "COM3"  # Same port
        mock_mcu2.board = "ESP32_GENERIC"  # Same board
        mock_mcu2.variant = "SPIRAM"  # Same variant
        mock_mcu2.toml = {}

        mocker.patch("mpflash.connected.list_mcus", return_value=[mock_mcu1, mock_mcu2])

        ports, boards, variants, mcus = connected_ports_boards_variants(include=[], ignore=[], bluetooth=False)

        assert ports == ["COM3"]  # Deduplicated
        assert boards == ["ESP32_GENERIC"]  # Deduplicated
        assert variants == ["SPIRAM"]  # Deduplicated
        assert len(mcus) == 2  # But MCUs list contains both

    def test_ignore_disconnected_mcus(self, mocker: MockerFixture):
        """Test filtering out disconnected MCUs."""
        mock_mcu1 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu1.connected = True
        mock_mcu1.port = "COM3"
        mock_mcu1.board = "ESP32_GENERIC"
        mock_mcu1.variant = "SPIRAM"
        mock_mcu1.toml = {}

        mock_mcu2 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu2.connected = False  # Not connected
        mock_mcu2.port = "COM4"
        mock_mcu2.board = "PICO"
        mock_mcu2.variant = "W"
        mock_mcu2.toml = {}

        mocker.patch("mpflash.connected.list_mcus", return_value=[mock_mcu1, mock_mcu2])

        ports, boards, variants, mcus = connected_ports_boards_variants(include=[], ignore=[], bluetooth=False)

        assert ports == ["COM3"]
        assert boards == ["ESP32_GENERIC"]
        assert variants == ["SPIRAM"]
        assert len(mcus) == 1
        assert mcus[0] == mock_mcu1

    def test_ignore_flagged_mcus(self, mocker: MockerFixture):
        """Test filtering out MCUs with mpflash ignore flag."""
        mock_mcu1 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu1.connected = True
        mock_mcu1.port = "COM3"
        mock_mcu1.board = "ESP32_GENERIC"
        mock_mcu1.variant = "SPIRAM"
        mock_mcu1.toml = {}

        mock_mcu2 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu2.connected = True
        mock_mcu2.port = "COM4"
        mock_mcu2.board = "PICO"
        mock_mcu2.variant = "W"
        mock_mcu2.toml = {"mpflash": {"ignore": True}}  # Ignored

        mocker.patch("mpflash.connected.list_mcus", return_value=[mock_mcu1, mock_mcu2])

        ports, boards, variants, mcus = connected_ports_boards_variants(include=[], ignore=[], bluetooth=False)

        assert ports == ["COM3"]
        assert boards == ["ESP32_GENERIC"]
        assert variants == ["SPIRAM"]
        assert len(mcus) == 1
        assert mcus[0] == mock_mcu1

    def test_none_variant_handling(self, mocker: MockerFixture):
        """Test handling of MCUs with None variant."""
        mock_mcu = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu.connected = True
        mock_mcu.port = "COM3"
        mock_mcu.board = "ESP32_GENERIC"
        mock_mcu.variant = None
        mock_mcu.toml = {}

        mocker.patch("mpflash.connected.list_mcus", return_value=[mock_mcu])

        ports, boards, variants, mcus = connected_ports_boards_variants(include=[], ignore=[], bluetooth=False)

        assert ports == ["COM3"]
        assert boards == ["ESP32_GENERIC"]
        assert variants == []  # None variant should be filtered out
        assert len(mcus) == 1


class TestListMcus:
    """Test list_mcus function."""

    def test_empty_port_list(self, mocker: MockerFixture):
        """Test with no available ports."""
        mocker.patch("mpflash.connected.filtered_portinfos", return_value=[])

        result = list_mcus(include=[], ignore=[], bluetooth=False)

        assert result == []

    def test_single_port_successful_connection(self, mocker: MockerFixture):
        """Test successful connection to single port."""
        # Create mock port info
        mock_port = mocker.Mock(spec=ListPortInfo)
        mock_port.device = "COM3"
        mock_port.location = "1-1.1"
        mock_port.hwid = "USB VID:PID=1A86:7523"

        mocker.patch("mpflash.connected.filtered_portinfos", return_value=[mock_port])
        mocker.patch("mpflash.connected.find_serial_by_path", return_value="USB\\VID_1A86&PID_7523")

        # Mock MPRemoteBoard
        mock_mcu = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu.serialport = "COM3"
        mock_mcu.get_mcu_info = mocker.Mock()

        mocker.patch("mpflash.connected.MPRemoteBoard", return_value=mock_mcu)
        result = list_mcus(include=[], ignore=[], bluetooth=False)

        assert len(result) == 1
        assert result[0] == mock_mcu
        mock_mcu.get_mcu_info.assert_called_once()

    def test_multiple_ports_successful_connections(self, mocker: MockerFixture):
        """Test successful connections to multiple ports."""
        # Create mock port infos
        mock_port1 = mocker.Mock(spec=ListPortInfo)
        mock_port1.device = "COM3"
        mock_port1.location = "1-1.1"
        mock_port1.hwid = "USB VID:PID=1A86:7523"

        mock_port2 = mocker.Mock(spec=ListPortInfo)
        mock_port2.device = "COM4"
        mock_port2.location = "1-1.2"
        mock_port2.hwid = "USB VID:PID=2E8A:0005"

        mocker.patch("mpflash.connected.filtered_portinfos", return_value=[mock_port1, mock_port2])
        mocker.patch("mpflash.connected.find_serial_by_path", side_effect=["USB\\VID_1A86&PID_7523", "USB\\VID_2E8A&PID_0005"])

        # Mock MPRemoteBoard instances
        mock_mcu1 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu1.serialport = "COM3"
        mock_mcu1.get_mcu_info = mocker.Mock()

        mock_mcu2 = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu2.serialport = "COM4"
        mock_mcu2.get_mcu_info = mocker.Mock()

        mocker.patch("mpflash.connected.MPRemoteBoard", side_effect=[mock_mcu1, mock_mcu2])
        result = list_mcus(include=[], ignore=[], bluetooth=False)

        assert len(result) == 2
        mock_mcu1.get_mcu_info.assert_called_once()
        mock_mcu2.get_mcu_info.assert_called_once()

    def test_connection_error_handling(self, mocker: MockerFixture):
        """Test handling of connection errors."""
        # Create mock port info
        mock_port = mocker.Mock(spec=ListPortInfo)
        mock_port.device = "COM3"
        mock_port.location = "1-1.1"
        mock_port.hwid = "USB VID:PID=1A86:7523"

        mocker.patch("mpflash.connected.filtered_portinfos", return_value=[mock_port])
        mocker.patch("mpflash.connected.find_serial_by_path", return_value="USB\\VID_1A86&PID_7523")

        # Mock rich.print to capture error output
        mock_print = mocker.patch("mpflash.connected.print")

        # Mock MPRemoteBoard that raises ConnectionError
        mock_mcu = mocker.Mock(spec=MPRemoteBoard)
        mock_mcu.serialport = "COM3"
        mock_mcu.get_mcu_info = mocker.Mock(side_effect=ConnectionError("Failed to connect"))

        mocker.patch("mpflash.connected.MPRemoteBoard", return_value=mock_mcu)
        result = list_mcus(include=[], ignore=[], bluetooth=False)

        assert len(result) == 1  # MCU is still in list
        assert result[0] == mock_mcu
        mock_print.assert_called_once_with("Error: Failed to connect")

    def test_fallback_location_handling(self, mocker: MockerFixture):
        """Test fallback location handling when find_serial_by_path returns None."""
        # Create mock port info
        mock_port = mocker.Mock(spec=ListPortInfo)
        mock_port.device = "COM3"
        mock_port.location = "1-1.1"
        mock_port.hwid = "USB VID:PID=1A86:7523"

        mocker.patch("mpflash.connected.filtered_portinfos", return_value=[mock_port])
        mocker.patch("mpflash.connected.find_serial_by_path", return_value=None)  # No path found

        # Mock MPRemoteBoard constructor to capture location parameter
        mock_constructor = mocker.patch("mpflash.connected.MPRemoteBoard")
        list_mcus(include=[], ignore=[], bluetooth=False)

        # Verify location fallback logic
        mock_constructor.assert_called_once_with("COM3", location="1-1.1")

    def test_bluetooth_parameter_passed(self, mocker: MockerFixture):
        """Test that bluetooth parameter is passed to filtered_portinfos."""
        mock_filtered_portinfos = mocker.patch("mpflash.connected.filtered_portinfos", return_value=[])

        list_mcus(include=[], ignore=[], bluetooth=True)

        # Verify bluetooth parameter was passed
        mock_filtered_portinfos.assert_called_once_with(ignore=[], include=[], bluetooth=True)

    def test_include_ignore_parameters_passed(self, mocker: MockerFixture):
        """Test that include and ignore parameters are passed correctly."""
        mock_filtered_portinfos = mocker.patch("mpflash.connected.filtered_portinfos", return_value=[])

        include_list = ["COM3", "COM4"]
        ignore_list = ["COM5"]

        list_mcus(include=include_list, ignore=ignore_list, bluetooth=False)

        # Verify parameters were passed correctly
        mock_filtered_portinfos.assert_called_once_with(ignore=ignore_list, include=include_list, bluetooth=False)

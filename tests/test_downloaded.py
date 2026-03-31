import pytest
from pytest_mock import MockerFixture

from mpflash.db.models import Firmware

# from mpflash.db.downloads import downloaded_fw
from mpflash.downloaded import find_downloaded_firmware
from mpflash.versions import clean_version

pytestmark = [pytest.mark.mpflash]


#########################################################################
# minimal Local test setup # TODO: Add to CI
# mpflash download --version 1.19.1 --board PICO
# mpflash download --version 1.22.2 --board RPI_PICO
# mpflash download --version 1.22.2 --board RPI_PICO_W
# mpflash download --version preview --board ESP32_GENRIC
#########################################################################


def test_load_jsonl_to_db_mocked(mocker: MockerFixture, test_fw_path):
    """Test the JSONL to DB migration"""
    mocker.patch("mpflash.db.loader.load_jsonl_to_db", return_value=None)
    mocker.patch("mpflash.db.loader.update_boards", return_value=None)
    mocker.patch("mpflash.db.core.create_database", return_value=None)
    mocker.patch("mpflash.db.core.run_schema_migrations", return_value=None)

    from mpflash.db.core import migrate_database

    migrate_database(boards=True, firmwares=True)
    assert True


@pytest.mark.parametrize(
    "port, board_id, version, OK",
    [
        ("esp32", "ESP32_GENERIC", "1.24.1", True),
        ("esp32", "GENERIC", "1.24.1", True),
        # Old and new names for PICO
        ("rp2", "RPI_PICO", "1.22.2", True),
        ("rp2", "PICO", "1.22.2", True),
        ("rp2", "PICO", "1.19.1", True),
        # old and new name for PICO_W
        ("rp2", "RPI_PICO_W", "1.22.2", True),
        ("rp2", "PICO_W", "1.22.2", True),
        # Old-style esp32 board names used up to v1.20.0, mapped via alternate_board_names
        # to their v1.21.0+ equivalents (e.g. GENERIC_SPIRAM → ESP32_GENERIC-SPIRAM).
        # Firmware in the test DB only goes back to v1.23.0, so use that version.
        ("esp32", "GENERIC_SPIRAM", "1.23.0", True),
        ("esp32", "GENERIC_OTA", "1.23.0", True),
        ("esp32", "GENERIC_D2WD", "1.23.0", True),
        ("fake", "NO_BOARD", "1.22.2", False),
    ],
)
def test_find_downloaded_firmware(port, board_id, version, OK, session_fx):

    result = find_downloaded_firmware(
        version=version,
        board_id=board_id,
        port=port,
    )
    if not OK:
        assert not result
        return
    version = clean_version(version)
    assert result
    for fw in result:
        assert isinstance(fw, Firmware), "All elements should be FWInfo objects"
        assert fw.port == port, f"Expected {port}, got {fw.port}"
        assert fw.version == version, f"Expected {version}, got {fw.version}"
        assert version in fw.firmware_file, f"Expected {version} in {fw.firmware_file}"
        if fw.board:
            assert fw.board.port == port, f"Expected {port}, got {fw.board.port}"
        else:
            # firware not linked to a board is OK
            pass


def test_find_downloaded_firmware_port_isolation(mocker: MockerFixture, session_fx):
    """Ensure port filter prevents cross-platform firmware selection.

    When the DB contains both ESP32_GENERIC and ESP8266_GENERIC firmware for the same
    version, querying by alternate name with port='esp32' must NOT return esp8266
    firmware and vice-versa. This guards against the regression where
    --port esp32 --board GENERIC would incorrectly return ESP8266 firmware.
    """


    # Search using the new ESP32_GENERIC name with explicit esp32 port
    esp32_results = find_downloaded_firmware(version="v1.24.1", board_id="ESP32_GENERIC", port="esp32")
    # Search using the new ESP8266_GENERIC name with explicit esp8266 port
    esp8266_results = find_downloaded_firmware(version="v1.24.1", board_id="ESP8266_GENERIC", port="esp8266")

    assert esp32_results, "Should find ESP32 firmware"
    assert esp8266_results, "Should find ESP8266 firmware"

    # esp32 query must only return esp32 firmware
    for fw in esp32_results:
        assert fw.port == "esp32", f"esp32 query returned wrong port: {fw.port} ({fw.board_id})"

    # esp8266 query must only return esp8266 firmware
    for fw in esp8266_results:
        assert fw.port == "esp8266", f"esp8266 query returned wrong port: {fw.port} ({fw.board_id})"

    # Verify that the port-specific searches do NOT overlap
    esp32_board_ids = {fw.board_id for fw in esp32_results}
    esp8266_board_ids = {fw.board_id for fw in esp8266_results}
    assert not esp32_board_ids.intersection(esp8266_board_ids), (
        f"ESP32 and ESP8266 results overlap: {esp32_board_ids & esp8266_board_ids}"
    )


def test_find_downloaded_firmware_preview_exact_match(mocker: MockerFixture, session_fx):
    """Preview firmware is found by exact board_id match (covers lines 70-80)."""


    result = find_downloaded_firmware(version="v1.25.0-preview", board_id="ESP32_GENERIC", port="esp32")
    assert result, "Should find preview firmware"
    assert len(result) == 1, "Preview search returns only the latest build"
    fw = result[0]
    assert fw.port == "esp32"
    assert "preview" in fw.firmware_file


def test_find_downloaded_firmware_preview_with_alternate_name(mocker: MockerFixture, session_fx):
    """Preview firmware found via alternate board names with port (covers lines 91-97)."""


    # PICO → RPI_PICO alternate name path for preview, with port filter (line 92→93 True branch)
    result = find_downloaded_firmware(version="v1.25.0-preview", board_id="PICO", port="rp2")
    assert result, "Should find preview firmware via alternate name"
    fw = result[0]
    assert fw.port == "rp2"
    assert "preview" in fw.firmware_file


def test_find_downloaded_firmware_preview_alternate_no_port(mocker: MockerFixture, session_fx):
    """Preview firmware via alternate names without port covers the line 92 False branch."""


    # No port provided → the 'if port:' on line 92 is False
    result = find_downloaded_firmware(version="v1.25.0-preview", board_id="PICO")
    assert result, "Should find preview firmware via alternate name without port"
    fw = result[0]
    assert "preview" in fw.firmware_file


def test_find_downloaded_firmware_preview_no_port(mocker: MockerFixture, session_fx):
    """Preview firmware search without port still returns results (covers port-filter branch)."""


    result = find_downloaded_firmware(version="v1.25.0-preview", board_id="ESP32_GENERIC")
    assert result, "Should find preview firmware even without port"
    fw = result[0]
    assert "preview" in fw.firmware_file

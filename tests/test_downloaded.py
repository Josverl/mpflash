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
        ("fake", "NO_BOARD", "1.22.2", False),
    ],
)
def test_find_downloaded_firmware(port, board_id, version, OK):

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
        assert board_id in fw.board_id, f"Expected {board_id}, got {fw.board_id}"

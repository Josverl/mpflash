from pathlib import Path

import pytest

from mpflash.build import _detect_port_from_board_id, import_firmware_to_database
from mpflash.config import config
from mpflash.db.models import Board, Firmware


@pytest.mark.parametrize(
    "board_id, expected_port",
    [
        ("NUCLEO_H563ZI", "stm32"),
        ("RPI_PICO2", "rp2"),
        ("ESP32_GENERIC", "esp32"),
        ("ESP8266_GENERIC", "esp8266"),
        ("SEEED_WIO_TERMINAL", "samd"),
        ("UNKNOWN_BOARD", "unknown"),
    ],
)
def test_detect_port_from_board_id(board_id: str, expected_port: str):
    assert _detect_port_from_board_id(board_id) == expected_port


def test_import_firmware_to_database_creates_board_and_firmware_records(session_fx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_firmware_folder", tmp_path)

    inside_file = tmp_path / "esp8266" / "ESP8266_GENERIC-v1.26.0.bin"
    inside_file.parent.mkdir(parents=True, exist_ok=True)
    inside_file.write_bytes(b"firmware")

    outside_file = tmp_path.parent / "ESP8266_GENERIC-v1.26.0.elf"
    outside_file.write_bytes(b"elf")

    imported = import_firmware_to_database(
        [inside_file, outside_file],
        board_id="ESP8266_GENERIC",
        version="v1.26.0",
    )

    assert imported == 2

    board = Board.get((Board.board_id == "ESP8266_GENERIC") & (Board.version == "v1.26.0"))
    assert board.port == "esp8266"
    assert board.custom is True
    assert board.path == "built"

    firmware_rows = list(Firmware.select().where((Firmware.board_id == "ESP8266_GENERIC") & (Firmware.version == "v1.26.0")))
    assert len(firmware_rows) == 2
    assert any(fw.firmware_file == "esp8266/ESP8266_GENERIC-v1.26.0.bin" for fw in firmware_rows)
    assert any(fw.firmware_file == str(outside_file) for fw in firmware_rows)


def test_import_firmware_to_database_upserts_existing_firmware(session_fx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_firmware_folder", tmp_path)

    firmware_file = tmp_path / "rp2" / "RPI_PICO2-v1.26.0.uf2"
    firmware_file.parent.mkdir(parents=True, exist_ok=True)
    firmware_file.write_bytes(b"uf2")

    first = import_firmware_to_database(
        [firmware_file],
        board_id="RPI_PICO2",
        version="v1.26.0",
    )
    second = import_firmware_to_database(
        [firmware_file],
        board_id="RPI_PICO2",
        version="v1.26.0",
    )

    assert first == 1
    assert second == 1

    rows = list(Firmware.select().where((Firmware.board_id == "RPI_PICO2") & (Firmware.version == "v1.26.0")))
    assert len(rows) == 1
    assert rows[0].firmware_file == "rp2/RPI_PICO2-v1.26.0.uf2"

import pytest
from pytest_mock import MockerFixture

from mpflash.download import download_firmwares
from mpflash.download.from_web import board_firmware_urls, get_board_urls, get_boards, get_page

pytestmark = [pytest.mark.mpflash]


def test_get_page(mocker: MockerFixture):
    page = get_page("https://micropython.org/download/esp32/")
    assert page
    assert "esp32" in page


def test_get_board_urls(mocker: MockerFixture):
    urls = get_board_urls("https://micropython.org/download/")
    assert urls

    for url in urls:
        assert url["url"].startswith("https://micropython.org/download/")
        assert url["board"]


def test_board_firmware_urls(mocker: MockerFixture):
    urls = board_firmware_urls(
        "https://micropython.org/download/esp32/",
        "esp32",
        "bin",
    )
    assert urls

    for url in urls:
        assert url.startswith("/resources/firmware")
        assert "esp32".upper() in url.upper()
        assert url.endswith("bin")


@pytest.mark.parametrize(
    "port, board_id",
    [
        ("stm32", "PYBV11"),
        ("rp2", "RPI_PICO"),
        ("esp32", "ESP32_GENERIC"),
    ],
)
def test_get_boards(mocker: MockerFixture, port, board_id):
    boards_fw = get_boards(ports=[port], boards=[board_id], clean=True)
    assert boards_fw
    assert len(boards_fw) >= 1
    for fw in boards_fw:
        assert fw.port == port  # same port
        assert fw.board_id.startswith(board_id)  # same or variant


@pytest.mark.parametrize(
    "port, board_id, version",
    [
        ("rp2", "RPI_PICO", "v1.25.0"),
        ("stm32", "PYBV11", "stable"),
        ("esp32", "ESP32_GENERIC", "v1.25.0"),
        ("esp32", "ESP32_GENERIC", "preview"),
    ],
)
def test_download_firmwares(
    mocker: MockerFixture,
    tmp_path,
    session_fx,
    port,
    board_id,
    version,
):
    mocker.patch("mpflash.download.Session", session_fx)
    count = download_firmwares(
        firmware_folder=tmp_path,
        ports=[port],
        boards=[board_id],
        versions=[version],
        force=True,
        clean=True,
    )
    assert count > 0
    # Check if the files are downloaded
    downloads = (tmp_path / port).rglob("*.*")
    assert len(list(downloads)) == count

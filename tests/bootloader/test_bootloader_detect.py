from types import SimpleNamespace

from mpflash.bootloader import detect


class _Backend:
    def __init__(self, ready=True, requires_bootloader=False, priority=0, supported_ports=None):
        self._ready = ready
        self.requires_bootloader = requires_bootloader
        self.priority = priority
        self.supported_ports = supported_ports if supported_ports is not None else set()

    def is_board_ready(self, mcu):
        return self._ready


def _mcu(port="stm32"):
    return SimpleNamespace(port=port, board="BOARD", serialport="COM1")


def test_in_bootloader_short_circuits_for_esp_ports():
    assert detect.in_bootloader(_mcu("esp32")) is True
    assert detect.in_bootloader(_mcu("esp8266")) is True


def test_in_bootloader_returns_false_when_no_backend(mocker):
    mocker.patch("mpflash.bootloader.detect.backend_for_port", return_value=None)
    assert detect.in_bootloader(_mcu("stm32")) is False


def test_in_bootloader_uses_given_backend():
    assert detect.in_bootloader(_mcu("stm32"), backend=_Backend(ready=True)) is True
    assert detect.in_bootloader(_mcu("stm32"), backend=_Backend(ready=False)) is False


def test_backend_for_port_none_when_port_missing():
    assert detect.backend_for_port("") is None


def test_backend_for_port_none_when_no_candidates(mocker):
    mocker.patch("mpflash.flash.registry.get_backends", return_value=[])
    assert detect.backend_for_port("stm32") is None


def test_backend_for_port_prefers_requires_bootloader_and_priority(mocker):
    backends = [
        _Backend(ready=True, requires_bootloader=False, priority=100, supported_ports={"stm32"}),
        _Backend(ready=True, requires_bootloader=True, priority=10, supported_ports={"stm32"}),
        _Backend(ready=True, requires_bootloader=True, priority=50, supported_ports={"stm32"}),
    ]
    mocker.patch("mpflash.flash.registry.get_backends", return_value=backends)

    selected = detect.backend_for_port("stm32")

    assert selected is backends[2]

"""Tests for WSL2 usbipd discovery and reattachment."""

import json
import subprocess

from mpflash.mpremoteboard.usbipd import (
    UsbipdDevice,
    parse_usbipd_state,
    reattach_usbipd_device,
    select_usbipd_device,
)


def _device(bus_id: str, pid: int, serial_number: str, *, attached: bool = False) -> UsbipdDevice:
    return UsbipdDevice(
        bus_id=bus_id,
        vid=0x2E8A,
        pid=pid,
        serial_number=serial_number,
        description="MicroPython board",
        attached=attached,
    )


def _state(device: UsbipdDevice) -> str:
    return json.dumps(
        {
            "Devices": [
                {
                    "BusId": device.bus_id,
                    "ClientIPAddress": "172.22.0.2" if device.attached else None,
                    "Description": device.description,
                    "InstanceId": (f"USB\\VID_{device.vid:04X}&PID_{device.pid:04X}\\{device.serial_number}"),
                }
            ]
        }
    )


def test_parse_usbipd_state_ignores_unplugged_records():
    output = json.dumps(
        {
            "Devices": [
                {
                    "BusId": "9-4",
                    "ClientIPAddress": None,
                    "Description": "MicroPython board",
                    "InstanceId": "USB\\VID_2E8A&PID_1002\\E46024C7434C552A",
                },
                {
                    "BusId": None,
                    "ClientIPAddress": None,
                    "Description": "old device",
                    "InstanceId": "USB\\VID_2E8A&PID_1002\\OLD",
                },
            ]
        }
    )

    assert parse_usbipd_state(output) == [_device("9-4", 0x1002, "E46024C7434C552A")]


def test_select_usbipd_device_uses_serial_with_multiple_boards():
    devices = [
        _device("9-1", 0x0005, "FIRST"),
        _device("9-2", 0x0005, "SECOND"),
    ]

    selected = select_usbipd_device(devices, vid=0x2E8A, pid=0x0005, serial_number="second")

    assert selected == devices[1]


def test_select_usbipd_device_refuses_ambiguous_vid_pid():
    devices = [
        _device("9-1", 0x0005, "FIRST"),
        _device("9-2", 0x0005, "SECOND"),
    ]

    assert select_usbipd_device(devices, vid=0x2E8A, pid=0x0005, serial_number="") is None


def test_reattach_usbipd_device_attaches_matching_bus(mocker):
    device = _device("9-4", 0x1002, "E46024C7434C552A")
    run = mocker.patch(
        "mpflash.mpremoteboard.usbipd.subprocess.run",
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout=_state(device), stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ],
    )

    assert (
        reattach_usbipd_device(
            vid=device.vid,
            pid=device.pid,
            serial_number=device.serial_number,
            executable="usbipd.exe",
        )
        is True
    )
    assert run.call_args_list[1].args[0] == [
        "usbipd.exe",
        "attach",
        "--wsl",
        "--busid",
        "9-4",
    ]


def test_reattach_usbipd_device_does_not_attach_twice(mocker):
    device = _device("9-4", 0x1002, "E46024C7434C552A", attached=True)
    run = mocker.patch(
        "mpflash.mpremoteboard.usbipd.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout=_state(device), stderr=""),
    )

    assert (
        reattach_usbipd_device(
            vid=device.vid,
            pid=device.pid,
            serial_number=device.serial_number,
            executable="usbipd.exe",
        )
        is True
    )
    run.assert_called_once()


def test_reattach_usbipd_device_accepts_attached_state_after_timeout(mocker):
    shared = _device("9-4", 0x1002, "E46024C7434C552A")
    attached = _device("9-4", 0x1002, "E46024C7434C552A", attached=True)
    run = mocker.patch(
        "mpflash.mpremoteboard.usbipd.subprocess.run",
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout=_state(shared), stderr=""),
            subprocess.TimeoutExpired([], 5),
            subprocess.CompletedProcess([], 0, stdout=_state(attached), stderr=""),
        ],
    )

    assert (
        reattach_usbipd_device(
            vid=shared.vid,
            pid=shared.pid,
            serial_number=shared.serial_number,
            executable="usbipd.exe",
        )
        is True
    )
    assert run.call_count == 3

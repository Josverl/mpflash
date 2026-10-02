import json
from typing import List

import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

# # module under test :
from mpflash import cli_main

# mark all tests
pytestmark = pytest.mark.mpflash


##########################################################################################
# list


@pytest.mark.parametrize(
    "id, ex_code, args",
    [
        ("1", 0, ["list"]),
        ("2", 0, ["list", "--json"]),
        ("3", 0, ["list", "--no-progress"]),
        ("4", 0, ["list", "--json", "--no-progress"]),
        ("5", 0, ["list", "--no-reset"]),
        ("6", 0, ["list", "--reset"]),
        ("7", 0, ["list", "--no-softdevice"]),
    ],
)
def test_mpflash_list(id, ex_code, args: List[str], mocker: MockerFixture):
    m_list_mcus = mocker.patch("mpflash.connected.list_mcus", return_value=[], autospec=True)
    m_show_mcus = mocker.patch("mpflash.list.show_mcus", return_value=None, autospec=True)
    m_echo = mocker.patch("mpflash.cli_list.click.echo", return_value=None, autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)
    assert result.exit_code == ex_code

    m_list_mcus.assert_called_once()
    assert m_list_mcus.call_args.kwargs["probe_softdevice"] is ("--no-reset" not in args and "--no-softdevice" not in args)
    if "--json" in args:
        m_echo.assert_called_once()
        m_show_mcus.assert_not_called()
    elif "--no-progress" not in args:
        m_show_mcus.assert_called_once()


def test_mpflash_list_reset_family_specific_commands(mocker: MockerFixture):
    class _Mcu:
        def __init__(self, family):
            self.family = family
            self.toml = {}
            self.run_command = mocker.Mock()

        def to_dict(self):
            return {"family": self.family}

    cp = _Mcu("circuitpython")
    unknown = _Mcu("unknown")
    mpy = _Mcu("micropython")

    mocker.patch("mpflash.connected.list_mcus", return_value=[cp, unknown, mpy], autospec=True)
    mocker.patch("mpflash.list.show_mcus", return_value=None, autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["list", "--no-progress", "--reset"], standalone_mode=True)

    assert result.exit_code == 0
    cp.run_command.assert_called_once_with(
        ["exec", "--no-follow", "import microcontroller,time;time.sleep(0.01);microcontroller.reset()"],
        soft_reset=True,
    )
    unknown.run_command.assert_not_called()
    mpy.run_command.assert_called_once_with("reset")


def test_mpflash_list_json_is_machine_readable(mocker: MockerFixture):
    class _Mcu:
        family = "unknown"
        softdevice = "S140 version 6.1.1"
        toml = {}

        def to_dict(self):
            return {
                "description": "A long nRF description that must not be wrapped inside JSON output",
                "softdevice": self.softdevice,
            }

    mocker.patch("mpflash.connected.list_mcus", return_value=[_Mcu()], autospec=True)

    result = CliRunner().invoke(
        cli_main.cli,
        ["list", "--json", "--no-reset"],
        standalone_mode=True,
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {
            "description": "A long nRF description that must not be wrapped inside JSON output",
            "softdevice": "S140 version 6.1.1",
        }
    ]


def test_mpflash_list_returns_one_when_all_ignored(mocker: MockerFixture):
    class _Mcu:
        family = "micropython"
        toml = {"mpflash": {"ignore": True}}

        def to_dict(self):
            return {}

    mocker.patch("mpflash.connected.list_mcus", return_value=[_Mcu()], autospec=True)
    mocker.patch("mpflash.list.show_mcus", return_value=None, autospec=True)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["list", "--no-progress", "--no-reset"], standalone_mode=False)

    assert result.exit_code == 0
    assert result.return_value == 1

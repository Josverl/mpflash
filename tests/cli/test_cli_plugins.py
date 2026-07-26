from click.testing import CliRunner

from mpflash import cli_main


class _Backend:
    def __init__(
        self,
        name,
        ports,
        formats,
        platforms,
        priority,
        requires_bootloader,
        available,
    ):
        self.name = name
        self.supported_ports = ports
        self.supported_formats = formats
        self.supported_platforms = platforms
        self.priority = priority
        self.requires_bootloader = requires_bootloader
        self._available = available

    def is_available(self):
        return self._available


def test_plugins_plain_output(mocker):
    platform = type("Platform", (), {"value": "linux"})()
    backend = _Backend("pyocd", {"rp2"}, [".bin", ".elf"], {platform}, -10, False, True)

    mocker.patch("mpflash.cli_plugins.get_backends", return_value=[backend])
    mocker.patch("mpflash.cli_plugins.default_services.current_platform", return_value=platform)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["plugins", "--format", "plain"], standalone_mode=True)

    assert result.exit_code == 0
    assert "pyocd" in result.output
    assert "available=yes" in result.output


def test_plugins_table_output(mocker):
    platform = type("Platform", (), {"value": "linux"})()
    backend = _Backend("uf2", {"rp2", "samd"}, [".uf2"], {platform}, 10, True, False)

    m_print = mocker.patch("mpflash.cli_plugins._console.print")
    mocker.patch("mpflash.cli_plugins.get_backends", return_value=[backend])
    mocker.patch("mpflash.cli_plugins.default_services.current_platform", return_value=platform)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["plugins"], standalone_mode=True)

    assert result.exit_code == 0
    m_print.assert_called_once()

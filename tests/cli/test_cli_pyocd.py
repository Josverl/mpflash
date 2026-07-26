from click.testing import CliRunner

from mpflash import cli_main


class _Probe:
    def __init__(self, unique_id="1234", description="Probe", vendor="Arm", product="DAP"):
        self.unique_id = unique_id
        self.description = description
        self.vendor_name = vendor
        self.product_name = product

    def detect_target_type(self):
        return "rp2040"


def test_list_supported_targets_returns_empty_on_error(mocker):
    import mpflash.cli_pyocd as cli_pyocd

    mocker.patch("mpflash.cli_pyocd.get_pyocd_targets", side_effect=RuntimeError("boom"))
    assert cli_pyocd.list_supported_targets() == {}


def test_cli_list_probes_pyocd_unavailable(mocker):
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", False)
    m_log = mocker.patch("mpflash.cli_pyocd.log")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["list-probes"], standalone_mode=True)

    assert result.exit_code == 0
    m_log.error.assert_called_once()


def test_cli_list_probes_not_functional(mocker):
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", True)
    mocker.patch("mpflash.cli_pyocd.is_pyocd_available", return_value=False)
    m_log = mocker.patch("mpflash.cli_pyocd.log")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["list-probes"], standalone_mode=True)

    assert result.exit_code == 0
    m_log.error.assert_called_once()


def test_cli_list_probes_none_found(mocker):
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", True)
    mocker.patch("mpflash.cli_pyocd.is_pyocd_available", return_value=True)
    mocker.patch("mpflash.cli_pyocd.list_pyocd_probes", return_value=[])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["list-probes"], standalone_mode=True)

    assert result.exit_code == 0
    assert "No pyOCD debug probes found" in result.output


def test_cli_list_probes_with_detection(mocker):
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", True)
    mocker.patch("mpflash.cli_pyocd.is_pyocd_available", return_value=True)
    mocker.patch("mpflash.cli_pyocd.list_pyocd_probes", return_value=[_Probe()])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["list-probes"], standalone_mode=True)

    assert result.exit_code == 0


def test_cli_list_probes_detection_exception(mocker):
    class BadProbe(_Probe):
        def detect_target_type(self):
            raise RuntimeError("probe timeout")

    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", True)
    mocker.patch("mpflash.cli_pyocd.is_pyocd_available", return_value=True)
    mocker.patch("mpflash.cli_pyocd.list_pyocd_probes", return_value=[BadProbe()])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["list-probes"], standalone_mode=True)

    assert result.exit_code == 0


def test_cli_pyocd_info_not_installed(mocker):
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", False)

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["pyocd-info"], standalone_mode=True)

    assert result.exit_code == 0
    assert "not installed" in result.output


def test_cli_pyocd_info_installed(mocker):
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", True)
    mocker.patch(
        "mpflash.cli_pyocd.pyocd_info",
        return_value={
            "available": True,
            "version": "0.38.0",
            "probes": [{"unique_id": "abc", "description": "STLink", "target_type": "stm32h5"}],
        },
    )
    mocker.patch(
        "mpflash.cli_pyocd.get_pyocd_targets",
        return_value={
            "NUCLEO_H563ZI": {"part_number": "stm32h563"},
            "RPI_PICO": {"part_number": "rp2040"},
            "SEEED_WIO_TERMINAL": {"part_number": "samd51"},
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["pyocd-info"], standalone_mode=True)

    assert result.exit_code == 0
    assert "installed" in result.output


def test_cli_pyocd_targets_filter_and_no_matches(mocker):
    targets = {
        "NUCLEO_H563ZI": "stm32h563",
        "RPI_PICO": "rp2040",
    }
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", True)
    mocker.patch("mpflash.cli_pyocd.list_supported_targets", return_value=targets)

    runner = CliRunner()

    matched = runner.invoke(
        cli_main.cli,
        ["pyocd-targets", "--board-filter", "PICO", "--target-filter", "rp20"],
        standalone_mode=True,
    )
    assert matched.exit_code == 0

    no_match = runner.invoke(
        cli_main.cli,
        ["pyocd-targets", "--board-filter", "DOES_NOT_EXIST"],
        standalone_mode=True,
    )
    assert no_match.exit_code == 0
    assert "No targets match the specified filters" in no_match.output


def test_cli_pyocd_targets_handles_runtime_error(mocker):
    mocker.patch("mpflash.cli_pyocd.PYOCD_AVAILABLE", True)
    mocker.patch("mpflash.cli_pyocd.list_supported_targets", side_effect=RuntimeError("boom"))
    m_log = mocker.patch("mpflash.cli_pyocd.log")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["pyocd-targets"], standalone_mode=True)

    assert result.exit_code == 0
    m_log.error.assert_called_once()

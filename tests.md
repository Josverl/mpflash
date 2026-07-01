# how to run tests

To install test dependencies, use:
```
uv sync --extra test
```

To run all tests, use:
```
uv run pytest
```

To run tests with coverage report:
```
uv run pytest --cov
```

To generate an HTML coverage report:
```
uv run pytest --cov=mpflash --cov-report=html
```
Open the generated `htmlcov/index.html` in your browser to view the coverage report.



Database tests
-----------------

The majority of thests is run using a (copy) of a populated database located in tests/data/mpflash.db

A number of fixtures have been setup in tests/conftest.py to simplify using the session or engine in tests. The fixtures are:
- session_fx: a session object that is used to run tests
- engine_fx: an engine object that is used to run tests
- db_fx: a database object that is used to run tests


Hardware-in-the-loop tests
--------------------------

The flash backends can also be exercised against real boards via the smoke
tests in [tests/hw/test_hw_backends.py](tests/hw/test_hw_backends.py). They are
skipped by default and only run when both:

1. The matching pytest marker is selected (each test is tagged with `hardware`
   plus one backend-specific marker).
2. The environment variables for that backend point at a connected board and a
   firmware file on disk.

### Markers

| Marker       | Backend  | Required ports / probes                                   |
| ------------ | -------- | --------------------------------------------------------- |
| `hw_uf2`     | UF2      | RP2, SAMD or nRF board in bootloader (mass-storage) mode  |
| `hw_dfu`     | DFU      | STM32 board in DFU mode                                   |
| `hw_esptool` | esptool  | ESP32 / ESP8266 board on a serial port                    |
| `hw_pyocd`   | pyOCD    | CMSIS-DAP / J-Link probe attached to a Cortex-M target    |

All four tests also carry the umbrella `hardware` marker, so the default
suite (`uv run pytest`) excludes them. Run `uv run pytest --markers` to list
every marker.

### Environment variables

Each backend is gated on two variables — one for the port/probe and one for
the firmware file:

| Backend  | Port variable               | Firmware variable          | Notes                                |
| -------- | --------------------------- | -------------------------- | ------------------------------------ |
| UF2      | `MPFLASH_HW_UF2_PORT`       | `MPFLASH_HW_UF2_FW`        | Serial port or mounted UF2 volume    |
| DFU      | `MPFLASH_HW_DFU_PORT`       | `MPFLASH_HW_DFU_FW`        | `.dfu` or `.bin` file                |
| esptool  | `MPFLASH_HW_ESP_PORT`       | `MPFLASH_HW_ESP_FW`        | `.bin` file                          |
| pyOCD    | `MPFLASH_HW_PYOCD_PROBE`    | `MPFLASH_HW_PYOCD_FW`      | Probe unique-id from `pyocd list`    |

If a variable is unset or points at a missing file, the matching test is
skipped with an explanatory message.

### Running

Install the test extras (and `pyocd` if you want to drive the pyOCD backend):

```bash
uv sync --extra test --extra pyocd
```

Use one shared `.env` file for hardware settings (recommended):

```env
# UF2 example
# Linux / WSL path examples:
MPFLASH_HW_UF2_PORT=/dev/ttyACM1
MPFLASH_HW_UF2_FW=/mnt/c/Users/jos_v/Downloads/firmware/rp2/RPI_PICO2-v1.28.0.uf2
# Native Windows path example (PowerShell / cmd):
# MPFLASH_HW_UF2_PORT=COM5
# MPFLASH_HW_UF2_FW=C:\Users\jos_v\Downloads\firmware\rp2\RPI_PICO2-v1.28.0.uf2

# Optional: tune loguru verbosity during pytest runs
LOGURU_LEVEL=INFO
```

This keeps board/probe and firmware paths in one place for:
- interactive debugging in VS Code
- `just` recipes
- direct `uv run pytest ...` command-line runs

Run a single backend from the command line (load `.env` first).

Linux / macOS / WSL:

```bash
set -a
source .env
set +a

uv run pytest -m hw_uf2 tests/hw -v
```

Windows PowerShell:

```powershell
Get-Content .env | ForEach-Object {
   if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
   $name, $value = $_ -split '=', 2
   [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
}

uv run pytest -m hw_uf2 tests/hw -v
```

With `just`, prefer enabling dotenv loading in `justfile` so recipes read `.env`
automatically:

```just
set dotenv-load := true
```

Then run:

```bash
just hil_pico2
```

This `just` command works on Linux/macOS/WSL and on Windows PowerShell
because `set dotenv-load := true` loads the same `.env` file before the recipe.

For interactive debugging in VS Code, point launch/test configuration at the
same `.env` file (for example `envFile: ${workspaceFolder}/.env`).

Run every hardware test for which the environment is configured:

```bash
uv run pytest -m hardware tests/hw -v
```

Windows PowerShell uses the same pytest command once `.env` is loaded.

Combine markers to select a subset, e.g. UF2 + DFU only:

```bash
uv run pytest -m "hw_uf2 or hw_dfu" tests/hw -v
```

### Discovering ports and probes

* Serial ports: `mpflash list` 
  (or `ls /dev/serial/by-id/` on Linux, `pnputil /enum-devices /connected` on Windows).
* pyOCD probes: `pyocd list` prints each probe's unique-id 
  copy that value into `MPFLASH_HW_PYOCD_PROBE`.

### Adding a new hardware test

Hardware tests should stay minimal — one happy-path call into
`mpflash.flash.flash_mcu` per backend. To add a new test:

1. Mark it with `@pytest.mark.hw_<backend>` (and rely on the module-level
   `pytestmark = pytest.mark.hardware` for the umbrella marker).
2. Request the `hw_board` fixture plus the backend's firmware fixture
   (`hw_uf2_firmware`, `hw_dfu_firmware`, …) — both are defined in
   [tests/hw/conftest.py](tests/hw/conftest.py).
3. Keep assertions to the externally observable result (an updated
   `MPRemoteBoard`); leave deeper verification to the unit tests.

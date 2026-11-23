## MPRemoteBoard API

The standalone `mpremoteboard` distribution provides serial discovery, raw
MicroPython board metadata, and `mpremote` command execution without importing
MPFlash, its firmware database, or its CLI configuration. MPFlash keeps the
`mpflash.mpremoteboard` compatibility facade for enriched board identity and
legacy reset/retry defaults. The standalone distribution is buildable from the
workspace; its publication is tracked separately.

Use `mpremoteboard.MPRemoteBoard` for the lightweight API. Use
`mpflash.mpremoteboard.MPRemoteBoard` when you need MPFlash's database-backed
board matching and its historical behavior.

**Common use cases**
- Identify connected boards, including vendor/product IDs and board IDs.
- Pull raw firmware details (family, version, build, mpy ABI) for compatibility checks.
- Read or write `board_info.toml` to persist metadata on the device.
- Run `mpremote` commands in scripts with structured logging.
- Install MicroPython packages via `mip` and wait for safe restarts.

### Core Class

**Standalone `MPRemoteBoard`** (source:
[packages/mpremoteboard/src/mpremoteboard/__init__.py](../packages/mpremoteboard/src/mpremoteboard/__init__.py))

- **`__init__(serialport: str = "", update: bool = False, *, location: str = "")`**
	- Prepares a board handle for a given serial port; optionally calls
		`get_mcu_info()` immediately to populate metadata. Captures VID/PID when
		available and records USB location hints.
	- Attributes available after `get_mcu_info()`: `family`, `version`, `build`,
		`port`, `cpu`, `arch`, `mpy`, `description`, `board_id`, `board`, `variant`,
		`toml` (optional board_info contents), `vid`, `pid`.
- **`connected_comports(bluetooth: bool = False, description: bool = False) -> list[str]`**
	- Enumerates serial ports; can include descriptive text, and filters out
		Bluetooth ports by default for cleaner MicroPython discovery.
- **`get_mcu_info(timeout: int = 2)`**
	- Executes the onboard probe script to read firmware identity, ABI info, CPU,
		and raw board descriptors without consulting MPFlash's firmware database.
		Probing preserves interpreter state by default; pass `soft_reset=True` to
		reset explicitly.
- **`get_board_info_toml(timeout: int = DEFAULT_TIMEOUT)`**
	- Reads `:board_info.toml` from the device (if present) and parses it into
		`self.toml`, enabling access to optional metadata downstream.
- **`set_board_info_toml(timeout: int = 1)`**
	- Writes the current `self.toml` back to the device as `board_info.toml`,
		useful for persisting calibrated or provisioning data on the board.
- **`run_command(cmd, *, log_errors=True, no_info=False, timeout=60, soft_reset=False)`**
	- Executes `mpremote` subcommands with logging control; interpreter state is
		preserved unless `soft_reset=True`. Returns `(rc, output)`.
- **`mip_install(name: str) -> bool`**
	- Installs a MicroPython package using `mip install <name>`; marks the session
		as connected upon success.
- **`wait_for_restart(timeout: int = 10)`**
	- Wait loop that polls for MCU availability after a reset or
		install, exiting early when communication is restored.
- **`disconnect() -> bool`**
	- Issues `mpremote disconnect` when a port is known, clears connection state,
		and reports success.
- **`to_dict() -> dict`**
	- Produces a serialization-ready dictionary of attributes and properties for
		logging, diagnostics, or API responses (omits transient members).

### Runner Utility

**`runner.run(cmd: list[str], timeout: int = 60, log_errors: bool = True, no_info: bool = False, *, log_warnings: bool = False, reset_tags=None, error_tags=None, warning_tags=None, success_tags=None, ignore_tags=None) -> tuple[int, list[str]]`** (source: [packages/mpremoteboard/src/mpremoteboard/runner.py](../packages/mpremoteboard/src/mpremoteboard/runner.py))

- Runs an external command (commonly `mpremote`) and streams stdout/stderr.
- Output lines are inspected for tag lists to classify logging behavior:
	- `reset_tags`: if matched, raises `RuntimeError` (board reset detected).
	- `error_tags`: logged at error level unless `log_errors=False`.
	- `warning_tags`: logged at warning level when present.
	- `success_tags`: logged as success.
	- `ignore_tags`: skipped entirely.
- Defaults cover common MicroPython/mpremote messages (see below and runner.py constants).
- Returns `(return_code, output_lines)`; raises `TimeoutError` on `timeout` and
	`FileNotFoundError` if the command cannot start.
- `no_info=True` suppresses info-level logging of neutral lines.
- `log_warnings=True` emits a warning if the process times out.
- `runner` is standalone; `MPRemoteBoard` uses it under the hood, but you can
	call it directly without constructing an `MPRemoteBoard` instance.

Default tag lists (abridged)

| Purpose        | Sample entries                                         |
| -------------- | ------------------------------------------------------ |
| reset_tags     | `rst cause:1, boot mode:`, `rst:0x10 (RTCWDT_RTC_RESET)` |
| error_tags     | `Traceback `, `Error: `, `Exception: `                 |
| warning_tags   | `WARN  :`, `TRACE :`                                  |
| success_tags   | `Done`, `File saved`, `File removed`                  |
| ignore_tags    | `mpremote: rm -r: cannot remove :/ Operation not permitted` |

#### Runner examples

Basic mpremote invocation with default tagging

```python
from mpremoteboard.runner import run

rc, lines = run(["python", "-m", "mpremote", "connect", "/dev/ttyACM0", "ls"])
print(rc, "".join(lines))
```

Suppress info logging but keep errors

```python
rc, lines = run(["python", "-m", "mpremote", "ls"], no_info=True)
```

Custom tag handling (treat a custom banner as success and silence a noisy warning)

```python
custom_success = ["UPLOAD COMPLETE"]
custom_ignore = ["Low battery warning"]

rc, lines = run(
		["python", "-m", "mpremote", "mount", "."],
		success_tags=custom_success,
		ignore_tags=custom_ignore,
)
```

Detect board resets explicitly

```python
try:
		run(["python", "-m", "mpremote", "repl"], timeout=15)
except RuntimeError:
		print("Board reset detected; reconnect and retry")
```

### Firmware Info Probe

**Script:** [packages/mpremoteboard/src/mpremoteboard/mpy_fw_info.py](../packages/mpremoteboard/src/mpremoteboard/mpy_fw_info.py)

- Designed to run on the board via `mpremote run`. Prints a single dictionary
	with keys like `family`, `version`, `build`, `port`, `board`, `board_id`,
	`variant`, `cpu`, `mpy`, `arch`, `ver`.

### Usage Examples

#### List available boards

```python
from mpremoteboard import MPRemoteBoard

ports = MPRemoteBoard.connected_comports()
print("Detected ports:", ports)
```

#### Read board info and board_info.toml

```python
from mpremoteboard import MPRemoteBoard

board = MPRemoteBoard(serialport="/dev/ttyACM0", update=True)
print(board.family, board.version, board.board_id)

# optional board_info.toml if present on device
if board.toml:
		print("board_info.toml description:", board.toml.get("description", ""))
```

#### Run a custom mpremote command

```python
from mpremoteboard import MPRemoteBoard

board = MPRemoteBoard("/dev/ttyACM0", update=True)
rc, out = board.run_command(["ls", ":/"])
if rc == 0:
		print("Files on device:\n" + "".join(out))
```

#### Install a MicroPython package with mip

```python
from mpremoteboard import MPRemoteBoard

board = MPRemoteBoard("/dev/ttyACM0", update=True)
if board.mip_install("micropython-ulab"):
		board.wait_for_restart()
		print("ulab installed")
```

#### Update board_info.toml on device

```python
from mpremoteboard import MPRemoteBoard

board = MPRemoteBoard("/dev/ttyACM0", update=True)
board.toml["description"] = "Custom lab board"
board.set_board_info_toml()
```

#### Directly use runner.run

```python
from mpremoteboard.runner import run

rc, lines = run(["python", "-m", "mpremote", "connect", "/dev/ttyACM0", "ls"])
print(rc, "".join(lines))
```

### MPFlash compatibility facade

Existing imports from `mpflash.mpremoteboard` remain supported. That facade
adds MPFlash's database-backed board ID/port matching, applies MPFlash-specific
`board_info.toml` overrides, and retains the previous default reset and retry
policies. It delegates command execution and raw probing to the standalone
package.

### Notes

- Most commands rely on `mpremote` being available in the active environment.
- The MPFlash facade retries `get_mcu_info()` and `run_command()` up to three
	times for compatibility. The standalone package leaves retry policy to its
	consumer.
- The MPFlash facade continues to accept deprecated `resume`; new code should
	use `soft_reset` to state whether an operation resets the interpreter.

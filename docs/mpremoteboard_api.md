## MPRemoteBoard API

`mpremoteboard` provides a resilient interface around `mpremote` for discovering
connected boards, reading firmware metadata, and executing commands with sensible
defaults (retries, timeouts, logging tags). Use it when you need a programmatic
way to interrogate or manage MicroPython devices over serial (e.g., `/dev/ttyACM0`).

**Common use cases**
- Identify connected boards, including vendor/product IDs and board IDs.
- Pull firmware details (family, version, build, mpy ABI) for compatibility checks.
- Read or write `board_info.toml` to persist metadata on the device.
- Run `mpremote` commands in scripts with retry/backoff and structured logging.
- Install MicroPython packages via `mip` and wait for safe restarts.

### Core Class

**`MPRemoteBoard`** (source: [mpflash/mpremoteboard/__init__.py](../mpflash/mpremoteboard/__init__.py))

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
		and board descriptors; auto-resolves board IDs via description matching.
		Retries transient failures up to 3 times.
- **`get_board_info_toml(timeout: int = 1)`**
	- Reads `:board_info.toml` from the device (if present) and parses it into
		`self.toml`, enabling richer metadata downstream.
- **`set_board_info_toml(timeout: int = 1)`**
	- Writes the current `self.toml` back to the device as `board_info.toml`,
		useful for persisting calibrated or provisioning data on the board.
- **`run_command(cmd, *, log_errors=True, no_info=False, timeout=60, resume=None)`**
	- Executes arbitrary `mpremote` subcommands with tagging, logging control, and
		optional session resume to avoid reconnect overhead; returns `(rc, output)`
		where `rc == 0` indicates success.
- **`mip_install(name: str) -> bool`**
	- Installs a MicroPython package using `mip install <name>`; marks the session
		as connected upon success.
- **`wait_for_restart(timeout: int = 10)`**
	- Progress-bar wait loop that polls for MCU availability after a reset or
		install, exiting early when communication is restored.
- **`disconnect() -> bool`**
	- Issues `mpremote disconnect` when a port is known, clears connection state,
		and reports success.
- **`to_dict() -> dict`**
	- Produces a serialization-ready dictionary of attributes and properties for
		logging, diagnostics, or API responses (omits transient members).

### Runner Utility

**`runner.run(cmd: list[str], timeout: int = 60, log_errors: bool = True, no_info: bool = False, *, log_warnings: bool = False, reset_tags=None, error_tags=None, warning_tags=None, success_tags=None, ignore_tags=None) -> tuple[int, list[str]]`** (source: [mpflash/mpremoteboard/runner.py](../mpflash/mpremoteboard/runner.py))

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
from mpflash.mpremoteboard.runner import run

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

**Script:** [mpflash/mpremoteboard/mpy_fw_info.py](../mpflash/mpremoteboard/mpy_fw_info.py)

- Designed to run on the board via `mpremote run`. Prints a single dictionary
	with keys like `family`, `version`, `build`, `port`, `board`, `board_id`,
	`variant`, `cpu`, `mpy`, `arch`, `ver`.

### Usage Examples

#### List available boards

```python
from mpflash.mpremoteboard import MPRemoteBoard

ports = MPRemoteBoard.connected_comports()
print("Detected ports:", ports)
```

#### Read board info and board_info.toml

```python
from mpflash.mpremoteboard import MPRemoteBoard

board = MPRemoteBoard(serialport="/dev/ttyACM0", update=True)
print(board.family, board.version, board.board_id)

# optional board_info.toml if present on device
if board.toml:
		print("board_info.toml description:", board.toml.get("description", ""))
```

#### Run a custom mpremote command

```python
from mpflash.mpremoteboard import MPRemoteBoard

board = MPRemoteBoard("/dev/ttyACM0", update=True)
rc, out = board.run_command(["ls", ":/"])
if rc == 0:
		print("Files on device:\n" + "".join(out))
```

#### Install a MicroPython package with mip

```python
from mpflash.mpremoteboard import MPRemoteBoard

board = MPRemoteBoard("/dev/ttyACM0", update=True)
if board.mip_install("micropython-ulab"):
		board.wait_for_restart()
		print("ulab installed")
```

#### Update board_info.toml on device

```python
from mpflash.mpremoteboard import MPRemoteBoard

board = MPRemoteBoard("/dev/ttyACM0", update=True)
board.toml["description"] = "Custom lab board"
board.set_board_info_toml()
```

#### Directly use runner.run

```python
from mpflash.mpremoteboard.runner import run

rc, lines = run(["python", "-m", "mpremote", "connect", "/dev/ttyACM0", "ls"])
print(rc, "".join(lines))
```

### Notes

- Most commands rely on `mpremote` being available in the active environment.
- `get_mcu_info()` and `run_command()` retry transient failures up to three times
	using exponential backoff parameters defined in the module.
- When `resume=True`, mpremote sessions stay open between calls, which is faster
	but requires explicit `disconnect()` when finished.

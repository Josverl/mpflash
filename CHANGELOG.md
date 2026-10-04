# Changelog

All notable changes to mpflash are documented in this file.

## [Unreleased]

### Changed

- Require the mpremote v1.30 preview and use its state-preserving default.
  `MPRemoteBoard.run_command` now accepts `soft_reset=True` when a clean
  interpreter is required. The old `resume=` keyword remains temporarily
  supported with a `DeprecationWarning`.

### Added

- **Backup bundle foundation (not yet user-visible)** — `mpflash.backup` provides a
  schema-versioned, hash-verified bundle format (`README.md`, `manifest.json`, artifacts),
  an atomic writer and strict reader, and a provider registry with the
  `mpflash.backup_plugins` entry-point group. The `backup` and `restore` commands are
  hidden until the MVP is documented.
- **VFS backup provider** — logical backup and mirror-restore of the MicroPython filesystem
  of any responsive board over one raw-REPL connection (SAMD, nRF, ESP32 and ESP8266 verified
  on hardware). The filesystem is stored once, in `artifacts/vfs.zip`, with a hashed
  inventory; restore verifies every file by SHA-256, deletes files that are not in the backup
  and leaves ROMFS and SD cards alone.
- **ESP raw flash backup provider** — byte-exact backup and restore of the whole SPI flash of
  a UART-connected ESP32 or ESP8266 through esptool, verified on hardware by restoring a
  damaged board and re-reading an identical image. The image already contains the filesystem,
  so restoring it replaces that too. Chips with flash encryption, secure boot or secure
  download mode are refused, restore requires the same chip and flash size, the result is
  verified by MD5 and esptool's `force` option is never used. eFuses and keys are not part of
  the image. Native-USB ESP boards are not supported yet.
- **RP2040 raw flash backup provider** — backup and restore of the whole flash of an RP2040
  board running MicroPython (verified on a Pico LiPo 16MB). No picotool, driver or extra
  dependency is needed: the flash is read through the REPL and restored through the board's UF2
  bootloader, rewriting only the 4 KiB sectors that differ. Every chunk carries a CRC32 and is
  retried if damaged, and the whole image is verified by a SHA-256 calculated on the board. Erased
  blocks are not transferred, so a mostly empty board takes seconds and a full 16 MiB about a minute.
- **Faster serial reads** — the backup commands read raw-REPL output in bulk instead of one byte
  at a time (mpremote's own reader). Large reads from a Pico measured about 4x faster; small
  filesystems are dominated by per-file latency and are unchanged.
- **Offline nRF SoftDevice migration** — `mpflash flash --softdevice` can
  migrate allowlisted nice!nano-compatible nRF52840 boards between the curated
  S140 6.1.1/nice!nano and S140 7.3.0/SuperMini profiles. MPFlash validates the
  bootloader, pinned Serial DFU package, and matching application UF2 before
  replacing the SoftDevice+bootloader and restoring MicroPython. Firmware blobs
  and license notices are packaged locally; flashing performs no runtime
  downloads. Install the transport with the `nrf` extra.
- **Forced nRF SoftDevice repair** — `flash --repair-softdevice` reinstalls the
  selected allowlisted SoftDevice+bootloader package even when UF2 metadata
  already reports that profile, allowing recovery when the application region
  or SoftDevice contents were corrupted by an incompatible UF2.
- **Explicit custom firmware metadata** — `mpflash add` accepts `--board`,
  `--port`, and `--version`, and explicitly described custom UF2 firmware can
  be selected for otherwise unknown boards with `flash --custom --volume`.
- **nRF SoftDevice details in `mpflash list`** — runtime nRF boards are
  round-tripped through UF2 mode so the installed SoftDevice can be read from
  `INFO_UF2.TXT`, then returned to their application without changing flash.
  Already-mounted nRF bootloaders are also reported when they can be matched
  unambiguously. Use `--no-softdevice` or `--no-reset` to skip the probe.

- **`--format` option for `mpflash flash`** — reformats the board's filesystem after
  flashing, recreating an empty filesystem of the same type (`VfsLfs2` or `VfsFat`) via
  the MicroPython block device. Supported on `rp2`, `esp32`, `esp8266`, `samd`, `stm32`,
  `nrf` and `mimxrt`. The mount point and filesystem type are detected at runtime using
  the same `vfs.mount()` enumeration as `mpremote df`.
- **`mpflash format` command** — reformats the filesystem of connected boards without
  flashing new firmware. Asks for confirmation before erasing (skip with `--yes`) and
  supports the same ports as `flash --format`.
- **`mpflash erase` command** — erases the filesystem of connected boards via the
  MicroPython block device and reboots them, without flashing new firmware. Reuses the
  `flash --erase` implementation. Asks for confirmation before erasing (skip with
  `--yes`). Supported on `rp2`, `samd` and `nrf`.

## [1.28.3] - 2026-07-26

This release is a major internal refactor of how mpflash flashes boards and enters
bootloaders, turning both into pluggable, port-agnostic backends — plus two big new
capabilities: local firmware builds via [**mpbuild**](https://github.com/mattytrentini/mpbuild#mpbuild) and SWD/JTAG flashing via [**pyOCD**](https://pyocd.io/).

### Highlights

- **Pluggable flash backends and bootloader activation** shared across MicroPython ports (UF2, DFU, esptool, pyOCD).
- **mpbuild integration** — build firmware locally right before flashing. *(Andrew Leech & Jos Verlinde)*
- **pyOCD integration** — flash STM32 / RP2040 / SAMD over a debug probe. *(Andrew Leech & Jos Verlinde)*
- **`--erase` now uses the MicroPython block device** instead of vendored flash-nuke images.

### Flash backend architecture

The monolithic flash logic (`mpflash/flash/stm32.py`, `esp.py`, `uf2/`) has been
reorganized into a registry of self-describing backends under `mpflash/flash/builtins/`
(`uf2_backend`, `dfu_backend`, `esptool_backend`, `pyocd_backend`), each declaring the
ports and firmware formats it supports and a priority. New `flash/registry.py`,
`flash/base.py`, `flash/context.py` and `flash/services.py` provide the shared plumbing,
and `flash_mcu(..., method=FlashMethod.<X>)` selects a backend automatically.

- New **`mpflash plugins`** command lists every registered backend and its support matrix (`--format table|plain`).
- `FlashMethod` enum added to `common.py`; `--method / --flash-method` gains `auto` (default) and `pyocd`.
- Third-party backends can register via entry points.

### Bootloader activation plugins

Bootloader entry has been refactored into a plugin structure (`bootloader/registry.py`,
`bootloader/base.py`, `bootloader/builtins/` with `manual`, `touch1200` and a new `mpy`
MicroPython-reset activator). Detection (`bootloader/detect.py`) was reworked, and a bug
was fixed where, if the serial port disappeared after an activator (board already reset
into its UF2 bootloader), mpflash would incorrectly fall through to a touch-1200 on a
now-missing port — it now re-checks bootloader state and waits for the UF2 volume to
mount before reporting success.

### mpbuild integration (build firmware locally) — *Andrew Leech & Jos Verlinde*

New `mpflash/build.py` with a `BuildManager` that builds MicroPython firmware on demand:

- New flash flags: **`--build`** (build with mpbuild before flashing) and **`--clean`** (run `mpbuild clean` first).
- Build caching, dependency validation (checks for mpbuild + Docker), and per-port
  preferred output formats (e.g. `.bin` for esptool, `.uf2` for UF2, `.dfu/.bin` for DFU,
  `.bin/.hex/.elf/.axf` for pyOCD).
- Built artifacts are imported into the mpflash firmware database and a ready-to-run
  `mpflash flash …` command is printed so you can re-flash without rebuilding.

### pyOCD integration (SWD/JTAG flashing) — *Andrew Leech & Jos Verlinde*

Flash STM32, RP2040 and SAMD boards through a CMSIS-DAP / ST-Link / J-Link probe
(`flash/builtins/pyocd/`):

- New flash options: **`--method pyocd`**, **`--probe / --probe-id`**, **`--target`**
  (explicit pyOCD target override) and **`--auto-install-packs / --no-auto-install-packs`** (default on).
- Probe discovery, MCU-info parsing with fuzzy target matching, dynamic target detection,
  and automatic CMSIS pack installation for missing targets.
- New commands: **`mpflash list-probes`**, **`mpflash pyocd-info`**, **`mpflash pyocd-targets`**
  (with `--board-filter` / `--target-filter`).
- ESP32/ESP8266 are intentionally excluded (use esptool).
- Extensive unit tests with mocked hardware so the suite runs without a probe or pyOCD installed.

### Filesystem erase via serial block device

`--erase` no longer relies on  `universal_flash_nuke.uf2` for rp2xxx boards, or a post-flash
`rm -r :` on others. Instead `mpremoteboard/erase_bdev.py` erases the filesystem block
device using `mpremoteboard/erase_bdev.py` and calls `machine.reset()`, leaving the board with a
fresh filesystem. Bootloader entry is now a separate, explicit step, and `flash_uf2` only
copies firmware. 
The previously vendored pico-universal-flash-nuke image by @Gadgetoid is no longer needed.

### UF2 reliability fixes

- **Windows drive detection** uses `psutil.disk_partitions(all=True)` and polls twice per
  second so a freshly-mounted removable volume isn't filtered out or missed.
- **`wait_for_restart()` now returns a bool** via a bounded quiet probe, so callers can
  detect when a board never reconnects.
- **No more false "copy failed" retries**: mpflash stopped copying file metadata to UF2
  destinations — the bootloader could consume the firmware and disconnect before the
  metadata step, causing a false failure and three useless retries.

### Board & port detection

- Added `best_matching_port` and a `sys_platform` attribute to `MPRemoteBoard`, improving
  reconnection to the correct serial port after a reset.
- Additional known-board mappings.

### Configuration & environment

- Loads environment variables from a **`.env`** file and expands `~` in user-supplied paths.

### Linux / udev rules

- Bundled udev rules for ST-Link v2 / v2-1 / v3, WCH-Link, CMSIS-DAP, picoprobe and STM32
  DFU (`mpflash/udev_rules/`, with a README), and expanded `docs/stm32_udev_rules.md` to
  cover the debug probes needed by pyOCD.

### Security & quality

- Removed use of `eval()` in favor of safe parsing, plus reformatting/cleanups.

### Tooling, CI & docs

- **Automated release process**: pushing a `v*` tag triggers build + PyPI trusted
  publishing + GitHub release; new `just release` recipe runs tests, bumps the version,
  tags and pushes. Documented in `docs/developer.md` and `docs/contributing.md`.
- CI installs all extras and uploads coverage + JUnit test results to Codecov; new **HIL
  testing** support (`--HIL <port>` pytest option and `just hil_*` targets) with a hardware
  filesystem-erase test.
- Dependency bumps: `actions/checkout` 4→7, `actions/setup-python` 6→7,
  `actions/upload-artifact` 4→7, `actions/download-artifact` 4→8, `astral-sh/setup-uv` 6→7.

### Dependencies

- Added `python-dotenv>=1.0.0`.
- New optional **`pyocd`** extra: `pyocd>=0.44.1`, `mpbuild>=1.0.0` (Python ≥ 3.12) /
  `mpbuild>=0.5.0,<1.0.0` (Python < 3.12). Install with `uv sync --extra pyocd` or
  `pip install "mpflash[pyocd]"`.

### Upgrade notes / breaking changes

- **Internal flash modules moved** under `mpflash/flash/builtins/…` (e.g. `flash/stm32.py`
  → `flash/builtins/dfu/`, `flash/esp.py` → `flash/builtins/esp/`, `flash/uf2/` →
  `flash/builtins/uf2/`). Use the public `mpflash.flash.flash_mcu(method=…)` entry point
  rather than importing these paths directly.
- **`--erase` is now a serial block-device erase** (board must be reachable on
  MicroPython), not a flash-nuke image; the vendored `universal_flash_nuke.uf2` was removed.

## [1.26.0] - Breaking API changes

**Important for library users**: the worklist module API was completely refactored, with
breaking changes. Legacy worklist functions were **removed**.

### Removed

- `auto_update_worklist()`, `manual_worklist()`, `manual_board()`,
  `single_auto_worklist()`, `full_auto_worklist()`, `filter_boards()`.

### Changed

- New modern interface with `create_worklist()`, the `FlashTask` dataclass and
  `WorklistConfig` objects. See `docs/api-reference.md` for the migration guide.
- The command-line interface remains fully compatible.

## [1.25.0.post2]

### Added

- `--variant` option to select a specific board variant when flashing.
- SQLite database storing information on all possible MicroPython firmwares and the
  management of downloaded firmware files, for better board identification and firmware matching.
- Use the MicroPython v1.25.0 `sys.implementation._build` as `board_id` when available.
- Automatic firmware download when not yet available locally (no longer need the `--download` option).

### Changed

- Restructured `mpboard_id` to use a SQLite database to identify more boards and variants.
- Vendored and adapted `board_database.py` from mpflash — kudos @mattytrentini.

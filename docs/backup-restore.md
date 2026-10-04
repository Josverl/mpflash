# Backing up and restoring a board

`mpflash backup` reads data from connected MicroPython boards into a folder (a *bundle*), and
`mpflash restore` writes a bundle back to **one** board. Both commands use only what is already on the
board and in the mpflash environment: there are no extra tools or drivers to install.

```text
mpflash backup                          # every connected board, everything it supports
mpflash backup --serial COM10 -c flash  # only the raw flash of one board
mpflash restore mpflash-backups\ESP32_GENERIC-esp32-20260101T120000Z --serial COM10 --dry-run
mpflash restore mpflash-backups\ESP32_GENERIC-esp32-20260101T120000Z --serial COM10 --yes
```

> **Warning – treat bundles as secrets.** A backup can contain Wi-Fi passwords, API keys, certificates and
> deleted data that is still in flash. Store bundles privately and do not share or publish them.

## What can be backed up

Each board offers the *components* that a provider can both read and write back. `mpflash backup` shows what was
saved; by default everything is included, or choose with `--component flash|vfs|romfs`.

| Board | Component | Provider | Exactness | Notes |
|-------|-----------|----------|-----------|-------|
| any MicroPython board | `vfs` | files over the raw REPL | logical | every file on the writable filesystems, as a zip plus an inventory; restore makes the board match it |
| ESP32 / ESP8266 (UART) | `flash` | esptool | exact | the whole SPI flash, including firmware, bootloader and the filesystem |
| ESP32-C3 (and other chips with built-in USB-Serial/JTAG) | `flash` | esptool | exact | verified on an ESP32-C3 |
| RP2040 | `flash` | raw REPL + UF2 bootloader | exact | the whole QSPI flash; no picotool or driver needed |
| boards with `vfs.rom_ioctl` (MicroPython 1.25+) and a ROMFS | `romfs` | `vfs.rom_ioctl` | exact | the ROMFS image mounted at `/rom`; verified on SAMD and nRF52840 |

A raw `flash` image already contains the filesystem and ROMFS, so those are not also restored when it is.
Restore order is `flash`, `romfs`, then `vfs`.

### Exactness

* **exact** – a byte-for-byte read of the stated address range. Restoring it reproduces those bytes.
* **partial** – read from the device but known to be incomplete (a warning is shown on restore).
* **logical** – only file contents, not the raw storage. Restoring recreates the files, not the on-flash layout.
* **reference** – not read from the device.

Every artifact is stored with its SHA-256 in `manifest.json`, and a backup is checked against the board (a
hash computed on the device, or a second read) before it is reported as created.

### What is *not* included

* ESP: eFuses/OTP (MAC address, keys, security configuration), RAM, RTC memory and PSRAM.
* RP2040: RAM and the boot ROM. Erased 4 KiB blocks are not transferred and are stored as erased.
* SD cards and other removable storage, which are never read or modified.
* ESP32 chips with flash encryption, secure boot or secure download mode are **refused**; their flash cannot be
  read or rewritten faithfully.

## The bundle

```text
ESP32_GENERIC-esp32-20260101T120000Z/
  README.md        what it contains, how it was made, how to restore it
  manifest.json    schema version, board identity, every artifact with role, exactness, range and SHA-256
  artifacts/       flash.bin, vfs.zip, vfs-inventory.json, romfs.img, ...
```

A bundle is created in a temporary folder and renamed only when complete, so a failed backup never leaves a
folder that looks usable. `mpflash restore` verifies every hash before touching the board.

## Restoring

* `--serial` must name exactly one board; wildcards are not accepted.
* `--dry-run` validates the bundle and the board and lists every erase and write without changing anything.
* Restore is destructive and asks for confirmation; use `--yes` when running non-interactively.
* A restore of a bundle made from a different physical board (different serial number) shows a warning.
* Raw flash restores check that the target is the same chip with the same flash size, then verify the result
  (MD5 on ESP, SHA-256 on RP2040 and ROMFS). `esptool`'s `force` option is never used.
* Boards reset when a restore finishes.

### Examples

```text
# Back up one board, then see what a restore would do
mpflash backup --serial COM10 --output D:\backups
mpflash restore D:\backups\ESP32_GENERIC-esp32-20260101T120000Z --serial COM10 --dry-run

# Only the files, not the firmware
mpflash restore D:\backups\ESP32_GENERIC-esp32-20260101T120000Z --serial COM10 --component vfs --yes
```

## Speed

Measured on real boards (MicroPython 1.29.0, Windows):

| Board | Operation | Time |
|-------|-----------|------|
| SAMD Wio Terminal | files | about 15 s |
| nRF52840 | files | about 20 s |
| ESP32 (4 MiB) | raw flash backup | about 1 minute |
| ESP32-C3 (4 MiB) | raw flash backup | about 30 s |
| ESP8266 | raw flash round trip (three backups and one restore) | about 6.5 minutes |
| Pico (16 MiB, 7 MiB of data) | raw flash backup | about 1.5 minutes |

Raw flash restores take about as long again, because the image is written and verified.

## Limits and what to do when something fails

* **Native USB ESP32-S2/S3 boards** that present a TinyUSB serial port (USB ID `303A:4001`) are not supported
  for raw flash yet: esptool cannot reach the bootloader without a re-enumeration step. Their files can still be
  backed up with `vfs`. ESP32-C3 and other chips using the built-in USB-Serial/JTAG (`303A:1001`) work.
* **RP2040 only.** RP2350 needs a different UF2 family and partition handling. Raw backup does not offer it.
* **STM32 (DFU), SAMD (bootloader), nRF, MIMXRT and debug-probe raw reads** are not available yet. Use `vfs`.
* A board must be responsive MicroPython for `vfs`, `romfs` and RP2040 backups.
* If a restore fails part way, run it again: the same bundle can be restored repeatedly. If an ESP board does
  not start afterwards, the raw flash restore can be repeated; the ROM bootloader is in the chip and cannot be overwritten.
* A script that runs at boot and writes to the filesystem can make the final verification fail (RP2040); run the
  restore again.
* esptool 5.4.0 currently fails the UART ESP32 round trip in our hardware tests, so the minimum is still 5.0.
  This is tracked in the project issues.

## Using it from Python

The `mpflash.backup` package provides `plan_backup`, `run_backup`, `plan_restore` and `run_restore`, and a
provider registry so other packages can register their own providers through the `mpflash.backup_plugins`
entry-point group.

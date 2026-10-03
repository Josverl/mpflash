# nRF SoftDevice and bootloader migration

MPFlash can replace the SoftDevice and bootloader on a small allowlist of
nice!nano-compatible ProMicro/SuperMini nRF52840 boards. It performs the
replacement over the bootloader's Serial/CDC DFU interface and then installs a
MicroPython UF2 linked for the selected SoftDevice.

This is different from normal UF2 flashing. A normal application UF2 cannot
replace the SoftDevice.

## Warning

Migration erases the existing MicroPython application and filesystem. Back up
all files first.

Do not disconnect the board while the SoftDevice+bootloader package is being
transferred. An interrupted transfer can require an SWD probe and pyOCD or
J-Link to recover the board.

## Supported profiles

| Profile | Bootloader after migration | Board-ID | Bootloader USB |
|---|---|---|---|
| `s140-6.1.1` | nice!nano 0.11.0 | `nRF52840-nicenano` | `239A:00B3` |
| `s140-7.3.0` | SuperMini 1.0.0 | `nRF52840-SuperMini-v0` | `1209:5284` |

- The S140 6.1.1 profile uses Adafruit's
  [nice!nano 0.11.0 release package](https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases/download/0.11.0/nice_nano_bootloader-0.11.0_s140_6.1.1.zip).
- The S140 7.3.0 profile uses the
  [pdcook SuperMini package at the pinned source commit](https://github.com/pdcook/nRFMicro-Arduino-Core/blob/2026077de21b520723ec4033f5fdc748b6dd3be8/bootloader/SuperMini_nRF52840/SuperMini_nRF52840_bootloader-1.0.0_s140_7.3.0.zip).
  It changes the board's bootloader identity, USB VID/PID, and UF2 volume label.

MPFlash accepts only the source bootloader versions listed in its packaged
profile manifest. Unknown or custom bootloaders are rejected before transfer.

## 1. Install Serial DFU support

```powershell
pip install "mpflash[nrf]"
```

For a source checkout:

```powershell
uv sync --extra test --extra nrf
```

## 2. Obtain a matching MicroPython application

The application UF2 must be linked for the target SoftDevice:

- S140 6.1.1 applications start at `0x26000`.
- S140 7.3.0 applications start at `0x27000`.

MPFlash validates the UF2 family, first address, complete block set, and address
range. It refuses an S140 6.1.1 application when targeting S140 7.3.0 and vice
versa.

## 3. Register the application UF2

```powershell
mpflash add `
  --path .\firmware.uf2 `
  --board PROMICRO_NRF52840 `
  --port nrf `
  --version 1.29.0 `
  --description "MicroPython v1.29.0 for S140 7.3.0"
```

Use the same board, port, and version values in the subsequent `flash` command.

## 4. Check the current device

```powershell
mpflash list
```

For a running supported nRF board, MPFlash briefly enters UF2 mode, reads the
Board-ID and SoftDevice, and returns to the application.

## 5a. Migrate a running board

```powershell
mpflash flash `
  --serial COM77 `
  --board PROMICRO_NRF52840 `
  --port nrf `
  --version 1.29.0 `
  --custom `
  --softdevice s140-7.3.0
```

SoftDevice migration always requires exactly one explicit serial port. Wildcard
and multi-board migration commands are rejected even when `--yes` is supplied.

MPFlash shows a destructive confirmation prompt after every preflight check and
before the Serial DFU transfer. Use `--yes` only for an unattended operation
where the selected device identity has already been verified.

## 5b. Migrate a board already in UF2 mode

Specify both interfaces belonging to the same physical board:

```powershell
mpflash flash `
  --volume D:\ `
  --serial COM78 `
  --board PROMICRO_NRF52840 `
  --port nrf `
  --version 1.29.0 `
  --custom `
  --softdevice s140-7.3.0
```

`--volume` selects the UF2 mass-storage interface. `--serial` selects its
Serial/CDC DFU interface. MPFlash proceeds only when exactly one allowlisted
bootloader CDC interface and one allowlisted nRF UF2 volume are present. If
multiple boards are already in bootloader mode, disconnect the others before
retrying so another board cannot receive the destructive package.

On Linux or macOS, use the corresponding mount and serial paths, for example:

```bash
mpflash flash \
  --volume /media/user/NICENANO \
  --serial /dev/ttyACM0 \
  --board PROMICRO_NRF52840 \
  --port nrf \
  --version 1.29.0 \
  --custom \
  --softdevice s140-7.3.0
```

## What MPFlash validates

Before transfer, MPFlash validates:

- application UF2 family, block sequence, and target address range;
- current Board-ID, SoftDevice, bootloader version, and USB VID/PID;
- selected source bootloader version against the packaged allowlist;
- packaged DFU ZIP size and SHA-256;
- Nordic DFU manifest, device type, revision, SoftDevice requirement, and
  SoftDevice/bootloader sizes.

After transfer, it validates the new Board-ID, bootloader version, SoftDevice,
USB VID/PID, and UF2 volume before copying the application. It then matches the
new runtime CDC port and reconnects to MicroPython.

All DFU packages and license notices are included with MPFlash. Migration does
not download bootloader or SoftDevice blobs at runtime.

## Reinstalling the application without replacing the SoftDevice

If the exact target bootloader and SoftDevice are already installed, MPFlash
skips Serial DFU and copies only the validated application UF2.

## Force-repairing a reported matching SoftDevice

`INFO_UF2.TXT` reports the SoftDevice version expected by the bootloader, but
it does not prove that every SoftDevice flash page is intact. An incompatible
UF2 can overwrite SoftDevice data while leaving the bootloader and its reported
version unchanged.

If the UF2 bootloader still mounts but a validated matching application does
not boot, force reinstall the allowlisted package before restoring the
application:

```powershell
mpflash flash `
  --volume D:\ `
  --serial COM79 `
  --board PROMICRO_NRF52840 `
  --port nrf `
  --version 1.29.0 `
  --custom `
  --softdevice s140-7.3.0 `
  --repair-softdevice
```

Replace the volume, CDC port, profile, and registered firmware version with the
values for the affected board. `--repair-softdevice` requires `--softdevice`
and retains the same single-device pairing, allowlist, package-hash,
application-layout, and confirmation checks as migration. Add `--yes` only
after independently verifying the selected bootloader volume and CDC port.

Do not manually copy an unvalidated UF2 as a recovery attempt. In particular,
an S140 6.1.1 application writes from `0x26000` and can corrupt an S140 7.3.0
installation, whose application must start at `0x27000`.

## Recovery

The failure message reports the stage reached and the board's expected current
state.

- If the target UF2 bootloader appears, retry with a matching application UF2.
- If the application was copied but the serial port changed, run
  `mpflash list` and use the new port.
- If neither UF2 nor Serial/CDC appears, recover through SWD with pyOCD or
  J-Link using a complete image appropriate for the physical board.

Do not try to repair the SoftDevice with an ordinary application UF2. The
Adafruit-derived UF2 updater intentionally does not write the SoftDevice area.

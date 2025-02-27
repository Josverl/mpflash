# MPFLASH
  [![pypi version](https://badgen.net/pypi/v/mpflash)](https://pypi.org/project/mpflash/)
  [![python versions](https://badgen.net/pypi/python/mpflash)](https://badgen.net/pypi/python/mpflash)
[![Downloads](https://static.pepy.tech/badge/mpflash)](https://pepy.tech/project/mpflash)


`mpflash` is a command-line tool for working with MicroPython firmware. It provides features to help you flash and update Micropython on one or more attached microcontrollers.

This tool was initially created to be used in a CI/CD pipeline to automate the process of downloading and flashing MicroPython firmware to multiple boards, but it has been extend with a TUI to be used for manual downloadig, flashing and development.

`mpflash` has been tested on:  
 - OS: Windows x64, Linux X64, and macOS.
 - Micropython (hardware) ports: 
    - `rp2`, using `.uf2`, using filecopy 
    - `samd`, using ` .uf2`, using filecopy 
    - `esp32`, using `.bin`, using esptool,
    - `esp8266`, using `.bin`, using esptool
    - `stm32`, using ` .dfu`, using pydfu

Not yet implemented: `nrf`, `cc3200`, `mimxrt`, `renesas`
 
## Features
 1. List the connected boards including their firmware details, in a tabular or json format
 2. Download MicroPython firmware for versions, and matching a specified board or matches your current attached board.
 3. Flash one or all connected MicroPython boards with a specific firmware or version.  
 
## Installation
To install mpflash, you can use either of the following commands: 
- `uv tool install mpflash`
- `pipx install mpflash`
- `pip install mpflash`

## Basic usage
You can use mpflash to perform various operations on your MicroPython boards. Here is an example of basic usage:

| Command | Description |
|---------|-------------|
| `mpflash list` | List the connected board(s) including their firmware details |
| `mpflash download` | Download the MicroPython firmware(s) for the connected board(s) |
| `mpflash flash` | Flash the latest stable firmware to the connected board(s) |

## selecting or ignoring specific serial ports

You can use the `--serial` option to select a specific serial port to flash, or the `--ignore` option to ignore a specific serial port.
both options can be specified multiple times 
Both can be globs (e.g. COM*) or exact port names (e.g. COM1)
in addition there is a --bluetooth option to simplify ignoring bluetooth ports

```
--serial,--serial-port      -s      SERIALPORT  Serial port(s) (or globs) to list. [default: *]                                                                                                                                                                           > > --ignore                    -i      SERIALPORT  Serial port(s) (or globs) to ignore. Defaults to MPFLASH_IGNORE.                                                                                                                                                          │
--bluetooth/--no-bluetooth  -b/-nb              Include bluetooth ports in the list [default: no-bluetooth] 
```

## Distinguishing similar boards 
The `mpflash list` command will list all connected boards, but sometimes you have multiple boards of the same type connected.
To help you identify the boards, you can add a board_info.toml file to the top/default folder for the board.
This file can contain a description of the board, which will be shown in the list and json output.
```toml
description = "Blue Norwegian actuator"
```

If you want the board to be ignored by mpflash, you can add the following to the board_info.toml file:
```toml
[mpflash]
ignore = true
```


## Linux permissions to access usb devices 
In order to flash the firmware to the board, you need to have the correct permissions to access the USB devices.
On Windows this will not be an issue, but on Linux you can use  udev rules to give non-root users access to the USB devices.
[See the stm32_permissions documentation](docs/stm32_udev_rules.md) for more information.


## Detailed usage
You can list the connected boards using the following command:
```bash
$> mpflash list
                                               Connected boards
┏━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━┓
┃ Serial  ┃Family       ┃Port  ┃Board                                      ┃CPU     ┃Version          ┃build ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━┩
│ COM21   │micropython  │rp2   │RPI_PICO                                   │RP2040  │v1.23.0-preview  │  236 │
│         │             │      │Raspberry Pi Pico with RP2040              │        │                 │      │
│ COM23   │micropython  │rp2   │RPI_PICO_W                                 │RP2040  │v1.23.0-preview  │  176 │
│         │             │      │Raspberry Pi Pico W with RP2040            │        │                 │      │
│ COM9    │micropython  │rp2   │ARDUINO_NANO_RP2040_CONNECT                │RP2040  │v1.23.0-preview  │  341 │
│         │             │      │Arduino Nano RP2040 Connect with RP2040    │        │                 │      │
└─────────┴─────────────┴──────┴───────────────────────────────────────────┴────────┴─────────────────┴──────┘
```
## Download the firmware

To download the MicroPython firmware for some boards, use the following command: 
 - `mpflash download` download the latest stable firmware for all connected boards
 - `mpflash download --version preview` download the current preview for all connected boards
 - `mpflash download --board ESP8266_GENERIC --board SEEED_WIO_TERMINAL` download these specific boards
 - `mpflash download --version ? --board ?` prompt to select a specific version and board to download

These will try to download the prebuilt MicroPython firmware for the boards from https://micropython.org/download/ and save it in your downloads folder in the  `firmware` directory.
The stable version (default) is determined based on the most recent published release,
other options are `--version stable`, `--version preview` and `--version x.y.z` to download the latest stable, preview or version x.y.z respectively.

By default the firmware will be downloaded to your OS's preferred `Downloads/firmware` folder, but you can speciy a different directory using the `--dir` option.

The directory structure will be something like this:

``` text
Downloads/firmware
|   firmware.jsonl
+---esp8266
|       ESP8266_GENERIC-FLASH_1M-v1.22.2.bin
|       ESP8266_GENERIC-FLASH_512K-v1.22.2.bin
|       ESP8266_GENERIC-OTA-v1.22.2.bin
|       ESP8266_GENERIC-v1.22.2.bin
\---samd
        SEEED_WIO_TERMINAL-v1.22.2.uf2
```

## Flashing the firmware
After you have downloaded a firmware you can  flash the firmware to a board using the following command: `mpflash flash`
This will (try to) autodetect the connected boards, and determine the correct firmware to flash to each board.

- `mpflash flash` will flash the latest stable firmware to all connected boards.
If you have a board withouth a running micropython version, you will need to specify the board and the serial port to flash.
- `mpflash flash --serial ? --board ?` will prompt to select a specific serial port and board to flash. (the firmware must be dowloaded earlier)

In order to flash the firmware some boards need to be put in bootloader mode, this is done automatically by mpflash where possible and supported by the boards hardware and current bootloader.
The supported `--bootloader` options are:

- `touch1200` bootloader is activated by connecting to the board at 1200 baud 
- `mpy`  using  micropython to enter the bootloader
- `manual` manual intervention is needed to enter the bootloader 
- `none`   mpflash assumes the board is ready to flash

For ESP32 and ESP8266 boards the `esptool` is used to flash the firmware, and this includes activating the bootloader.

### Flashing all connected boards with the latest stable firmware
```bash
> mpflash flash
22:15:55 | ℹ️  - Using latest stable version: v1.22.2
                                       Connected boards
┏━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Serial ┃ Family      ┃ Port    ┃ Board              ┃ CPU         ┃ Version        ┃ build ┃
┡━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ COM11  │ micropython │ rp2     │ RPI_PICO_W         │ RP2040      │ 1.20.0         │       │
│ COM12  │ micropython │ esp8266 │ ESP8266_GENERIC    │ ESP8266     │ 1.22.2         │       │
│ COM18  │ micropython │ rp2     │ RPI_PICO_W         │ RP2040      │ 1.23.0-preview │ 155   │
│ COM3   │ micropython │ samd    │ SEEED_WIO_TERMINAL │ SAMD51P19A  │ 1.23.0-preview │ 155   │
│ COM5   │ micropython │ stm32   │ PYBV11             │ STM32F405RG │ 1.23.0-preview │ 166   │
│ COM8   │ micropython │ esp32   │ ESP32_GENERIC_S3   │ ESP32S3     │ 1.23.0-preview │ 155   │
└────────┴─────────────┴─────────┴────────────────────┴─────────────┴────────────────┴───────┘
22:15:58 | ℹ️  - Found v1.22.2 firmware rp2\RPI_PICO_W-v1.22.2.uf2 for RPI_PICO_W on COM11.
22:15:58 | ℹ️  - Found v1.22.2 firmware esp8266\ESP8266_GENERIC-v1.22.2.bin for ESP8266_GENERIC on COM12.
22:15:58 | ℹ️  - Found v1.22.2 firmware rp2\RPI_PICO_W-v1.22.2.uf2 for RPI_PICO_W on COM18.
22:15:58 | ℹ️  - Found v1.22.2 firmware samd\SEEED_WIO_TERMINAL-v1.22.2.uf2 for SEEED_WIO_TERMINAL on COM3.
22:15:58 | ⚠️  - Trying to find a firmware for the board PYBV11
22:15:58 | ❌  - No v1.22.2 firmware found for PYBV11 on COM5.
22:15:58 | ⚠️  - Trying to find a firmware for the board ESP32-GENERIC-S3
22:15:58 | ❌  - No v1.22.2 firmware found for ESP32_GENERIC_S3 on COM8.
22:15:58 | ℹ️  - Updating RPI_PICO_W on COM11 to 1.22.2
22:15:58 | ℹ️  - Erasing not yet implemented for UF2 flashing.
22:15:58 | ℹ️  - Entering UF2 bootloader on RPI_PICO_W on COM11
22:15:58 | ℹ️  - Waiting for mcu to mount as a drive : 10 seconds left
22:15:59 | ℹ️  - Waiting for mcu to mount as a drive : 9 seconds left
22:16:00 | ℹ️  - Board is in bootloader mode
22:16:00 | ℹ️  - Copying firmware\rp2\RPI_PICO_W-v1.22.2.uf2 to F:
22:16:13 | ✅  - Done copying, resetting the board and wait for it to restart
22:16:23 | ℹ️  - Updating ESP8266_GENERIC on COM12 to 1.22.2
22:16:23 | ℹ️  - Flashing firmware\esp8266\ESP8266_GENERIC-v1.22.2.bin on ESP8266_GENERIC on COM12
22:16:23 | ℹ️  - Running esptool --chip ESP8266 --port COM12 erase_flash 
esptool.py v4.7.0
Serial port COM12
Connecting....
...
Chip erase completed successfully in 6.5s
Hard resetting via RTS pin...
22:16:31 | ℹ️  - Running esptool --chip ESP8266 --port COM12 -b 460800 write_flash --flash_size=detect 0x0 firmware\esp8266\ESP8266_GENERIC-v1.22.2.bin 
esptool.py v4.7.0
Serial port COM12
Connecting....
...
Leaving...
Hard resetting via RTS pin...
22:16:43 | ℹ️  - Done flashing, resetting the board and wait for it to restart
22:16:49 | ✅  - Flashed 1.22.2 to ESP8266_GENERIC on COM12 done
22:16:49 | ℹ️  - Updating RPI_PICO_W on COM18 to 1.22.2
22:16:49 | ℹ️  - Erasing not yet implemented for UF2 flashing.
22:16:49 | ℹ️  - Entering UF2 bootloader on RPI_PICO_W on COM18
22:16:49 | ℹ️  - Waiting for mcu to mount as a drive : 10 seconds left
22:16:50 | ℹ️  - Waiting for mcu to mount as a drive : 9 seconds left
22:16:51 | ℹ️  - Board is in bootloader mode
22:16:51 | ℹ️  - Copying firmware\rp2\RPI_PICO_W-v1.22.2.uf2 to F:[/bold]
22:17:02 | ✅  - Done copying, resetting the board and wait for it to restart
22:17:12 | ℹ️  - Updating SEEED_WIO_TERMINAL on COM3 to 1.22.2
22:17:12 | ℹ️  - Erasing not yet implemented for UF2 flashing.
22:17:12 | ℹ️  - Entering UF2 bootloader on SEEED_WIO_TERMINAL on COM3
22:17:12 | ℹ️  - Waiting for mcu to mount as a drive : 10 seconds left
22:17:13 | ℹ️  - Waiting for mcu to mount as a drive : 9 seconds left
22:17:14 | ℹ️  - Board is in bootloader mode
22:17:14 | ℹ️  - Copying firmware\samd\SEEED_WIO_TERMINAL-v1.22.2.uf2 to F:[/bold]
22:17:17 | ✅  - Done copying, resetting the board and wait for it to restart
22:17:27 | ℹ️  - Flashed 4 boards
                               Connected boards after flashing
┏━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Serial ┃ Family      ┃ Port    ┃ Board              ┃ CPU         ┃ Version        ┃ build ┃
┡━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ COM11  │ micropython │ rp2     │ RPI_PICO_W         │ RP2040      │ 1.22.2         │       │
│ COM12  │ micropython │ esp8266 │ ESP8266_GENERIC    │ ESP8266     │ 1.22.2         │       │
│ COM18  │ micropython │ rp2     │ RPI_PICO_W         │ RP2040      │ 1.22.2         │       │
│ COM3   │ micropython │ samd    │ SEEED_WIO_TERMINAL │ SAMD51P19A  │ 1.22.2         │       │
│ COM5   │ micropython │ stm32   │ PYBV11             │ STM32F405RG │ 1.23.0-preview │ 166   │
│ COM8   │ micropython │ esp32   │ ESP32_GENERIC_S3   │ ESP32S3     │ 1.23.0-preview │ 155   │
└────────┴─────────────┴─────────┴────────────────────┴─────────────┴────────────────┴───────┘
```
Note that if no matching firmware can be found for a board, it will be skipped.
(For example, the PYBV11 and ESP32_GENERIC_S3 boards in the example above.)

## Issues and bug reports
Please report any issues or bugs in the [issue tracker](https://github.com/Josverl/mpflash/issues).

## License
mpflash is licensed under the MIT license. See the LICENSE file for more details.

# Contributions
<!-- spell-checker: disable -->
<!-- 
To add via the cli run the following command:
npx all-contributors-cli add user things

 - bug
 - tool
 - stubs
 - test
 - doc
 - code
 - research
 - ideas
 - content
 - mpflash
 -->

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Josverl"><img src="https://avatars2.githubusercontent.com/u/981654?v=4?s=100" width="100px;" alt="Jos Verlinde"/><br /><sub><b>Jos Verlinde</b></sub></a><br /><a href="https://github.com/Josverl/mpflash/commits?author=josverl" title="Code">💻</a> <a href="#research-josverl" title="Research">🔬</a> <a href="#ideas-josverl" title="Ideas, Planning, & Feedback">🤔</a> <a href="#content-josverl" title="Content">🖋</a> <a href="#test-josverl" title="Test">✅</a> <a href="#mpflash-josverl" title="mpflash">💥</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/shariltumin"><img src="https://avatars.githubusercontent.com/u/186120?v=4?s=100" width="100px;" alt="shariltumin"/><br /><sub><b>shariltumin</b></sub></a><br /><a href="#mpflash-shariltumin" title="mpflash">💥</a> <a href="#test-shariltumin" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/mattytrentini"><img src="https://avatars.githubusercontent.com/u/194201?v=4?s=100" width="100px;" alt="Matt Trentini"/><br /><sub><b>Matt Trentini</b></sub></a><br /><a href="#mpflash-mattytrentini" title="mpflash">💥</a> <a href="#test-mattytrentini" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="http://scruss.com/blog/"><img src="https://avatars.githubusercontent.com/u/425706?v=4?s=100" width="100px;" alt="Stewart Russell"/><br /><sub><b>Stewart Russell</b></sub></a><br /><a href="#mpflash-scruss" title="mpflash">💥</a> <a href="#test-scruss" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://www.gitlab.com/alelec"><img src="https://avatars.githubusercontent.com/u/3318786?v=4?s=100" width="100px;" alt="Andrew Leech"/><br /><sub><b>Andrew Leech</b></sub></a><br /><a href="#mpflash-andrewleech" title="mpflash">💥</a> <a href="#test-andrewleech" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/wovo"><img src="https://avatars.githubusercontent.com/u/9039468?v=4?s=100" width="100px;" alt="Wouter van Ooijen"/><br /><sub><b>Wouter van Ooijen</b></sub></a><br /><a href="#mpflash-wovo" title="mpflash">💥</a> <a href="#test-wovo" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/shaneapowell"><img src="https://avatars.githubusercontent.com/u/12113620?v=4?s=100" width="100px;" alt="Shane Powell"/><br /><sub><b>Shane Powell</b></sub></a><br /><a href="#mpflash-shaneapowell" title="mpflash">💥</a> <a href="#test-shaneapowell" title="Test">✅</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/robert-hh"><img src="https://avatars.githubusercontent.com/u/12476868?v=4?s=100" width="100px;" alt="Robert Hammelrath"/><br /><sub><b>Robert Hammelrath</b></sub></a><br /><a href="#mpflash-robert-hh" title="mpflash">💥</a> <a href="#test-robert-hh" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/beetlegigg"><img src="https://avatars.githubusercontent.com/u/34552737?v=4?s=100" width="100px;" alt="Bg"/><br /><sub><b>Bg</b></sub></a><br /><a href="#mpflash-beetlegigg" title="mpflash">💥</a> <a href="#test-beetlegigg" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/rkompass"><img src="https://avatars.githubusercontent.com/u/90282516?v=4?s=100" width="100px;" alt="Raul Kompaß"/><br /><sub><b>Raul Kompaß</b></sub></a><br /><a href="#mpflash-rkompass" title="mpflash">💥</a> <a href="#test-rkompass" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/garryp4"><img src="https://avatars.githubusercontent.com/u/96994876?v=4?s=100" width="100px;" alt="garryp4"/><br /><sub><b>garryp4</b></sub></a><br /><a href="#mpflash-garryp4" title="mpflash">💥</a> <a href="#test-garryp4" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/shanepowell-ast"><img src="https://avatars.githubusercontent.com/u/102747617?v=4?s=100" width="100px;" alt="Shane Powell"/><br /><sub><b>Shane Powell</b></sub></a><br /><a href="#mpflash-shanepowell-ast" title="mpflash">💥</a> <a href="#test-shanepowell-ast" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://andypiper.org/"><img src="https://avatars.githubusercontent.com/u/552452?v=4?s=100" width="100px;" alt="Andy Piper"/><br /><sub><b>Andy Piper</b></sub></a><br /><a href="#mpflash-andypiper" title="mpflash">💥</a> <a href="#test-andypiper" title="Test">✅</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/DavesCodeMusings"><img src="https://avatars.githubusercontent.com/u/61114342?v=4?s=100" width="100px;" alt="David Horton"/><br /><sub><b>David Horton</b></sub></a><br /><a href="#mpflash-DavesCodeMusings" title="mpflash">💥</a> <a href="#test-DavesCodeMusings" title="Test">✅</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

This project follows the [all-contributors](https://github.com/all-contributors/all-contributors) specification. Contributions of any kind welcome!

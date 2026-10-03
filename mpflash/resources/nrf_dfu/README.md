# Packaged nRF DFU artifacts

These packages are vendored for MPFlash's offline, allowlisted nRF52840
SoftDevice migration and recovery workflow. Runtime flashing does not download
artifacts from these links.

| Packaged file | Origin | SHA-256 |
|---|---|---|
| `nice_nano_bootloader-0.11.0_s140_6.1.1.zip` | [Adafruit nRF52 Bootloader 0.11.0 release asset](https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases/download/0.11.0/nice_nano_bootloader-0.11.0_s140_6.1.1.zip) | `892b912af30b5b16b23dae383550c468c9fbd24e0312050b9d075b9f155473e8` |
| `SuperMini_nRF52840_bootloader-1.0.0_s140_7.3.0.zip` | [pdcook nRFMicro Arduino Core package at commit `2026077`](https://github.com/pdcook/nRFMicro-Arduino-Core/blob/2026077de21b520723ec4033f5fdc748b6dd3be8/bootloader/SuperMini_nRF52840/SuperMini_nRF52840_bootloader-1.0.0_s140_7.3.0.zip) | `54bcde643caf7fd567275ed89405d3373cc61e33219985e66ebc6f11d225b22d` |

The machine-readable profile metadata and exact package sizes are in
[`manifest.json`](manifest.json). Applicable upstream and Nordic license
notices are retained in [`licenses/`](licenses/).

# mpremoteboard

`mpremoteboard` is the lightweight board and runner API used by MPFlash. It
provides serial-port discovery, raw MicroPython board metadata, `mpremote`
command execution, and the board-side filesystem scripts without importing
MPFlash, its firmware database, or its CLI configuration.

```python
from mpremoteboard import MPRemoteBoard

board = MPRemoteBoard("/dev/ttyACM0")
board.get_mcu_info(soft_reset=False)
print(board.port, board.version, board.board_id)
```

The package is in the MPFlash uv workspace and has its own distribution
metadata. MPFlash's `mpflash.mpremoteboard` module remains the compatibility
facade for enriched board identity, configuration, and legacy defaults.

"""Compatibility module for the on-device firmware probe script."""

import sys

from mpremoteboard import mpy_fw_info as _probe

sys.modules[__name__] = _probe
setattr(sys.modules[__name__.rpartition(".")[0]], "mpy_fw_info", _probe)

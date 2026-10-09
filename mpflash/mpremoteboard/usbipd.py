"""Compatibility imports for usbipd device handling."""

from mpremoteboard.usbipd import *  # noqa: F403
from mpremoteboard.usbipd import __dict__ as _usbipd_namespace

globals().update({name: value for name, value in _usbipd_namespace.items() if not name.startswith("__")})

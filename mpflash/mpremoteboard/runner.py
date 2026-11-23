"""Compatibility imports for the standalone runner."""

from mpremoteboard.runner import *  # noqa: F403
from mpremoteboard.runner import __dict__ as _runner_namespace

globals().update({name: value for name, value in _runner_namespace.items() if not name.startswith("__")})

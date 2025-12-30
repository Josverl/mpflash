# pragma: no cover
import os
import sys


# our own logging module to avoid dependency on and interfering with logging module
class logging:
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    level = INFO
    prnt = print

    @staticmethod
    def getLogger(name):
        return logging()

    @classmethod
    def basicConfig(cls, level):
        cls.level = level

    def debug(self, msg):
        if self.level <= logging.DEBUG:
            self.prnt("DEBUG :", msg)

    def info(self, msg):
        if self.level <= logging.INFO:
            self.prnt("INFO  :", msg)

    def warning(self, msg):
        if self.level <= logging.WARNING:
            self.prnt("WARN  :", msg)

    def error(self, msg):
        if self.level <= logging.ERROR:
            self.prnt("ERROR :", msg)


log = logging.getLogger("stubber")
logging.basicConfig(level=logging.INFO)
# logging.basicConfig(level=logging.DEBUG)


def get_build(s):
    # extract build from sys.version or os.uname().version if available
    # sys.version: 'MicroPython v1.23.0-preview.6.g3d0b6276f'
    # sys.implementation.version: 'v1.13-103-gb137d064e'
    if not s:
        return ""
    s = s.split(" on ", 1)[0] if " on " in s else s
    if s.startswith("v"):
        if "-" not in s:
            return ""
        b = s.split("-")[1]
        return b
    if "-preview" not in s:
        return ""
    b = s.split("-preview")[1].split(".")[1]
    return b


def _version_str(version: tuple) -> str:
    v_str = ".".join([str(n) for n in version[:3]])
    if len(version) > 3 and version[3]:
        v_str += "-" + version[3]
    return v_str


def _get_base_system_info() -> dict[str, str]:
    """Get basic system implementation details."""
    try:
        fam = sys.implementation[0]  # type: ignore
    except TypeError:
        # testing on CPython 3.11
        fam = sys.implementation.name

    info = dict(
        {
            "family": fam,
            "version": "",
            "build": "",
            "ver": "",
            "port": sys.platform,  # port: esp32 / win32 / linux / stm32
            "board": "UNKNOWN",
            "board_id": "",
            "variant": "",
            "cpu": "",
            "mpy": "",
            "arch": "",
            "description": "",
        }
    )
    return info


def _normalize_port_info(info: dict[str, str]) -> None:
    """Normalize port names to be consistent with the repo."""
    if info["port"].startswith("pyb"):
        info["port"] = "stm32"
    elif info["port"] == "win32":
        info["port"] = "windows"
    elif info["port"] == "linux":
        info["port"] = "unix"


def _extract_version_info(info: dict[str, str]) -> None:
    """Extract version information from sys.implementation."""
    try:
        info["version"] = _version_str(sys.implementation.version)  # type: ignore
    except AttributeError:
        pass


def get_boardname(info: dict) -> None:
    "Read the board_id from the boardname.py file that may have been created upfront"
    try:
        from boardname import BOARD_ID  # type: ignore

        log.info("Found BOARD_ID: {}".format(BOARD_ID))
    except ImportError:
        log.warning("BOARD_ID not found")
        BOARD_ID = ""
    info["board_id"] = BOARD_ID
    info["board"] = BOARD_ID.split("-")[0] if "-" in BOARD_ID else BOARD_ID
    info["variant"] == BOARD_ID.split("-")[1] if "-" in BOARD_ID else ""


def _extract_hardware_info(info: dict[str, str]) -> None:
    """Extract board, CPU, and machine details."""
    try:
        _machine = sys.implementation._machine if "_machine" in dir(sys.implementation) else os.uname().machine  # type: ignore
        description = _machine.strip()
        info["description"] = description
        info["board"] = description
        si_build = sys.implementation._build if "_build" in dir(sys.implementation) else ""
        if si_build:
            info["board"] = si_build.split("-")[0]
            info["variant"] = si_build.split("-")[1] if "-" in si_build else ""
        info["board_id"] = si_build
        info["cpu"] = _machine.split("with")[-1].strip()
        info["mpy"] = (
            sys.implementation._mpy  # type: ignore
            if "_mpy" in dir(sys.implementation)
            else sys.implementation.mpy
            if "mpy" in dir(sys.implementation)
            else ""  # type: ignore
        )
    except (AttributeError, IndexError):
        pass

    if not info["board_id"]:
        get_boardname(info)


def _build(s):
    # extract build from sys.version or os.uname().version if available
    # sys.version: 'MicroPython v1.24.0-preview.6.g3d0b6276f'
    # sys.implementation.version: 'v1.13-103-gb137d064e'
    if not s:
        return ""
    s = s.split(" on ", 1)[0] if " on " in s else s
    if s.startswith("v"):
        if not "-" in s:
            return ""
        b = s.split("-")[1]
        return b
    if not "-preview" in s:
        return ""
    b = s.split("-preview")[1].split(".")[1]
    return b


def _extract_build_info(info: dict[str, str]) -> None:
    """Extract build information from various system sources."""
    try:
        if "uname" in dir(os):  # old
            # extract build from uname().version if available
            info["build"] = _build(os.uname()[3])  # type: ignore
            if not info["build"]:
                # extract build from uname().release if available
                info["build"] = _build(os.uname()[2])  # type: ignore
        elif "version" in dir(sys):  # new
            # extract build from sys.version if available
            info["build"] = _build(sys.version)
    except (AttributeError, IndexError, TypeError):
        pass

    # Fallback version detection for specific platforms
    if info["version"] == "" and sys.platform not in ("unix", "win32"):
        try:
            u = os.uname()  # type: ignore
            info["version"] = u.release
        except (IndexError, AttributeError, TypeError):
            pass


def _detect_firmware_family(info: dict[str, str]) -> None:
    """Detect special firmware families (pycopy, pycom, ev3-pybricks)."""
    for fam_name, mod_name, mod_thing in [
        ("pycopy", "pycopy", "const"),
        ("pycom", "pycom", "FAT"),
        ("ev3-pybricks", "pybricks.hubs", "EV3Brick"),
    ]:
        try:
            _t = __import__(mod_name, None, None, (mod_thing))
            info["family"] = fam_name
            del _t
            break
        except (ImportError, KeyError):
            pass

    if info["family"] == "ev3-pybricks":
        info["release"] = "2.0.0"


def _process_micropython_version(info: dict[str, str]) -> None:
    """Process MicroPython-specific version formatting."""
    if info["family"] == "micropython":
        if (
            info["version"]
            and info["version"].endswith(".0")
            and info["version"] >= "1.10.0"  # versions from 1.10.0 to 1.24.0 do not have a micro .0
            and info["version"] <= "1.19.9"
        ):
            # versions from 1.10.0 to 1.24.0 do not have a micro .0
            info["version"] = info["version"][:-2]


def _process_mpy_info(info: dict[str, str]) -> None:
    """Process MPY architecture and version information."""
    # spell-checker: disable
    if "mpy" in info and info["mpy"]:  # mpy on some v1.11+ builds
        sys_mpy = int(info["mpy"])
        # .mpy architecture
        try:
            arch = [
                None,
                "x86",
                "x64",
                "armv6",
                "armv6m",
                "armv7m",
                "armv7em",
                "armv7emsp",
                "armv7emdp",
                "xtensa",
                "xtensawin",
                "rv32imc",
            ][sys_mpy >> 10]
            if arch:
                info["arch"] = arch
        except IndexError:
            info["arch"] = "unknown"
        # .mpy version.minor
        info["mpy"] = "v{}.{}".format(sys_mpy & 0xFF, sys_mpy >> 8 & 3)


def _format_version_strings(info: dict[str, str]) -> None:
    """Handle final version string formatting."""
    if info["build"] and not info["version"].endswith("-preview"):
        info["version"] = info["version"] + "-preview"
    # simple to use version[-build] string
    info["ver"] = f"{info['version']}-{info['build']}" if info["build"] else f"{info['version']}"


def _info():  # type:() -> dict[str, str]
    """
    Gather comprehensive system information for MicroPython stubbing.

    Returns a dictionary containing family, version, port, board, and other
    system details needed for stub generation.
    """
    # Get base system information
    info = _get_base_system_info()

    # Apply transformations and gather additional info
    _normalize_port_info(info)
    _extract_version_info(info)
    _extract_hardware_info(info)
    _extract_build_info(info)
    _detect_firmware_family(info)
    _process_micropython_version(info)
    _process_mpy_info(info)
    _format_version_strings(info)

    return info


print(_info())
del _info, get_build, _version_str

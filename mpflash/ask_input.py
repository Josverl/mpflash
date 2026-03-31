"""
Interactive input for mpflash using richui for a modern TUI experience.

Port selection uses tab-completion from a list.  Board-variant selection uses
tab-completion from a ``{board_id: variant_hint}`` dict — the user types a
partial board name, presses Tab and sees all matching board[-variant] options.
A Rich tree is printed before the board prompt to show the hierarchy visually.

``ask_port_board_variant`` is the primary entry point that returns
``(port, boards, variant)`` so callers can distinguish the base board name
from the variant part of ``board_id = board[-variant]``.
"""

from typing import Dict, List, Optional, Sequence, Tuple, Union

from loguru import logger as log

from .common import DownloadParams, FlashParams, ParamType
from .config import config
from .mpboard_id import get_known_boards_for_port, known_board_variants_dict, known_ports, known_stored_boards
from .mpremoteboard import MPRemoteBoard
from .versions import clean_version, micropython_versions


# ---------------------------------------------------------------------------
# Module-level lazy Richui instance (avoids paying import cost at startup)
# ---------------------------------------------------------------------------

def _ui():
    """Return a shared Richui instance, imported on first use."""
    from richui import Richui

    return Richui()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ask_missing_params(
    params: ParamType,
) -> ParamType:
    """
    Asks the user for parameters not supplied on the command line and returns updated params.

    Runs interactive richui prompts for serial port, firmware version, and board
    selection (including variant for flash mode).  Returns an empty list if the
    user cancels any prompt.

    Args:
        params: The parameters to be updated.

    Returns:
        The updated parameters, or an empty list if the user cancelled.
    """
    if not config.interactive:
        log.info("Interactive mode disabled. Skipping ask for user input.")
        return params

    log.trace(f"ask_missing_params: {params}")

    multi_select = isinstance(params, DownloadParams)
    action = "download" if isinstance(params, DownloadParams) else "flash"

    answers: Dict[str, Union[str, List]] = {"action": action}

    # Serial port (flash mode only)
    if not multi_select:
        if not params.serial or "?" in params.serial:
            serial = ask_serialport(multi_select=False, bluetooth=False)
            if serial is None:
                return []  # type: ignore
            answers["serial"] = serial
        else:
            answers["serial"] = params.serial

    # Firmware version(s)
    if params.versions == [] or "?" in params.versions:
        versions = ask_mp_version(
            multi_select=multi_select,
            action=action,
            serial=str(answers.get("serial", "")),
        )
        if versions is None:
            return []  # type: ignore
        answers["versions"] = versions
    else:
        answers["versions"] = params.versions  # type: ignore

    # Port, board(s), and variant
    if not params.boards or "?" in params.boards:
        port, boards, variant = ask_port_board_variant(
            multi_select=multi_select,
            action=action,
            answers=answers,
        )
        if port is None or boards is None:
            return []  # type: ignore
        answers["port"] = port
        answers["boards"] = boards
        if isinstance(params, FlashParams):
            answers["variant"] = variant or ""

    log.trace(f"answers: {answers}")

    if isinstance(params, FlashParams) and "serial" in answers:
        if isinstance(answers["serial"], str):
            answers["serial"] = [answers["serial"]]
        params.serial = [s.split()[0] for s in answers["serial"]]  # strip description

    if "port" in answers:
        if isinstance(answers["port"], str):
            params.ports.append(answers["port"])
        elif isinstance(answers["port"], list):  # type: ignore
            params.ports.extend(answers["port"])
        else:
            raise ValueError(f"Unexpected type for answers['port']: {type(answers['port'])}")

    if "boards" in answers:
        params.boards = [b for b in params.boards if b != "?"]
        params.boards.extend(
            answers["boards"] if isinstance(answers["boards"], list) else [answers["boards"]]
        )

    if "versions" in answers:
        params.versions = [v for v in params.versions if v != "?"]
        if isinstance(answers["versions"], (list, tuple)):
            params.versions.extend(answers["versions"])
        else:
            params.versions.append(answers["versions"])

    if "variant" in answers and isinstance(params, FlashParams):
        params.variant = answers["variant"]

    # remove duplicates
    params.ports = list(set(params.ports))
    params.boards = list(set(params.boards))
    params.versions = list(set(params.versions))
    log.trace(f"ask_missing_params returns: {params}")

    return params


def filter_matching_boards(answers: dict) -> Sequence[Tuple[str, str]]:
    """
    Filters the known boards based on the selected versions and returns the filtered boards.
    If no boards are found for the requested version(s), falls back to previous stable/preview versions.

    Args:
        answers (dict): The user's answers.

    Returns:
        Sequence[Tuple[str, str]]: The filtered boards.
    """
    versions = []
    original_versions = []

    if "versions" in answers:
        original_versions = list(answers["versions"])
        versions = list(answers["versions"])
        if "stable" in versions:
            versions.remove("stable")
            versions.append(micropython_versions()[-2])  # latest stable
        elif "preview" in versions:
            versions.remove("preview")
            versions.extend((micropython_versions()[-1], micropython_versions()[-2]))

    some_boards = known_stored_boards(answers["port"], versions)

    if not some_boards and versions:
        log.debug(f"No boards found for {answers['port']} with version(s) {versions}, trying fallback")

        all_versions = micropython_versions()
        fallback_versions = []

        for original_version in original_versions:
            if original_version == "stable":
                stable_versions = [v for v in all_versions if not v.endswith("preview")]
                fallback_versions.extend(stable_versions[-3:])
            elif original_version == "preview":
                preview_versions = [v for v in all_versions if v.endswith("preview")]
                stable_versions = [v for v in all_versions if not v.endswith("preview")]
                fallback_versions.extend(preview_versions[-1:] + stable_versions[-2:])
            else:
                try:
                    version_index = all_versions.index(original_version)
                    start_idx = max(0, version_index - 2)
                    fallback_versions.extend(all_versions[start_idx : version_index + 1])
                except ValueError:
                    stable_versions = [v for v in all_versions if not v.endswith("preview")]
                    fallback_versions.extend(stable_versions[-2:])

        fallback_versions = [clean_version(v) for v in list(set(fallback_versions))]

        if fallback_versions:
            log.debug(f"Trying fallback versions: {fallback_versions}")
            some_boards = known_stored_boards(answers["port"], fallback_versions)

    if some_boards:
        unique_dict = {item[1]: item for item in some_boards}
        some_boards = list(unique_dict.values())
    else:
        some_boards = [(f"No {answers['port']} boards found for version(s) {versions}", "")]
    return some_boards


def ask_port_board_variant(
    *,
    multi_select: bool,
    action: str,
    answers: dict,
) -> Tuple[Optional[str], Optional[List[str]], Optional[str]]:
    """
    Ask for MicroPython port, board (with variant), interactively.

    For flash mode (``multi_select=False``), displays a Rich tree of all
    available boards grouped by base board with variants indented, then uses
    richui ``input(completion=dict)`` so the user can type and Tab-complete
    a full ``board[-variant]`` identifier.

    For download mode (``multi_select=True``), uses richui ``select`` with
    multi-select enabled.

    Args:
        multi_select: True for download (multiple boards), False for flash.
        action: ``'flash'`` or ``'download'``.
        answers: Current answers dict supplying version context for filtering.

    Returns:
        ``(port, boards, variant)`` where *boards* is a list of base board
        names and *variant* is the variant string (may be ``""``).
        Returns ``(None, None, None)`` if the user cancelled.
    """
    # import only when needed to reduce load time
    from rich.console import Console

    ui = _ui()
    _console = Console()

    serial = str(answers.get("serial", ""))
    suffix = f" to {serial}" if serial and action == "flash" else ""

    # --- Port -----------------------------------------------------------
    ports = known_ports()
    if not ports:
        log.warning("No known ports found in database.")
        return None, None, None

    port = ui.input(
        f"Which port do you want to {action}{suffix}?",
        completion=ports,
        footer="<Tab to complete, Enter to confirm>",
    )
    if not port or port not in ports:
        return None, None, None

    # --- Board + variant -----------------------------------------------
    answers_with_port = {**answers, "port": port}

    # Resolve actual versions for the dict lookup (same logic as filter_matching_boards)
    resolved_versions = _resolve_versions(list(answers.get("versions", [])))

    boards_dict = known_board_variants_dict(port, resolved_versions)
    if not boards_dict:
        # Fall back to filter_matching_boards (returns List[Tuple[display, board_id]])
        # to get the "no boards found" sentinel or boards from a different version.
        board_choices = list(filter_matching_boards(answers_with_port))
        boards_dict = {bid: "" for display, bid in board_choices if bid}

    # Display a rich Tree so the user sees the hierarchy before typing
    _print_board_tree(port=port, boards_dict=boards_dict, console=_console)

    boards_message = f"Which {port} board firmware do you want to {action}{suffix}?"

    if multi_select:
        board_options = list(boards_dict.keys())
        while True:
            selected = ui.select(
                board_options,
                prompt=boards_message,
                footer="<Space to toggle, Enter to confirm>",
                multi_select=True,
            )
            if selected is None:
                return port, None, None
            if selected:
                return port, list(selected), ""
            _console.print("[red]Please select at least one board.[/red]")
    else:
        while True:
            board_input = ui.input(
                boards_message,
                completion=boards_dict,
                footer="<Tab to complete board[-variant], Enter to confirm>",
            )
            if not board_input:
                return port, None, None
            if board_input in boards_dict:
                base_board, variant = _split_board_variant(board_input)
                return port, [base_board], variant
            _console.print(f"[red]Unknown board {board_input!r}. Use Tab to see valid choices.[/red]")


def ask_port_board(
    *,
    multi_select: bool,
    action: str,
    answers: dict,
) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    Ask for port and board(s) without variant.

    Thin wrapper around :func:`ask_port_board_variant` that drops the variant
    return value for callers that don't need it.

    Args:
        multi_select: True for download (multiple boards), False for flash.
        action: ``'flash'`` or ``'download'``.
        answers: Current answers dict.

    Returns:
        ``(port, boards)`` or ``(None, None)`` if cancelled.
    """
    port, boards, _ = ask_port_board_variant(multi_select=multi_select, action=action, answers=answers)
    return port, boards


def ask_mp_version(
    multi_select: bool,
    action: str,
    serial: str = "",
) -> Optional[Union[str, List[str]]]:
    """
    Ask for firmware version(s) interactively using richui.

    For single selection (flash), uses ``input`` with tab-completion from the
    version list.  For multi-selection (download), uses ``select`` with
    multi-select enabled and a validation loop.

    Args:
        multi_select: True to allow selecting multiple versions (download mode).
        action: ``'flash'`` or ``'download'``.
        serial: Current serial port string (for message context).

    Returns:
        Selected version string, list of version strings, or ``None`` if cancelled.
    """
    # import only when needed to reduce load time
    from rich.console import Console

    _console = Console()
    ui = _ui()

    mp_versions: List[str] = micropython_versions()
    mp_versions.reverse()  # newest first
    mp_versions = [v for v in mp_versions if "preview" in v or get_known_boards_for_port("stm32", [v])]

    suffix = f" to {serial}" if serial and action == "flash" else ""
    message = f"Which version(s) do you want to {action}{suffix}?"

    if multi_select:
        while True:
            result = ui.select(
                mp_versions,
                prompt=message,
                footer="<Space to toggle, Enter to confirm>",
                multi_select=True,
            )
            if result is None:
                return None
            if result:
                return list(result)
            _console.print("[red]Please select at least one version.[/red]")
    else:
        result = ui.input(
            message,
            completion=mp_versions,
            footer="<Tab to complete, Enter to confirm>",
        )
        return result if result else None


def ask_serialport(
    *,
    multi_select: bool = False,
    bluetooth: bool = False,
) -> Optional[str]:
    """
    Ask for serial port selection using richui tab-completion from a list.

    Args:
        multi_select: Reserved for future use (currently unused).
        bluetooth: Whether to include Bluetooth serial ports.

    Returns:
        Selected serial port string (may include a description suffix) or
        ``None`` if the user cancelled.
    """
    # import only when needed to reduce load time
    ui = _ui()

    comports = MPRemoteBoard.connected_comports(bluetooth=bluetooth, description=True) + ["auto"]
    result = ui.input(
        "Which serial port do you want to use?",
        completion=comports,
        footer="<Tab to complete, Enter to confirm>",
    )
    return result if result else None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_versions(versions: List[str]) -> List[str]:
    """Resolve symbolic version names (``stable``, ``preview``) to actual version strings."""
    resolved: List[str] = []
    for v in versions:
        if v == "stable":
            resolved.append(micropython_versions()[-2])
        elif v == "preview":
            resolved.extend([micropython_versions()[-1], micropython_versions()[-2]])
        elif v != "?":
            resolved.append(clean_version(v))
    return resolved


def _split_board_variant(board_id: str) -> Tuple[str, str]:
    """
    Split a ``board[-variant]`` identifier into ``(base_board, variant)``.

    The DB stores board_id as the full key (e.g. ``ESP32_GENERIC-SPIRAM``).
    The ``-`` separates the base board from the variant suffix.

    Returns:
        ``(base_board, variant)`` — variant is ``""`` when not present.
    """
    if "-" in board_id:
        base, variant = board_id.split("-", 1)
        return base, variant
    return board_id, ""


def _print_board_tree(port: str, boards_dict: dict, console) -> None:
    """
    Print a Rich tree showing board → variant hierarchy before the input prompt.

    Boards are grouped by their base name (the part before the first ``-``).
    Variants are shown as child nodes.

    Args:
        port: Port name used as the tree root label.
        boards_dict: ``{board_id: variant_hint}`` as from :func:`known_board_variants_dict`.
        console: Rich Console instance.
    """
    from rich.tree import Tree

    # Group boards by base name
    groups: Dict[str, List[Tuple[str, str]]] = {}
    for board_id, variant in boards_dict.items():
        base, var = _split_board_variant(board_id)
        groups.setdefault(base, []).append((board_id, var))

    tree = Tree(f"[bold cyan]{port}[/bold cyan] boards")
    for base in sorted(groups):
        entries = groups[base]
        if len(entries) == 1 and not entries[0][1]:
            # No variants — show board directly under root
            tree.add(f"[green]{base}[/green]")
        else:
            branch = tree.add(f"[green]{base}[/green]")
            for full_id, var in sorted(entries, key=lambda x: x[1]):
                label = f"[yellow]{var}[/yellow]" if var else "[dim](base)[/dim]"
                branch.add(f"{full_id}  {label}")

    console.print(tree)

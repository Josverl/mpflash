"""
Interactive input for mpflash using questionary for a cross-platform TUI experience.

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
# High-contrast questionary style
# Works on dark terminals (Windows Terminal, most Linux defaults) and
# light-background terminals.  Uses standard ANSI colours only — no
# 256-colour codes — so contrast is handled by the terminal theme itself.
# ---------------------------------------------------------------------------


def _mpflash_style():
    """Return a high-contrast questionary Style for all interactive prompts."""
    from questionary import Style

    return Style(
        [
            ("qmark", "bold"),  # "?" prefix — bold, inherits fg
            ("question", "bold"),  # question text
            ("answer", "fg:cyan bold"),  # confirmed answer — cyan is readable on dark AND light
            ("pointer", "fg:cyan bold"),  # selection cursor
            ("selected", "fg:cyan"),  # ticked checkbox item
            ("search_success", "bold fg:green"),
            ("search_none", "bold fg:red"),
            ("highlighted", "fg:cyan bold"),  # currently highlighted autocomplete match
            ("separator", "fg:default"),
            ("instruction", "fg:default italic"),
            ("text", ""),
            # Autocomplete dropdown — dark background, dim text, no glare
            ("completion-menu", "bg:ansiblack fg:ansiwhite"),
            ("completion-menu.completion", "bg:ansiblack fg:ansiwhite"),
            ("completion-menu.completion.current", "bg:ansidarkgray fg:ansicyan bold"),
            ("completion-menu.meta", "bg:ansiblack fg:ansidarkgray"),
            ("completion-menu.meta.completion", "bg:ansiblack fg:ansidarkgray"),
            ("completion-menu.meta.completion.current", "bg:ansidarkgray fg:ansigray"),
        ]
    )


# ---------------------------------------------------------------------------
# Questionary-based input helpers (cross-platform replacement for richui)
# ---------------------------------------------------------------------------


def _ask_with_completion(
    prompt: str,
    completion,
    meta: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Ask for input with tab-completion using questionary."""
    import questionary

    choices = list(completion.keys()) if isinstance(completion, dict) else list(completion)

    q = questionary.autocomplete(
        prompt,
        choices=choices,
        match_middle=True,
        complete_while_typing=True,
        meta_information=meta,
        validate=lambda val: bool(val) or "Please select an option (Ctrl-C to abort).",
        style=_mpflash_style(),
    )

    def _open_completions() -> None:
        q.application.current_buffer.start_completion(select_first=False)

    try:
        return q.application.run(pre_run=_open_completions)
    except KeyboardInterrupt:
        return None


def _ask_select(
    options: List[str],
    *,
    prompt: str,
    multi_select: bool,
) -> Optional[Union[str, List[str]]]:
    """Select from a list using questionary (single or multi-select)."""
    import questionary

    style = _mpflash_style()
    if multi_select:
        return questionary.checkbox(prompt, choices=options, style=style).ask()
    return questionary.select(prompt, choices=options, style=style).ask()


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

    variant_unknown = isinstance(params, FlashParams) and params.variant == "?"
    needs_serial = not multi_select and (not params.serial or "?" in params.serial)
    needs_versions = params.versions == [] or "?" in params.versions
    needs_board = not params.boards or "?" in params.boards or variant_unknown

    if not (needs_serial or needs_versions or needs_board):
        return params

    from rich.console import Console
    Console().print("[dim]Type to filter, Tab to complete, Enter confirms[/dim]")

    answers: Dict[str, Union[str, List]] = {"action": action}

    # Serial port (flash mode only)
    if not multi_select:
        if needs_serial:
            serial = ask_serialport(multi_select=False, bluetooth=False)
            if serial is None:
                return []  # type: ignore
            answers["serial"] = serial
        else:
            answers["serial"] = params.serial

    # Firmware version(s)
    if needs_versions:
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
    if needs_board:
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
    questionary ``autocomplete`` so the user can type and Tab-complete
    a full ``board[-variant]`` identifier.

    For download mode (``multi_select=True``), uses questionary ``checkbox``
    with multi-select enabled.

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

    _console = Console()

    # --- Port -----------------------------------------------------------
    ports = known_ports()
    if not ports:
        log.warning("No known ports found in database.")
        return None, None, None

    port_meta = _port_meta()
    port = _ask_with_completion(
        f"Port to {action}?",
        ports,
        meta=port_meta,
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
    # (omitted — options are available via Tab completion)

    boards_message = f"{port.upper()} board to {action}?"

    # Build a mapping from base board name -> list of full board_ids (with variants)
    base_to_variants: Dict[str, List[str]] = {}
    for board_id in boards_dict:
        base, _ = _split_board_variant(board_id)
        base_to_variants.setdefault(base, []).append(board_id)

    if multi_select:
        board_options = list(boards_dict.keys())
        while True:
            selected = _ask_select(
                board_options,
                prompt=boards_message,
                multi_select=True,
            )
            if selected is None:
                return port, None, None
            if selected:
                return port, list(selected), ""
            _console.print("[red]Please select at least one board.[/red]")
    else:
        # Step 1: pick from unique base board names only
        base_boards = sorted(base_to_variants.keys())
        while True:
            base_input = _ask_with_completion(boards_message, base_boards)
            if not base_input:
                return port, None, None
            if base_input in base_to_variants:
                break
            _console.print(f"[red]Unknown board {base_input!r}.[/red]")

        # Step 2: if multiple variants exist, ask which one
        variants = base_to_variants[base_input]
        if len(variants) == 1:
            full_id = variants[0]
        else:
            while True:
                full_id = _ask_with_completion(
                    f"Variant to {action}?",
                    variants,
                )
                if not full_id:
                    return port, None, None
                if full_id in variants:
                    break
                _console.print(f"[red]Unknown variant {full_id!r}.[/red]")

        base_board, variant = _split_board_variant(full_id)
        return port, [base_board], variant


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
    Ask for firmware version(s) interactively using questionary.

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

    mp_versions: List[str] = micropython_versions()
    mp_versions.reverse()  # newest first
    mp_versions = [v for v in mp_versions if "preview" in v or get_known_boards_for_port("stm32", [v])]

    message = f"Version(s) to {action}?"

    if multi_select:
        while True:
            result = _ask_select(
                mp_versions,
                prompt=message,
                multi_select=True,
            )
            if result is None:
                return None
            if result:
                return list(result)
            _console.print("[red]Please select at least one version.[/red]")
    else:
        result = _ask_with_completion(
            message,
            mp_versions,
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
    from rich.console import Console
    from rich.tree import Tree

    _console = Console()
    comports = MPRemoteBoard.connected_comports(bluetooth=bluetooth, description=True) + ["auto"]

    result = _ask_with_completion(
        "Serial port to use?",
        comports,
    )
    return result if result else None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _port_meta() -> Dict[str, str]:
    """Build a meta-information dict describing each port's flash/download support."""
    from .common import PORT_FWTYPES, SA_PORTS
    from .mpboard_id import known_ports

    meta: Dict[str, str] = {}
    for port in PORT_FWTYPES:
        exts = ", ".join(PORT_FWTYPES[port])
        meta[port] = f"flash ({exts})"
    for port in SA_PORTS:
        meta[port] = "n/a"
    try:
        for port in known_ports():
            if port not in meta:
                meta[port] = "not yet supported"
    except Exception:
        pass
    return meta


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

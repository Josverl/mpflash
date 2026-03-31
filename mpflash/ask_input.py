"""
Interactive input for mpflash using rich-inquirer for a modern TUI experience.

Prompts are rendered with Rich styling and support keyboard navigation,
fuzzy search (version picker), and multi-select (download mode).
"""

from typing import Dict, List, Optional, Sequence, Tuple, Union

from loguru import logger as log

from .common import DownloadParams, FlashParams, ParamType
from .config import config
from .mpboard_id import get_known_boards_for_port, known_ports, known_stored_boards
from .mpremoteboard import MPRemoteBoard
from .versions import clean_version, micropython_versions


def ask_missing_params(
    params: ParamType,
) -> ParamType:
    """
    Asks the user for parameters not supplied on the command line and returns updated params.

    Runs interactive rich-inquirer prompts for serial port, firmware version,
    and board selection.  Returns an empty list if the user cancels any prompt.

    Args:
        params: The parameters to be updated.

    Returns:
        The updated parameters, or an empty list if the user cancelled.
    """
    if not config.interactive:
        # no interactivity allowed
        log.info("Interactive mode disabled. Skipping ask for user input.")
        return params

    log.trace(f"ask_missing_params: {params}")

    # if action flash, single input; if action download, multiple input
    multi_select = isinstance(params, DownloadParams)
    action = "download" if isinstance(params, DownloadParams) else "flash"

    answers: Dict[str, Union[str, List]] = {"action": action}

    # Ask for serial port (flash mode only)
    if not multi_select:
        if not params.serial or "?" in params.serial:
            serial = ask_serialport(multi_select=False, bluetooth=False)
            if serial is None:
                return []  # type: ignore
            answers["serial"] = serial
        else:
            answers["serial"] = params.serial

    # Ask for firmware version(s) when not already provided
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
        # versions is used to show only the boards for the selected versions
        answers["versions"] = params.versions  # type: ignore

    # Ask for port and board(s) when not already provided
    if not params.boards or "?" in params.boards:
        port, boards = ask_port_board(multi_select=multi_select, action=action, answers=answers)
        if port is None or boards is None:
            return []  # type: ignore
        answers["port"] = port
        answers["boards"] = boards

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
        params.boards = [b for b in params.boards if b != "?"]  # remove placeholder
        params.boards.extend(answers["boards"] if isinstance(answers["boards"], list) else [answers["boards"]])

    if "versions" in answers:
        params.versions = [v for v in params.versions if v != "?"]  # remove placeholder
        if isinstance(answers["versions"], (list, tuple)):
            params.versions.extend(answers["versions"])
        else:
            params.versions.append(answers["versions"])

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

    # if version is not asked ; then need to get the version from the inputs
    if "versions" in answers:
        original_versions = list(answers["versions"])
        versions = list(answers["versions"])
        if "stable" in versions:
            versions.remove("stable")
            versions.append(micropython_versions()[-2])  # latest stable
        elif "preview" in versions:
            versions.remove("preview")
            versions.extend((micropython_versions()[-1], micropython_versions()[-2]))  # latest preview and stable

    some_boards = known_stored_boards(answers["port"], versions)

    # If no boards found and we have specific versions, try fallback
    if not some_boards and versions:
        log.debug(f"No boards found for {answers['port']} with version(s) {versions}, trying fallback")

        # Get all micropython versions to find fallback candidates
        all_versions = micropython_versions()
        fallback_versions = []

        for original_version in original_versions:
            if original_version == "stable":
                # For stable, try previous stable versions
                stable_versions = [v for v in all_versions if not v.endswith("preview")]
                # Try the last 3 stable versions
                fallback_versions.extend(stable_versions[-3:])
            elif original_version == "preview":
                # For preview, try current preview and recent stable versions
                preview_versions = [v for v in all_versions if v.endswith("preview")]
                stable_versions = [v for v in all_versions if not v.endswith("preview")]
                fallback_versions.extend(preview_versions[-1:] + stable_versions[-2:])
            else:
                # For specific version, try that version and previous versions
                try:
                    version_index = all_versions.index(original_version)
                    # Try current and up to 2 previous versions
                    start_idx = max(0, version_index - 2)
                    fallback_versions.extend(all_versions[start_idx : version_index + 1])
                except ValueError:
                    # Version not found in list, try recent stable versions
                    stable_versions = [v for v in all_versions if not v.endswith("preview")]
                    fallback_versions.extend(stable_versions[-2:])

        # Remove duplicates and clean versions
        fallback_versions = [clean_version(v) for v in list(set(fallback_versions))]

        if fallback_versions:
            log.debug(f"Trying fallback versions: {fallback_versions}")
            some_boards = known_stored_boards(answers["port"], fallback_versions)

    if some_boards:
        # Create a dictionary where the keys are the second elements of the tuples
        # This will automatically remove duplicates because dictionaries cannot have duplicate keys
        unique_dict = {item[1]: item for item in some_boards}
        # Get the values of the dictionary, which are the unique items from the original list
        some_boards = list(unique_dict.values())
    else:
        some_boards = [(f"No {answers['port']} boards found for version(s) {versions}", "")]
    return some_boards


def ask_port_board(*, multi_select: bool, action: str, answers: dict) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    Runs port and board selection prompts interactively using rich-inquirer.

    Asks the user to select a port first, then filters boards by port and
    selected versions before asking for board selection.

    Args:
        multi_select: Whether to allow multiple board selections (download mode).
        action: The action being performed ('flash' or 'download').
        answers: Current answers dict used for message context and board filtering.

    Returns:
        Tuple of (port, boards) or (None, None) if the user cancelled.
    """
    # import only when needed to reduce load time
    from rich_inquirer.prompt import MultiSelectPrompt, SelectPrompt

    serial = str(answers.get("serial", ""))
    suffix = f" to {serial}" if serial and action == "flash" else ""

    # Ask for port
    ports = known_ports()
    if not ports:
        log.warning("No known ports found in database.")
        return None, None

    port_prompt = SelectPrompt(
        message=f"Which port do you want to {action}{suffix}?",
        choices=ports,
    )
    port = port_prompt.ask()
    if port is None:
        return None, None

    # Get board choices based on selected port and current version answers
    answers_with_port = {**answers, "port": port}
    board_choices = list(filter_matching_boards(answers_with_port))
    boards_message = f"Which {port} board firmware do you want to {action}{suffix}?"

    if multi_select:
        from rich.console import Console

        _console = Console()
        while True:
            boards_prompt = MultiSelectPrompt(message=boards_message, choices=board_choices)
            boards = boards_prompt.ask()
            if boards is None:
                return port, None
            if boards:
                return port, boards
            _console.print("[red]Please select at least one board.[/red]")
    else:
        boards_prompt = SelectPrompt(message=boards_message, choices=board_choices)
        boards = boards_prompt.ask()
        if boards is None:
            return port, None
        return port, [boards] if isinstance(boards, str) else boards


def ask_mp_version(multi_select: bool, action: str, serial: str = "") -> Optional[Union[str, List[str]]]:
    """
    Runs firmware version selection prompt interactively using rich-inquirer.

    Uses FuzzyPrompt for single selection (flash) and MultiSelectPrompt for
    multiple selections (download) with a validation loop.

    Args:
        multi_select: Whether to allow selecting multiple versions.
        action: The action being performed ('flash' or 'download').
        serial: Current serial port string (for message context in flash mode).

    Returns:
        Selected version string, list of version strings, or None if cancelled.
    """
    # import only when needed to reduce load time
    from rich.console import Console
    from rich_inquirer.prompt import FuzzyPrompt, MultiSelectPrompt

    _console = Console()
    mp_versions: List[str] = micropython_versions()
    mp_versions.reverse()  # newest first

    # remove the versions for which there are no known boards in the board_info.json
    mp_versions = [v for v in mp_versions if "preview" in v or get_known_boards_for_port("stm32", [v])]

    suffix = f" to {serial}" if serial and action == "flash" else ""
    message = f"Which version(s) do you want to {action}{suffix}?"

    if multi_select:
        while True:
            prompt = MultiSelectPrompt(message=message, choices=mp_versions)
            result = prompt.ask()
            if result is None:
                return None
            if result:
                return result
            _console.print("[red]Please select at least one version.[/red]")
    else:
        # FuzzyPrompt provides autocomplete-style search for single selection
        prompt = FuzzyPrompt(message=message, choices=mp_versions, limit=15)
        return prompt.ask()


def ask_serialport(*, multi_select: bool = False, bluetooth: bool = False) -> Optional[str]:
    """
    Runs serial port selection prompt interactively using rich-inquirer.

    Args:
        multi_select: Reserved for future multi-select support (currently unused).
        bluetooth: Whether to include Bluetooth serial ports in the list.

    Returns:
        Selected serial port string (may include description), or None if cancelled.
    """
    # import only when needed to reduce load time
    from rich_inquirer.prompt import SelectPrompt

    comports = MPRemoteBoard.connected_comports(bluetooth=bluetooth, description=True) + ["auto"]
    prompt = SelectPrompt(
        message="Which serial port do you want to use?",
        choices=comports,
    )
    return prompt.ask()

from os import path
from pathlib import Path
from typing import List, Optional, Tuple

import click
from typing_extensions import TypeAlias

import mpflash.basicgit as git
from mpflash.logger import log
from mpflash.mpremoteboard import HERE
from mpflash.vendor.board_database import Database
from mpflash.versions import micropython_versions

BoardList: TypeAlias = List[Tuple[str, ...]]

HERE = Path(__file__).parent.resolve()


## iterator to flatten the board database into a list of tuples
def iter_boards(db: Database, version: str = ""):
    """Iterate over the boards in the database and yield tuples of board information."""
    version = version.strip()
    for b in db.boards:
        board = db.boards[b]
        yield (
            version,
            board.name,
            board.name,
            board.mcu,
            "",  # no variant
            board.port.name if board.port else "",
            board.path.split("/micropython/", 1)[1],  # TODO - remove hack
            board.description,
            "micropython",  # family
        )
        if board.variants:
            for v in board.variants:
                yield (
                    version,
                    f"{board.name}-{v.name}",
                    board.name,
                    board.mcu,
                    v.name,
                    board.port.name if board.port else "",
                    board.path.split("/micropython/", 1)[1],  # TODO - remove hack
                    v.description,
                    "micropython",  # family
                )


def boardlist_from_repo(
    versions: List[str],
    mpy_dir: Path,
):
    longlist: BoardList = []
    if not mpy_dir.is_dir():
        log.error(f"Directory {mpy_dir} not found")
        return longlist
    # make sure that we have all the latest and greatest from the repo
    git.fetch(mpy_dir)
    git.pull(mpy_dir, branch="master", force=True)
    for version in versions:
        build_nr = ""
        if "preview" in version:
            ok = git.checkout_tag("master", mpy_dir)
            if describe := git.get_git_describe(mpy_dir):
                parts = describe.split("-", 3)
                if len(parts) >= 3:
                    build_nr = parts[2]
        else:
            ok = git.checkout_tag(version, mpy_dir)
        if not ok:
            log.warning(f"Failed to checkout {version} in {mpy_dir}")
            continue

        log.info(f"{git.get_git_describe(mpy_dir)} - {build_nr}")
        # un-cached database
        db = Database(mpy_dir)
        shortlist: BoardList = list(iter_boards(db, version=version))
        log.info(f"boards found {len(db.boards.keys())}")
        log.info(f"boards-variants found {len(shortlist) - len(db.boards.keys())}")
        longlist.extend(shortlist)
    return longlist


def create_zip_file(longlist: BoardList, zip_file: Path):
    """Create a ZIP file containing the CSV data without external deps.

    Uses the standard library csv module to minimize dependencies while
    preserving identical column ordering to the prior pandas implementation.
    """
    import csv
    import io
    import zipfile  # lazy import

    csv_filename = "micropython_boards.csv"
    columns = [
        "version",
        "board_id",
        "board_name",
        "mcu",
        "variant",
        "port",
        "path",
        "description",
        "family",
    ]

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    # rows already in correct order matching columns
    for row in longlist:
        writer.writerow(row)
    csv_data = buf.getvalue()

    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr(csv_filename, csv_data)


def write_version_file(version: str, output_path: Path):
    version_file = output_path / "boards_version.txt"
    with version_file.open("w", encoding="utf-8") as vf:
        vf.write(version + "\n")
    log.info(f"Wrote version file {version_file}")


def package_repo(mpy_path: Path):
    mpy_path = mpy_path or Path("../repos/micropython")
    log.info(f"Packaging Micropython boards from {mpy_path}")
    mp_versions = micropython_versions(minver="1.18")
    if not mp_versions:
        log.error("No Micropython versions found")
        return
    # checkout
    longlist = boardlist_from_repo(
        versions=mp_versions,
        mpy_dir=mpy_path,
    )
    log.info(f"Total boards-variants: {len(longlist)}")
    zip_file = HERE / "micropython_boards.zip"
    create_zip_file(longlist, zip_file=zip_file)
    log.info(f"Created {zip_file} with {len(longlist)} entries")
    boards_version = mp_versions[-1]
    write_version_file(boards_version, HERE)

    assert zip_file.is_file(), f"Failed to create {zip_file}"


@click.command()
@click.option(
    "--mpy-path",
    "mpy_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to local micropython repo (default: ../repos/micropython).",
)
def cli(mpy_path: Optional[Path]):
    """Package board metadata into a compressed archive.

    Enumerates boards and variants from a Micropython repo, builds CSV, and
    writes it into a zip archive for fast loading and distribution.
    """
    package_repo(mpy_path if mpy_path else Path("../repos/micropython"))


if __name__ == "__main__":
    cli()

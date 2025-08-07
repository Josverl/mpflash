from os import path
from pathlib import Path
from typing import List

import mpflash.basicgit as git
from mpflash.logger import log
from mpflash.mpremoteboard import HERE
from mpflash.vendor.board_database import Database
from mpflash.versions import micropython_versions

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
    longlist = []
    if not mpy_dir.is_dir():
        log.error(f"Directory {mpy_dir} not found")
        return longlist
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
        shortlist = list(iter_boards(db, version=version))
        log.info(f"boards found {len(db.boards.keys())}")
        log.info(f"boards-variants found {len(shortlist) - len(db.boards.keys())}")
        longlist.extend(shortlist)
    return longlist


def create_zip_file(longlist, zip_file: Path):
    """Create a ZIP file containing the CSV data."""
    # lazy import
    import zipfile

    import pandas as pd

    csv_filename = "micropython_boards.csv"

    columns = ["version", "board_id", "board_name", "mcu", "variant", "port", "path", "description", "family"]
    df = pd.DataFrame(longlist, columns=columns)

    # Create the ZIP file and add the CSV data directly without creating an intermediate file
    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Create a temporary in-memory CSV string
        csv_data = df.to_csv(index=False)
        # Write the CSV data directly to the zip file
        zipf.writestr(csv_filename, csv_data)


def package_repo(mpy_path: Path):
    mpy_path = mpy_path or Path("../repos/micropython")
    log.info(f"Packaging Micropython boards from {mpy_path}")
    mp_versions = micropython_versions(minver="1.18")
    longlist = boardlist_from_repo(
        versions=mp_versions,
        mpy_dir=mpy_path,
    )
    log.info(f"Total boards-variants: {len(longlist)}")
    zip_file = HERE / "micropython_boards.zip"
    create_zip_file(longlist, zip_file=zip_file)

    assert zip_file.is_file(), f"Failed to create {zip_file}"


if __name__ == "__main__":
    package_repo(Path("D:\\mypython\\mpflash\\repos\\micropython"))

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Sequence

import click
from packaging.version import InvalidVersion, Version

import mpflash.basicgit as git
from mpflash.db.gather_boards import iter_boards
from mpflash.logger import log
from mpflash.vendor.board_database import Database
from mpflash.versions import micropython_versions

BOARD_COLUMNS = (
    "version",
    "board_id",
    "board_name",
    "mcu",
    "variant",
    "port",
    "path",
    "description",
    "family",
)

LEGACY_CUTOFF = Version("1.18")


def _ensure_parent(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _prepare_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS board_rows;
        DROP TABLE IF EXISTS version_stats;
        DROP TABLE IF EXISTS metadata;

        CREATE TABLE board_rows (
            version TEXT NOT NULL,
            board_id TEXT NOT NULL,
            board_name TEXT NOT NULL,
            mcu TEXT NOT NULL,
            variant TEXT NOT NULL,
            port TEXT NOT NULL,
            path TEXT NOT NULL,
            description TEXT NOT NULL,
            family TEXT NOT NULL
        );

        CREATE TABLE version_stats (
            version_order INTEGER NOT NULL,
            version TEXT NOT NULL,
            boards_found INTEGER NOT NULL,
            board_variants_found INTEGER NOT NULL,
            ports_found INTEGER NOT NULL,
            total_rows INTEGER NOT NULL
        );

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX idx_board_rows_version ON board_rows(version);
        CREATE INDEX idx_board_rows_port ON board_rows(port);
        CREATE INDEX idx_board_rows_variant ON board_rows(variant);
        """
    )


def _collect_version_stats(rows: Sequence[tuple[str, ...]], versions: Sequence[str]) -> list[tuple[int, str, int, int, int, int]]:
    rows_by_version: dict[str, list[tuple[str, ...]]] = {v: [] for v in versions}
    for row in rows:
        version = row[0]
        rows_by_version.setdefault(version, []).append(row)

    stats: list[tuple[int, str, int, int, int, int]] = []
    for index, version in enumerate(versions):
        version_rows = rows_by_version.get(version, [])
        boards_found = sum(1 for row in version_rows if row[4] == "")
        board_variants_found = sum(1 for row in version_rows if row[4] != "")
        ports_found = len({row[5] for row in version_rows if row[5]})
        total_rows = len(version_rows)
        stats.append((index, version, boards_found, board_variants_found, ports_found, total_rows))
    return stats


def _version_sort_key(version: str) -> tuple[int, int, int, int, str]:
    """Sort versions using PEP 440 parsing when possible."""
    pep440 = _to_pep440_version(version)
    if pep440 is not None:
        return (1, pep440)
    return (0, version)


def _to_pep440_string(version: str) -> str:
    """Normalize MicroPython tags into a PEP 440 compatible version string."""
    v = version.strip().lstrip("v")

    # preview tags behave like prereleases for ordering.
    v = re.sub(r"-preview(?:-[0-9]+-g[0-9a-f]+)?$", "rc999", v)
    v = re.sub(r"-rc([0-9]+)$", r"rc\1", v)

    if "-" in v:
        base, suffix = v.split("-", 1)
        safe_suffix = re.sub(r"[^A-Za-z0-9.]+", ".", suffix)
        v = f"{base}+{safe_suffix}"

    return v


def _to_pep440_version(version: str) -> Version | None:
    """Parse version with packaging.Version after normalization."""
    try:
        return Version(_to_pep440_string(version))
    except InvalidVersion:
        return None


def _is_legacy_version(version: str) -> bool:
    """Versions before 1.18 use folder-based fallback board discovery."""
    pep440 = _to_pep440_version(version)
    if pep440 is None:
        return False
    return pep440 < LEGACY_CUTOFF


def _relative_repo_path(path: Path, repo_root: Path) -> str:
    """Convert an absolute path to a stable repo-relative POSIX path."""
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _rows_from_folder_layout(mpy_dir: Path, version: str) -> list[tuple[str, ...]]:
    """Fallback board discovery by scanning modern and legacy boards folders.

    Supported patterns:
    - ports/<port>/boards/<BOARD_ID>
    - <port>/boards/<BOARD_ID>   (older repo layout)
    """
    rows: list[tuple[str, ...]] = []

    candidate_port_dirs: list[Path] = []

    # Newer layout
    ports_dir = mpy_dir / "ports"
    if ports_dir.is_dir():
        candidate_port_dirs.extend([p for p in ports_dir.iterdir() if p.is_dir()])

    # Legacy layout: top-level port dirs directly under repo root
    for top_dir in mpy_dir.iterdir():
        if not top_dir.is_dir():
            continue
        if top_dir.name in {"ports", ".git"}:
            continue
        if (top_dir / "boards").is_dir():
            candidate_port_dirs.append(top_dir)

    seen_paths: set[str] = set()
    for port_dir in sorted(candidate_port_dirs, key=lambda p: p.name):
        boards_dir = port_dir / "boards"
        if not boards_dir.is_dir():
            continue

        for board_dir in sorted(boards_dir.iterdir(), key=lambda p: p.name):
            if not board_dir.is_dir():
                continue
            rel_path = _relative_repo_path(board_dir, mpy_dir)
            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)

            board_id = board_dir.name
            rows.append(
                (
                    version,
                    board_id,
                    board_id,
                    "",
                    "",
                    port_dir.name,
                    rel_path,
                    "",
                    "micropython",
                )
            )
    return rows


def _collect_rows_with_fallback(versions: Sequence[str], mpy_dir: Path) -> list[tuple[str, ...]]:
    """Collect board rows per version with legacy fallback for pre-1.18 tags."""
    all_rows: list[tuple[str, ...]] = []

    if not mpy_dir.is_dir():
        raise FileNotFoundError(f"MicroPython repository not found: {mpy_dir}")

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

        db = Database(mpy_dir)
        db_rows = list(iter_boards(db, version=version))

        if _is_legacy_version(version):
            fallback_rows = _rows_from_folder_layout(mpy_dir, version)
            if fallback_rows:
                log.info(f"Legacy fallback for {version}: using {len(fallback_rows)} boards from folder layout")
                all_rows.extend(fallback_rows)
                continue

        all_rows.extend(db_rows)

    return all_rows


def build_reporting_database(
    micropython_repo: Path,
    output_db: Path,
    min_version: str,
    include_preview: bool,
) -> Path:
    """Build a standalone reporting SQLite database from gather_boards logic.

    This does not touch mpflash.db. It reads boards by checking out tags in a local
    MicroPython repository, then stores raw rows and per-version aggregates in a
    separate SQLite file intended for reporting.
    """
    versions = micropython_versions(minver=min_version, cache_it=False)
    versions = sorted(set(versions), key=_version_sort_key)
    if not include_preview:
        versions = [version for version in versions if not version.endswith("preview")]

    if not versions:
        raise ValueError("No MicroPython versions found for the selected range.")

    log.info(f"Collecting board rows from {len(versions)} versions")
    rows = _collect_rows_with_fallback(versions=versions, mpy_dir=micropython_repo)
    stats = _collect_version_stats(rows=rows, versions=versions)

    _ensure_parent(output_db)
    with sqlite3.connect(output_db) as conn:
        _prepare_schema(conn)
        conn.executemany(
            """
            INSERT INTO board_rows (
                version, board_id, board_name, mcu, variant, port, path, description, family
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.executemany(
            """
            INSERT INTO version_stats (
                version_order, version, boards_found, board_variants_found, ports_found, total_rows
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            stats,
        )

        now_utc = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            [
                ("created_at_utc", now_utc),
                ("micropython_repo", str(micropython_repo.resolve())),
                ("min_version", min_version),
                ("include_preview", str(include_preview)),
                ("version_count", str(len(versions))),
                ("row_count", str(len(rows))),
            ],
        )

    log.info(f"Created reporting database: {output_db}")
    return output_db


@click.command()
@click.option(
    "--mpy-path",
    "mpy_path",
    type=click.Path(path_type=Path),
    default=Path("repos/micropython"),
    show_default=True,
    help="Path to local MicroPython repository.",
)
@click.option(
    "--output-db",
    "output_db",
    type=click.Path(path_type=Path),
    default=Path("reporting/micropython_boards_reporting.sqlite3"),
    show_default=True,
    help="Output path for the reporting SQLite database.",
)
@click.option(
    "--min-version",
    "min_version",
    default="0",
    show_default=True,
    help="Lowest version tag to include.",
)
@click.option(
    "--include-preview/--no-include-preview",
    "include_preview",
    default=True,
    show_default=True,
    help="Include preview tag(s) in the reporting database.",
)
def cli(mpy_path: Path, output_db: Path, min_version: str, include_preview: bool) -> None:
    build_reporting_database(
        micropython_repo=mpy_path,
        output_db=output_db,
        min_version=min_version,
        include_preview=include_preview,
    )


if __name__ == "__main__":
    cli()

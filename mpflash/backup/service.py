"""Backup and restore planning and execution.

Planning is separate from execution so ``mpflash restore --dry-run`` can run
every validation (bundle hashes, target identity, provider compatibility)
without modifying the device.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from mpflash.errors import MPFlashError
from mpflash.logger import log

from .base import BackupContext, BackupProvider
from .bundle import Bundle, BundleWriter, bundle_name
from .models import Artifact, ArtifactRole, ComponentKind, DeviceIdentity, Exactness, ProviderCapability
from .registry import capabilities_for, choose

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard

#: Raw flash replaces everything beneath it, so it goes first; files go last.
RESTORE_ORDER: Tuple[ComponentKind, ...] = (ComponentKind.FLASH, ComponentKind.ROMFS, ComponentKind.VFS)


@dataclass(frozen=True)
class BackupPlan:
    """The components that will be read and the provider that reads each."""

    device: DeviceIdentity
    selections: Tuple[Tuple[BackupProvider, ProviderCapability], ...]
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoreItem:
    """One component to restore with its artifacts and provider."""

    component: ComponentKind
    provider: BackupProvider
    artifacts: Tuple[Artifact, ...]


@dataclass(frozen=True)
class RestorePlan:
    """A fully validated restore, ready to show to the user or execute."""

    bundle: Bundle
    target: DeviceIdentity
    items: Tuple[RestoreItem, ...]
    lines: Tuple[str, ...]
    warnings: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def plan_backup(mcu: "MPRemoteBoard", components: Sequence[ComponentKind] = ()) -> BackupPlan:
    """Decide what to back up.

    With no explicit ``components`` only data that MPFlash can both read and
    restore is selected. An explicit component only needs to be readable, and
    the plan then records that it cannot be restored.
    """
    device = DeviceIdentity.from_mcu(mcu)
    available = capabilities_for(mcu)
    requested = list(dict.fromkeys(components))
    selections: List[Tuple[BackupProvider, ProviderCapability]] = []
    notes: List[str] = []

    if requested:
        for kind in requested:
            match = choose(available, kind, restore=False)
            if match is None:
                raise MPFlashError(
                    f"No backup provider can read {kind.value} from {device.port} {device.board_id}. {_describe_available(available)}"
                )
            if not match[1].can_restore:
                notes.append(f"{kind.value} was read by {match[0].name} but MPFlash cannot restore it to the device.")
            selections.append(match)
    else:
        for kind in ComponentKind:
            match = choose(available, kind, restore=True)
            if match is not None:
                selections.append(match)
            elif choose(available, kind, restore=False) is not None:
                notes.append(f"{kind.value} can be read but not restored, so it was skipped; request it with --component {kind.value}.")
        if not selections:
            raise MPFlashError(f"No backup provider supports {device.port} {device.board_id}. {_describe_available(available)}")

    selections.sort(key=lambda item: tuple(ComponentKind).index(item[1].component))
    return BackupPlan(device=device, selections=tuple(selections), notes=tuple(notes))


def run_backup(
    mcu: "MPRemoteBoard",
    plan: BackupPlan,
    output: Path,
    *,
    include_files: bool = False,
    now: Optional[datetime] = None,
) -> Path:
    """Execute ``plan`` and return the published bundle folder.

    Nothing is published unless every component succeeds.
    """
    notes = list(plan.notes)
    trees: List[str] = []
    with BundleWriter(output, bundle_name(plan.device, now=now)) as writer:
        context = BackupContext(writer=writer, include_files=include_files)
        for provider, capability in plan.selections:
            kind = capability.component
            before = len(writer.artifacts)
            log.info(f"Backing up {kind.value} with {provider.name}")
            try:
                result = provider.backup(mcu, kind, context)
            except (MPFlashError, OSError, ConnectionError) as error:
                raise MPFlashError(f"Backup of {kind.value} by {provider.name} failed: {error}. No backup was created.") from error
            _check_provider_output(provider, capability, writer.artifacts[before:])
            notes.extend(result.notes)
            if result.tree_text:
                trees.append(result.tree_text)
        return writer.commit(plan.device, tree_text="\n".join(trees), notes=notes)


def _check_provider_output(provider: BackupProvider, capability: ProviderCapability, produced: Sequence[Artifact]) -> None:
    """Reject providers that return artifacts claiming more than they declared."""
    primary = [artifact for artifact in produced if artifact.role is not ArtifactRole.REFERENCE]
    if not any(artifact.component is capability.component for artifact in primary):
        raise MPFlashError(f"Provider {provider.name!r} produced no {capability.component.value} artifact")
    for artifact in primary:
        if artifact.component is not capability.component:
            raise MPFlashError(
                f"Provider {provider.name!r} staged {artifact.component.value} while backing up {capability.component.value}"
            )
        if artifact.exactness is not capability.exactness:
            raise MPFlashError(
                f"Provider {provider.name!r} declared {capability.exactness.value} but staged {artifact.exactness.value} {artifact.path}"
            )
        if not set(artifact.covers) <= set(capability.covers):
            raise MPFlashError(f"Provider {provider.name!r} claimed coverage it did not declare for {artifact.path}")
        if not set(capability.exclusions) <= set(artifact.exclusions):
            raise MPFlashError(f"Provider {provider.name!r} omitted declared exclusions from {artifact.path}")


def _describe_available(available: Sequence[Tuple[BackupProvider, ProviderCapability]]) -> str:
    if not available:
        return "No backup providers are registered or available for this board."
    entries = sorted({f"{capability.component.value} via {provider.name}" for provider, capability in available})
    return "Available for this board: " + ", ".join(entries) + "."


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def plan_restore(bundle: Bundle, mcu: "MPRemoteBoard", components: Sequence[ComponentKind] = ()) -> RestorePlan:
    """Validate ``bundle`` against ``mcu`` and describe exactly what a restore would do.

    This verifies every artifact hash and asks each provider to check
    compatibility, but never modifies the device.
    """
    bundle.verify()
    target = DeviceIdentity.from_mcu(mcu)
    source = bundle.manifest.device
    problems = source.mismatches(target)
    if problems:
        raise MPFlashError("The bundle does not match the target board:\n  - " + "\n  - ".join(problems))
    warnings: List[str] = []
    if source.serial_number and target.serial_number and source.serial_number != target.serial_number:
        warnings.append("The bundle was made from a different physical board (serial number differs).")

    selected = _select_components(bundle, components, warnings)
    available = capabilities_for(mcu)
    items: List[RestoreItem] = []
    lines: List[str] = []
    for kind in selected:
        artifacts = tuple(artifact for artifact in bundle.manifest.artifacts if artifact.component is kind and artifact.restorable)
        match = choose(available, kind, restore=True, prefer=artifacts[0].provider)
        if match is None:
            raise MPFlashError(f"No provider can restore {kind.value} to {target.port} {target.board_id}. {_describe_available(available)}")
        provider = match[0]
        if any(artifact.exactness is Exactness.PARTIAL for artifact in artifacts):
            warnings.append(f"{kind.value} is a partial device read and may not reproduce every region of the original.")
        lines.extend(f"[{kind.value}] {line}" for line in provider.describe_restore(mcu, bundle, artifacts))
        items.append(RestoreItem(component=kind, provider=provider, artifacts=artifacts))

    return RestorePlan(bundle=bundle, target=target, items=tuple(items), lines=tuple(lines), warnings=tuple(warnings))


def _select_components(bundle: Bundle, requested: Sequence[ComponentKind], warnings: List[str]) -> List[ComponentKind]:
    """Resolve the components to restore, rejecting unsatisfiable or overlapping requests."""
    restorable: Dict[ComponentKind, List[Artifact]] = {}
    references = set()
    for artifact in bundle.manifest.artifacts:
        if artifact.restorable:
            restorable.setdefault(artifact.component, []).append(artifact)
        else:
            references.add(artifact.component)

    explicit = list(dict.fromkeys(requested))
    for kind in explicit:
        if kind not in restorable:
            hint = " It only holds a reference copy; use `mpflash flash` to install firmware." if kind in references else ""
            raise MPFlashError(f"The bundle has no restorable {kind.value} data.{hint}")
    chosen = explicit or [kind for kind in RESTORE_ORDER if kind in restorable]
    if not chosen:
        raise MPFlashError("The bundle contains nothing that can be restored.")

    covered = {inner for kind in chosen for artifact in restorable[kind] for inner in artifact.covers if inner in chosen}
    for covered_kind in sorted(covered, key=RESTORE_ORDER.index):
        if explicit:
            raise MPFlashError(
                f"Cannot restore {covered_kind.value} together with an image that already contains it; "
                "restore the image alone, or only the individual component."
            )
        warnings.append(f"{covered_kind.value} is part of the raw flash image and is not restored separately.")
        chosen.remove(covered_kind)
    return sorted(chosen, key=RESTORE_ORDER.index)


def run_restore(plan: RestorePlan, mcu: "MPRemoteBoard") -> Tuple[ComponentKind, ...]:
    """Execute a validated plan; failures report what was and was not restored."""
    done: List[ComponentKind] = []
    for position, item in enumerate(plan.items):
        log.info(f"Restoring {item.component.value} with {item.provider.name}")
        try:
            item.provider.restore(mcu, plan.bundle, item.artifacts)
        except (MPFlashError, OSError, ConnectionError) as error:
            pending = [entry.component.value for entry in plan.items[position:]]
            finished = [kind.value for kind in done] or ["nothing"]
            raise MPFlashError(
                f"Restore of {item.component.value} by {item.provider.name} failed: {error}. "
                f"Already restored: {', '.join(finished)}. Not completed: {', '.join(pending)}."
            ) from error
        done.append(item.component)
    return tuple(done)

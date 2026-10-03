"""Test doubles shared by the backup/restore tests."""

from typing import Any, List, Optional, Sequence

from mpflash.backup.base import BackupContext, BackupOutput, BackupProvider
from mpflash.backup.models import ArtifactRole, ComponentKind, Exactness, ProviderCapability
from mpflash.errors import MPFlashError

FLASH_SIZE = 16


def capability(
    component: ComponentKind,
    *,
    can_backup: bool = True,
    can_restore: bool = True,
    exactness: Optional[Exactness] = None,
    covers: Sequence[ComponentKind] = (),
    exclusions: Sequence[str] = (),
) -> ProviderCapability:
    default = Exactness.EXACT if component is ComponentKind.FLASH else Exactness.LOGICAL
    return ProviderCapability(
        component=component,
        can_backup=can_backup,
        can_restore=can_restore,
        exactness=exactness or default,
        covers=tuple(covers),
        exclusions=tuple(exclusions),
    )


class FakeProvider(BackupProvider):
    """Provider that stages small deterministic artifacts and records restores."""

    def __init__(
        self,
        capabilities: Sequence[ProviderCapability],
        *,
        name: str = "fake",
        priority: int = 0,
        fail_backup: bool = False,
        fail_restore: Optional[ComponentKind] = None,
        lie_exactness: bool = False,
        omit_exclusions: bool = False,
        skip_artifact: bool = False,
        reject_restore: bool = False,
    ):
        self.name = name
        self.priority = priority
        self._capabilities = list(capabilities)
        self.fail_backup = fail_backup
        self.fail_restore = fail_restore
        self.lie_exactness = lie_exactness
        self.omit_exclusions = omit_exclusions
        self.skip_artifact = skip_artifact
        self.reject_restore = reject_restore
        self.backed_up: List[ComponentKind] = []
        self.restored: List[ComponentKind] = []
        self.contexts: List[BackupContext] = []

    def capabilities(self, mcu: Any) -> Sequence[ProviderCapability]:
        return self._capabilities

    def backup(self, mcu: Any, component: ComponentKind, ctx: BackupContext) -> BackupOutput:
        if self.fail_backup:
            raise MPFlashError("device unreachable")
        self.contexts.append(ctx)
        self.backed_up.append(component)
        if self.skip_artifact:
            return BackupOutput()
        cap = next(item for item in self._capabilities if item.component is component)
        is_flash = component is ComponentKind.FLASH
        if component is ComponentKind.VFS and ctx.include_files:
            (ctx.writer.files_dir() / "main.py").write_text("print('hi')\n", encoding="utf-8")
        ctx.writer.add_artifact_bytes(
            f"{component.value}.bin",
            b"x" * FLASH_SIZE if is_flash else b"files",
            component=component,
            role=ArtifactRole.DEVICE_READ if is_flash else ArtifactRole.LOGICAL_FILES,
            exactness=Exactness.PARTIAL if self.lie_exactness else cap.exactness,
            provider=self.name,
            address=0 if is_flash else None,
            length=FLASH_SIZE if is_flash else None,
            covers=cap.covers,
            exclusions=() if self.omit_exclusions else cap.exclusions,
        )
        return BackupOutput(tree_text=f"tree of {component.value}", notes=(f"{component.value} note",))

    def describe_restore(self, mcu: Any, bundle: Any, artifacts: Sequence[Any]) -> Sequence[str]:
        if self.reject_restore:
            raise MPFlashError("flash size differs")
        return [f"write {artifact.path} ({artifact.size} bytes)" for artifact in artifacts]

    def restore(self, mcu: Any, bundle: Any, artifacts: Sequence[Any]) -> None:
        component = artifacts[0].component
        if self.fail_restore is component:
            raise MPFlashError("write error")
        self.restored.append(component)

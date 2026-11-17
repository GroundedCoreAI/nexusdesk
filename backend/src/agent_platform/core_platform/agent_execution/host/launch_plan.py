"""Provider-generated launch plan consumed by the Host/ProcessRunner seam."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SandboxLaunchPlan:
    """Server-owned argv/environment; clients never contribute either."""

    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    working_dir: Path | None = None
    container_name: str | None = None

    def __post_init__(self) -> None:
        if not self.argv or not all(isinstance(value, str) and value for value in self.argv):
            raise ValueError("launch plan requires a nonempty argv")
        if self.working_dir is not None and not isinstance(self.working_dir, Path):
            raise ValueError("launch plan working_dir must be a Path or None")

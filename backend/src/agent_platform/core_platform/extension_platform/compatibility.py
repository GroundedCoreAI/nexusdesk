"""Small, dependency-free compatibility helpers for extension manifests."""

import re
from dataclasses import dataclass
from functools import total_ordering

PLATFORM_VERSION = "0.1.0"
_VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
_CONSTRAINT_PATTERN = re.compile(r"^(?P<operator>\^|~|>=|<=|>|<|=)?\s*(?P<version>.+)$")


@total_ordering
@dataclass(frozen=True)
class SemanticVersion:
    """A SemVer value with ordering suitable for compatibility checks."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemanticVersion":
        match = _VERSION_PATTERN.fullmatch(value.strip())
        if match is None:
            raise ValueError(f"invalid semantic version: {value}")
        prerelease = tuple(
            int(part) if part.isdigit() else part
            for part in (match.group("pre") or "").split(".")
            if part
        )
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=prerelease,
        )

    def _compare(self, other: object) -> int:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if core != other_core:
            return (core > other_core) - (core < other_core)
        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if isinstance(left, int) and isinstance(right, int):
                return (left > right) - (left < right)
            if isinstance(left, int):
                return -1
            if isinstance(right, int):
                return 1
            return (left > right) - (left < right)
        return (len(self.prerelease) > len(other.prerelease)) - (
            len(self.prerelease) < len(other.prerelease)
        )

    def __lt__(self, other: object) -> bool:
        return self._compare(other) < 0

    def __eq__(self, other: object) -> bool:
        return self._compare(other) == 0


def version_satisfies(actual: str, requirement: str | None) -> bool:
    """Return whether a SemVer value satisfies a compact constraint expression.

    Supported operators are ``^``, ``~``, comparison operators, exact versions,
    and comma-separated AND expressions. This intentionally stays smaller than
    a package-manager resolver: extension dependencies are validated, not
    resolved from a remote catalog.
    """

    if requirement is None or not requirement.strip() or requirement.strip() == "*":
        return True
    actual_version = SemanticVersion.parse(actual)
    for expression in requirement.split(","):
        match = _CONSTRAINT_PATTERN.fullmatch(expression.strip())
        if match is None:
            raise ValueError(f"invalid version constraint: {requirement}")
        operator = match.group("operator") or "="
        expected = SemanticVersion.parse(match.group("version"))
        if operator == "^":
            upper = (
                SemanticVersion(expected.major + 1, 0, 0)
                if expected.major > 0
                else SemanticVersion(0, expected.minor + 1, 0)
                if expected.minor > 0
                else SemanticVersion(0, 0, expected.patch + 1)
            )
            satisfied = actual_version >= expected and actual_version < upper
        elif operator == "~":
            upper = SemanticVersion(expected.major, expected.minor + 1, 0)
            satisfied = actual_version >= expected and actual_version < upper
        elif operator == ">=":
            satisfied = actual_version >= expected
        elif operator == "<=":
            satisfied = actual_version <= expected
        elif operator == ">":
            satisfied = actual_version > expected
        elif operator == "<":
            satisfied = actual_version < expected
        else:
            satisfied = actual_version == expected
        if not satisfied:
            return False
    return True


def validate_constraint(requirement: str | None) -> None:
    """Validate a compatibility expression without comparing it to a version."""

    if requirement is None or not requirement.strip() or requirement.strip() == "*":
        return
    for expression in requirement.split(","):
        match = _CONSTRAINT_PATTERN.fullmatch(expression.strip())
        if match is None:
            raise ValueError(f"invalid version constraint: {requirement}")
        SemanticVersion.parse(match.group("version"))

"""Common Secret redaction for boundaries that can emit text (T-07/FR-3)."""

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy

PLACEHOLDER = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credential_ref",
        "private_key",
        "access_key",
        "secret_key",
        "bearer",
    }
)
_DEFAULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)


class SecretRedactor:
    def __init__(
        self,
        registered: Iterable[str] = (),
        *,
        patterns: Iterable[re.Pattern[str]] = (),
        max_depth: int = 6,
    ) -> None:
        self._registered = [value for value in registered if value]
        if max_depth < 1:
            raise ValueError("redaction max_depth must be positive")
        self._max_depth = max_depth
        self._patterns = _DEFAULT_PATTERNS + tuple(pattern for pattern in patterns if pattern)

    def redact_text(self, value: str, *, max_chars: int = 8192) -> str:
        if not isinstance(value, str):
            raise TypeError("redact_text requires a string")
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        result = value
        for secret in self._registered:
            result = result.replace(secret, PLACEHOLDER)
        for pattern in self._patterns:
            if pattern.groups:
                result = pattern.sub(lambda match: match.group(1) + PLACEHOLDER, result)
            else:
                result = pattern.sub(PLACEHOLDER, result)
        return result[:max_chars]

    def redact_structure(self, value, *, _depth: int = 0):
        if _depth >= self._max_depth:
            return PLACEHOLDER
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                    result[key] = PLACEHOLDER
                else:
                    result[key] = self.redact_structure(item, _depth=_depth + 1)
            return result
        if isinstance(value, list):
            return [self.redact_structure(item, _depth=_depth + 1) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_structure(item, _depth=_depth + 1) for item in value)
        if isinstance(value, str):
            return self.redact_text(value)
        return deepcopy(value)

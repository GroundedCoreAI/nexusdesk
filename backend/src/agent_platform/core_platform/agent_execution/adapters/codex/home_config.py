"""Key-free Codex ``config.toml`` for one Execution's private engine home.

P5/G6 renders only deployment-owned, non-secret provider metadata into the
per-Execution ``CODEX_HOME`` created by P3. The Broker secret (P6) is never
written here: ``env_key`` is the variable NAME the Host will bind, not a value.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ...contracts.config import CODEX_CREDENTIAL_ENV_KEYS
from ...workspace.execution_workdir import (
    WORKDIR_FS_FAILED,
    WorkdirOperationError,
    create_platform_file,
)

CONFIG_FILE_NAME = "config.toml"
WIRE_API = "responses"
_PROVIDER_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class CodexEngineHomeConfig:
    """Deployment-owned provider metadata; no credential value can enter it."""

    model: str
    model_provider: str
    base_url: str
    env_key: str

    def __post_init__(self) -> None:
        if not _MODEL_ID.fullmatch(self.model):
            raise ValueError("codex model must be a bounded identifier")
        if not _PROVIDER_ID.fullmatch(self.model_provider):
            raise ValueError("codex model provider must be a bounded identifier")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or any(ch.isspace() for ch in self.base_url):
            raise ValueError("codex base_url must be a bare https URL")
        if self.env_key not in CODEX_CREDENTIAL_ENV_KEYS:
            raise ValueError("codex credential env_key is not in the closed allowlist")

    def to_toml(self) -> str:
        """Render a key-free TOML document with TOML-safe quoted strings."""
        provider = json.dumps(self.model_provider)
        return "\n".join(
            (
                f"model = {json.dumps(self.model)}",
                f"model_provider = {provider}",
                "",
                f"[model_providers.{self.model_provider}]",
                f"name = {provider}",
                f"base_url = {json.dumps(self.base_url)}",
                f"env_key = {json.dumps(self.env_key)}",
                f"wire_api = {json.dumps(WIRE_API)}",
                "",
            )
        )


def write_private_engine_config(home: Path, config: CodexEngineHomeConfig) -> Path:
    """Write ``home/config.toml`` at 0600 through no-follow primitives.

    The caller passes the P3-verified private home. A planted symlink or a
    ownership/mode fault fails closed as a workspace error before the Host call.
    """
    dir_fd = -1
    try:
        dir_fd = os.open(str(home), os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        fd = create_platform_file(dir_fd, CONFIG_FILE_NAME)
        try:
            payload = config.to_toml().encode("utf-8")
            written = 0
            while written < len(payload):
                written += os.write(fd, payload[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        raise WorkdirOperationError(WORKDIR_FS_FAILED, CONFIG_FILE_NAME) from None
    finally:
        if dir_fd >= 0:
            os.close(dir_fd)
    return home / CONFIG_FILE_NAME

"""Execution credential encryption with AAD-style version binding (T-07).

Fernet encrypts the secret, while a per-binding HKDF key (credential id +
tenant + version) authenticates the context: decrypting with any other binding
derives a different key and fails as ``InvalidToken``. The installation key is
read from a deployment Secret path and is never generated, cached to disk, or
auto-created by runtime access (02 FR-1/FR-11).
"""

import base64
import hashlib
import json
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class ExecutionCredentialKeyError(RuntimeError):
    """The installation key is missing/unreadable; runtime access fails closed."""


class CredentialBindingMismatch(RuntimeError):
    """Ciphertext belongs to a different credential/tenant/version."""


class ExecutionCredentialVault:
    def __init__(self, key_file: Path) -> None:
        self._key_file = Path(key_file)
        self._master: bytes | None = None

    def _master_key(self) -> bytes:
        if self._master is not None:
            return self._master
        try:
            value = self._key_file.read_bytes()
        except OSError:
            raise ExecutionCredentialKeyError("execution_credential_key_unavailable") from None
        if not value:
            raise ExecutionCredentialKeyError("execution_credential_key_unavailable")
        self._master = value
        return value

    @staticmethod
    def _binding(credential_id: UUID, tenant_id: str, version: int) -> bytes:
        return f"{credential_id}:{tenant_id}:{version}".encode()

    def _fernet(self, credential_id: UUID, tenant_id: str, version: int) -> Fernet:
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=self._binding(credential_id, tenant_id, version),
        ).derive(self._master_key())
        return Fernet(base64.urlsafe_b64encode(derived))

    def key_version(self) -> str:
        return "k" + hashlib.sha256(self._master_key()).hexdigest()[:12]

    def encrypt(
        self, secret: str, *, credential_id: UUID, tenant_id: str, version: int
    ) -> tuple[str, str]:
        if not isinstance(secret, str) or not secret:
            raise ValueError("credential secret must be nonempty")
        ciphertext = self._fernet(credential_id, tenant_id, version).encrypt(
            json.dumps({"secret": secret}).encode()
        )
        return ciphertext.decode(), self.key_version()

    def decrypt(self, encrypted: str, *, credential_id: UUID, tenant_id: str, version: int) -> str:
        try:
            value = json.loads(
                self._fernet(credential_id, tenant_id, version).decrypt(encrypted.encode())
            )
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise CredentialBindingMismatch("execution_credential_decryption_failed") from None
        secret = value.get("secret") if isinstance(value, dict) else None
        if not isinstance(secret, str) or not secret:
            raise CredentialBindingMismatch("execution_credential_decryption_failed")
        return secret

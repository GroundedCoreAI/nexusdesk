"""Gateway contracts. Provider secrets are write-only and excluded from serialization."""

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

Operation = Literal["chat", "embed", "rerank", "transcribe", "synthesize", "recognize"]
OPERATIONS = ("chat", "embed", "rerank", "transcribe", "synthesize", "recognize")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


_CODEX_PROVIDER_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class Connection(Contract):
    name: str = Field(min_length=1, max_length=100)
    protocol: Literal["demo", "openai_compatible", "gateway_http"] = "demo"
    base_url: str = Field(default="", max_length=500)
    credential_ref: str | None = Field(default=None, pattern=r"^AGENT_MODEL_SECRET_[A-Z0-9_]+$")
    concurrency: int = Field(default=8, ge=1, le=64)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=8192, exclude=True)
    clear_api_key: bool = Field(default=False, exclude=True)
    # Codex CLI transport metadata (Q3). All four are optional and defaulted so
    # stored connection specs stay valid. ``execution_credential_ref`` is a UUID
    # *reference* into ``execution_credentials``, never a secret; it is distinct
    # from ``credential_ref`` above, which names an ``AGENT_MODEL_SECRET_*`` env
    # variable for the outbound Gateway client. The Codex CLI calls the resolved
    # upstream directly, so these describe that transport, not Gateway.invoke().
    execution_credential_ref: UUID | None = None
    codex_base_url: str | None = Field(default=None, max_length=500)
    codex_wire_api: Literal["responses", "chat"] | None = None
    codex_model_provider: str | None = Field(default=None, max_length=64)

    @field_validator("codex_base_url")
    @classmethod
    def codex_base_url_must_be_bare_https(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        try:
            _ = parsed.port  # malformed ports raise ValueError in urllib
        except ValueError:
            raise ValueError("codex_base_url must be a bare https URL") from None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ch.isspace() for ch in value)
        ):
            raise ValueError("codex_base_url must be a bare https URL")
        return value

    @field_validator("codex_model_provider")
    @classmethod
    def codex_model_provider_must_be_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _CODEX_PROVIDER_ID.fullmatch(value):
            raise ValueError("codex_model_provider must be a bounded provider identifier")
        return value


class Model(Contract):
    name: str = Field(min_length=1, max_length=100)
    connection_id: UUID
    model_name: str = Field(min_length=1, max_length=200)
    operations: list[Operation] = Field(min_length=1, max_length=6)
    tool_calling: bool = False
    embedding_dimension: int | None = Field(default=None, ge=1, le=8192)
    vector_space: str | None = Field(default=None, min_length=1, max_length=200)
    max_input_chars: int = Field(default=32000, ge=1, le=200000)
    max_batch: int = Field(default=32, ge=1, le=128)
    voices: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def embedding_contract(self):
        if "embed" in self.operations and (not self.embedding_dimension or not self.vector_space):
            raise ValueError("Embedding requires a fixed dimension and vector_space version")
        return self


class Parameters(Contract):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    thinking: Literal["enabled", "disabled"] | None = None


class Profile(Contract):
    name: str = Field(min_length=1, max_length=100)
    operation: Operation
    model_id: UUID
    fallback_model_ids: list[UUID] = Field(default_factory=list, max_length=2)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    retries: int = Field(default=0, ge=0, le=2)
    parameters: Parameters = Field(default_factory=Parameters)
    require_tools: bool = False

    @model_validator(mode="after")
    def parameters_match(self):
        if self.operation != "chat" and (
            self.parameters.model_dump(exclude_none=True) or self.require_tools
        ):
            raise ValueError("Chat parameters cannot be used for another operation")
        ids = [self.model_id, *self.fallback_model_ids]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate model route")
        return self


class Message(Contract):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(default="", max_length=200000)
    tool_call_id: str | None = None
    tool_calls: list[dict] = Field(default_factory=list, max_length=30)
    reasoning_content: str | None = Field(default=None, max_length=1_000_000)


class ChatRequest(Contract):
    operation: Literal["chat"] = "chat"
    messages: list[Message] = Field(min_length=1, max_length=200)
    tools: list[dict] = Field(default_factory=list, max_length=30)

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, tools):
        names = set()
        for tool in tools:
            function = tool.get("function", {})
            if tool.get("type") != "function" or not isinstance(function, dict):
                raise ValueError("Only function tools are supported")
            name = function.get("name")
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("Tool names must be unique nonempty strings")
            names.add(name)
            schema = function.get("parameters")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ValueError("Tool parameters require an object JSON Schema")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError:
                raise ValueError("Invalid tool parameters schema") from None
        return tools


class TextItem(Contract):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=200000)


class EmbedRequest(Contract):
    operation: Literal["embed"] = "embed"
    inputs: list[TextItem] = Field(min_length=1, max_length=128)


class RerankRequest(Contract):
    operation: Literal["rerank"] = "rerank"
    query: str = Field(min_length=1, max_length=10000)
    candidates: list[TextItem] = Field(min_length=1, max_length=128)
    top_n: int = Field(default=5, ge=1, le=128)


class ASRRequest(Contract):
    operation: Literal["transcribe"] = "transcribe"
    media_id: UUID
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


class TTSRequest(Contract):
    operation: Literal["synthesize"] = "synthesize"
    text: str = Field(min_length=1, max_length=4096)
    voice_id: str = Field(min_length=1, max_length=100)
    format: Literal["mp3", "wav"] = "mp3"


class PageInput(Contract):
    source_id: str = Field(min_length=1, max_length=100)
    media_id: UUID


class OCRRequest(Contract):
    operation: Literal["recognize"] = "recognize"
    pages: list[PageInput] = Field(min_length=1, max_length=32)


RequestPayload = Annotated[
    ChatRequest | EmbedRequest | RerankRequest | ASRRequest | TTSRequest | OCRRequest,
    Field(discriminator="operation"),
]


class Invocation(Contract):
    profile_id: UUID
    version: int = Field(ge=1)
    payload: RequestPayload


class Revision(Contract):
    revision: int = Field(ge=1)


class Rollback(Contract):
    version: int = Field(ge=1)


class Toggle(Revision):
    enabled: bool

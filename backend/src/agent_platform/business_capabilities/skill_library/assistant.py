"""Optional AI-assisted Skill draft generation through the Model Gateway."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_platform.core_platform.platform_services.model_gateway.contracts import (
    ChatRequest,
    Message,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError

from .models import SkillCategory, SkillDefinition


class GeneratedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    category: SkillCategory
    tags: list[str] = Field(default_factory=list, max_length=10)
    definition: SkillDefinition


SYSTEM_PROMPT = """You generate one NexusDesk Skill draft.
Return a single JSON object with exactly these keys:
name, description, category, tags, definition.
category is service, finance, sales, or general.
definition must use the v1 SkillDefinition shape and creation_mode="ai".
Never generate secrets, endpoint URLs, credentials, roles, or permission changes.
Use an empty model_profile_id and knowledge_base_ids when the deployment dependency is unknown."""


def _json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except ValueError:
        raise DomainError("skill_definition_invalid", 422) from None
    if not isinstance(value, dict):
        raise DomainError("skill_definition_invalid", 422)
    return value


async def generate_skill(
    *,
    tenant: str,
    actor: str,
    prompt: str,
    settings: Any,
    gateway: Any,
) -> dict[str, Any]:
    if not settings.skill_ai_generation_enabled or settings.skill_ai_profile_id is None:
        raise DomainError("skill_ai_generation_unavailable", 503)
    profile_id: UUID = settings.skill_ai_profile_id
    try:
        result = await gateway.invoke(
            tenant,
            profile_id,
            settings.skill_ai_profile_version,
            ChatRequest(
                messages=[
                    Message(role="system", content=SYSTEM_PROMPT),
                    Message(role="user", content=prompt.strip()),
                ]
            ),
            actor=actor,
        )
        raw = _json_object(str(result["payload"]["content"]))
        generated = GeneratedSkill.model_validate(raw)
    except DomainError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError):
        raise DomainError("skill_definition_invalid", 422) from None
    definition = generated.definition.model_copy(update={"creation_mode": "ai"})
    definition.creation_mode = "ai"
    return {
        "name": generated.name,
        "description": generated.description,
        "category": generated.category,
        "tags": generated.tags,
        "type": definition.type,
        "definition": definition.model_dump(mode="json", by_alias=True),
    }


__all__ = ["generate_skill"]

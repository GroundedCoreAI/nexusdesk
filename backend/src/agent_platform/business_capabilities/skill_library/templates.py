"""Code-owned Skill creation templates.

Templates are defaults, never customer records. They intentionally do not
resolve a model profile or knowledge base at catalogue time; readiness checks
require the author to select an available deployment dependency.
"""

from pydantic import BaseModel, ConfigDict, Field

from .models import SkillDefinition


class SkillTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    category: str
    type: str
    tags: list[str] = Field(default_factory=list)
    definition: SkillDefinition | None = None


TEMPLATES = (
    SkillTemplate(
        key="customer-info-extraction",
        name="Customer information extraction",
        description="Extract structured customer fields from unstructured service text.",
        category="service",
        type="instruction",
        tags=("extraction", "customer"),
        definition=SkillDefinition(
            creation_mode="template",
            type="instruction",
            instructions=(
                "Extract the customer name, phone number, and email from the supplied text. "
                "Return only fields that are explicitly present."
            ),
            parameters=[
                {
                    "name": "text",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "description": "Unstructured customer text",
                }
            ],
            output={
                "format": "json",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": ["string", "null"]},
                        "phone": {"type": ["string", "null"]},
                        "email": {"type": ["string", "null"]},
                    },
                    "required": ["name", "phone", "email"],
                    "additionalProperties": False,
                },
            },
        ),
    ),
    SkillTemplate(
        key="order-status-query",
        name="Order status query",
        description="Look up an order through a read-only business tool.",
        category="service",
        type="query",
        tags=("order", "query"),
        definition=SkillDefinition(
            creation_mode="template",
            type="query",
            instructions="Look up the requested order and summarize its current status.",
            parameters=[
                {
                    "name": "order_id",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "description": "Customer order identifier",
                }
            ],
            dependencies={"tool_names": ["order_lookup"]},
        ),
    ),
    SkillTemplate(
        key="knowledge-policy-answer",
        name="Policy answer",
        description="Answer from selected knowledge bases with retrieval evidence.",
        category="general",
        type="knowledge",
        tags=("knowledge", "policy"),
        definition=SkillDefinition(
            creation_mode="template",
            type="knowledge",
            instructions="Answer the question using only retrieved policy content.",
            parameters=[
                {
                    "name": "question",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "description": "Customer question",
                }
            ],
        ),
    ),
    SkillTemplate(
        key="handoff-to-human",
        name="Handoff to human",
        description="Validate a handoff request against the configured human queue.",
        category="service",
        type="handoff",
        tags=("handoff", "human"),
        definition=SkillDefinition(
            creation_mode="template",
            type="handoff",
            instructions="Hand off the conversation with a concise reason.",
            parameters=[
                {
                    "name": "reason",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "description": "Why a human is required",
                }
            ],
            dependencies={"handoff_queue": "customer-service"},
        ),
    ),
    SkillTemplate(
        key="expense-extraction",
        name="Expense extraction",
        description="Extract bounded finance fields from reimbursement text.",
        category="finance",
        type="instruction",
        tags=("finance", "extraction"),
        definition=SkillDefinition(
            creation_mode="template",
            type="instruction",
            instructions="Extract the amount, currency, date, and merchant when explicitly present.",
            parameters=[
                {
                    "name": "text",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "description": "Reimbursement document text",
                }
            ],
            output={
                "format": "json",
                "schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": ["number", "null"]},
                        "currency": {"type": ["string", "null"]},
                        "date": {"type": ["string", "null"]},
                        "merchant": {"type": ["string", "null"]},
                    },
                    "additionalProperties": False,
                },
            },
        ),
    ),
)


def get_template(key: str) -> SkillTemplate | None:
    return next((item for item in TEMPLATES if item.key == key), None)


def template_catalog(ai_generation_enabled: bool, ai_generation_reason: str | None) -> dict:
    return {
        "items": [item.model_dump(mode="json", by_alias=True) for item in TEMPLATES],
        "ai_generation_enabled": ai_generation_enabled,
        "ai_generation_reason": ai_generation_reason,
    }


__all__ = ["TEMPLATES", "SkillTemplate", "get_template", "template_catalog"]

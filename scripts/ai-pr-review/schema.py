"""Structured schemas for the AI PR review pipeline.

Two families of models live here:

- ``Policy`` / nested models: the trusted, deterministic policy loaded from
  ``.github/ai-review-policy.yml`` on the default branch. The LLM never sees
  write access to this; a PR cannot relax its own review by editing the file
  because the workflow checks out the default branch, not the PR head.
- ``ReviewResult`` / nested models: the structured output the LLM must
  produce. Every LLM response is validated against these models before the
  policy engine touches it (spec section 7 step 4 / 13.2).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Decision(StrEnum):
    """Final policy-engine verdict for one PR head SHA."""

    AUTO_APPROVE = "auto_approve"
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    BLOCK_FOR_FIX = "block_for_fix"


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """One concrete issue reported by the LLM.

    Display text is bilingual: ``title``/``recommendation`` are English,
    ``title_zh``/``recommendation_zh`` are Simplified Chinese. The published
    review keeps the two languages in separate sections — never mixed.
    """

    severity: Severity
    path: str = Field(description="Repo-relative file path the issue belongs to")
    line: int | None = Field(
        default=None,
        ge=1,
        description="Line number in the NEW version of the file, if known",
    )
    title: str = Field(description="Short title in English")
    title_zh: str = Field(description="Short title in Simplified Chinese")
    evidence: str = Field(description="Quoted code or concrete reasoning backing the finding")
    recommendation: str = Field(description="Suggested fix in English")
    recommendation_zh: str = Field(description="Suggested fix in Simplified Chinese")


class UncertainItem(BaseModel):
    """Something the model could not reliably judge; routes to humans."""

    path: str | None = None
    question: str = Field(description="Question for the human reviewer, in English")
    question_zh: str = Field(description="Question for the human reviewer, in Simplified Chinese")
    reason: str = Field(description="Why the model cannot judge, in English")
    reason_zh: str = Field(description="Why the model cannot judge, in Simplified Chinese")


class ReviewResult(BaseModel):
    """Validated LLM review output. Invalid output must never reach policy."""

    review_complete: bool = Field(
        description="True only if every changed file was actually reviewed"
    )
    summary_en: str = Field(description="Overall assessment in English")
    summary_zh: str = Field(description="Overall assessment in Simplified Chinese")
    findings: list[Finding] = Field(default_factory=list)
    uncertain: list[UncertainItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Policy file schema (.github/ai-review-policy.yml)
# ---------------------------------------------------------------------------


class BranchPolicy(BaseModel):
    auto_approve_targets: list[str] = Field(default_factory=list)
    never_auto_approve_targets: list[str] = Field(default_factory=list)


class ReviewLimits(BaseModel):
    max_changed_files: int = 20
    max_changed_lines: int = 400


class SeverityPolicy(BaseModel):
    critical: Literal["block_for_fix"] = "block_for_fix"
    high: Literal["require_human_review"] = "require_human_review"
    medium: Literal["require_human_review", "comment_only"] = "require_human_review"
    low: Literal["comment_only"] = "comment_only"
    uncertain: Literal["require_human_review"] = "require_human_review"


class FailurePolicy(BaseModel):
    invalid_output: Literal["require_human_review"] = "require_human_review"
    missing_context: Literal["require_human_review"] = "require_human_review"
    llm_timeout: Literal["require_human_review"] = "require_human_review"
    github_api_error: Literal["keep_blocked"] = "keep_blocked"
    stale_head_sha: Literal["rerun_review"] = "rerun_review"
    ci_failure: Literal["keep_blocked"] = "keep_blocked"


class ReviewPolicy(BaseModel):
    enabled: bool = True
    # Phase gate: the policy engine may compute AUTO_APPROVE, but an actual
    # APPROVE review is only submitted when this is true (spec Phase 3).
    # Phase 1 keeps it false: the bot only ever posts COMMENT reviews.
    auto_approve_enabled: bool = False
    require_complete_review: bool = True
    require_latest_head_sha: bool = True
    require_ci_success: bool = True
    limits: ReviewLimits = Field(default_factory=ReviewLimits)
    severity_policy: SeverityPolicy = Field(default_factory=SeverityPolicy)
    human_review_paths: list[str] = Field(default_factory=list)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)


class ChecksPolicy(BaseModel):
    # Phase gate for the "AI Review Policy" check run (spec Phase 3/4).
    # Phase 1 publishes reviews only and creates no check runs.
    enabled: bool = False
    ai_review_check_name: str = "AI Review Policy"
    required_ci_workflows: list[str] = Field(default_factory=list)
    require_latest_head_sha: bool = True


class ReviewOutputPolicy(BaseModel):
    publish_summary: bool = True
    publish_inline_comments: bool = True
    include_file_and_line: bool = True
    include_severity: bool = True
    include_evidence: bool = True
    include_recommendation: bool = True


class Policy(BaseModel):
    version: int = 1
    branches: BranchPolicy = Field(default_factory=BranchPolicy)
    review: ReviewPolicy = Field(default_factory=ReviewPolicy)
    checks: ChecksPolicy = Field(default_factory=ChecksPolicy)
    review_output: ReviewOutputPolicy = Field(default_factory=ReviewOutputPolicy)

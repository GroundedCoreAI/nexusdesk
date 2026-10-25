"""Deterministic approval policy (spec section 8).

The LLM only analyzes code; every approval decision is made here, from fixed
rules, the trusted policy file, and the validated LLM output. The LLM never
decides check-run state and never gets write access to GitHub.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fetch_pr_context import PRContext
from pydantic import ValidationError
from schema import Decision, Policy, ReviewResult, Severity


def _default_policy_path() -> Path:
    """Policy lives at the repo root; the job's working directory is scripts/ai-pr-review."""
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace) / ".github" / "ai-review-policy.yml"
    # Local fallback: this file is scripts/ai-pr-review/policy_engine.py.
    return Path(__file__).resolve().parents[2] / ".github" / "ai-review-policy.yml"


class PolicyError(RuntimeError):
    """Policy file missing or invalid — fail closed (require human)."""


def load_policy(path: Path | None = None) -> Policy:
    """Load the trusted policy from the checked-out default branch."""
    path = path or _default_policy_path()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PolicyError(f"cannot read policy file {path}: {exc}") from exc
    try:
        return Policy.model_validate(raw or {})
    except ValidationError as exc:
        raise PolicyError(f"invalid policy file {path}: {exc}") from exc


@dataclass
class PolicyVerdict:
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    human_review_paths_hit: list[str] = field(default_factory=list)


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def decide(ctx: PRContext, policy: Policy, review: ReviewResult) -> PolicyVerdict:
    """Apply the deterministic rules from spec section 8.2/8.3 in order."""
    reasons: list[str] = []

    # --- hard blockers: confirmed critical defects -------------------------
    critical = [f for f in review.findings if f.severity == Severity.CRITICAL]
    if critical:
        return PolicyVerdict(
            decision=Decision.BLOCK_FOR_FIX,
            reasons=[f"{len(critical)} critical finding(s) must be fixed before merge"],
        )

    # --- conditions that require a human ------------------------------------
    if ctx.base_ref in policy.branches.never_auto_approve_targets:
        reasons.append(f"target branch '{ctx.base_ref}' never allows auto-approval")

    limits = policy.review.limits
    if ctx.changed_files > limits.max_changed_files:
        reasons.append(f"changed files {ctx.changed_files} > limit {limits.max_changed_files}")
    if ctx.changed_lines > limits.max_changed_lines:
        reasons.append(f"changed lines {ctx.changed_lines} > limit {limits.max_changed_lines}")

    paths_hit = sorted(
        {f.path for f in ctx.reviewable_files if _matches_any(f.path, policy.review.human_review_paths)}
    )
    if paths_hit:
        reasons.append(f"touches human-review paths: {', '.join(paths_hit)}")

    if policy.review.require_complete_review:
        if not review.review_complete:
            reasons.append("LLM reported the review as incomplete")
        unreviewed = [f.path for f in ctx.files_without_patch]
        if unreviewed:
            reasons.append(f"files without reviewable patch: {', '.join(unreviewed)}")
        truncated = [f.path for f in ctx.reviewable_files if f.truncated]
        if truncated:
            reasons.append(f"files truncated in prompt: {', '.join(truncated)}")

    for sev in (Severity.HIGH, Severity.MEDIUM):
        hits = [f for f in review.findings if f.severity == sev]
        if hits and getattr(policy.review.severity_policy, sev.value) == "require_human_review":
            reasons.append(f"{len(hits)} {sev.value} finding(s) require human judgement")

    if review.uncertain:
        reasons.append(f"{len(review.uncertain)} uncertain item(s) require human judgement")

    if reasons:
        return PolicyVerdict(
            decision=Decision.REQUIRE_HUMAN_REVIEW,
            reasons=reasons,
            human_review_paths_hit=paths_hit,
        )

    if ctx.base_ref not in policy.branches.auto_approve_targets:
        return PolicyVerdict(
            decision=Decision.REQUIRE_HUMAN_REVIEW,
            reasons=[f"target branch '{ctx.base_ref}' is not in auto_approve_targets"],
        )

    return PolicyVerdict(decision=Decision.AUTO_APPROVE, reasons=["all auto-approve conditions met"])

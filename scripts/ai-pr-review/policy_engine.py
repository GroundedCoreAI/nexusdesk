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
from github_client import GitHubApiError, GitHubClient
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
class Reason:
    """One policy rationale, in both display languages (never mixed)."""

    zh: str
    en: str


@dataclass
class PolicyVerdict:
    decision: Decision
    reasons: list[Reason] = field(default_factory=list)
    human_review_paths_hit: list[str] = field(default_factory=list)


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def decide(ctx: PRContext, policy: Policy, review: ReviewResult) -> PolicyVerdict:
    """Apply the deterministic rules from spec section 8.2/8.3 in order."""
    reasons: list[Reason] = []

    # --- hard blockers: confirmed critical defects -------------------------
    critical = [f for f in review.findings if f.severity == Severity.CRITICAL]
    if critical:
        return PolicyVerdict(
            decision=Decision.BLOCK_FOR_FIX,
            reasons=[Reason(
                zh=f"存在 {len(critical)} 个必须修复的严重问题",
                en=f"{len(critical)} critical finding(s) must be fixed before merge",
            )],
        )

    # --- conditions that require a human ------------------------------------
    if ctx.base_ref in policy.branches.never_auto_approve_targets:
        reasons.append(Reason(
            zh=f"目标分支 {ctx.base_ref} 不允许自动批准",
            en=f"target branch '{ctx.base_ref}' never allows auto-approval",
        ))

    limits = policy.review.limits
    if ctx.changed_files > limits.max_changed_files:
        reasons.append(Reason(
            zh=f"变更文件数 {ctx.changed_files} 超过阈值 {limits.max_changed_files}",
            en=f"changed files {ctx.changed_files} > limit {limits.max_changed_files}",
        ))
    if ctx.changed_lines > limits.max_changed_lines:
        reasons.append(Reason(
            zh=f"变更行数 {ctx.changed_lines} 超过阈值 {limits.max_changed_lines}",
            en=f"changed lines {ctx.changed_lines} > limit {limits.max_changed_lines}",
        ))

    paths_hit = sorted(
        {f.path for f in ctx.reviewable_files if _matches_any(f.path, policy.review.human_review_paths)}
    )
    if paths_hit:
        joined = ", ".join(paths_hit)
        reasons.append(Reason(
            zh=f"命中必须人工审批的路径：{joined}",
            en=f"touches human-review paths: {joined}",
        ))

    if policy.review.require_complete_review:
        if not review.review_complete:
            reasons.append(Reason(
                zh="LLM 报告本次评审不完整",
                en="LLM reported the review as incomplete",
            ))
        unreviewed = [f.path for f in ctx.files_without_patch]
        if unreviewed:
            joined = ", ".join(unreviewed)
            reasons.append(Reason(
                zh=f"以下文件缺少可评审的 diff：{joined}",
                en=f"files without reviewable patch: {joined}",
            ))
        truncated = [f.path for f in ctx.reviewable_files if f.truncated]
        if truncated:
            joined = ", ".join(truncated)
            reasons.append(Reason(
                zh=f"以下文件在评审输入中被截断：{joined}",
                en=f"files truncated in prompt: {joined}",
            ))

    for sev in (Severity.HIGH, Severity.MEDIUM):
        hits = [f for f in review.findings if f.severity == sev]
        if hits and getattr(policy.review.severity_policy, sev.value) == "require_human_review":
            reasons.append(Reason(
                zh=f"存在 {len(hits)} 个 {sev.value} 级别问题，需要人工判断",
                en=f"{len(hits)} {sev.value} finding(s) require human judgement",
            ))

    if review.uncertain:
        reasons.append(Reason(
            zh=f"存在 {len(review.uncertain)} 个模型无法可靠判断的事项",
            en=f"{len(review.uncertain)} uncertain item(s) require human judgement",
        ))

    if reasons:
        return PolicyVerdict(
            decision=Decision.REQUIRE_HUMAN_REVIEW,
            reasons=reasons,
            human_review_paths_hit=paths_hit,
        )

    if ctx.base_ref not in policy.branches.auto_approve_targets:
        return PolicyVerdict(
            decision=Decision.REQUIRE_HUMAN_REVIEW,
            reasons=[Reason(
                zh=f"目标分支 {ctx.base_ref} 不在自动批准白名单中",
                en=f"target branch '{ctx.base_ref}' is not in auto_approve_targets",
            )],
        )

    return PolicyVerdict(
        decision=Decision.AUTO_APPROVE,
        reasons=[Reason(zh="满足全部自动批准条件", en="all auto-approve conditions met")],
    )


# ---------------------------------------------------------------------------
# Gate evaluation (spec 8.2 items 8/9/12): CI status and human approval.
# ---------------------------------------------------------------------------


@dataclass
class GateState:
    """What still blocks the AI Review Policy check from turning green."""

    awaiting: list[str] = field(default_factory=list)  # subset of {"ci", "human"}
    ci_passed: bool = True
    human_approved: bool = False


def ci_workflows_passed(client: GitHubClient, head_sha: str, required: list[str]) -> bool:
    """True iff every required CI workflow has a successful run on head_sha.

    Matches runs by workflow *name* (not filename) on the exact head SHA —
    a green run on any other commit proves nothing (spec section 11).
    """
    if not required:
        return True
    try:
        runs = client.list_workflow_runs(head_sha=head_sha, event="pull_request")
    except GitHubApiError:
        return False  # fail closed: unknown CI status never counts as passed
    latest_by_name: dict[str, dict] = {}
    for run in runs:  # API returns newest first
        latest_by_name.setdefault(run["name"], run)
    for name in required:
        run = latest_by_name.get(name)
        if run is None or run.get("status") != "completed" or run.get("conclusion") != "success":
            return False
    return True


def has_valid_human_approval(client: GitHubClient, ctx: PRContext) -> bool:
    """True iff a qualified human approved the current head SHA.

    Rules (spec 5.2): the AI App's own reviews never count; the PR author's
    reviews never count; only the *latest* review per reviewer matters (a
    later CHANGES_REQUESTED revokes an earlier APPROVED); the approval must
    be on the current head SHA and from someone with write access.
    """
    try:
        reviews = client.list_pr_reviews(ctx.number)
    except GitHubApiError:
        return False  # fail closed
    latest_by_user: dict[str, dict] = {}
    for rv in reviews:  # chronological order from the API
        user = rv.get("user") or {}
        if user.get("type") == "Bot":
            continue
        latest_by_user[user.get("login", "")] = rv
    for login, rv in latest_by_user.items():
        if not login or login == ctx.author:
            continue
        if rv.get("state") != "APPROVED" or rv.get("commit_id") != ctx.head_sha:
            continue
        try:
            if client.get_collaborator_permission(login) in ("admin", "write"):
                return True
        except GitHubApiError:
            continue
    return False


def evaluate_gate(client: GitHubClient, ctx: PRContext, policy: Policy, verdict: PolicyVerdict) -> GateState:
    """Combine the policy verdict with live CI and human-approval state."""
    gate = GateState()
    if verdict.decision == Decision.BLOCK_FOR_FIX:
        return gate  # failure is terminal until a new commit arrives

    if policy.review.require_ci_success:
        gate.ci_passed = ci_workflows_passed(client, ctx.head_sha, policy.checks.required_ci_workflows)
        if not gate.ci_passed:
            gate.awaiting.append("ci")

    if verdict.decision == Decision.REQUIRE_HUMAN_REVIEW:
        gate.human_approved = has_valid_human_approval(client, ctx)
        if not gate.human_approved:
            gate.awaiting.append("human")

    return gate

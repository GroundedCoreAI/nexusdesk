"""Publish the review to GitHub: PR review + optional inline comments.

Phase 1 behavior: only ever submits ``COMMENT`` reviews. Even when the policy
engine computes AUTO_APPROVE, an actual ``APPROVE`` is submitted only when
``policy.review.auto_approve_enabled`` is true (spec Phase 3 gate). The
review is always bound to the re-fetched PR head SHA.
"""

from __future__ import annotations

from fetch_pr_context import PRContext
from github_client import GitHubClient, UnprocessableEntity
from policy_engine import PolicyVerdict
from schema import Decision, Policy, ReviewResult

SEVERITY_BADGE = {
    "critical": "🔴 CRITICAL",
    "high": "🟠 HIGH",
    "medium": "🟡 MEDIUM",
    "low": "🔵 LOW",
}

DECISION_TEXT = {
    Decision.AUTO_APPROVE: "✅ 低风险，符合自动批准条件",
    Decision.REQUIRE_HUMAN_REVIEW: "👀 需要人工审批",
    Decision.BLOCK_FOR_FIX: "⛔ 存在必须修复的严重问题",
}


def build_summary_body(
    ctx: PRContext,
    review: ReviewResult,
    verdict: PolicyVerdict,
    policy: Policy,
    model: str,
) -> str:
    lines: list[str] = []
    lines.append("## 🤖 AI 代码评审")
    lines.append("")
    lines.append(f"**结论**：{DECISION_TEXT[verdict.decision]}")
    lines.append("")
    lines.append(review.summary)
    lines.append("")

    if verdict.reasons and verdict.decision != Decision.AUTO_APPROVE:
        lines.append("**判定依据**:")
        for reason in verdict.reasons:
            lines.append(f"- {reason}")
        lines.append("")

    if review.findings:
        lines.append(f"**发现 {len(review.findings)} 个问题**:")
        lines.append("")
        lines.append("| 级别 | 文件 | 问题 |")
        lines.append("|---|---|---|")
        for f in review.findings:
            loc = f.path
            if policy.review_output.include_file_and_line and f.line:
                loc = f"{f.path}:{f.line}"
            sev = SEVERITY_BADGE[f.severity.value] if policy.review_output.include_severity else ""
            lines.append(f"| {sev} | `{loc}` | {f.title} |")
        lines.append("")

    if review.uncertain:
        lines.append("**无法可靠判断（需人工确认）**:")
        for u in review.uncertain:
            loc = f" (`{u.path}`)" if u.path else ""
            lines.append(f"- {u.question}{loc} — {u.reason}")
        lines.append("")

    lines.append("---")
    lines.append(
        f"<sub>head `{ctx.head_sha[:10]}` · model `{model}` · policy v{policy.version} · "
        "本评审由 LLM 生成，仅供参考；审批决策由确定性策略引擎执行。</sub>"
    )
    return "\n".join(lines)


def build_inline_comments(review: ReviewResult, changed_paths: set[str]) -> list[dict]:
    """Inline comments for findings with a valid path+line.

    Only findings on changed files with a concrete new-side line number are
    eligible; the API rejects anything anchored outside the diff, in which
    case the caller falls back to a body-only review.
    """
    comments = []
    for f in review.findings:
        if f.line is None or f.path not in changed_paths:
            continue
        comments.append(
            {
                "path": f.path,
                "line": f.line,
                "side": "RIGHT",
                "body": (
                    f"**{SEVERITY_BADGE[f.severity.value]}** {f.title}\n\n"
                    f"{f.evidence}\n\n**建议**: {f.recommendation}"
                ),
            }
        )
    return comments


def publish_review(
    client: GitHubClient,
    ctx: PRContext,
    review: ReviewResult,
    verdict: PolicyVerdict,
    policy: Policy,
    model: str,
) -> None:
    body = build_summary_body(ctx, review, verdict, policy, model)

    # Phase gate: APPROVE only when the policy explicitly enables it.
    if verdict.decision == Decision.AUTO_APPROVE and policy.review.auto_approve_enabled:
        event = "APPROVE"
    else:
        event = "COMMENT"

    comments: list[dict] = []
    if policy.review_output.publish_inline_comments:
        comments = build_inline_comments(review, {f.path for f in ctx.reviewable_files})

    try:
        client.create_review(ctx.number, ctx.head_sha, event, body, comments or None)
    except UnprocessableEntity:
        # An inline comment anchor was invalid (line outside the diff). Retry
        # body-only rather than losing the whole review.
        client.create_review(ctx.number, ctx.head_sha, event, body)


def publish_failure_notice(client: GitHubClient, number: int, head_sha: str, reason: str) -> None:
    """Best-effort visible notice when the review itself cannot run."""
    body = (
        "## 🤖 AI 代码评审\n\n"
        f"⚠️ 自动评审未能完成：{reason}\n\n"
        "按评审规范，此 PR 需要**人工完整评审**作为兜底。\n\n"
        f"---\n<sub>head `{head_sha[:10]}`</sub>"
    )
    try:
        client.create_review(number, head_sha, "COMMENT", body)
    except Exception as exc:  # noqa: BLE001 - best-effort notice must not mask the original failure
        print(f"warning: failed to publish failure notice: {exc}")

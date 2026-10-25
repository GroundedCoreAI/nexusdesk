"""Publish the review to GitHub: PR review + optional inline comments.

All user-visible text is bilingual with **strictly separated sections**: one
Chinese block and one English block, never mixed within a sentence.

Approval rules (spec Phase 3): an ``APPROVE`` review is submitted only when
the caller passes ``event="APPROVE"`` — i.e. the policy engine decided
AUTO_APPROVE, the gate (CI / head SHA) is fully satisfied, and the policy
file has ``review.auto_approve_enabled: true``. The review is always bound
to the re-fetched PR head SHA.
"""

from __future__ import annotations

from fetch_pr_context import PRContext
from github_client import GitHubClient, UnprocessableEntity
from policy_engine import GateState, PolicyVerdict
from schema import Decision, Policy, ReviewResult

SEVERITY_BADGE = {
    "critical": "🔴 CRITICAL",
    "high": "🟠 HIGH",
    "medium": "🟡 MEDIUM",
    "low": "🔵 LOW",
}

DECISION_TEXT_ZH = {
    Decision.AUTO_APPROVE: "✅ 低风险，符合自动批准条件",
    Decision.REQUIRE_HUMAN_REVIEW: "👀 需要人工审批",
    Decision.BLOCK_FOR_FIX: "⛔ 存在必须修复的严重问题",
}

DECISION_TEXT_EN = {
    Decision.AUTO_APPROVE: "✅ Low risk; eligible for auto-approval",
    Decision.REQUIRE_HUMAN_REVIEW: "👀 Human review required",
    Decision.BLOCK_FOR_FIX: "⛔ Critical issues must be fixed",
}

GATE_TEXT = {
    "ci": ("等待必需 CI 检查通过", "waiting for required CI checks to pass"),
    "human": ("等待人工审批", "waiting for human approval"),
}


def _audit_footer(ctx: PRContext, policy: Policy, model: str) -> str:
    return (
        f"<sub>head `{ctx.head_sha[:10]}` · model `{model}` · policy v{policy.version} · "
        "AI-generated review; approval decisions are made by the deterministic policy engine.</sub>"
    )


def _findings_table_zh(review: ReviewResult, policy: Policy) -> list[str]:
    lines = [f"**发现 {len(review.findings)} 个问题**：", "", "| 级别 | 文件 | 问题 |", "|---|---|---|"]
    for f in review.findings:
        loc = f.path
        if policy.review_output.include_file_and_line and f.line:
            loc = f"{f.path}:{f.line}"
        sev = SEVERITY_BADGE[f.severity.value] if policy.review_output.include_severity else ""
        lines.append(f"| {sev} | `{loc}` | {f.title_zh} |")
    return lines


def _findings_table_en(review: ReviewResult, policy: Policy) -> list[str]:
    lines = [f"**{len(review.findings)} finding(s)**:", "", "| Severity | File | Issue |", "|---|---|---|"]
    for f in review.findings:
        loc = f.path
        if policy.review_output.include_file_and_line and f.line:
            loc = f"{f.path}:{f.line}"
        sev = SEVERITY_BADGE[f.severity.value] if policy.review_output.include_severity else ""
        lines.append(f"| {sev} | `{loc}` | {f.title} |")
    return lines


def build_summary_body(
    ctx: PRContext,
    review: ReviewResult,
    verdict: PolicyVerdict,
    gate: GateState,
    policy: Policy,
    model: str,
) -> str:
    lines: list[str] = ["## 🤖 AI 代码评审 / AI Code Review", ""]

    # ---------------- Chinese section ----------------
    lines.append("### 中文")
    lines.append("")
    lines.append(f"**结论**：{DECISION_TEXT_ZH[verdict.decision]}")
    if gate.awaiting and verdict.decision != Decision.BLOCK_FOR_FIX:
        waiting = "；".join(GATE_TEXT[a][0] for a in gate.awaiting)
        lines.append(f"**门禁状态**：{waiting}")
    lines.append("")
    lines.append(review.summary_zh)
    lines.append("")
    if verdict.reasons and verdict.decision != Decision.AUTO_APPROVE:
        lines.append("**判定依据**：")
        lines.extend(f"- {r.zh}" for r in verdict.reasons)
        lines.append("")
    if review.findings:
        lines.extend(_findings_table_zh(review, policy))
        lines.append("")
    if review.uncertain:
        lines.append("**无法可靠判断（需人工确认）**：")
        for u in review.uncertain:
            loc = f"（`{u.path}`）" if u.path else ""
            lines.append(f"- {u.question_zh}{loc}——{u.reason_zh}")
        lines.append("")

    # ---------------- English section ----------------
    lines.append("---")
    lines.append("")
    lines.append("### English")
    lines.append("")
    lines.append(f"**Verdict**: {DECISION_TEXT_EN[verdict.decision]}")
    if gate.awaiting and verdict.decision != Decision.BLOCK_FOR_FIX:
        waiting = "; ".join(GATE_TEXT[a][1] for a in gate.awaiting)
        lines.append(f"**Gate status**: {waiting}")
    lines.append("")
    lines.append(review.summary_en)
    lines.append("")
    if verdict.reasons and verdict.decision != Decision.AUTO_APPROVE:
        lines.append("**Policy rationale**:")
        lines.extend(f"- {r.en}" for r in verdict.reasons)
        lines.append("")
    if review.findings:
        lines.extend(_findings_table_en(review, policy))
        lines.append("")
    if review.uncertain:
        lines.append("**Uncertain items (need a human)**:")
        for u in review.uncertain:
            loc = f" (`{u.path}`)" if u.path else ""
            lines.append(f"- {u.question}{loc} — {u.reason}")
        lines.append("")

    lines.append("---")
    lines.append(_audit_footer(ctx, policy, model))
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
                    f"**{SEVERITY_BADGE[f.severity.value]}** {f.title_zh} / {f.title}\n\n"
                    f"{f.evidence}\n\n"
                    f"**建议**：{f.recommendation_zh}\n\n"
                    f"**Suggestion**: {f.recommendation}"
                ),
            }
        )
    return comments


def publish_review(
    client: GitHubClient,
    ctx: PRContext,
    review: ReviewResult,
    verdict: PolicyVerdict,
    gate: GateState,
    policy: Policy,
    model: str,
    event: str = "COMMENT",
) -> None:
    """Submit the PR review. ``event`` is APPROVE only when main.py has
    confirmed every auto-approve gate (spec 8.2)."""
    body = build_summary_body(ctx, review, verdict, gate, policy, model)

    comments: list[dict] = []
    if policy.review_output.publish_inline_comments:
        comments = build_inline_comments(review, {f.path for f in ctx.reviewable_files})

    try:
        client.create_review(ctx.number, ctx.head_sha, event, body, comments or None)
    except UnprocessableEntity:
        # An inline comment anchor was invalid (line outside the diff). Retry
        # body-only rather than losing the whole review.
        client.create_review(ctx.number, ctx.head_sha, event, body)


def build_approval_body(ctx: PRContext, policy: Policy, model: str) -> str:
    """Body for a standalone APPROVE submitted after pending gates clear."""
    return "\n".join([
        "## 🤖 AI 代码评审 / AI Code Review",
        "",
        "### 中文",
        "",
        "✅ 之前等待的门禁（CI / 人工审批）已全部满足，现按策略自动批准。",
        "",
        "### English",
        "",
        ("✅ All previously pending gates (CI / human approval) are now satisfied; "
         "approving automatically per policy."),
        "",
        "---",
        _audit_footer(ctx, policy, model),
    ])


def publish_failure_notice(client: GitHubClient, number: int, head_sha: str, reason: str) -> None:
    """Best-effort visible notice when the review itself cannot run."""
    body = (
        "## 🤖 AI 代码评审 / AI Code Review\n\n"
        "### 中文\n\n"
        f"⚠️ 自动评审未能完成：{reason}\n\n"
        "按评审规范，此 PR 需要**人工完整评审**作为兜底。\n\n"
        "### English\n\n"
        f"⚠️ The automated review could not complete: {reason}\n\n"
        "Per the review policy, this PR requires a **full human review** as the fallback.\n\n"
        f"---\n<sub>head `{head_sha[:10]}`</sub>"
    )
    try:
        client.create_review(number, head_sha, "COMMENT", body)
    except Exception as exc:  # noqa: BLE001 - best-effort notice must not mask the original failure
        print(f"warning: failed to publish failure notice: {exc}")

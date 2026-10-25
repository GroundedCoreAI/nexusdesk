"""Entry point: coordinate the AI PR review pipeline (spec section 7).

Runs inside privileged contexts (``pull_request_target`` etc.), so it must
never execute PR code — it only reads the PR via the GitHub API and treats
the diff as untrusted data for the LLM. Trusted code and policy come from the
checked-out default branch (the workflow guarantees this).

Event routing (spec section 5):

- ``pull_request_target`` (opened/reopened/synchronize/ready_for_review):
  full LLM review, then gate evaluation.
- ``pull_request_review`` (submitted): a human review may clear the
  REQUIRE_HUMAN_REVIEW gate. The AI App's own reviews are ignored to prevent
  self-triggered approval loops (spec 5.2).
- ``workflow_run`` (CI completed): a finished CI run may clear the
  awaiting-CI gate.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from check_run import read_check_run_state, upsert_check_run
from fetch_pr_context import fetch_pr_context
from github_client import GitHubClient
from llm_review import LLMError, review_with_llm
from policy_engine import (
    GateState,
    PolicyError,
    PolicyVerdict,
    Reason,
    decide,
    evaluate_gate,
    load_policy,
)
from publish_review import (
    build_approval_body,
    publish_failure_notice,
    publish_review,
)
from schema import Decision, Policy


class EventError(RuntimeError):
    pass


def _load_event() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise EventError("GITHUB_EVENT_PATH is not set")
    return json.loads(Path(event_path).read_text(encoding="utf-8"))


def run_full_review(client: GitHubClient, policy: Policy, number: int) -> None:
    """Full pipeline: fetch context, LLM review, decide, publish, set gate."""
    ctx = fetch_pr_context(client, number)
    print(f"PR #{number}: {ctx.title!r} base={ctx.base_ref} head={ctx.head_sha[:10]} "
          f"files={ctx.changed_files} lines={ctx.changed_lines}")

    if ctx.draft:
        print("PR is a draft; skipping review.")
        return

    try:
        review, model = review_with_llm(ctx)
    except LLMError as exc:
        # Fail closed: visible notice, human review required, check stays open.
        print(f"LLM review failed: {exc}", file=sys.stderr)
        publish_failure_notice(client, number, ctx.head_sha, str(exc)[:300])
        verdict = PolicyVerdict(
            decision=Decision.REQUIRE_HUMAN_REVIEW,
            reasons=[Reason(
                zh=f"LLM 评审失败：{str(exc)[:200]}",
                en=f"LLM review failed: {str(exc)[:200]}",
            )],
        )
        gate = GateState(awaiting=["human"], ci_passed=False, human_approved=False)
        upsert_check_run(client, ctx.head_sha, verdict, gate, policy, "LLM review failed; human review required.")
        return

    verdict = decide(ctx, policy, review)
    gate = evaluate_gate(client, ctx, policy, verdict)
    print(f"decision={verdict.decision.value} awaiting={gate.awaiting} "
          f"reasons={[r.en for r in verdict.reasons]}")

    # APPROVE only when every condition in spec 8.2 holds right now.
    can_approve = (
        verdict.decision == Decision.AUTO_APPROVE
        and not gate.awaiting
        and policy.review.auto_approve_enabled
    )
    publish_review(
        client, ctx, review, verdict, gate, policy, model,
        event="APPROVE" if can_approve else "COMMENT",
    )
    upsert_check_run(client, ctx.head_sha, verdict, gate, policy, review.summary_en, model)


def reevaluate_gate(client: GitHubClient, policy: Policy, number: int) -> None:
    """Re-check the gate after a human review or a completed CI run.

    Never calls the LLM: it reuses the decision stored in the check run. If
    no valid decision exists for the *current* head SHA, falls back to a full
    review instead of trusting stale state.
    """
    ctx = fetch_pr_context(client, number)
    if ctx.draft:
        print(f"PR #{number} is a draft; skipping gate re-evaluation.")
        return

    state = None
    if policy.checks.enabled:
        state = read_check_run_state(client, ctx.head_sha, policy.checks.ai_review_check_name)
    if state is None:
        print(f"PR #{number}: no stored decision for head {ctx.head_sha[:10]}; running full review.")
        run_full_review(client, policy, number)
        return

    if state.decision == Decision.BLOCK_FOR_FIX.value:
        print(f"PR #{number}: blocked on confirmed critical findings; a new commit is required.")
        return

    verdict = PolicyVerdict(decision=Decision(state.decision))
    gate = evaluate_gate(client, ctx, policy, verdict)
    print(f"PR #{number}: re-evaluated decision={state.decision} awaiting={gate.awaiting}")

    if gate.awaiting:
        upsert_check_run(client, ctx.head_sha, verdict, gate, policy,
                         "Gate still pending: " + ", ".join(gate.awaiting), state.model)
        return

    # All gates cleared.
    if verdict.decision == Decision.AUTO_APPROVE and policy.review.auto_approve_enabled:
        client.create_review(
            ctx.number, ctx.head_sha, "APPROVE",
            build_approval_body(ctx, policy, state.model),
        )
    upsert_check_run(client, ctx.head_sha, verdict, gate, policy,
                     "All gates satisfied.", state.model)


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise EventError("GITHUB_REPOSITORY is not set")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    payload = _load_event()

    # Trusted policy from the checked-out default branch (spec section 9).
    policy = load_policy()
    if not policy.review.enabled:
        print("AI review disabled by policy; exiting.")
        return 0

    with GitHubClient(repo) as client:
        if event_name == "pull_request_target":
            run_full_review(client, policy, int(payload["pull_request"]["number"]))

        elif event_name == "pull_request_review":
            review = payload.get("review") or {}
            user = review.get("user") or {}
            if user.get("type") == "Bot":
                # The AI App's own APPROVE/COMMENT must never retrigger the
                # pipeline — that would be a self-reinforcing approval loop.
                print(f"Ignoring bot review by {user.get('login')}; exiting.")
                return 0
            reevaluate_gate(client, policy, int(payload["pull_request"]["number"]))

        elif event_name == "workflow_run":
            run = payload.get("workflow_run") or {}
            prs = run.get("pull_requests") or []
            if not prs:
                # Cannot reliably associate the CI run with a PR: do nothing
                # (spec 6 item 10 — never approve on an unverified mapping).
                print("workflow_run has no associated pull requests; exiting.")
                return 0
            for pr in prs:
                reevaluate_gate(client, policy, int(pr["number"]))

        else:
            raise EventError(f"unsupported event: {event_name}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EventError, PolicyError) as exc:
        # Configuration/environment problems: fail the job loudly so they are
        # noticed, but never publish an approval.
        print(f"ai-pr-review: {exc}", file=sys.stderr)
        sys.exit(1)

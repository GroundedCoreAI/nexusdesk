"""Entry point: coordinate the AI PR review pipeline (spec section 7).

Runs inside the privileged ``pull_request_target`` context, so it must never
execute PR code — it only reads the PR via the GitHub API and treats the diff
as untrusted data for the LLM. Trusted code and policy come from the checked
out default branch (the workflow guarantees this).

Phase 1 scope (spec section 15): pull_request events only; publishes COMMENT
reviews and a summary; never approves, never blocks, creates no check runs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from check_run import upsert_check_run
from fetch_pr_context import fetch_pr_context
from github_client import GitHubClient
from llm_review import LLMError, review_with_llm
from policy_engine import PolicyError, decide, load_policy
from publish_review import publish_failure_notice, publish_review


class EventError(RuntimeError):
    pass


def _pr_number_from_event() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise EventError("GITHUB_EVENT_PATH is not set")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = payload.get("pull_request")
    if not pr:
        raise EventError(f"event '{os.environ.get('GITHUB_EVENT_NAME')}' has no pull_request payload")
    return int(pr["number"])


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise EventError("GITHUB_REPOSITORY is not set")

    number = _pr_number_from_event()

    # Trusted policy from the checked-out default branch (spec section 9).
    policy = load_policy()
    if not policy.review.enabled:
        print("AI review disabled by policy; exiting.")
        return 0

    with GitHubClient(repo) as client:
        ctx = fetch_pr_context(client, number)
        print(f"PR #{number}: {ctx.title!r} base={ctx.base_ref} head={ctx.head_sha[:10]} "
              f"files={ctx.changed_files} lines={ctx.changed_lines}")

        if ctx.draft:
            print("PR is a draft; skipping review.")
            return 0

        try:
            review, model = review_with_llm(ctx)
        except LLMError as exc:
            # Fail closed: no approval, a visible notice, human review required.
            print(f"LLM review failed: {exc}", file=sys.stderr)
            publish_failure_notice(client, number, ctx.head_sha, str(exc)[:300])
            return 0

        verdict = decide(ctx, policy, review)
        print(f"decision={verdict.decision.value} reasons={verdict.reasons}")

        publish_review(client, ctx, review, verdict, policy, model)
        upsert_check_run(client, ctx.head_sha, verdict, policy, review.summary)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EventError, PolicyError) as exc:
        # Configuration/environment problems: fail the job loudly so they are
        # noticed, but never publish an approval.
        print(f"ai-pr-review: {exc}", file=sys.stderr)
        sys.exit(1)

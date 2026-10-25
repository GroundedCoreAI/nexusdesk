"""Maintain the ``AI Review Policy`` check run (spec section 10).

Phase 1 does not create check runs (``checks.enabled: false`` in the policy);
this module exists so Phase 3/4 only needs a config flip. Key invariants
already implemented here:

- the check run is always created/updated on the re-fetched PR head SHA,
  never on ``GITHUB_SHA`` (``pull_request_target`` runs on the base branch);
- for a given head SHA an existing check run of the same name is updated
  instead of creating duplicates;
- the machine-readable decision is embedded in the check output for later
  ``pull_request_review`` / ``workflow_run`` re-evaluation.
"""

from __future__ import annotations

from github_client import GitHubClient
from policy_engine import PolicyVerdict
from schema import Decision, Policy

_STATUS_BY_DECISION = {
    # (status, conclusion)
    Decision.AUTO_APPROVE: ("completed", "success"),
    Decision.REQUIRE_HUMAN_REVIEW: ("in_progress", None),
    Decision.BLOCK_FOR_FIX: ("completed", "failure"),
}


def upsert_check_run(
    client: GitHubClient,
    head_sha: str,
    verdict: PolicyVerdict,
    policy: Policy,
    summary: str,
) -> None:
    if not policy.checks.enabled:
        return

    name = policy.checks.ai_review_check_name
    status, conclusion = _STATUS_BY_DECISION[verdict.decision]
    output = {
        "title": name,
        "summary": summary[:60000],
        # Machine-readable state for later re-evaluation events. Never put
        # secrets or tokens in here (spec section 7 step 6).
        "text": f"decision={verdict.decision.value}; policy_version={policy.version}; head_sha={head_sha}",
    }

    existing = client.list_check_runs(head_sha, check_name=name)
    if existing:
        client.update_check_run(
            existing[0]["id"],
            {"status": status, "conclusion": conclusion, "output": output},
        )
    else:
        payload = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
            "output": output,
        }
        if conclusion:
            payload["conclusion"] = conclusion
        client.create_check_run(payload)

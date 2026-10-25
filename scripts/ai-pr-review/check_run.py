"""Maintain the ``AI Review Policy`` check run (spec section 10).

Key invariants:

- the check run is always created/updated on the re-fetched PR head SHA,
  never on ``GITHUB_SHA`` (``pull_request_target`` runs on the base branch);
- for a given head SHA an existing check run of the same name is updated
  instead of creating duplicates;
- the decision is embedded in the check output in a machine-readable form so
  later ``pull_request_review`` / ``workflow_run`` events can re-evaluate the
  gate without calling the LLM again;
- a BLOCK_FOR_FIX failure is terminal for that head SHA: only a new commit
  (which triggers a fresh review on a new SHA) can clear it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from github_client import GitHubApiError, GitHubClient
from policy_engine import GateState, PolicyVerdict
from schema import Decision, Policy


@dataclass
class CheckState:
    """Machine-readable decision persisted in the check-run output."""

    decision: str  # Decision value
    awaiting: list[str] = field(default_factory=list)  # subset of {"ci", "human"}
    reviewed_sha: str = ""
    policy_version: int = 0
    model: str = ""


def format_state(state: CheckState) -> str:
    return (
        f"decision={state.decision}; awaiting={','.join(state.awaiting) or 'none'}; "
        f"reviewed_sha={state.reviewed_sha}; policy_version={state.policy_version}; "
        f"model={state.model or 'unknown'}"
    )


def parse_state(text: str) -> CheckState | None:
    """Parse a state line previously written by format_state."""
    values: dict[str, str] = {}
    for part in text.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            values[key.strip()] = value.strip()
    if "decision" not in values or "reviewed_sha" not in values:
        return None
    awaiting = values.get("awaiting", "none")
    return CheckState(
        decision=values["decision"],
        awaiting=[] if awaiting == "none" else [a for a in awaiting.split(",") if a],
        reviewed_sha=values["reviewed_sha"],
        policy_version=int(values.get("policy_version") or 0),
        model=values.get("model", ""),
    )


def read_check_run_state(client: GitHubClient, head_sha: str, check_name: str) -> CheckState | None:
    """Recover the stored decision for a head SHA, if a check run exists."""
    try:
        runs = client.list_check_runs(head_sha, check_name=check_name)
    except GitHubApiError:
        return None
    if not runs:
        return None
    text = ((runs[0].get("output") or {}).get("text")) or ""
    return parse_state(text)


def _status_conclusion(verdict: PolicyVerdict, gate: GateState) -> tuple[str, str | None]:
    if verdict.decision == Decision.BLOCK_FOR_FIX:
        return "completed", "failure"
    if gate.awaiting:
        return "in_progress", None
    return "completed", "success"


def upsert_check_run(
    client: GitHubClient,
    head_sha: str,
    verdict: PolicyVerdict,
    gate: GateState,
    policy: Policy,
    summary: str,
    model: str = "",
) -> None:
    """Create or update the AI Review Policy check run on ``head_sha``."""
    if not policy.checks.enabled:
        return

    name = policy.checks.ai_review_check_name
    status, conclusion = _status_conclusion(verdict, gate)
    state = CheckState(
        decision=verdict.decision.value,
        awaiting=gate.awaiting,
        reviewed_sha=head_sha,
        policy_version=policy.version,
        model=model,
    )
    output = {
        "title": name,
        "summary": summary[:60000],
        # Machine-readable state for later re-evaluation events. Never put
        # secrets or tokens in here (spec section 7 step 6).
        "text": format_state(state),
    }

    existing = client.list_check_runs(head_sha, check_name=name)
    if existing:
        # Always send conclusion (null clears it) so a completed check can
        # legitimately move back to in_progress when the gate re-opens.
        client.update_check_run(
            existing[0]["id"],
            {"status": status, "conclusion": conclusion, "output": output},
        )
    else:
        payload = {"name": name, "head_sha": head_sha, "status": status, "output": output}
        if conclusion:
            payload["conclusion"] = conclusion
        client.create_check_run(payload)

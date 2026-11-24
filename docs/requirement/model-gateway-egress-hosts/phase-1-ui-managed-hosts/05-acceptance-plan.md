# Phase 1 · UI-managed model egress hosts — Acceptance Plan

> Status: to be executed before release
> Created: 2026-11-24
> Basis: `01-business-goals.md` (G1..G4), `02-requirements.md` (AC-1..AC-8);
> execution evidence comes from `04-test-plan.md`

## 1. Scope and Responsibility

Confirm that the feature is correct in the default-off state and safe when
enabled: only public HTTPS hosts can be added, every change is audited, tenants
are isolated, and existing env-only deployments are unchanged.

Adopt the minimal core team: one acceptance owner, who may also execute. No
multi-role UAT or signature matrix.

Enabling UI-managed hosts in a shared or production deployment is an operator
decision, not an acceptance verdict. Phase acceptance does not authorize any
other high-risk capability.

## 2. Environment and Preconditions

| Environment | Use |
|---|---|
| Automated integration | AC and hard-gate evidence |
| Console test session | Visual/UX checks for the page and inline allow action |

**Preconditions**: all applicable `04-test-plan.md` cases pass; no open P0/P1;
use a dedicated tenant and test data.

## 3. Functional Acceptance (AC-1..AC-8)

| # | Step | Pass criteria | Evidence |
|---|---|---|---|
| A1 | Default deployment, admin opens 出站主机 | Page read-only with env hint; add/remove API disabled | P1-UT-07, P1-IT-07 |
| A2 | Enable switch, add `www.duckcoding.ai`, save/probe a channel using `https://www.duckcoding.ai/v1` | Add 201; channel save and probe succeed | P1-IT-01 |
| A3 | Try `http://...`, `127.0.0.1`, `localhost`, private-resolving name | Each rejected with its specific code; table unchanged | P1-UT-03..06 |
| A4 | Remove the host used by A2 | Save/probe fail with `model_address_not_allowed`; audit has removal | P1-IT-04 |
| A5 | Non-admin opens the page and calls the API | Nav hidden; API 403 | P1-IT-02 |
| A6 | Tenant A adds a host; Tenant B lists and uses it | B cannot see or use it | P1-IT-03 |
| A7 | Env baseline host with empty managed list | Allowed with the switch on and off | P1-IT-05 |
| A8 | Channel save blocked by the allowlist while the switch is on | Hint names the host; allow action succeeds; retry saves | P1-IT-01 + console check |

Each scenario records executor, date, environment, target SHA, preconditions,
actual result, verdict and evidence. Automated cases reference 06/CI; failures or
skips are not written as passing.

## 4. Key Manual Checks (max 3-5)

- The 出站主机 page clearly separates the deployment baseline from managed hosts
  and states whether management is enabled.
- The channel save error names the exact host and offers the allow action only to
  admins when management is enabled.
- Removing a host shows a confirmation that existing channels may stop working.

## 5. Security, Data and Release Hard Gates

| # | Check | Pass criteria and evidence |
|---|---|---|
| C1 | Default-off parity | Switch off: existing gateway/Codex/discovery suites pass unchanged; managed rows are not effective | 
| C2 | Public-only egress | Private/loopback/link-local/reserved/metadata/literal-IP/wildcard hosts rejected by automated tests |
| C3 | Tenant isolation and audit | Cross-tenant access impossible; audit rows contain tenant, actor, host and no secret |
| C4 | Migration and rollback | Additive migration upgrades and downgrades on a populated DB; code rollback leaves the table unused |

## 6. Pass Criteria and Record

- **Pass**: all applicable A/C have evidence, no open P0/P1.
- **Conditional pass**: only non-gate P2/P3 with owner and deadline, confirmed by
  the acceptance owner; security/data gaps cannot be waived.
- **Fail**: any applicable AC/gate fails, or a skip is recorded as a pass.

Output the Phase 1 acceptance report with scope/SHA, A/C verdicts and evidence,
residual items, conclusion and the record below.

| Acceptance owner | Executor | Date | Target SHA | Verdict | Evidence/Residual |
|---|---|---|---|---|---|
| TBD | TBD (may be the owner) | TBD | TBD | Pending | TBD |

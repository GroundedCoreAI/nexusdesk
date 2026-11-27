# Phase 1 · Skill Library Overview — Acceptance Plan

> Status: Pending implementation and verification.
> Created: 2026-11-26
> Basis: `01-business-goals.md` (G1–G3), `02-requirements.md` (AC-1–AC-7); execution follows `04-test-plan.md`.
> Revised: 2026-11-26 — Playwright coverage is required by the user and supplements static checks and manual browser evidence.

## 1. Scope and Responsibility

Acceptance verifies a correct, high-fidelity static overview, working local discovery, intact existing navigation, complete localization, and clean rollback. It does not authorize backend execution or any high-risk capability.

Use the minimum-core-team model: one acceptance owner may also execute checks. There is no independent UAT phase, multi-role responsibility table, or signature workflow. Developer self-checks establish requirement conformance, not independent business acceptance.

## 2. Environment and Preconditions

| Environment | Purpose |
|---|---|
| Local typecheck/i18n/build output | Static correctness evidence |
| Browser with local Vite page | AC-1 and AC-3–AC-7 manual evidence |
| Desktop/mobile screenshots | AC-2 and responsive visual evidence |

Preconditions: all applicable checks in `04-test-plan.md` pass or have an explicit accepted limitation, no P0/P1 remains, and only synthetic static data is used.

## 3. Functional Acceptance

| # | Steps | Pass criterion | Evidence |
|---|---|---|---|
| A1 | Open from Resource Center and directly via hash route | Both render the selected Skill overview | P1-IT-01 |
| A2 | Inspect desktop page against reference | Required regions/cards and visual language are materially aligned | P1-IT-02, P1-CM-05, screenshot |
| A3 | Search known/unknown terms and reset | Results, count, empty state, and recovery are correct | P1-IT-03 |
| A4 | Exercise category/status/sort/view | Deterministic local state and result changes | P1-IT-04 |
| A5 | Activate future actions | Honest feedback; no false mutation/navigation | P1-IT-05 |
| A6 | Inspect desktop and 390px widths | Usable reflow and no horizontal document overflow | P1-IT-06 |
| A7 | Run static checks and review existing navigation | Commands pass; existing route remains usable | P1-CM-01–04 |

Record executor, date, environment, target SHA, actual result, verdict, and evidence in `07-acceptance-report.md`; missing checks remain pending rather than passing.

## 4. Key Manual Checks

- **A2 visual review:** Compare the desktop screenshot to the supplied reference for structure, blue/white palette, card hierarchy, hero treatment, density, and right rail.
- **A6 narrow-screen review:** Confirm text is not clipped and primary controls remain understandable at 390px.

## 5. Safety, Data, and Release Gates

| # | Check | Pass criterion and evidence |
|---|---|---|
| C1 | Static-data and Secret boundary | No credentials, real customer data, new endpoint, or backend mutation; future actions are local |
| C2 | Compatibility and rollback | Existing navigation review passes; rollback needs no migration |

Performance, CI provenance, production telemetry, large-sample measurements are outside this phase gate.

## 6. Pass Standard and Single Acceptance Record

- **Pass:** A1–A7 and C1–C2 have passing evidence; no P0/P1 remains.
- **Conditional pass:** Only non-gate P2/P3 items remain, each with owner/deadline acknowledged below; visual or compatibility gaps cannot be waived.
- **Fail:** Any applicable AC/gate fails or skipped work is misreported as passed.

Produce `07-acceptance-report.md` only when the acceptance owner performs acceptance:

| Acceptance owner | Executor | Date | Target SHA | Conclusion | Evidence / leftovers |
|---|---|---|---|---|---|
| To be assigned | To be assigned (may be same) | Pending | Pending | Pending acceptance | Pending |

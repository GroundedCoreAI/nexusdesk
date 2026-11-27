# Phase 1 · Skill Library Overview — Test Plan

> Status: Completed; all applicable checks passed.
> Created: 2026-11-26
> Basis: `02-requirements.md` (FR-1–FR-4, AC-1–AC-7), `03-technical-design.md`.
> Revised: 2026-11-26 — Playwright coverage is required by the user and supplements static checks and visual screenshot review.

## 1. Scope and Principles

Scope covers the static catalog, route/sidebar/i18n wiring, responsive presentation, and preservation of existing behavior. Verification uses TypeScript, locale-key parity, production build, and manual browser inspection. Playwright browser tests are included for routes, interactions, responsive overflow, and screenshot evidence. Performance and CI provenance are not gates.

## 2. Environment and Fixtures

| Environment | Purpose |
|---|---|
| Local TypeScript/Vite tooling | Typecheck, locale validation, production build |
| Existing local Vite page in a browser | Route, interaction, responsive and visual inspection |
| Reference-size desktop 1672×944 and mobile 390×844 | Layout and overflow review |

Fixtures are the eight typed local Skill records. No DB, model, real customer data, credentials, or backend process is required.

## 3. Unit and Integration Tests

No separate unit-test runner is introduced. Playwright covers the browser integration cases below, with manual visual review of captured screenshots.

## 4. Browser Integration Checks

| ID | Case | Expected | Trace |
|---|---|---|---|
| P1-IT-01 | Playwright: sidebar navigation and direct `#/skills` load | Overview renders; Skill nav selected; deep-link survives reload | AC-1 |
| P1-IT-02 | Required overview content (Playwright + visual inspection) | Hero, category tabs, 4 metrics, popular/guide/resources, toolbar, and 8 cards are present | AC-2 |
| P1-IT-03 | Known and unknown search (Playwright) | Correct known result/count; empty state; reset restores list | AC-3 |
| P1-IT-04 | Category/status/sort/view controls (Playwright) | Deterministic filtered order/state and list/grid changes | AC-4 |
| P1-IT-05 | Future actions (Playwright) | Later-phase feedback is visible; no false success or route change | AC-5 |
| P1-IT-06 | Responsive viewport checks (Playwright + visual inspection) | No document horizontal overflow; primary content remains visible | AC-6 |

## 5. Common Checks

| ID | Check | Pass criterion |
|---|---|---|
| P1-CM-01 | Type safety | `npm run typecheck` exits zero |
| P1-CM-02 | Locale completeness | `npm run check:i18n` exits zero; visible copy uses `t()` |
| P1-CM-03 | Build | `npm run build` exits zero |
| P1-CM-04 | Existing navigation review | Diff keeps existing routes and Workflow/Connector placeholders intact |
| P1-CM-05 | Visual review | Actual browser screenshots inspected at desktop/mobile; major hierarchy, color, spacing, and card anatomy align with the reference |

## 6. Regression Scope

Review the final diff and manually visit at least one existing route. Confirm unrelated workspace modifications remain present. Playwright `skills.spec.ts` plus existing sidebar/hash-routing regression tests apply. No backend regression applies.

## 7. Defects and Exit Criteria

| Level | Definition | Handling |
|---|---|---|
| P0 | Existing application unusable or unrelated data/security impact | Must fix and recheck |
| P1 | Skill route, main render, build, or primary interaction broken | Must fix before delivery |
| P2 | Responsive or meaningful visual mismatch | Correct before visual delivery where practical; otherwise record owner/deadline |
| P3 | Minor copy or cosmetic issue | Record and schedule correction |

Exit requires all applicable checks green or explicitly recorded as not run, no open P0/P1, and an honest `06-test-report.md`. A skipped or unexecuted check is never recorded as passed.

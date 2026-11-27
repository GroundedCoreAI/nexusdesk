# Phase 2 · Skill Authoring, Testing, and Release Workflows — Business Goals

> Status: Planning approved; implementation in progress.
> Created: 2026-11-27
> Basis: user requirements 4–6, the supplied NexusDesk creation/detail references, and the Phase 1 catalog.
> Dependency: Phase 1 Skill Library Overview.

## Problems

### P1: The current Skill pages are presentation-only

The current creation and detail surfaces render useful shapes but do not close a business loop:

- `frontend/src/features/skills/CreateSkillPage.tsx` stores only local `step`, `tested`, and `published` state. Publishing ends with a static-success message and never creates a record.
- `frontend/src/features/skills/SkillDetailPage.tsx` uses fixed detail fixtures; Edit, Start Test, and Publish New Version are placeholders.
- `frontend/src/features/skills/SkillsPage.tsx` reads from a fixed in-memory catalog, so a created or published Skill cannot appear there.

The result is a believable demo but not a usable Skill lifecycle.

### P2: Complex Skill configuration has no settled interaction model

The current "Configure Capability" step exposes only name, description, category, runtime mode, and tags. AI, template, and professional creation modes all converge on the same minimal form. Users cannot express execution behavior, parameters, output shape, dependencies, permissions, or safety constraints.

Without a frozen editor contract, backend models, validation rules, and UI states would be designed independently and would drift.

### P3: Testing is not an executable workbench

The current test screen has a fixed question and a fixed success payload. It cannot accept user input, show running/failed states, retain history, or tie a successful run to the current draft revision. Publishing can therefore proceed even when no valid test exists.

### P4: Release management is only a visual list

The version tab displays fixed versions and the release button only switches tabs or shows a later-phase message. There is no draft/published separation, release readiness gate, immutable version creation, current-version update, or rollback.

## Business Goals

| Goal | Description |
|---|---|
| G1: Frozen authoring experience | AI, template, and professional creation modes lead into one coherent editor whose sections, validation, save state, and navigation are testable and backend-ready. |
| G2: Executable test workbench | Users can edit a structured test input, run a Skill test, inspect a result, and retain test history against the exact draft revision. |
| G3: Governed release lifecycle | A saved and successfully tested draft can become an immutable published version. Previous versions remain inspectable and can be rolled back without rewriting history. |
| G4: State integrity and honesty | Draft revisions, published versions, test runs, and UI status all refer to the same persisted Skill. No button may claim success before the backend confirms it. |

## Success Indicators

| Indicator | Baseline | Target |
|---|---|---|
| Frozen interaction coverage | Ad-hoc static screens | Every creation/editing/testing/release state and transition is documented with one unambiguous expected behavior |
| Dead-end lifecycle actions | Edit, test, and publish actions end in placeholder messages | Every lifecycle action maps to a defined state transition or an explicit read-only/disabled reason |
| Test-to-release gate | No relationship between test and publish | Publication requires a passing test for the latest saved draft revision |
| Release traceability | Static version list | Every published version has immutable identity, author, time, notes, and rollback lineage |

These indicators are functional correctness checks reused by later tests and acceptance; they are not separate business-UAT metrics.

## Scope

**Included**
- Freeze the UI interaction contract for:
  - Skill creation modes and handoff into the editor.
  - Complex Skill editor sections and draft behavior.
  - Test workbench input, run, result, history, and release-gate behavior.
  - Version readiness, publish confirmation, version history, and rollback.
- Define route ownership, loading/empty/error/permission states, responsive behavior, and accessibility expectations.
- Define the data and API semantics that the Phase 2 implementation must satisfy.

**Excluded from this documentation-freeze step**
- Backend implementation, database migration, runtime model invocation, and real connector execution; backend lifecycle implementation is planned for Phase 2 after review and confirmation.
- Batch test suites, regression datasets, automatic scoring, A/B testing, gradual rollout, scheduled releases, approval workflows, and multi-environment promotion.
- Marketplace publishing, category administration, billing, and cross-tenant sharing.
- Pixel-level redesign of the Phase 1 catalog or global console shell.
- Changes to the service-application Skill and release implementation unless a later design explicitly reuses it.

## Risks and Constraints

- **Draft versus live mutation:** Editing a published Skill must not mutate the live version. The UI must clearly separate draft revision from published version.
- **Test evidence drift:** A successful test is valid only for the exact saved draft revision. Any edit after the test marks the evidence stale and blocks release until retested.
- **Rollback semantics:** Rollback must create a new immutable version from an older snapshot rather than deleting or rewriting historical versions.
- **Static-data residue:** Existing demo fixtures must not be mistaken for API-backed state. The later implementation must label empty/loading/error states honestly.
- **Shell compatibility:** The existing 228px business sidebar, Skill header, responsive rules, and four-locale i18n contract remain unchanged.
- **Scope control:** Phase 2 should not become a general workflow builder or a full test-automation platform.

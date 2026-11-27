# NexusDesk Skill Capability Library · Phased Planning

> Status: Phase 1 implemented and verified; pending user acceptance. Phase 2 implementation complete and verification executed; pending user acceptance. Phase 3 packaging P0 (backend), P1 (frontend package management), and P2 (import a zip into a new Skill) implemented and verified; runtime mounting remains pending.
> Created: 2026-11-26
> Revised: 2026-11-27 (added Phase 3 packaging design; recorded Phase 3 P0 and P1 verification in `phase-3-skill-packaging/03-technical-design.md`)

## Background

`frontend/src/app/ConsoleSidebar.tsx` reserves a disabled **Skill 能力库** entry under Resource Center, while `frontend/src/app/hashRouter.ts` and `frontend/src/app/App.tsx` had no `skills` route or renderer. Phase 1 replaces that placeholder with a high-fidelity static catalog. The current creation and detail pages remain presentation-only: they use local state or fixed fixtures and cannot persist a draft, test against a saved revision, publish an immutable version, or roll back.

Phase 2 plans the complete authoring, testing, and release lifecycle. Its design uses a new global Skill domain instead of extending the application-owned `service_application_skills` tables, so a Skill has a stable identity independent of one service application.

## Principles

1. Reuse the React 19, TypeScript, Ant Design, hash-router, and i18n foundations. Phase 1 adds no backend dependency; Phase 2 reuses the existing backend persistence, scope, permission, model-gateway, retrieval, and tool-gateway foundations without a new component library or intermediary.
2. Deliver independent value in each phase; Phase 1 is a complete browsable static catalog, not a non-functional mock route.
3. Preserve the existing routes, 228px console shell, and unrelated uncommitted workspace changes.
4. Keep all user-visible copy in every supported locale. Phase 1 labels its static data honestly; Phase 2 uses API-confirmed state and never substitutes fixture success for a mutation.

## Roadmap

| Phase | Topic | Value | Difficulty | Directory |
|---|---|---|---|---|
| Phase 1 | Skill library overview | Discover, search, filter, and inspect the static Skill catalog | Low | [phase-1-library-overview/](phase-1-library-overview/) |
| Phase 2 | Authoring, testing, and release | Persisted draft, shared complex editor, revision-bound test workbench, readiness, immutable publishing, and rollback | Medium | [phase-2-authoring-test-release/](phase-2-authoring-test-release/) — **Implementation complete; verification executed; acceptance pending** |
| Phase 3 | Packaging and artefact storage | Verified zip ingestion, digest-addressed object storage, draft and version binding, weight/scope derivation, and an upload/attach surface in the editor | Medium | [phase-3-skill-packaging/](phase-3-skill-packaging/) — **P0 (backend), P1 (frontend management), and P2 (zip import) implemented; runtime mounting pending** |

Each phase uses the standard `01`–`08` document sequence. Test reports are written after verification occurs; acceptance reports are written only after user acceptance.

## Overall Boundaries

- No authorization administration, template marketplace, or independent category-management pages. Phase 3 adds verified artefact ingestion from an uploaded archive; it does not add marketplace distribution, public sharing, or remote fetch.
- Phase 1 has no backend API, persistence, model invocation, real Skill execution, or release operation.
- Phase 2 adds the planned global Skill persistence and lifecycle APIs. Runtime Analytics remains an honest empty state until a separate aggregation design exists; this is not permission to fabricate metrics.
- Phase 3 stores a package but does not execute it. Script execution stays behind the existing untrusted-code gate and requires the Docker sandbox provider.
- Phase 2 does not retrofit or replace the application-owned `service_application_skills` and `service_application_versions` implementation. Cross-domain integration into Agent or application snapshots is a later phase.
- No changes to existing service-application Skills tabs beyond navigation to the new catalog when explicitly in scope.

## Review Guide

Review Phase 1 for reference fidelity, route/sidebar integration, complete localization, static-data honesty, responsive behavior, and isolation from unrelated work.

Review Phase 2 for the frozen UI transition contract (`00-ui-interaction-freeze.md`), the global-domain architecture decision, `0076_skill_library` as an additive migration on top of the existing `0075_gateway_allowed_hosts` graph, revision-bound test evidence, immutable version and rollback semantics, permission mapping, safe default-off switches, four-locale coverage, and preservation of the existing 228px console shell and application-owned Skill paths.

Review Phase 3 for the separation of artefact, definition, and runtime; the complete rejection policy in `importing.py`; digest-addressed object keys; the rule that attaching a package recomputes weight and data scope while a draft save must not downgrade it; the `skill_s3_*` → `knowledge_s3_*` configuration fallback; the upload-is-attach decision and its client-side guard; the import-as-create endpoint and the fourth mode card that calls it; the read-only detail panel; and the explicit statement that packaging does not imply execution.


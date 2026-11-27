# Phase 1 · Skill Library Overview — Technical Design

> Status: Implemented and verified; pending user acceptance.
> Created: 2026-11-26
> Basis: Inspected `App.tsx`, `ConsoleSidebar.tsx`, `hashRouter.ts`, global styles, locale files, and Playwright sidebar tests on 2026-11-26.
> Revised: 2026-11-26 — Reference-fidelity pass uses cropped user-supplied illustration/icon assets, a 228px desktop sidebar, 366px right rail, and viewport-aligned card spacing.

## Change Overview

| Layer | File | Change |
|---|---|---|
| New feature | `frontend/src/features/skills/SkillsPage.tsx` | Typed static catalog, local discovery state, overview sections, and future-action feedback |
| New feature styles | `frontend/src/features/skills/skills.css` | Skill-scoped high-fidelity layout, visual tokens, responsive rules, and CSS/icon hero composition |
| Route | `frontend/src/app/hashRouter.ts` | Add `skills` to recognized top-level pages |
| App wiring | `frontend/src/app/App.tsx` | Add title/description, lazy page import, and `skills` renderer |
| Sidebar | `frontend/src/app/ConsoleSidebar.tsx` | Replace planned `skills` leaf with navigable leaf in Resource Center |
| Tests | `frontend/tests/skills.spec.ts` | Route, content, discovery interactions, future-action feedback, responsive overflow, and visual screenshots |
| Regression | `frontend/tests/sidebar.spec.ts` | Skill Library is enabled; Workflow and Connector remain disabled placeholders |
| i18n | `frontend/src/i18n/locales/{en,hi,zh-CN,zh-TW}.json` | Add matching keys for all new visible copy |

No migration, backend file, API client, dependency, deployment, or environment configuration changes.

## Data Model

A local exported-or-internal `SkillCatalogItem` union-backed interface contains `id`, localized name/description keys, category, status, usage, rating, icon variant, and tags. Static summary values reproduce the reference: total 271, published 243, in use 228, average rating 4.7; visible cards include customer intent recognition, order information query, invoice extraction, sales analysis, refund policy answers, customer profile analysis, code assistant, and task-flow recommendations.

Counts in category tabs and summary cards are reference-level catalog metrics, while the toolbar result count describes the eight loaded representative cards. Labels make that distinction clear and avoid deriving contradictory totals from partial static data.

## Core Flow

### Navigation and rendering

```text
Resource Center > Skill Library
  -> router.navigate('/skills')
  -> normalizeRoute recognizes '/skills'
  -> App renders lazy SkillsPage inside existing shell
  -> sidebar marks skills selected and expands resources
```

### Local discovery

```text
search + category + status + sort + view mode (React state)
  -> case-insensitive localized name/description/tag match
  -> category/status predicates
  -> latest/rating/usage comparator
  -> accessible grid or list of filtered items
  -> empty state + reset when result count is zero
```

### Visual composition

Use existing `ConsoleSidebar` and console header. `SkillsPage` owns a pale blue-gray content canvas, compact title/hero, rounded category tabs, summary/right-rail grid, white filter/card surfaces, blue/teal/purple/orange icon tiles, status pills, star ratings, and cropped illustration and icon assets from the user-supplied reference, stored locally under `frontend/public/assets/skills/`. No remote image or base64 fixture is required.

Skill-specific selectors are rooted at `.skills-page`; App adds `skills-shell` only if necessary to scope the content background. Existing `.console-*` selectors are not broadly rewritten.

## Configuration

None. Static values are code fixtures, not secrets or environment-specific endpoints.

## Test Summary

| Layer | Coverage |
|---|---|
| Static checks | TypeScript, i18n key parity, production build |
| Playwright | Route/deep-link, reference sections, search/filter/sort/view, feedback, responsive overflow, and screenshots |
| Manual visual review | Reference-size 1672×944 desktop and 390px mobile screenshots |

## Release and Rollback

The page is additive and requires no migration or feature flag. Rollback removes the route/page wiring and restores the disabled sidebar leaf; there is no persisted data or backend side effect. Existing uncommitted files are edited surgically and must not be reset or overwritten wholesale.


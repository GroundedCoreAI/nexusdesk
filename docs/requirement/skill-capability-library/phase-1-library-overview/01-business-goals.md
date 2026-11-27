# Phase 1 · Skill Library Overview — Business Goals

> Status: Implemented and verified; pending user acceptance.
> Created: 2026-11-26
> Basis: User-supplied NexusDesk Skill library reference and current frontend placeholder.

## Problems

### P1: Reserved navigation has no destination

The `skills` item is rendered as `planned` and disabled in `frontend/src/app/ConsoleSidebar.tsx`. Users cannot enter the Skill library from Resource Center.

### P2: No unified catalog experience

The application has service-app-specific Skill controls but no product-level page for understanding available capabilities, categories, publication status, usage, ratings, or popular Skills. The new page must establish the shared visual and information architecture before lifecycle pages are added.

## Business Goals

| Goal | Description |
|---|---|
| G1: Working catalog entry | Resource Center opens a real `#/skills` page without disturbing existing navigation. |
| G2: High-fidelity product overview | The page closely follows the supplied reference: dark-blue shell, pale blue-gray canvas, hero, category tabs, metric cards, Skill cards, and right-hand guidance panels. |
| G3: Useful static discovery | Search, category/status/sort filters, and card/list view operate on local static data with accurate result counts and empty states. |

## Success Indicators

| Indicator | Baseline | Target |
|---|---|---|
| Skill route availability | Disabled placeholder; no route | `#/skills` renders the catalog and selects the sidebar item |
| Reference regions | Absent | All specified overview regions are visible and visually coherent at desktop size |
| Discovery behavior | Absent | Local filters produce deterministic results and a recovery path from empty state |

These are functional correctness checks reused by tests and acceptance, not separate business-UAT metrics.

## Scope

**Included**
- Static Skill overview at `#/skills`, route registration, sidebar activation, responsive CSS, four-locale copy, and Playwright coverage.
- Eight representative Skill cards plus summary metrics, popular Skills, guidance, related resources, search/filter/sort, and grid/list switch.
- Local UI feedback for actions whose destinations belong to later phases.

**Excluded**
- Skill detail, create, editor, test workbench, release management, backend integration, authentication changes, analytics, template market, and category administration.

## Risks and Constraints

- **Reference versus existing shell:** Existing global CSS is intentionally reused; Skill-scoped selectors provide the pale canvas and blue accents without retheming unrelated pages.
- **Dense interface:** Desktop uses a main content/right rail grid; smaller widths collapse the rail and Skill grid without horizontal page overflow.
- **Static-data honesty:** No control implies a backend mutation or completed creation/navigation that does not exist.
- **Compatibility:** Existing routes, API contracts, service-app Skill features, and user changes remain untouched except for additive route and navigation wiring.

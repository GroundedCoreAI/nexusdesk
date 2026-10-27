# 05. Migration Plan

## Order of execution

1. Freeze the target directories and dependency boundaries.
2. Move Core Platform code.
3. Move Extension Contracts.
4. Move Business Capabilities.
5. Move Applications, workers, and initialization scripts.
6. Repair all imports with longest-prefix-first replacement.
7. Remove empty legacy directories instead of retaining compatibility layers.
8. Update architecture tests and static gates.
9. Update `/docs` operational guides and architecture links.
10. Run backend, frontend, and PostgreSQL regression checks.

## Completed so far

- The four main directories have been created.
- The main platform, business, and application code has been physically migrated.
- The old `modules`, `apps`, `integrations`, and `platform` directories have been removed from the working tree.
- Main runtime imports have been switched to the new namespaces.
- External plugins, capabilities, and UI extensions remain within the new extension boundaries. The sample implementation is under `business_capabilities/sample_operations`; no separate top-level `extensions/` directory is retained.

## Current close-out work

- Remove legacy paths from documentation.
- Fix historical path assumptions in architecture tests.
- Run complete import, Ruff, pytest, and frontend-build validation.
- Record actual failing cases; directory movement alone does not mean the refactor is complete.

## Operating constraints

- Do not run `git reset` or `git clean`.
- Do not overwrite existing uncommitted user changes.
- Do not add database tables or migrations for directory movement.
- Do not expand into a plugin marketplace, SDK ecosystem, or new business feature.

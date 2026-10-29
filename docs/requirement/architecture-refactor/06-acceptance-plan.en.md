# 06. Acceptance Plan

## A. Directory acceptance

- [x] `core_platform/`, `extension_contracts/`, `business_capabilities/`, and `applications/` exist.
- [x] `modules/`, `apps/`, `integrations/`, and `platform/` no longer exist as runtime directories.
- [x] Moved Python packages contain the required `__init__.py` files.

## B. Namespace acceptance

- [x] Runtime code no longer imports legacy module namespaces.
- [x] Runtime code no longer imports legacy application namespaces.
- [x] Runtime code no longer imports legacy integration namespaces.
- [x] Runtime code no longer imports legacy contract namespaces.
- [x] Legacy paths in documentation appear only in migration or historical notes.

## C. Architecture-boundary acceptance

- [x] Contracts do not depend on business implementations or Applications.
- [x] Core Platform does not depend on an Application composition root.
- [x] Business Capabilities do not depend on Application routes or startup code.
- [x] Applications compose the system without owning platform or domain implementations.
- [x] The architecture gate passes.

## D. Code and test acceptance

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
```

Frontend:

```powershell
cd frontend
npm run typecheck
npm run check:i18n
npm run build
```

## E. Database acceptance

Use the existing PostgreSQL instance with a dedicated test database:

```powershell
python -m alembic upgrade head
python -m pytest -q -m postgres
```

The directory refactor must not create undocumented database changes.

## F. Documentation acceptance

```powershell
rg "agent_platform\.(modules|apps|integrations|contracts|platform)" docs
```

Matches may remain only in migration maps and historical notes, never in current commands or valid runtime paths.

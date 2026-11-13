# NexusDesk Service Application Platform v2 · Phased Planning

> Status: Phase 1 implementation has landed across contracts, backend, frontend and migration; targeted tests and static gates pass, while full CI, empty-volume quickstart validation and manual UAT remain pending
> Created: 2026-11-11
> Basis: code review of the existing `service_apps` / `scenarios` / `providers` / `industry_packs` / `channels` implementation (`feat/customer-service-optimization`, migrations through `0057_industry_pack_runtime`) and the confirmed product decisions

## Background

The current product adds a service-application layer above Agents, but that layer still mixes two models:

1. The v1 `service_applications` configuration consists of `scenarios + capabilities + default_execution_order`; an Agent is only one capability type rather than an application-level binding.
2. `service_provider_registry` is scoped by tenant/business/workspace but has no `application_id`; real HTTP URLs, headers and credentials still live in Tool Gateway `registered_tools` / `tool_credentials`.
3. Scenarios can reference global tools, queues and providers through `ScenarioToolBridge`, bypassing the application boundary.
4. `channels` and `runtime_conversations` bind directly to `agent_id`; inbound messages are not pinned to a published service-application version.
5. Industry-template installation, upgrade preview and conflict merge create a second lifecycle that conflicts with "copy a standard example and own the copy".
6. `ServiceAppsPage.tsx` is 2,384 lines and combines applications, scenarios, capabilities, debugging, publishing and industry entry points, producing excessive concepts and interaction complexity.

This directory defines the convergence plan for service application platform v2 and serves as one review and implementation baseline for product, backend, frontend and QA.

## Target architecture

```text
Customer channel
  ↓ pinned application release version
Published service application version
  ↓ pinned Agent version
Agent (Prompt / model / knowledge / memory / evaluation)
  ↓ only application-authorized skills are visible
Application skill
  ↓ resolves an application-owned connection
Application connection / knowledge base / human queue
```

Core boundaries:

1. **The service application is the business delivery unit**; it does not fall back to Agent management.
2. **The Agent is the reasoning and execution foundation** and does not own application URLs, authentication or business skills.
3. **Skills belong directly to service applications**; the same skill name in two applications may target different connections.
4. **Connections are isolated per application**; the same URL does not imply a shared instance, credential or authorization.
5. **Channels bind to a published application version**; inbound events, conversations and runs retain the application-version snapshot.
6. **No external Router is introduced**; the Agent loop still invokes application-authorized skills.
7. **Deterministic rules protect the safety boundary**: human confirmation, amount/permission limits, idempotency, timeouts, fallback and result validation must not be left to model discretion.

## Concept convergence

The UI retains only five primary concepts:

- Service application
- Agent
- Skill
- Application connection
- Customer channel

The following legacy concepts are removed from new code, APIs and UI:

- Scenario, business orchestration, execution capability, integration capability
- Provider, industry-pack installation, upgrade preview, upgrade history
- Business-object Template
- Scenario Handler, ScenarioToolBridge

Legacy documents may remain for history, but are no longer the product or implementation source of truth.

## Roadmap

| Phase | Theme | Core value | Difficulty | Estimate | Directory |
|---|---|---|---|---|---|
| Phase 1 | Skill-centric application runtime | Application-level Agent binding, app-owned skills/connections, immutable releases, version-bound channels, example copying and clean-break | High | ~3-4 weeks | [phase-1-skill-centric-runtime/](phase-1-skill-centric-runtime/) |
| Phase 2 | Operational enhancements | After Phase 1 acceptance, improve version rollout, bulk channel switching and advanced observability based on real usage; not designed yet | Medium | TBD | To be created |

The Phase 1 directory contains:

- `01-business-goals.md` - goals, success metrics, scope and risks
- `02-requirements.md` - user stories, functional/non-functional requirements and acceptance criteria
- `03-technical-design.md` - data model, migration, APIs, runtime and frontend/backend changes
- `04-test-plan.md` - UT / IT / CM cases, regression scope and exit criteria
- `05-acceptance-plan.md` - per-AC acceptance, business metrics, compliance and sign-off
- `08-implementation-breakdown.md` - task breakdown, dependencies, current-code gaps and decisions
- `06-test-report.md` / `07-acceptance-report.md` - created only after actual testing and acceptance

## Explicit non-goals

- **No general drag-and-drop workflow designer**: a service application is not a low-code platform; complex work remains Agent + explicit skills.
- **No external application router**: no separate intent-classification service or second orchestration runtime.
- **No general expansion into an Agent platform**: prompts, models, knowledge, memory and evaluation stay with Agents; business delivery stays with applications.
- **No legacy data migration or dual read/write**: the product is not generally available; development data may be reset, and no compatibility layer is kept.
- **No industry-pack installation/upgrade lifecycle**: standard examples appear as immutable sample applications; users copy them and own the copies.
- **No credentials in release JSON, API responses, audit or logs**: only encrypted references are stored.
- **No platform-level business-object Template system**: if business objects remain necessary, they are a data contract of a skill or connection, not a new platform concept.

## Review guide

Each phase is independently reviewable. Phase 1 review focus:

1. Whether the five concepts - service application, Agent, skill, application connection and customer channel - cover real business needs without another intermediate layer.
2. Whether data and runtime fully isolate same-named skills with different URLs, credentials and rules in different applications.
3. Whether releases are truly immutable and channels, inbound outboxes, conversations and runs all pin an application version.
4. Whether clean-break is complete: legacy APIs, UI, table references and tests are all removed.
5. Whether standard examples are immutable, copyable, independently owned and never overwritten by restart.
6. Whether skill safety rules cover human confirmation, amount/permission limits, idempotency, timeout, fallback and result validation.

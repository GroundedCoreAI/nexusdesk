# Service Scenario Platform · Delivery and Acceptance

> Status: implementation planning draft, pending review
> Principle: deliver in internal milestones on one platform architecture; no rework along a
> "demo first, platformize later" path

## 1. Delivery strategy

"Finalize the architecture once, verify it milestone by milestone":

```text
Architecture finalized once
  ↓
Core contracts defined once
  ↓
Admin console built once
  ↓
First scenario running end to end
  ↓
Later scenarios only need configuration and Provider extensions
```

"One pass" here means the platform skeleton exists in V1; it does not mean every business goes live at
the same time.

## 2. V1 scope

### 2.1 V1 must include

1. the scenario definition and version model;
2. service catalog configuration;
3. business object selection and object references;
4. business fact projection;
5. user decisions and suggested questions;
6. a unified handling entry point for Direct / knowledge / query / Agent / human;
7. the scenario workbench;
8. simulation and preview;
9. draft, publish, canary, rollback;
10. decision tracing and basic metrics;
11. tenant isolation, permissions and audit.

### 2.2 V1 may implement a small subset

- the first batch supports only 1-2 kinds of business object;
- the first batch supports one channel or a small number of channels;
- the first batch fully supports only 3 scenario templates: inquiry, query and action;
- the action template may support only one action at first;
- tracking may start with status display only; a complete notification system is not required.

### 2.3 Explicitly out of V1

- an arbitrary drag-and-drop flow designer;
- a general DSL;
- an arbitrary form designer;
- Providers for every business object;
- integration with every external system;
- arbitrary Agent orchestration;
- exposing low-level routing rules to business administrators.

## 3. Milestones

### Milestone 1: platform skeleton and the query scenario loop

Goal: run the first complete scenario the platform way.

Deliverables:

- the scenario definition model;
- the service catalog;
- business object types plus order / trip objects;
- the object list and object selection;
- the object context card;
- business fact projection;
- object-aware suggested questions;
- Direct / query / human handling;
- decision tracing;
- read-only or basic editing in the admin console;
- live preview.

First scenario: **query my order / trip**.

Acceptance:

- users can enter from natural language, the catalog or an object entry point;
- users can select an order / trip;
- the page clearly shows the currently bound object;
- users can correct "this is not the object";
- there is an exit when there is no object;
- a human handoff carries object context;
- the admin console can explain why one handling instance took the path it did.

### Milestone 2: add a second scenario through pure configuration

Goal: verify that the platform abstraction holds.

Add through configuration alone:

- ask about order rules;
- query logistics;
- ask about invoice rules.

Acceptance:

- no frontend code changes;
- no changes to backend scenario branch code;
- reuse the existing object selection, fact projection, suggested questions and handling capabilities;
- the admin console can simulate and publish;
- rollback works after publishing.

If the second scenario needs a new page or a new set of branches, platformization has not happened; fix
the abstraction first instead of adding more scenarios.

### Milestone 3: action handling

Goal: verify write operations, confirmation, receipts and tracking.

Deliverables:

- apply for after-sales;
- submit feedback;
- action forms;
- explicit confirmation;
- submission receipt;
- in-progress state;
- human handoff;
- result metrics.

Acceptance:

- nothing is submitted until the user explicitly confirms;
- a receipt is visible after submission;
- the in-progress state is visible;
- on failure there is retry, human handoff or a message;
- the human can see what the user submitted and which business object it concerns.

### Milestone 4: operations and governance loop

Goal: make configuration operable, explainable and rollback-able.

Deliverables:

- scenario metrics;
- decision explanation;
- version comparison;
- canary rollout;
- rollback;
- audit;
- anomaly analysis;
- tenant-level permissions.

Acceptance:

- administrators can locate one misrouting;
- two scenario versions can be compared;
- a scenario can be canaried;
- rollback to the previous stable version works;
- metrics can be viewed by scenario, entry point, channel and object type.

## 4. Acceptance checklist for the first scenario

### 4.1 Service catalog

- business domain names use customer language;
- second-level tasks stay within what users can understand;
- the catalog always offers "other questions" or free text input;
- one task may have several entry points but shares one scenario configuration.

### 4.2 Business objects

- the object list has filters;
- object cards show status and identity facts;
- there is "view more" and "no matching object";
- object selection is not a mandatory step in every task;
- object permissions are filtered before display.

### 4.3 Business facts

- object cards show only the necessary facts;
- facts have a source and a refresh policy;
- sensitive fields are masked;
- the full business snapshot is not copied into the conversation;
- facts refresh after the object state changes.

### 4.4 User decisions

- users can explicitly select an object;
- users can confirm and correct;
- actions with consequences require explicit confirmation;
- users can switch object or business;
- user decisions and system decisions are recorded separately.

### 4.5 Handling

- Direct is not misapplied to scenarios that need an object query;
- query failures have a fallback;
- the Agent does not guess the object;
- the human queue is correct;
- a human handoff carries the scenario, object, facts and user decisions;
- the handling result has a clear next step.

### 4.6 Admin console

- the catalog can be configured;
- scenario cards can be configured;
- user input and object selection can be simulated;
- the matched scenario and handling path can be inspected;
- drafts, publishing and rollback work;
- decision records and metrics can be viewed.

## 5. Platformization acceptance criteria

The following criteria are the hard test of whether the platform is "in one pass":

| Criterion | How it is accepted |
|---|---|
| Adding a scenario of the same kind needs no code change | Verify pure-configuration onboarding with "ask about order rules" |
| Scenarios are versionable | Draft, publish and rollback are all verifiable |
| The admin console is explainable | Take any decision record and explain the scenario, object, facts, handling and reason |
| Context is correctable | After picking the wrong object, "not this object / switch object" works |
| Failures have fallbacks | No object, stale object, query failure and unreachable human all have a path |
| Tenants are isolated | One tenant's catalog, scenarios, objects and metrics do not affect other tenants |
| Capabilities are extensible | New objects via Providers, new handling via extension points, without changing scenario UI |
| Results are measurable | Conversion and failure can be viewed by scenario, entry point, object type and channel |

## 6. Roles and responsibilities

| Role | Main responsibilities |
|---|---|
| Product manager | Defines service scenarios, customer tasks, object policies, decisions and success metrics |
| Business operations | Maintains the catalog, copy, suggested questions, scenario ordering and canary |
| Platform engineering | Scenario model, runtime, Providers, handling extension points and governance capabilities |
| Frontend engineering | Generic scenario components, preview, admin workbench |
| Data / operations analysis | Metric definitions, decision analysis, scenario optimization |
| Customer support / business experts | Human queues, fallback strategy, business rules and script review |

## 7. Key risks

| Risk | Consequence | Mitigation |
|---|---|---|
| The first scenario is written too rigidly | Later scenarios have to copy code | The first scenario also goes through the scenario definition, object and handling contracts |
| Building a universal flow engine too early | Over-abstraction, delivery out of control | Fixed templates + limited slots, no arbitrary flows |
| Configuration without versions and audit | No way to diagnose or roll back in production | V1 ships versions, publishing, rollback and audit |
| Objects copied as snapshots | Inconsistent state, permission leaks | Store object references only, project facts on demand |
| The admin console exposes low-level rules | Business users cannot understand it, high risk of misconfiguration | The admin console configures scenario cards and business language only |
| Metric definitions are inconsistent | Scenario value cannot be judged | Define metric definitions before a scenario launches |

## 8. Decisions pending review

1. Should the first batch of business objects be orders, trips, or both?
2. Should the first handling mode be Direct, or query?
3. Should the V1 admin console be fully editable, or read-only first and then editable in a small scope?
4. Should business object Providers be integrated through configuration, through code, or both?
5. Is scenario configuration platform-level, tenant-level, or platform templates plus tenant overrides?
6. Who maintains the human queue mapping?
7. Are suggested questions configured by operations, generated from the knowledge base, or generated by a
   model and then reviewed?
8. Should metrics distinguish "resolved automatically" from "user says it is resolved"?

## 9. Final acceptance picture

Customer side:

```text
Find the task → pick the right object → see the facts clearly → make a choice
→ get a result → back out on failure → reach a human
```

Admin side:

```text
Configure a scenario → simulate and preview → publish and canary → inspect evidence
→ analyze metrics → change the version → roll back
```

Only when both loops hold is the service scenario platform truly delivered.

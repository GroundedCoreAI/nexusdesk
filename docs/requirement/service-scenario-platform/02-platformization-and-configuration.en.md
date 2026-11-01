# Service Scenario Platform · Configuration and Platformization

> Status: architecture draft, pending review
> Core decision: configuration and platformization are part of the V1 product skeleton, not a retrofit
> applied after the fact

## 1. What "in one pass" means

### 1.1 The scope of one pass

"One pass" in this document means the following already has a stable design and a verifiable end-to-end
loop in V1:

- the scenario definition model;
- business object and business fact contracts;
- user decision and handling contracts;
- the scenario runtime;
- the admin scenario workbench;
- versioning, publishing, audit and rollback;
- decision tracing and metric definitions.

The first version may support only a few scenarios and one kind of business object, but adding another
scenario of the same kind must be possible through configuration, not by writing new pages and branch
logic.

### 1.2 One pass does not mean doing every business at once

The following must not be preconditions for V1:

- integrating every business object;
- integrating every channel;
- supporting every handling mode;
- providing an arbitrary form designer;
- providing an arbitrary drag-and-drop flow designer;
- building a home-grown general DSL;
- letting business administrators configure low-level routing expressions.

The goal of platformization is not "everything can be configured", but:

> **Common capabilities stay fixed, business differences are configured, external systems plug in
> through extension points.**

## 2. Target architecture

```text
Customer side
Service catalog / natural language / object cards / external entry points
                    ↓
Scenario runtime
Scenario resolution → Object resolution → Fact projection → User decisions → Handling → Decision trace
                    ↑
Versioned scenario configuration
                    ↑
Admin console
Catalog management → Scenario card → Live preview → Publish / rollback → Metrics
```

Corresponding five platform layers:

| Layer | Platform capability |
|---|---|
| Configuration layer | Service catalog, scenario cards, objects, facts, decisions, recommendations, handling, fallback |
| Runtime | Scenario resolution, object binding, context construction, interaction orchestration, handler routing |
| Provider layer | Object queries, fact retrieval, knowledge retrieval, business actions, human queues |
| Admin console | Configuration, preview, simulation, publishing, versions, permissions, audit |
| Evidence layer | Decision records, context snapshots, execution results, metrics |

### 2.1 Relationship with request routing

Request routing and the service scenario platform are two complementary layers:

```text
Request routing
  decides: reject / human handoff / defer / continue
        ↓ continue
Service scenario platform
  decides: which scenario is entered, around which object, with which facts,
           which choices the user makes, which handling mode processes it
```

The two share scenarios, objects and context, but their responsibilities differ:

- Routing does not own order lists, after-sales forms and business object queries;
- the scenario platform does not replace ingress handling such as "close the conversation", "blacklist"
  and "the user explicitly asks for a human";
- `Direct` is one of the scenario platform's handling modes, not a scenario itself;
- structured Interaction and natural-language Routing may enter through different doors but land on the
  same set of scenarios and context.

## 3. Seven core contracts that must be finalized in one pass

### 3.1 Scenario definition contract

A scenario must be a versionable, publishable, rollback-able configuration, not branches scattered
through the code.

It contains at least:

```text
Scenario ID
Version
Tenant
Applicable channels
Customer task
Entry mode
Business object type and whether it is required
Displayed facts
User decisions
Suggested questions or actions
Handling
Exception fallback
Metric definitions
```

A scenario definition must distinguish:

- draft;
- pending publish;
- published;
- retired;
- historical versions.

### 3.2 Business object contract

Inside a conversation a business object stores only a reference and the display information it needs; it
never copies a full business snapshot.

The object contract expresses at least:

```text
Object type
Object ID
Object candidate set
Object instance
Current state
Permission boundary
Stale state
```

An object list is a candidate set view, not the business object itself. The platform must distinguish:

- object type: order;
- object candidate set: order list;
- object instance: order #A123;
- object reference: the order ID stored in the conversation.

### 3.3 Business fact projection contract

Fact projection converts data from business systems into information the current scenario may display
and is authorized to use.

It describes at least:

```text
Field source
Display name
Display order
Formatting
Whether it is masked
Whether it may be passed to an Agent
Whether it may be passed to a human
Refresh policy
```

Principles:

- the same object shows different facts in different scenarios;
- facts are a projection, not a full copy;
- facts must be tagged with their source and freshness;
- permission filtering happens before fact projection and object resolution, not by hiding data after it
  has been displayed.

### 3.4 User decision contract

Every decision point describes at least:

```text
Decision ID
Decision type
Options
Whether it is required
Default value
Recommendation order
Whether free text input is allowed
Whether skipping is allowed
Whether confirmation is required
Whether correction is allowed
Where the choice leads
```

It must distinguish:

- system decisions: routing, triage, handling selection;
- user decisions: choosing an object, choosing a question, confirming a submission, handing off to a
  human.

Any user action with business consequences must be explicitly confirmed and leave an auditable record.

### 3.5 Handling contract

Direct, knowledge, query, action, Agent, human and tracking share one handling contract.

Unified input:

```text
Scenario
Object reference
Business facts
User decisions
Current question
Conversation context
```

Unified output:

```text
Success / failure / more information needed / in progress
Result content
Next action
Whether a human handoff is possible
Whether tracking is created
```

Direct is responsible for deterministic answers only, not for object queries or business actions.

### 3.6 Decision trace contract

Every handling instance must be able to answer:

- why this scenario was entered;
- why this object was selected;
- which business facts were used;
- what decision the user made;
- which handling mode was finally used;
- why a human handoff happened;
- what the result was.

A decision trace is not a log string but structured evidence, containing at least:

```text
Scenario ID and version
Object reference
Fact snapshot (within the authorized scope)
User decisions
Handling mode
Handling result
Failure reason
Human queue
```

### 3.7 Version, tenant and audit contract

From V1 onward the platform must support:

- tenant isolation;
- configuration drafts;
- publishing;
- canary rollout;
- version comparison;
- rollback;
- operation audit;
- permission control.

Without these, configuration quickly turns into an operational risk where "anyone can change things and
nobody knows what changed".

## 4. Configuration boundaries

### 4.1 Three levels of capability

| Change type | How it lands |
|---|---|
| Add a scenario that reuses existing objects and existing handling modes | Pure configuration, no code |
| Add a new kind of business object or order source | New Provider + configuration |
| Add a new handling capability or external system action | New platform extension point + configuration |
| Add an arbitrary flow or page layout | Fixed template + limited extension; no universal flow engine |

### 4.2 Configuration is not a low-code platform

May be configured:

- the service catalog;
- scenario cards;
- object policies;
- fact fields;
- suggested questions;
- decision options;
- handling modes and fallback;
- channels and canary;
- metric definitions.

Must not be configured:

- arbitrary scripts;
- an arbitrary DSL;
- arbitrary cross-system call order;
- business actions that bypass permissions;
- low-level routing expressions edited directly by business administrators.

### 4.3 Platformization acceptance test

The most important acceptance criterion for the first version is:

> **A second scenario can be added through the admin console without changing frontend or backend
> code.**

For example:

1. first configure "query my order";
2. then add "ask about order rules" through configuration alone;
3. if the second scenario needs code changes, platformization has not really happened.

## 5. Runtime design

The runtime should split into six stable steps:

```text
SceneResolver       identifies the scenario
ObjectResolver      resolves the object or candidate set
FactProjector       projects business facts
InteractionEngine   generates user decisions and suggestions
HandlerRouter       selects the handling mode
TraceRecorder       records decisions and results
```

### 5.1 SceneResolver

Input:

- the user message;
- the entry point;
- the channel;
- the tenant;
- conversation state;
- possible object context.

Output:

- candidate scenarios;
- confidence or deterministic basis;
- inputs that need to be supplied.

### 5.2 ObjectResolver

Input:

- the scenario;
- the current user / business principal;
- the candidate object type;
- the object the user has selected.

Output:

- the object instance;
- the object candidate set;
- the no-object state;
- the stale state;
- the insufficient-permission state.

### 5.3 FactProjector

Input:

- the object reference;
- the scenario;
- the displayed field configuration;
- the permission context.

Output:

- facts visible to the user;
- facts available to the Agent;
- facts available to the human;
- masking results.

### 5.4 InteractionEngine

Input:

- the scenario;
- object state;
- facts;
- the decision configuration;
- the suggested question configuration.

Output:

- the options to display now;
- clickable suggested questions;
- actions that need user confirmation;
- correction and switching entry points.

### 5.5 HandlerRouter

Input:

- the scenario;
- user decisions;
- the object and facts;
- the handling strategy.

Output:

- Direct / knowledge / query / action / Agent / human / tracking.

### 5.6 TraceRecorder

Input:

- the scenario resolution result;
- the object binding result;
- the fact projection;
- user decisions;
- the handling result.

Output:

- the decision record;
- the context snapshot;
- metric events;
- the admin-readable explanation.

## 6. Admin console design

### 6.1 Five fixed workspaces

1. **Service catalog management**
   - business domains, scenarios, tasks;
   - icons, ordering, channels, visibility scope;
   - disable, canary, duplicate.

2. **Scenario card**
   - basic information;
   - entry points;
   - objects;
   - facts;
   - decisions;
   - recommendations;
   - handling;
   - fallback;
   - metrics.

3. **Live preview**
   - simulate user input;
   - simulate object selection;
   - inspect recommendations and handling;
   - inspect exception paths.

4. **Publishing and versions**
   - draft;
   - preview;
   - publish;
   - canary;
   - version comparison;
   - rollback;
   - audit.

5. **Decision explanation and metrics**
   - recent decision records;
   - why the scenario matched;
   - why the object was bound;
   - why a human handoff happened;
   - conversion and resolution rates.

### 6.2 What administrators need to see

Administrators do not need to see every detail of the low-level routing expressions, but they must be able
to answer:

1. which entry points does this scenario have?
2. which users can enter it?
3. which business object is it built around?
4. which facts will users see?
5. which choices can users make?
6. which suggestions will the system give?
7. which cases hand off to a human?
8. how do we roll back if something goes wrong?
9. how well does it work after launch?

### 6.3 Scenario simulator

The console should simply provide:

```text
Enter the user question
→ Select or simulate a business object
→ Show the matched scenario
→ Show the displayed facts
→ Show the suggested questions
→ Show the decision points
→ Show the handling mode
→ Show the fallback path
```

Before publishing, the simulator must be able to catch:

- misrouting;
- the wrong object;
- empty states;
- irrelevant suggested questions;
- the wrong handling mode;
- the wrong human queue.

## 7. Anti-patterns

1. Hard-coding the first scenario and then promising "configuration later".
2. Turning the scenario platform into an arbitrary drag-and-drop flow designer.
3. Turning the service catalog into an infinitely deep menu tree.
4. Treating the order list as the business object itself.
5. Copying the whole order snapshot into the conversation.
6. Forcing every scenario to select an order first.
7. Serving suggested questions from a global static FAQ.
8. Handing off to a human without business context.
9. Exposing low-level routing expressions to business administrators.
10. Opening up configuration without versions, canary, audit and rollback.

## 8. Conclusion

The service scenario platform should be built around "scenario cards + fixed templates + configurable
slots", not a "universal flow engine".

The key to doing platformization in one pass is not to finish every business, but to fix first:

```text
Scenario definition
Object contract
Fact contract
Decision contract
Handling contract
Evidence contract
Configuration governance
```

On top of these contracts the first scenario may be small, but the second must be addable mainly through
configuration. That is the core test of whether platformization really holds.

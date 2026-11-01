# Service Scenario Platform · Product Model and UI Blueprint

> Status: draft, pending review
> Goal: distil the common patterns of the three case studies into a reusable, configurable product shape
> for NexusDesk

## 1. Core proposition

Together the three cases show that the competitiveness of an intelligent customer service bot does not
lie in "how human the chat box feels", but in whether it lets users:

1. find what they can get done at low cost;
2. build accurate business context;
3. move smoothly between objects, rules, execution and humans.

So the basic unit of product modeling is neither "chat session" nor "flow chart", but the **service
scenario**.

A service scenario is made of five layers:

```text
Service catalog → Business object → Business facts → User decisions → Handling
```

This is not five pages, nor a five-step flow that must run in order: it answers five product questions:

| Layer | Question it answers |
|---|---|
| Service catalog | Where do users find the task? |
| Business object | Which entity is this interaction about? |
| Business facts | What must be seen to confirm the object and make a decision? |
| User decisions | What must the user choose, confirm or authorize? |
| Handling | Who actually gets this done? |

## 2. The five-layer product model

### 2.1 Service catalog

**Definition:** the user-facing business discovery layer, which organizes customer service capabilities
by business structure that customers understand.

Recommended structure:

```text
Business domain → Service scenario → Customer task
```

Example:

```text
Shopping → Order service → Query my order
Shopping → Order service → Ask about order rules
Account service → Account security → Recover account
```

**UI shape:**

- business domain cards;
- category panels;
- second-level task selection;
- "you might also ask";
- free text input;
- an "other questions" exit.

**Role:**

- let users see the boundary of what the bot can do;
- lower the cost of expressing a need in business language;
- lead vague questions to a concrete task;
- give administrators a maintainable capability map.

**Boundary:**

- the catalog is responsible for "finding the task", not "completing the task";
- the catalog is not a list of backend technical modules;
- the catalog is not an infinitely deep menu tree;
- the catalog is not a decision tree;
- one task may have several entry points, but must not produce duplicated scenarios.

**Admin configuration:**

- business domain, scenario and task names;
- icons, descriptions, ordering;
- applicable channels;
- display position and visibility scope;
- disable, hide, canary.

### 2.2 Business object

**Definition:** the business entity a customer task revolves around.

Typical objects:

- order;
- trip;
- membership;
- account;
- coupon;
- user-generated content;
- reported object;
- shop;
- ticket.

**Object relationships must be kept distinct:**

| Concept | Meaning | Example |
|---|---|---|
| Object type | A class of entity | Order |
| Object candidate set | A collection view over several objects | Order list |
| Object instance | One concrete record | Order #A123 |
| Object reference | The object locator stored in the conversation | The ID of order #A123 |

An "order list" is not the business object itself but an object selector; "an order" is an object
instance, not a business fact.

**How objects are used:**

| Mode | Meaning | Example |
|---|---|---|
| No object | A general rule question | How do I buy a membership |
| Implicit object | Uses the current account, membership or conversation | Check account status |
| Optional object | An object makes the answer more precise, but is not required | Questions about order rules |
| Required object | Cannot be handled without binding an object | There is a problem with this trip's charge |
| Multi-object selection | The same user has several candidate objects | Order list, recent order cards |

**Product principles:**

- the object is a context anchor, not a full snapshot;
- show only objects the user has permission to access;
- choosing an object is not a mandatory step in every scenario;
- there must be empty states, stale states and a correction path.

**Admin configuration:**

- object type;
- whether it is required;
- how it is obtained;
- candidate ordering;
- empty and stale handling;
- object permission boundary.

### 2.3 Business facts

**Definition:** the minimum information the current scenario needs, taken from the business object and
displayed.

Facts are neither the object itself nor the full data set:

```text
Order #A123            ← object instance
Status: shipped        ← fact
Amount: 299 CNY        ← fact
Placed: 20 October     ← fact
```

**Three uses of facts:**

1. confirm the object: is this the one I am looking for;
2. support the decision: can it be refunded, invoiced, complained about;
3. support handling: give the query, the Agent or the human the context they need.

**Fact categories:**

| Type | Description | Example |
|---|---|---|
| Identity facts | Help the user confirm the object | Time, place, name, amount |
| State facts | Describe the object's current state | Shipped, closed, in progress |
| Action facts | Support a particular action | Refund window, invoice status, whether it can be changed |

**Difference from knowledge and data:**

- raw data: every field in the business tables;
- business facts: the fields the current scenario needs to display and use;
- knowledge: general rules, e.g. "how long does an invoice take";
- conversation context: object references, user decisions and the necessary facts combined.

**Admin configuration:**

- which fields are displayed;
- field order and format;
- whether fields are masked;
- which fields feed recommendations;
- which fields may be passed to an Agent;
- which fields may be passed to a human;
- refresh and staleness policy.

### 2.4 User decisions

**Definition:** the choices, confirmations or authorizations the user must explicitly make in the
product.

Common decisions:

- choose the problem area;
- choose the concrete task;
- choose an order or trip;
- choose the concrete question;
- confirm "this is the object";
- correct "this is not the object";
- submit a refund, after-sales request or feedback;
- choose to keep asking, hand off to a human, or finish;
- switch order or business.

**System decisions and user decisions must be separated:**

| Type | Who decides | Example |
|---|---|---|
| System decision | Platform / model / rules | Close the conversation, detect a human request, choose the handling mode |
| User decision | The user | Which order, what to ask, whether to submit, whether to hand off |

The system may recommend, order and preselect, but must not make consequential choices for the user.

**Decision point design principles:**

- appear only once the user has enough information;
- do not force the user to answer questions unrelated to the current task;
- important actions require explicit confirmation;
- allow going back, correcting and switching;
- allow free text input as a fallback.

**Admin configuration:**

- decision points;
- options;
- whether a choice is required;
- defaults and recommendation order;
- whether skipping is allowed;
- whether confirmation is required;
- where the choice leads.

### 2.5 Handling

**Definition:** the capability that actually completes the task after the user makes a choice.

| Handling mode | What it does | Example |
|---|---|---|
| Direct | Returns deterministic content directly | Service hours, how to buy, fixed acknowledgement |
| Knowledge answer | Retrieves FAQs, rules, documents | Membership benefits, invoice rules |
| Query | Reads orders, trips, logistics, balances | Query order status |
| Action | Submits refunds, appeals, feedback, settings | Apply for after-sales, change dispatch settings |
| Agent | Multi-step reasoning, calls several tools | Complex disputes, cross-system problems |
| Human | Hands off with context or takes a message | Connect to "ride hailing · passenger" support |
| Tracking | Records task status, progress and notifications | Complaint progress, refund progress |

**Handling input:**

```text
Service scenario
+ Object reference
+ Required business facts
+ User decisions
+ Current question
+ Conversation context
```

**Handling output:**

```text
Success / failure / more information needed / in progress
+ Result content
+ Next action
+ Whether a human handoff is possible
+ Whether tracking is created
```

**Boundary:**

- handling is not "replying with one sentence";
- a human handoff must carry scenario and object context;
- failure, missing permission, timeout and unavailable service are all normal handling paths;
- Direct is not a standalone business; it is one of the handling modes.

## 3. Customer-side UI blueprint

### 3.1 Reusable UI capabilities

| Component | Layer it serves | Role |
|---|---|---|
| Service catalog component | Service catalog | Business domain, scenario and task navigation |
| Suggested question component | Service catalog / scenario | Cuts the cost of expressing a need |
| Object selector | Business object | List, filter, select, empty state |
| Object context card | Business facts | Shows the currently bound object and key facts |
| Decision area | User decisions | Options, confirmation, correction, switching |
| Handling result area | Handling | Answer, query result, action receipt, human handoff |
| Fallback area | Whole chain | Other questions, no results, switching, human |

### 3.2 Three scenario templates

#### Template A: inquiry

```text
Catalog / suggested questions → Knowledge answer → Follow-up / human handoff
```

Applies to:

- how do I buy a membership;
- invoice rules;
- account rules;
- content creation guide.

#### Template B: query

```text
Object selection → Object context → Dynamic questions → Query result → Fallback / human handoff
```

Applies to:

- query my order;
- query a trip;
- query logistics;
- query refund progress.

#### Template C: action

```text
Object selection → Problem confirmation → Form → Explicit confirmation → Submission receipt → Tracking
```

Applies to:

- apply for after-sales;
- submit a report;
- change settings;
- report a problem.

"Selection type" is not a separate template; it is the object selection capability shared by the query
and action templates.

### 3.3 Customer-side principles

- structured entry points and free text input always coexist;
- the catalog is not the only entry point;
- object selection is not a mandatory step in every scenario;
- after an object is bound, a summary must be shown;
- after an object is bound, correction and switching must be allowed;
- suggested questions must change with the object and its state;
- failure, no results and human handoff are all first-class paths.

## 4. Admin console shape

The admin console is neither a "routing rule editor" nor an arbitrary drag-and-drop flow designer. It
should be a "scenario workbench":

```text
┌──────────────────────┬──────────────────────────────┬───────────────────┐
│ Service catalog tree │ Scenario configuration       │ Live preview      │
│                      │                              │                   │
│ Shopping             │ Basic information            │ Mobile UI         │
│   Query orders       │ Entry points and catalog     │ Simulate input    │
│   Ask about rules    │ Business objects             │ Matched scenario  │
│  Request after-sales │ Displayed facts              │ Handling path     │
│                      │ User decisions               │                   │
│ Account services     │ Suggested questions / actions│                   │
│                      │ Handling and fallback        │                   │
│                      │ Metrics                      │                   │
└──────────────────────┴──────────────────────────────┴───────────────────┘
```

The admin console must answer five questions:

1. which scenarios exist?
2. how do users enter them?
3. which object does the system answer around?
4. why is it handled this way?
5. how well does it work?

Core admin console capabilities:

- service catalog management;
- scenario card configuration;
- live preview and simulation;
- draft, publish, canary and rollback;
- decision explanation;
- metric dashboards.

## 5. First flagship scenario: query my order / trip

Recommended flow:

```text
Entry
  ├─ Natural language "check my order"
  ├─ Home / order page entry
  └─ Recent object card
        ↓
Determine the business domain (optional)
        ↓
Show candidate objects (recent first + filter + view more)
        ↓
User selects an object
        ↓
Show "you are asking about this object" + minimal fact summary
        ↓
Suggest questions based on object state
        ↓
Direct / knowledge / query / action / Agent / human
        ↓
Result, keep asking, switch object or hand off to a human
```

Key product decisions:

1. Do not treat "order problem" as a single scenario.
2. Split "check order", "ask about rules", "request after-sales" and "give service feedback" into separate
   tasks.
3. The object list must show status.
4. Object cards carry identity facts only.
5. After binding, show a summary and a correction entry point.
6. There must be "no matching order" and "not this order".
7. Suggested questions change with object state.
8. A human handoff carries the scenario, the object reference, the question the user picked and the
   necessary facts.

## 6. Success criteria

Once the first scenario is live, it should be possible to answer:

- can users find the order entry point?
- can users pick the right order quickly?
- after binding, do they know which order they are asking about?
- are the suggested questions relevant to the current object?
- are there exits when there is no order, the wrong order, or a stale object?
- does a human handoff carry context?
- can the admin console explain one routing decision?
- can a second scenario be added without changing code?

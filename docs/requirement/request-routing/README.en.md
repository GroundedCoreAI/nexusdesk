# NexusDesk Request Routing · Phased Planning Documents

> Status: Phase 1 planning complete, awaiting review; Phase 2-4 list direction only
> Created: 2026-10-30
> Revised: 2026-10-30 (initial version)

## Background

Within a single conversation, the customer-service bot has to choose a handling path based on question
complexity: simple questions should not run through the full ReAct loop, while complex questions need
multi-step reasoning and tools. The current implementation has three concrete problems:

1. **Ingress decisions are invisible.** `business_capabilities/customer_service/service.py::send()`
   uses a chain of `if` statements to decide where a message goes (`mode=closed` at line 129,
   `{"转人工","人工客服"}` at line 131, `mode in {human,waiting}` at line 142, blacklist handoff at
   line 167), and none of those branches records anything. When production asks "why did this message
   get no reply / why was it handed off straight away", the only option is to dig through application
   logs and infer.
2. **Handoff detection covers Chinese only.** Line 131 hard-codes `{"转人工", "人工客服"}`. The
   platform already ships 7 channel adapters (WeCom / WeCom Customer Service / Feishu / DingTalk /
   Slack / Telegram / Discord) and 4 languages (zh-CN / zh-TW / en / hi). Overseas users on WhatsApp or
   Telegram saying `human` / `agent` are not recognised, and the word list cannot be configured per
   tenant.
3. **No routing data, so later tiers cannot prove their value.** How much traffic is simple questions
   (FAQ, order status lookup), and how much latency would we save? Neither is measurable today. Adding
   lightweight execution tiers without that data carries a "large investment, small return" risk.

This directory holds the phased planning documents for request routing, so product and engineering can
review each phase independently.

## Overall principles

1. **Observe first, optimise later.** The first phase only adds decision observability and changes no
   existing behaviour; every later tier must prove its value with first-phase data before it ships.
2. **Core provides mechanism only, never business semantics.** Core Platform must not contain business
   terms such as `handoff` / `reject` / `退款` / `订单`, nor built-in business priorities; routing policy
   and business handling live in Business Capabilities.
3. **Each phase ships and pays off on its own.** Phase 1 can ship now, but it is **not a
   zero-behaviour-change** phase: besides decision records it also extends the human-request rules and
   adjusts the return contract of the two 409s (intended changes, already listed in the phase
   documents); Phase 2 starts only after Phase 1 data proves the case.
4. **Execution policy and authorisation are separate.** Routing decides *how* to execute; whether it
   is allowed is decided at execution time by `core_platform/policy_harness`. Core only validates the
   `profile` scope and does not re-authorise.
5. **An empty implementation equals the status quo.** With any phase's switch off, system behaviour
   must match the pre-change system item by item, and automated tests must prove a zero diff.

## Business handling path model

The way a message is assigned for handling once it enters the system is called a **path**. Paths are
**not** mutually exclusive execution-mode enum values — they belong to three dimensions and are used
in combination:

| Dimension | Path | Meaning |
|---|---|---|
| Business disposition | Reject / Handoff / Defer / **Continue** | Whether the message is still handled by the bot |
| Execution tier | Direct / Lightweight / Agent | Which execution capability is used on `Continue` |
| Process control | Resume / Escalate | Resume an existing task across turns / change the handling subject or policy mid-execution |

How they combine (the key point: they are not eight parallel values):

- Only `Continue` involves an execution tier, chosen among Direct / Lightweight / Agent
- `Resume` may be followed by Lightweight or by Agent
- `Escalate` may be followed by a Handoff, or by escalation to a stronger Agent Profile
- A failed `Agent` run does not necessarily Handoff; it may retry, degrade, or ask the user for more
  information
- `Clarify` is **not a path**; it is the interaction action of the task state `waiting_user`, and once
  the user supplies more information the flow goes through `Resume`

**Decision records therefore express "disposition + tier + process control" in three columns, and are
not written as a single `RouteMode` enum.** This is the core design constraint of this topic: the
moment it becomes an 8-value enum, routing freezes customer-service business semantics into a
platform enum.

There are 8 target paths: Reject, Handoff, Defer, Direct, Lightweight, Agent, Resume, Escalate. **This
is the target model, not what is implemented today.** Today only 4 dispositions exist (Reject /
Handoff / Defer / Continue→Agent), and Agent is the only active execution tier; Direct, Lightweight,
Resume and Escalate are all unimplemented (see the scope section of `01-business-goals.md`).

## Phase roadmap

| Phase | Theme | New paths | Core value | Difficulty | Estimate | Directory |
|---|---|---|---|---|---|---|
| Phase 1 | Routing decisions visible | The existing 4 dispositions (Reject / Handoff / Defer / Continue→Agent) | Decisions queryable; human-request rules extended; the two 409s no longer retried in vain | Low | ~1 week | [phase-1-routing-decision-trace/](phase-1-routing-decision-trace/) |
| Phase 2 | Direct tier (deterministic answers) | Direct | Simple questions with zero model and zero tools; preferred for system-script acknowledgements | Medium | ~1.5 weeks | To be planned |
| Phase 3 | Lightweight tier + execution escalation | Lightweight, Escalate | Retrieval plus constrained tools; introduces Core's provider host and the execution-tier loop | High | ~2-3 weeks | To be planned |
| Phase 4 | In-conversation task lifecycle | Resume | Creating, continuing, clarifying, switching and resuming multi-turn tasks | High | ~2-3 weeks | To be planned |

Every phase directory contains the same set of documents:

- `01-business-goals.md` — business goals, value, success metrics, scope boundaries
- `02-requirements.md` — user stories, functional requirements, acceptance criteria
- `03-technical-design.md` — data model, code change points, API design, test approach summary
- `04-test-plan.md` — test plan: unit/integration cases, general checklist, exit criteria
- `05-acceptance-plan.md` — acceptance plan: step-by-step AC verification, business metric
  measurement, compliance checks and sign-off
- `06-test-report.md` — test report (produced after testing)
- `07-acceptance-report.md` — acceptance report (produced after acceptance)
- `08-implementation-breakdown.md` — implementation breakdown and decisions (optional, large phases)

## Out of scope (overall boundaries)

- **No standalone microservice**: request routing is a concern inside the modular monolith, so no new
  deployment unit.
- **No general-purpose process designer / rules DSL**: rules are structured configuration plus code,
  avoiding the maintenance cost of a home-grown DSL.
- **No general Task Engine**: task lifecycle belongs to the conversation domain; customer-service
  task rules belong to the customer-service capability. Core will not host a general task engine that
  carries refund, order or ticket concepts.
- **Models do not decide tool permissions**: routing produces an execution plan; authorisation is
  always decided at execution time by `policy_harness`.
- **Model classification never replaces deterministic rules**: conversation closed, an explicit human
  request, blacklist and similar checks must outrank model classification and run before the model.
- **No separate Runtime per customer-service intent**: a tier is an execution policy, not a Runtime
  instance.
- **Phase 1 publishes no events and builds no Outbox**: nothing consumes `routing.decision_created`
  yet, and reliable delivery needs an event bus plus an Outbox; revisit once a consumer actually
  exists.

## Review guidance

- Each phase can be reviewed and scheduled independently; **Phase 1 must ship and produce data
  before Phase 2 is reviewed**.
- Review focus:
  - Phase 1: whether the `send()` decision sequence is action-equivalent to the original branches
    (except the two intended changes in FR-3 and FR-4); whether decision writes are isolated with a
    SAVEPOINT and stay inside the existing transaction and lock order; whether the two 409 contract
    changes only affect `send()` internals and leave the external status code unchanged.
  - Phase 2: the applicability boundary of the `direct` tier (which intents may use deterministic
    answers), and the fallback for misrouting risk.
  - Phase 3: whether Core only gains a provider host and execution tiers, with no new business enums
    and no new business priorities; whether `routers` contributes kinds through the existing
    `extension_platform` registry.
  - Phase 4: ownership of the task table (conversation domain) versus customer-service task rules;
    task state is not merged with `runtime_runs` state.

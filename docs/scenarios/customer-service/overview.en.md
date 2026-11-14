# Customer service

> This tutorial records the design judgments behind NexusDesk's customer service scenario: why it is split this way, why these constraints exist, and how choices that look like implementation details end up shaping the product.

## What this tutorial solves

It is easy to build a customer service product as "a chat window plus one Agent": the interface comes first, capabilities are added later, and knowledge, tools, tickets, and human agents are squeezed in afterwards.

NexusDesk's first production scenario takes the opposite order: define the service task the customer has to complete first, then decide where the Agent, knowledge, tools, and human handoff appear and how each result is expressed as a state.

So this tutorial does not try to cover every feature. It answers three kinds of questions:

1. **Why each concept exists**: what problem service applications, service scenarios, business objects, business facts, and execution capabilities each solve.
2. **Where the boundaries are**: which capabilities belong to a scenario, which belong to an Agent, and which must be carried over to the human side.
3. **How to express state**: why simulated, pending confirmation, in progress, succeeded, failed, unknown result, and handed off must be strictly separated.

API fields, deployment commands, and operations details are out of scope here; see the user guide, architecture, and deployment sections instead.

## Who it is for

- Practitioners who are integrating or configuring the customer service product;
- Product and engineering reviewers who need to decide which layer a requirement belongs to;
- Developers who maintain this design and need to understand the original trade-offs.

## The seven design judgments

These are the skeleton of the whole tutorial. Every chapter expands one of them.

1. **The service application is the delivery unit.** What a customer uses is a service application, not an isolated Agent or page.
2. **The service scenario is the core reusable asset.** What gets reused is the task the customer needs to complete, not a prompt.
3. **Business objects are first-class product components.** Objects such as orders, devices, and bookings must be visible, selectable, and confirmable by both customers and human agents.
4. **The Agent is one execution capability of a scenario, not the scenario itself.** The scenario owns the task and its boundaries; the Agent only handles the parts that are suitable for automation.
5. **The human workspace inherits the full context.** A handoff transfers the scenario, objects, facts, decisions, and trajectory, not just a transcript.
6. **Industry differences are expressed through templates, configuration, and registries.** They are never expressed by stacking runtime industry branches.
7. **States must be strictly separated.** Simulated, pending confirmation, in progress, succeeded, failed, unknown result, and handed off cannot share one vague completed/not-completed flag.

## Tutorial catalog

| Chapter | Question it answers | Status |
| --- | --- | --- |
| 1. [Recommended question design trade-offs](./recommended-questions.md) | Where do recommendations come from, when should they appear, and what goes wrong when they are wrong? | Published |
| 2. From a customer service page to a service application | Why is the delivery unit an application rather than a page or an Agent? | Planned |
| 3. Scenario first | Why is the reusable asset a scenario rather than a prompt? | Planned |
| 4. Business objects and business facts | Why must objects and facts be first-class components? | Planned |
| 5. The Agent is an execution capability | What should be delegated to an Agent, and what should not? | Planned |
| 6. Designing the human handoff | Why does a handoff transfer context rather than a conversation? | Planned |
| 7. State semantics | Why must "unknown result" exist as its own state? | Planned |
| 8. Expressing industry differences | Why use scenario packs and registries instead of industry branches? | Planned |

> The catalog will be filled in as each chapter lands. For the structure of a new chapter, see `docs/scenarios/customer-service/lesson-template.md` in the repository.

## About writing

- Each chapter answers exactly one question, and the title is that question;
- Start with the counter-example, then the design judgment, then the boundary conditions and where it lives in the implementation;
- Keep Chinese and English side by side (`xxx.md` + `xxx.en.md`);
- After adding a page, register it in the `scenarios` group in `site/nav.mjs`.

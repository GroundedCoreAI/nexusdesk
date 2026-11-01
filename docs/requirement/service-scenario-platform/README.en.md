# Service Scenario Platform

> Status: draft product model and platformization blueprint, pending review
> Created: 2026-10-31
> Related: [Request Routing Roadmap](../request-routing/README.md),
> [Zhihu / Douyin / Amap case study](../request-routing/case-studies/01-service-scenario-analysis-zhihu-douyin-amap.md)

## Positioning

This directory captures the product model and the platformization plan for moving intelligent customer
service from "single-turn Q&A" to a configurable business scenario platform.

Its relationship with request routing:

- **Request routing** answers, for one natural-language message, "should this be rejected, handed off to
  a human, deferred, or handled";
- **Service scenario platform** answers, once handling continues, "which business, which object, which
  facts, and which capability completes it";
- the two share scenarios, business objects and business context, but they are not two unrelated
  systems;
- Direct is not a standalone feature; it is one of the handling modes inside the service scenario
  platform.

## Key conclusions

1. Commonality cannot be turned into a universal customer service page, and the first version should not
   be an arbitrary drag-and-drop flow designer either.
2. The right shape is "a generic scenario shell + configurable scenario cards + a limited set of scenario
   templates".
3. Configuration and platformization belong in the V1 product skeleton, not in a retrofit after the first
   scenario ships.
4. "One pass" means the model, contracts, admin console, runtime and evidence chain are designed once and
   land in V1; it does not require onboarding every business at the same time.
5. V1 closes the loop with "query my order / trip", then proves pure-configuration reuse with "ask about
   order rules".

## Documents

- [01-product-model.md](01-product-model.md): the five-layer product model, customer-side UI capabilities,
  three scenario templates, the admin workbench and the first flagship scenario
- [02-platformization-and-configuration.md](02-platformization-and-configuration.md): the one-pass target
  architecture, core contracts, configuration boundaries, runtime and admin console design
- [03-delivery-and-acceptance.md](03-delivery-and-acceptance.md): V1 scope, implementation milestones,
  acceptance criteria, roles and the not-doing list
- [ui/README.md](ui/README.md): V1 UI designs and page previews in the current workbench visual language

## Current boundaries

This directory is currently **product and architecture documentation**; it does not mean the code is
implemented. Every item still needs review before implementation:

- the data model for scenario configuration;
- how business object Providers are integrated;
- the reuse boundary between frontend components and the existing customer service shell;
- the unified handling contract across Direct / knowledge / query / action / Agent / human;
- tenant permissions, version publishing, audit and metric definitions.

## Related conclusion

```text
Service catalog → Business object → Business facts → User decisions → Handling
```

This chain is not a five-step flow that must run in order; it answers five questions:

1. where users find the task;
2. which business entity this interaction revolves around;
3. which key information needs to be seen;
4. what the user must explicitly choose or confirm;
5. who actually completes the task.

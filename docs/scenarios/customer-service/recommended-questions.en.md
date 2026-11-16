# Recommended question design trade-offs

> Status: published
>
> This chapter answers: where recommended questions come from, whether each question needs its own fixed answer, and what "recommendation", "knowledge retrieval", and "Agent execution" each own.

## One-sentence conclusion

**Do not introduce a separate QA-pair data model, and do not bind a fixed answer to each recommended question.** Recommended questions are only the user's entry point; frequently used fixed knowledge becomes FAQ content in the knowledge base; by default Agent Runtime retrieves it through `knowledge_search` and combines it with business tools; only a small number of high-confidence, context-independent questions get an optional exact-match fast path.

## Why not give every recommended question its own QA pair

The recommended questions in a business catalog usually look alike — "one sentence in, one sentence out" — but they actually fall into three groups:

| Question type | Examples | Better fit |
| --- | --- | --- |
| Static rules and process explanations | How to request a trip invoice; how to reach a human agent | FAQ knowledge + `knowledge_search` |
| Needs user context | How to look up past trips; fare differs from the estimate | ReAct + business query tools |
| Needs to execute an action | Lost item recovery; complain about a driver; cancel an order | ReAct + the matching Skill/Action |

Building an independent QA pair for every recommended question causes five problems:

1. **Answers go stale.** When campaign rules, invoice policy, or support channels change, both the recommendation config and the QA answer have to be maintained.
2. **The same answer is stored repeatedly.** Several recommended questions may end up pointing at the same knowledge.
3. **Natural-language variants are not covered.** Users do not always click a recommendation verbatim; free-form input still needs retrieval.
4. **Fixed answers lack context.** Past trips, fare disputes, and lost items require querying user and order data, which a QA pair cannot handle.
5. **Unnecessary management complexity.** It adds QA editing, versioning, publishing, permissions, and evaluation systems.

## Four responsibilities

| Layer | Responsibility |
| --- | --- |
| Suggested questions | The user's entry point |
| FAQ / QA content | Data in the knowledge layer |
| `knowledge_search` | The retrieval mechanism |
| Agent Runtime | Understand, decide, and generate the answer |

These four are not alternatives; each has its own job:

- **Recommended questions** make it easier for the user to start, and do not store answers;
- **FAQ content** carries stable knowledge and is managed together with knowledge-base versions and sources;
- **`knowledge_search`** recalls relevant chunks and returns titles, versions, and sources;
- **Agent Runtime** combines context, tool results, and knowledge into the final answer.

## What a recommended question should bind to

A recommended question only keeps entry-point metadata:

```text
question text
optional: intent_key
optional: skill_key
optional: object or context scope
```

Not:

```text
question text → fixed answer
```

In the current service application experience config, recommended questions are just text (`suggestion_sets: list[list[str]]`), with no answer binding at all; business catalog entries bind to capabilities through the four entry kinds `knowledge`, `query`, `action`, and `handoff`. What needs refinement is the mapping from entry to capability, not another "question + answer" data model:

- Static knowledge questions: store as FAQ knowledge and go through `knowledge_search`;
- Order and trip lookups: bind a specific query Skill and let the Agent decide whether to call it;
- Cancellations, complaints, and lost-item recovery: bind an Action Skill and keep human confirmation;
- Human support: hand off directly; the model does not need to retrieve an answer first.

## Why FAQ can already carry fixed knowledge

The knowledge module already supports an `faq` chunking strategy that turns question/answer columns in Excel into FAQ chunks:

`backend/src/agent_platform/business_capabilities/knowledge/chunking.py`

So a knowledge base can be organized like this:

```text
Travel support knowledge base
├── FAQ: invoice rules
├── FAQ: fare dispute handling
├── FAQ: lost item recovery process
├── FAQ: how to reach a human agent
└── Documents: other policies and operating instructions
```

The Agent calls `knowledge_search` inside the ReAct loop and answers after retrieving the relevant chunks. There is no need for a separate `qa_pairs` table, and no need to store an answer next to each "suggested question".

## Should there be an exact-match fast path

For a small number of high-risk or fully fixed questions, an optional fast path is acceptable:

```text
recommended question
→ exact / high-confidence FAQ match
→ on hit, return the standard answer directly
→ on miss, enter ReAct + knowledge_search/tools
```

The fast path should satisfy:

- the question's meaning does not depend on context;
- the standard answer is unique and stable;
- the answer has a version and a source;
- below the confidence threshold it falls back to ReAct automatically;
- it does not apply to personalized queries such as orders, trips, or accounts.

## Boundary conditions

- Personalized queries and write operations do not use QA pairs or the exact-match fast path;
- even when a write operation matches an Action Skill, it keeps human confirmation and cannot be triggered directly by a recommended question;
- the human support entry hands off directly instead of making the model retrieve a support phone number first;
- when FAQ content changes, publish a new knowledge-base version rather than editing the answer of a single recommended question.

## Implementation and further reading

- FAQ chunking strategy: `backend/src/agent_platform/business_capabilities/knowledge/chunking.py` (`strategy="faq"`, splitting row by row on question and answer columns);
- Knowledge retrieval tool: `backend/src/agent_platform/business_capabilities/knowledge/tools.py` (`knowledge_search` returns titles, versions, chunks, and sources);
- Recommended question config: `backend/src/agent_platform/business_capabilities/customer_service/service_apps/models.py` (`suggestion_sets`, `ExperienceEntryKind`);
- Client "suggested questions" panel: `frontend/src/features/service-apps/experience/CustomerInteractionWorkspace.tsx`.

## Summary

A recommended question is not a row in a question-answer table; it is the entry layer of the service. It brings the user into the scenario, while the real answer comes from FAQ knowledge, business queries, or an Action Skill, composed by Agent Runtime with context. This keeps the Agent's contextual understanding while avoiding a large, hard-to-maintain FAQ table.

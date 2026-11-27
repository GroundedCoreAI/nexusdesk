# Phase 2 · Skill Authoring, Testing, and Release — UI Interaction Freeze

> Status: Interaction contract frozen; implementation in progress.
> Created: 2026-11-27
> Basis: `01-business-goals.md` (G1–G4), `02-requirements.md` (FR-1–FR-10, AC-1–AC-12), and the supplied NexusDesk creation/detail references.
> Purpose: give backend, frontend, tests, and acceptance one unambiguous description of every screen, state, and transition before implementation.

## 1. Frozen Decisions

1. The existing business console shell is authoritative: the Skill area must keep the same 228px business sidebar, header, breadcrumb language, blue/white visual tokens, and mobile collapse behavior. No Skill-specific sidebar is introduced.
2. The catalog, creation wizard, editor, test workbench, and release surface are one lifecycle. A locally rendered success state is never accepted as evidence that a backend mutation succeeded.
3. Creation mode selection is a one-time entry choice. AI, template, and professional modes all converge on the same editor model and the same save/test/publish contract.
4. The detail page keeps six in-page tabs: Overview, Capability Definition, Resource Dependencies, Test Records, Version Management, and Runtime Analytics. Test and version views are not separate routes.
5. Draft revision and published version are separate concepts everywhere. Editing never mutates a published version.
6. Test evidence is bound to the exact saved draft revision. A local edit, a newer save, or a later failed/error test invalidates the prior pass for release readiness.
7. Published versions are immutable. Rollback creates a new higher version and records `rollback_from`; it never rewrites or deletes history.
8. Only API-confirmed results may show success. Loading, empty, error, blocked, and permission states are first-class UI states.

## 2. Screen and Route Map

| Surface | Route | Primary entry | Lifecycle role |
|---|---|---|---|
| Skill catalog | `/skills` | Resource Center → Skill 能力库 | Discover and open a Skill |
| Creation wizard | `/skills/create` | Catalog → Create Skill | Choose AI, template, or professional mode |
| Skill editor | `/skills/:skillKey/edit` | Creation handoff, detail → Edit | Save and validate the current draft |
| Skill detail | `/skills/:skillKey` | Catalog card, publish/back navigation | Inspect live state and use the six in-page tabs |

The existing route allow-list in `frontend/src/app/hashRouter.ts` must accept generic Skill keys and the `/edit` suffix. Unknown or cross-scope keys render a non-destructive not-found panel with a return-to-catalog action; they never fall back to fixture data.

| Detail tab | Content owner | In-page interaction |
|---|---|---|
| Overview | Published snapshot plus basic status | View metrics, basic info, current version, dependencies, and trend/empty state |
| Capability Definition | Draft when editable, otherwise published snapshot | Read definition and parameters; Edit routes to the editor |
| Resource Dependencies | Current selected draft/published snapshot | Read resolved resources and availability; Edit routes to the editor |
| Test Records | Draft revision plus test history | Open the two-pane test workbench and history |
| Version Management | Immutable version history | Publish dialog, version details, rollback dialog |
| Runtime Analytics | Runtime aggregation or honest empty state | Read-only; no fixture trends or fabricated counts |

## 3. Creation Wizard Contract

### 3.1 Step 1: mode selection

| Mode | Required input | Primary action | On success |
|---|---|---|---|
| AI-assisted | Non-empty prompt, 1–2000 characters | Generate draft | Create a draft, attach `creation_mode=ai`, route to editor |
| Template | Exactly one selected template | Use template | Create a draft from the template defaults, attach `creation_mode=template`, route to editor |
| Professional | None | Open editor | Create an empty/valid-default draft, attach `creation_mode=professional`, route to editor |

The mode card itself selects the mode. The card action button advances; clicking the card must not create a draft by itself.

AI mode states: `idle → prompt entered → generating → draft created | generation_error`. Generation errors stay on Step 1, preserve the prompt, and offer Retry. If AI generation is not configured on the deployment, the card remains visible but its action is disabled with the reason “AI generation model is not configured”. Template and professional creation stay usable.

Template mode states: `idle → template selected → creating → editor`. The template list has loading, empty, and error states. Selecting another template replaces the selection; it does not create multiple drafts.

Professional mode states: `idle → creating → editor`. An empty draft may be saved, but it cannot be tested or published until mandatory fields are valid.

### 3.2 Draft creation state machine

```text
/skills/create
  ├─ AI: prompt valid ─────────────┐
  ├─ Template: one template selected ┤→ POST create draft
  └─ Professional: no input ────────┘
                                      ├─ success → /skills/{skillKey}/edit
                                      └─ failure → remain on Step 1, preserve input

/skills/{skillKey}/edit (creation context)
  Draft editing → Save Draft → Test → Release → Publish
                                        └─ success → /skills/{skillKey}?tab=versions
```

The editor route is stable while the user moves between Save, Test, and Release stages. Stage movement is local UI state; it does not create additional routes.

### 3.3 Cancellation and back behavior

- Before the first successful save, Cancel asks for confirmation if any field is dirty. Discard returns to `/skills`; keep editing returns focus to the form.
- After at least one successful save, Cancel leaves the persisted draft intact and returns to the Skill detail page or catalog according to entry context.
- Browser Back or navigation away with dirty fields opens the same dirty-navigation confirmation. There is no silent discard.

## 4. Editor Contract

### 4.1 Shared editor

The detail Edit action and creation Steps 2–4 use the same editor component. The editor is not a separate visual system.

| Region | Content |
|---|---|
| Page header | Breadcrumb, Skill name, status, mode label, Save Draft, Test, Publish entry |
| Identity banner | `Draft rN`, current published version (if any), last saved time, dirty/saving/conflict status |
| Section navigation | Basic, Capability, Parameters, Dependencies, Runtime/Safety |
| Form body | Only the selected section or a vertical mobile layout |
| Sticky action bar | Save Draft, validation summary, Test/Publish readiness destinations |

The editor must not show a fake “Saved” state while the request is in flight. Saving displays `Saving…`, then the revision returned by the backend.

### 4.2 Section and field inventory

| Section | Field | Control | Required | Notes |
|---|---|---|---|---|
| Basic | Skill key | Read-only text | Yes | Stable identifier; generated on draft creation and not editable |
| Basic | Name | Text, 1–100 | Yes | Duplicate-name handling is server-owned; key remains unique |
| Basic | Description | Multiline, 0–1000 | Yes for publish | Explains capability and expected value |
| Basic | Category | Select | Yes | Service, Finance, Sales, General; server validates the allow-list |
| Basic | Tags | Tag input | No | Maximum 10, each ≤32 characters, normalized and de-duplicated |
| Basic | Visibility | Select | Yes | MVP: Current workspace only; no public/marketplace option |
| Basic | Owner | Read-only summary | Yes | Derived from authenticated actor and timestamps |
| Capability | Skill type | Segmented/select | Yes | Instruction, Knowledge, Query, Action, Handoff |
| Capability | Trigger | Select | Yes | Agent automatic or manual test; no scheduler in this phase |
| Capability | Execution mode | Read-only derived label | Yes | Derived from type and dependencies, not free text |
| Capability | Instructions/prompt | Multiline | For Instruction | 1–12000 characters; forbidden when irrelevant |
| Capability | Input schema summary | Read-only derivation | Yes | Generated from the parameter table |
| Capability | Output format | Select | Yes | Text or JSON |
| Capability | Output schema | JSON/schema editor | For JSON | Valid JSON Schema; required for structured extraction |
| Parameters | Parameter rows | Dynamic table | No | Add, remove, reorder; name, type, required, default, description |
| Parameters | Parameter name | Text | Yes per row | Unique, machine-safe, ≤64 characters |
| Parameters | Parameter type | Select | Yes per row | string, number, integer, boolean, object, array |
| Parameters | Required | Checkbox | Yes per row | Drives generated schema |
| Parameters | Default | Typed input/literal | No | Must validate against the selected type |
| Parameters | Description | Text | No | ≤200 characters |
| Dependencies | Model profile | Selector | For Instruction | Published, available profile/version only |
| Dependencies | Knowledge bases | Multi-select | For Knowledge | Enabled, same-scope bases only |
| Dependencies | Primary tool | Selector | For Query/Action | Enabled tool; effect must match the Skill type |
| Dependencies | Tool collections/connectors | Read-only summary | No | Derived from selected tools; broken references are surfaced |
| Dependencies | Handoff queue | Selector/text | For Handoff | Existing queue only; no free-form queue creation here |
| Runtime/Safety | Timeout | Number | Yes | 1–60 seconds inclusive |
| Runtime/Safety | Retry policy | Select | Yes | None, one retry, two retries; never applies to write actions |
| Runtime/Safety | Confirmation required | Switch | For write actions | Required unless an explicit exemption exists |
| Runtime/Safety | Idempotency | Select | For Action | None, optional, required |
| Runtime/Safety | Error behavior | Select | Yes | Fail, fallback, or handoff |
| Runtime/Safety | Permission scope | Read-only summary | Yes | Current workspace in MVP |
| Runtime/Safety | Maximum amount | Decimal | No | Only for Action; evaluated before external execution |

Cross-field validation is explicit:

- Query requires a read-only primary tool.
- Action requires an external tool and a confirmation or documented exemption decision.
- Knowledge requires at least one knowledge base.
- Instruction requires a model profile and instructions.
- Handoff requires a queue.
- JSON output requires a valid output schema.
- A published Skill’s current version remains visible even while its draft is invalid.

### 4.3 Draft status machine

```text
loaded/clean ──edit──▶ dirty ──Save────▶ saving ──success──▶ clean (revision N+1)
   ▲                    │                   │
   │                    │                   ├─validation error──▶ dirty + inline errors
   │                    │                   ├─network error─────▶ dirty + retry
   │                    │                   └─409 conflict──────▶ conflict
   │                    └─discard/leave────▶ confirm dialog ──▶ discard
   └──────────────────── reload server copy or duplicate-as-new ─ conflict resolution
```

Rules:

- Dirty status appears on the first field change and clears only after a confirmed save or an explicit discard/reload.
- Test evidence becomes stale in the UI immediately when the first local edit occurs, even before the next save.
- A save conflict compares the client revision with the server revision. The dialog offers Reload server draft or Duplicate as new Skill; neither option is automatic.
- On save failure, local input remains intact and the Save action becomes retryable.
- Every successful save increments the draft revision exactly once.

## 5. Test Workbench Contract

### 5.1 Component map

```text
┌──────────────────────────────────────────────────────────────┐
│ Test header: draft revision, latest result, Run/Cancel        │
├───────────────────────────────┬──────────────────────────────┤
│ Input pane                    │ Result pane                   │
│ - Parameter form / Raw JSON   │ - Running indicator           │
│ - Optional scenario text      │ - Pass/Fail/Error/Blocked     │
│ - Client validation           │ - Output, duration, diagnostics│
├───────────────────────────────┴──────────────────────────────┤
│ History: time, revision, input summary, result, duration, user│
└──────────────────────────────────────────────────────────────┘
```

Desktop uses two columns; tablet and mobile stack Input above Result. History remains below both panes and uses a contained horizontal scroll rather than widening the document.

### 5.2 Test states

| State | Trigger | Required display | Allowed actions |
|---|---|---|---|
| Empty | No result for this revision | “Run first test” guidance | Edit input, Run |
| Invalid input | Empty required parameter, invalid JSON, wrong type | Inline field or JSON error | Fix input, Run |
| Running | Run accepted by the client and request in flight | Progress indicator, elapsed time, Run disabled | Navigate away without claiming completion |
| Passed | Backend executed and output satisfied the declared contract | Pass badge, output, duration, revision, diagnostics summary | View details, Run again, continue to release |
| Failed | Execution completed but output/business contract failed | Fail badge, output or error reason, duration, revision | Retry with preserved input |
| Error | Infrastructure, model, tool, timeout, or execution unavailable | Error badge, stable reason code, safe diagnostic text | Retry; contact-admin guidance when persistent |
| Blocked by safety | Write test lacks a safe fixture/sandbox policy | Blocked badge and exact reason | Edit configuration; no pass evidence |
| Stale | Latest successful run revision is older than current saved revision | Stale banner naming both revisions | Run again |

The backend response is the source of truth for Passed/Failed/Error/Blocked. The client must not infer Passed from an HTTP 200 alone or from a fixed fixture.

The input pane supports two equivalent editors:

- Parameter form: one control per declared parameter.
- Raw JSON: the exact payload submitted to the API.

Switching editors keeps the same in-memory value when it remains valid. Invalid raw JSON cannot silently overwrite a valid form value; the user receives an inline error and must fix or cancel the switch.

### 5.3 History contract

- History is reverse chronological and paginated.
- Each row displays time, draft revision, input summary, status, duration, executor, and a detail action.
- The active result is highlighted and remains visible if history loading fails.
- History failure shows an inline retry; it does not erase the result pane.
- Empty history is an instructional empty state, not synthetic sample rows.

## 6. Release Readiness and Version Contract

### 6.1 Readiness checklist

| Check code | Pass condition | Blocked-state destination |
|---|---|---|
| `draft_saved` | Client revision equals server revision and no dirty fields remain | Save Draft |
| `required_fields_valid` | Server-side definition validation passes | First invalid editor section |
| `latest_test_passed` | Latest test for the current saved revision is Passed | Test Records |
| `dependencies_available` | Every referenced model, tool, collection, KB, and queue resolves in-scope | Resource Dependencies |
| `permission_granted` | Principal has publish permission | Permission explanation; no navigation loophole |
| `publish_available` | No conflicting publish transaction/version conflict is active | Retry after the current operation ends |

The readiness view is evaluator-owned, not a static checklist. Each row has `status`, human reason, stable reason code, and an optional destination. Warnings that do not block publication are visually separate from failures.

### 6.2 Publish dialog

| Field | Behavior |
|---|---|
| Version bump | Minor, major, or patch; first release is always `1.0.0` |
| Next version preview | Server-suggested semver and monotonic version number |
| Release notes | Required, 1–2000 characters |
| Summary | Skill name, draft revision, passing test time, dependency count |
| Confirm action | Disabled while saving/publishing; label changes to `Publishing…` |

Publish transition:

```text
readiness all pass → dialog open → fields valid → confirm
  ├─ success → immutable version created → current version updated
  │             → history refreshed → success toast → version tab
  └─ conflict/error → dialog remains open, entered metadata preserved, Retry shown
```

Closing the dialog before confirmation discards dialog fields only, never the draft. Pressing Escape while the publish request is in flight is blocked or explicitly cancelled only when the backend confirms no version was created.

### 6.3 Version history

Each version row displays:

- Semver and monotonic version.
- Release type: initial, major, minor, patch, or rollback.
- Release notes.
- Author and release time.
- Draft revision and test evidence used.
- `Current` marker and optional `Rollback from vX` lineage.

Version details may show the immutable snapshot and a safe field-level diff. History has no Edit or Delete action. A failed publish creates no row.

### 6.4 Rollback dialog

Rollback is available only for historical versions older than the current version.

| Field | Behavior |
|---|---|
| Target version | Required selection; shows release time and notes |
| Current version | Read-only comparison |
| Release notes | Required for the new rollback version |
| Warning | Explains that a new higher version is created and history is preserved |
| Confirm | Creates a new version copying the target snapshot and recording `rollback_from` |

After success, the new version becomes Current and the target remains in history unchanged. If dependency validation fails, current version stays unchanged and the dialog shows the reason.

## 7. Honest Async-State Matrix

| Surface | Loading | Empty | Error | Permission/read-only |
|---|---|---|---|---|
| Catalog | Skeleton cards and disabled filters | “No Skills yet” with Create when allowed | Inline alert + Retry; no fixture cards | Cards/details readable; Create disabled with reason |
| Detail | Header skeleton, tab shell | Draft-only Skill explains it has not been published | Not-found or scope-denied panel + Back | Edit/Test/Publish disabled with reasons |
| Editor | Load draft and dependency pickers independently | Newly created empty draft remains editable | Preserve local edits, retry failed dependency loads | Entire form read-only only if no manage permission; explicit banner |
| AI generation | Generating indicator on the mode card | Model not configured disables action | Inline error + Retry; prompt retained | Disabled with deployment reason |
| Test workbench | Input/result skeleton while draft loads | Run-first state | Active result preserved; inline request error | Run disabled; history remains readable if permitted |
| Test history | List skeleton | “Run first test” | Inline retry below active result | Read-only history |
| Readiness | Checklist skeleton | First release has a valid initial checklist | Entire checklist retryable; never optimistically green | Publish disabled if permission missing |
| Versions | List skeleton | “No published version yet” | Inline retry | History readable; Publish/Rollback disabled |
| Analytics | Chart skeleton | “No runtime data for this Skill yet” | Inline retry | Read-only |

No in-scope action may end with “this will be available later”. Unsupported future actions are either omitted or show a concrete configuration/permission reason.

## 8. Responsive Behavior

| Width | Shell and page behavior |
|---|---|
| Reference desktop (1672×941) | Existing sidebar/header geometry; editor section navigation and test panes remain side by side; version table shows full columns |
| Desktop/tablet ≥1024 | Cards and forms reflow; test panes may remain side by side above 900px; sticky action bar remains reachable |
| Tablet/narrow 768–1023 | Editor sections stack; test panes stack; dependency controls use full width; tables scroll inside their panel |
| Mobile 390 | Existing sidebar collapses; one-column cards/forms; stage control scrolls within its own region; dialogs fit viewport; no horizontal document overflow |

The document itself must never horizontally scroll. Long JSON, schema, version notes, and diagnostics use contained code blocks or table wrappers.

## 9. Accessibility and Internationalization

- The detail tablist supports Left/Right arrow navigation and selected-state announcement; panel identity is associated with the selected tab.
- Dialogs have a title, focus trap, initial focus, Escape behavior, and return focus to the invoking control.
- All async regions use `role="status"` or `aria-live="polite"`; errors use an assertive alert only when immediate action is required.
- Every form control has a persistent visible label or an accessible name. Icon-only actions have names.
- Required fields and validation messages are programmatically associated with their controls.
- Focus moves to the first invalid field after a failed save or run, without skipping hidden controls.
- Colour is never the sole indicator of pass/fail/stale/permission state.
- Motion respects `prefers-reduced-motion`.
- Every new visible string is added to `frontend/src/i18n/locales/en.json`, `hi.json`, `zh-CN.json`, and `zh-TW.json`.
- Dates, numbers, durations, and plural forms use the active locale; no concatenated translated fragments.

## 10. UI Transition Table Required by the Backend

| # | Event | Precondition | UI result | Backend/API contract implied |
|---|---|---|---|---|
| U1 | Select creation mode | Wizard Step 1 | Mode selected; mode-specific input appears | No mutation yet |
| U2 | Advance from AI | Prompt valid and generation configured | Generating, then editor | Create draft response returns key/revision/mode or stable error |
| U3 | Advance from template | Exactly one template selected | Creating, then editor | Create draft from template returns persisted defaults |
| U4 | Advance from professional | Wizard Step 1 | Creating, then editor | Create empty/default draft; server owns key generation |
| U5 | Save Draft | Editor loaded and dirty | Saving, then new revision | Revision-checked update; 409 conflict must be distinguishable |
| U6 | Leave dirty editor | Dirty form | Confirmation dialog | No API; client must block accidental navigation |
| U7 | Run test | Saved revision and valid input | Running, then Passed/Failed/Error/Blocked | Server executes and persists run against exact revision |
| U8 | Edit after Passed | Existing pass | Test evidence immediately Stale | Next save increments revision and invalidates prior pass gate |
| U9 | Open readiness | Detail/version surface | Checklist loading then actual states | Server evaluates saved draft, latest test, dependencies, permission |
| U10 | Confirm publish | All checks pass, metadata valid | Publishing, then new current version | Revision/bump/notes checked under lock; immutable version returned |
| U11 | Open rollback | Historical version exists | Dialog with target/version/notes | API lists immutable targets and lineage |
| U12 | Confirm rollback | Target valid, notes valid | Publishing, then new higher version | Server copies snapshot, records `rollback_from`, never edits history |
| U13 | Any read fails | Network, scope, or not-found | Honest retry/denied/not-found state | Stable error code and no cross-scope data disclosure |

## 11. Explicit Non-Goals for This Interaction Freeze

- No general workflow builder, scheduled execution, batch dataset runner, auto-scoring, A/B test, or gradual rollout UI.
- No marketplace publishing, cross-tenant sharing, category administration, or billing.
- No independent Skill sidebar or redesign of the shared console shell.
- No optimistic version creation or client-side calculation presented as a server-published result.
- No fixture metrics, fixture test runs, or fixture version rows after API integration.

## 12. Review Exit Criteria

This freeze is ready for backend design when reviewers agree that:

1. Every route and in-page tab has one owner.
2. Every creation mode reaches one shared editor.
3. Draft, test evidence, readiness, and immutable version semantics are unambiguous.
4. Every placeholder action in the current static pages maps to a defined transition or an explicit excluded reason.
5. Backend engineers can name the persistence and API operations required by U1–U13 without inventing a second UI contract.

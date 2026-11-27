# Phase 2 · Skill Authoring, Testing, and Release Workflows — Requirements

> Status: Requirements frozen; implementation in progress.
> Created: 2026-11-27
> Basis: `01-business-goals.md` (G1–G4), `00-ui-interaction-freeze.md`, and the supplied NexusDesk reference screenshots.

## User Stories

**US-1 (Skill builder):** As a Skill builder, I want to start from AI assistance, a template, or the professional editor and continue in one consistent configuration experience, so that I can turn an idea into a structured Skill without losing context.

**US-2 (Skill builder):** As a Skill builder, I want to edit complex capability, parameter, dependency, and safety settings while keeping my draft separate from the published version, so that I can prepare changes safely.

**US-3 (Skill tester):** As a Skill tester, I want to enter a real test payload, run it, inspect the result, and review previous runs, so that I can verify the current draft before release.

**US-4 (Skill publisher):** As a Skill publisher, I want to see release blockers, publish an immutable version with notes, and roll back to an earlier version, so that releases are controlled and reversible.

**US-5 (Read-only console user):** As a read-only console user, I want clear disabled controls and reasons, so that I understand what I can view without being misled by actions I cannot perform.

## Functional Requirements

### FR-1 Route and surface ownership

| Item | Description |
|---|---|
| Trigger | Open the catalog, create flow, detail page, or editor |
| Input | Hash route and existing Skill identifier |
| Output | Catalog `/skills`; creation wizard `/skills/create`; detail `/skills/:skillKey`; editor `/skills/:skillKey/edit` |
| Execution | Synchronous route selection; data loading is asynchronous in the later implementation |
| Failure | Unknown Skill identifiers show a non-destructive not-found state with a return-to-catalog action |

The detail page owns six in-page tabs: Overview, Capability Definition, Resource Dependencies, Test Records, Version Management, and Runtime Analytics. Test and version tabs are not separate routes in this phase.

### FR-2 Creation-mode handoff

| Item | Description |
|---|---|
| Trigger | Select AI-assisted, template, or professional mode on `/skills/create` |
| Input | Selected mode, optional AI prompt, or selected template |
| Output | Step 2 editor context with mode-specific defaults and a visible mode label |
| Execution | Card click selects; the card action button advances; template selection prefills the form |
| Failure | If a required mode input is missing, stay on Step 1 or block generation with an inline message; never create an empty draft silently |

AI mode must expose a prompt field before generation. Template mode must expose the recommended template list and select exactly one template. Professional mode opens the editor directly with no generated content. All three modes use the same editor after handoff.

### FR-3 Complex editor

| Item | Description |
|---|---|
| Trigger | Enter Step 2 of creation or open Edit on a detail page |
| Input | Draft form values grouped into Basic, Capability, Parameters, Dependencies, and Runtime/Safety sections |
| Output | Validated draft values and a saved draft revision |
| Execution | Local form editing with explicit Save Draft; navigation warns before discarding dirty changes |
| Failure | Field errors appear inline; save failures preserve local edits and expose retry; permission failures disable editing with a reason |

The editor must support:

- Basic: name, description, category, tags, visibility, and owner summary.
- Capability: Skill type, trigger, execution mode, instruction/prompt, input schema summary, and output schema summary.
- Parameters: add, remove, reorder, and edit fields with name, type, required flag, default, and description.
- Dependencies: selected model profile, knowledge bases, tools, and connectors.
- Runtime/Safety: timeout, retry policy, confirmation requirement, error behavior, and permission scope.

The editor must show a draft revision label such as `Draft r3`, and a published Skill must show the live version separately.

### FR-4 Draft integrity

| Item | Description |
|---|---|
| Trigger | Save Draft, leave a dirty editor, or navigate back into the editor |
| Input | Dirty form state and last-saved draft revision |
| Output | Saved draft or explicit discard confirmation |
| Execution | Saving is a backend mutation in the later implementation; no success state before confirmation |
| Failure | Save conflict displays “newer draft exists”, offers reload or duplicate-as-new; local unsaved changes remain until the user chooses |

Any successful save increments a draft revision. Editing after a test marks that test as stale for release readiness.

### FR-5 Test workbench

| Item | Description |
|---|---|
| Trigger | Open Test Records, click Test on a detail page, or reach creation Step 3 |
| Input | Structured parameter values or raw JSON, plus optional natural-language scenario text |
| Output | Running state, then a pass/fail/error result with output, duration, and diagnostic summary |
| Execution | One test run per action; asynchronous request with cancelable navigation |
| Failure | Validation errors prevent starting; execution errors render an error result and preserve the input for retry |

The workbench layout is two panes on desktop: input on the left and result on the right. History appears below. On narrow screens the panes stack. The run action must show a spinner and disable duplicate submissions.

### FR-6 Test history and release evidence

| Item | Description |
|---|---|
| Trigger | Open Test Records or complete a test run |
| Input | Saved draft revision and test runs |
| Output | Reverse-chronological history with time, revision, input summary, result, duration, executor, and detail action |
| Execution | History loads independently from the active tab; newest result is highlighted |
| Failure | Empty history shows a “Run first test” state; failure to load history does not erase the active result pane |

The latest passing test must be linked to the latest saved draft revision. A newer save or a failed latest test makes release readiness fail.

### FR-7 Release readiness

| Item | Description |
|---|---|
| Trigger | Open Version Management or creation Step 4 |
| Input | Current draft revision, validation state, latest test evidence, dependencies, permission state, and release metadata |
| Output | Explicit pass/block checklist and an enabled or disabled publish action |
| Execution | Readiness is recalculated when the tab opens and before publishing |
| Failure | Blocked checks name the blocker and link to the relevant editor/test section; publish cannot be forced by the client |

Required checks are: draft saved, mandatory fields valid, latest revision tested successfully, dependencies available, permission granted, no publish already running. Each check has a visible state and a reason.

### FR-8 Version publishing and rollback

| Item | Description |
|---|---|
| Trigger | Publish, open version history, or roll back |
| Input | Version bump choice, release notes, confirmation, and target historical version for rollback |
| Output | New immutable version; updated current version; new history row; rollback lineage |
| Execution | Confirm dialog then backend mutation; UI remains on the version surface with progress |
| Failure | Conflicts create no new version; rollback failures leave current version unchanged; all failures provide retry and preserve entered metadata |

The publish dialog exposes minor/major/patch choices with a server-suggested next version. Release notes are required. The published version becomes current only after success.

Rollback must create a new version above the current one, copying the selected historical snapshot and recording `rollback_from`. Historical versions are never edited or deleted by rollback.

### FR-9 Honest loading, empty, error, and permission states

| Item | Description |
|---|---|
| Trigger | Data loading, no records, request errors, or insufficient permissions |
| Input | Async request state and capability response |
| Output | Skeletons/spinners, explicit empty states, retryable errors, and disabled actions with reasons |
| Execution | No optimistic mutation and no fake success message |
| Failure | Every failed request has a retry path; unsaved form content is not silently discarded |

### FR-10 Visual, responsive, and localization compatibility

The creation and editor surfaces must preserve the Phase 1 blue/white visual language and the supplied reference hierarchy. The existing 228px console sidebar and Skill header remain unchanged. All new visible copy must exist in `en`, `hi`, `zh-CN`, and `zh-TW`. Desktop, tablet, and 390px layouts must avoid horizontal document overflow. Controls must remain keyboard accessible and icon-only actions must have accessible names.

## Non-functional Requirements

- **Performance:** Async operations show feedback within 100 ms of activation; no blocking full-page spinner for already-loaded sections.
- **Reliability:** Duplicate publish or test submissions are prevented while an operation is in flight.
- **Compatibility:** Existing catalog routes, sidebar behavior, service-application Skill APIs, and release flows remain unchanged until explicitly integrated.
- **Multi-tenancy:** Every later API call and UI state is scoped by trusted tenant/business/workspace context; cross-scope identifiers are not disclosed.
- **Data integrity:** Draft revisions and published versions are append-only where applicable; published versions are immutable.
- **Accessibility:** Form labels, validation messages, tab semantics, dialogs, and async status announcements are accessible.

## Acceptance Criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Choose each creation mode and advance to Step 2 | AI requires a prompt; template requires one template selection; professional opens directly; every mode reaches the same editor with a visible mode label |
| AC-2 | Edit basic, capability, parameter, dependency, and safety sections | All sections are reachable, editable, and validated; required errors identify the field |
| AC-3 | Save a draft, leave with unsaved changes, then return | Save confirmation is honest; dirty navigation prompts; reload returns the saved draft revision |
| AC-4 | Edit a published Skill | The live version stays visible and unchanged; the draft receives a new revision label |
| AC-5 | Open the test workbench with empty, valid, and invalid input | Empty state guides the first run; valid input starts a run with progress; invalid input is blocked before execution |
| AC-6 | Run one successful and one failing test | Result pane distinguishes pass/fail/error, preserves input for retry, and appends both to history |
| AC-7 | Edit the draft after a passing test | The prior test becomes stale for release readiness and the publish action is blocked until retest |
| AC-8 | Open release readiness with blockers and then resolve them | Every blocker names its cause and destination; publish becomes enabled only when all required checks pass |
| AC-9 | Publish a version with metadata | Confirmation is required; success creates an immutable current version and updates the version history |
| AC-10 | Roll back to an older version | A new higher version is created from the old snapshot; history is unchanged; current-version indicators update |
| AC-11 | Simulate loading, empty, network error, and insufficient permission states | Each state is honest and recoverable; no placeholder “later phase” message remains for in-scope actions |
| AC-12 | Inspect desktop, tablet, and 390px layouts with keyboard navigation and all four locales | Layout remains usable, no horizontal overflow; controls are accessible; copy is complete in every locale |

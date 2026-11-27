# Phase 3 · Skill Packaging and Artefact Storage — Technical Design

> Status: P0 (backend), P1 (frontend package management), and P2 (import into a new Skill) implemented and verified. Runtime mounting and remote import remain planned.
> Created: 2026-11-27 · Revised: 2026-11-27 (frontend upload surface, `filename` column, `POST /skills/import`)

## 1. What this phase changes

Phase 1 and 2 model a Skill as a declarative record: instructions, parameters,
dependencies, and runtime policy, all stored as JSONB. That model cannot carry
files. A Skill that ships a `SKILL.md`, reference documents, or scripts has no
place to put them, and no place to run them.

Phase 3 introduces the missing middle layer: an **artefact**. The Skill record
keeps describing intent; the artefact holds bytes. They are bound, not merged.

Three planes, deliberately separate:

| Plane | Holds | Stored in | Mutability |
|---|---|---|---|
| Artefact | the zip itself | object storage, addressed by digest | immutable |
| Definition | how to use it: instructions, parameters, dependencies, entrypoint | Postgres JSONB | draft editable, version frozen |
| Runtime | unpacked files inside a sandbox workdir | created per execution | ephemeral |

Collapsing these is the usual failure mode of skill systems: a draft edit
rewrites bytes, or a re-run silently uses different files than the one that was
tested.

## 2. Why a package is not a `skills` column

A package is large, immutable, and belongs in object storage. Mixing it into the
mutable Skill row would make every draft save carry a blob, make rollback a byte
copy, and make the row unusable for list queries. So `skill_packages` is its own
table, and `skills.draft_package_id` is a pointer.

`skill_versions.package_id` records which package a release shipped with. It is
nullable because declarative Skills predate packages and must keep working.

## 3. Data model

```sql
CREATE TABLE skill_packages (
  id             uuid PRIMARY KEY,
  tenant_id      text NOT NULL,
  business_id    text NOT NULL,
  workspace_id   text NOT NULL,
  skill_id       uuid NOT NULL,
  s3_bucket      text NOT NULL,
  s3_key         text NOT NULL,
  digest         text NOT NULL,      -- sha256:<64 hex>, over the archive bytes
  size_bytes     bigint NOT NULL,
  file_count     int NOT NULL,
  manifest       jsonb NOT NULL,     -- verified file list + SKILL.md metadata
  entrypoint     text,
  has_scripts    boolean NOT NULL DEFAULT false,
  filename       text NOT NULL,      -- display label only (0079)
  created_by     text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
```

Migration `0078_skill_packages` also adds `skills.draft_package_id` and
`skill_versions.package_id`. Both default to `NULL`, so every existing row stays
valid and the migration needs no backfill.

Migration `0079_skill_package_filename` adds `filename`. The digest answers
"which bytes", never "which file did I drop in" — support and audit need the
second answer. Attempting the second archive on the same Skill replaces the
first, so without this column the history of names is lost the moment an author
iterates. Rows written before the column existed are backfilled with the upload
route's own default (`package.zip`) and the column is then made `NOT NULL`: a
missing label would mean "unknown file", and no real package has one.

The value is reduced to a basename and stripped of control characters
(`_package_filename`) rather than rejected. Some browsers send full paths, and a
naming quirk must not fail an upload whose bytes are already in object storage.
The name is never used to address anything, so a caller that lies about it
changes only the label.

The foreign key is scope-bound `(tenant_id, business_id, workspace_id, skill_id)
→ skills`, matching the rest of the library: a package cannot outlive its Skill
or cross a workspace boundary.

### S3 key layout

```
skills/{tenant}/{business}/{workspace}/{skill_key}/{sha256}.zip
```

Digest-addressed so the same key always means the same bytes. Deliberately no
content-addressed deduplication across Skills: the garbage-collection complexity
costs more than the storage saves at this scale.

### Local object storage

Packages need an S3-compatible bucket or every upload path answers
`503 skill_package_storage_unavailable`. The dev environment reuses the MinIO
container that already serves the knowledge stack
(`nexusdesk/deploy/knowledge/compose.local.yaml`), on `127.0.0.1:19000`:

```
AGENT_SKILL_S3_ENDPOINT=http://127.0.0.1:19000
AGENT_SKILL_S3_BUCKET=agent-skills
AGENT_SKILL_S3_ACCESS_KEY=<MINIO_ROOT_USER>
AGENT_SKILL_S3_SECRET_KEY=<MINIO_ROOT_PASSWORD>
```

`agent-skills` is declared in `MINIO_DEFAULT_BUCKETS` so a fresh volume
provisions it. Only the `skill_*` four are set locally: pointing
`AGENT_KNOWLEDGE_S3_*` at the same bucket would also move knowledge ingestion
onto object storage, which this environment does not need.

Two details worth keeping: the container runs as uid 1001 and its data
directory is `/bitnami/minio/data`, so the named volume must mount there — a
volume on `/data` is root-owned and the container restart-loops on
`Permission denied`. And the endpoint is the host-published port because the
backend runs on the host, not inside the compose network.

## 4. Ingestion policy

`skill_library/importing.py` is a pure function over bytes: no disk writes, no
imports of package content, no network. It returns an `InspectedPackage` or
raises `PackageRejected`.

| Attack surface | Rule |
|---|---|
| Empty payload | reject `skill_package_empty` (422) |
| Oversized archive | reject above 50 MB before decoding (413) |
| Not a zip | reject `skill_package_unsupported` (415) |
| Zip Slip | normalise every entry to a relative POSIX path; reject `..`, absolute paths, drive prefixes, and `.` segments |
| Windows separators | reject any entry containing `\` |
| Symlink escape | reject when `external_attr >> 16` carries `S_IFLNK` |
| Zip bomb (entry count) | reject above 200 entries (413) |
| Zip bomb (size) | reject when accumulated uncompressed size exceeds 50 MB, or a single file exceeds 10 MB (413) |
| Zip bomb (ratio) | reject files above 1 MB that expand more than 100:1 (413) |
| Nested archives | reject `.zip/.tar/.gz/.tgz/.bz2/.xz/.7z/.rar/.whl` entries |
| Native payloads | reject `.exe/.dll/.so/.dylib/.msi/.bat/.cmd/.ps1/.vbs/.jar/.class/.pyc/.pyd` |
| Size honesty | re-read each entry and compare the actual byte count against the central directory; mismatch is `skill_package_corrupt` |
| Missing document | require `SKILL.md` at the package root after prefix stripping (`skill_package_missing_manifest`) |
| Encoding | reject a `SKILL.md` that is not valid UTF-8 |

Scripts (`.py`, `.sh`, `.js`, `.ts`, `.rb`, `.pl`, `.lua`, …) are **allowed**.
They are the point of an executable package; they are flagged, not blocked.

A single wrapping directory (`my-skill/SKILL.md`) is stripped when every entry
shares that top level and the document is not already at the root, so a plain
"zip this folder" export works unchanged.

### Resulting manifest

```json
{
  "schema": "skill-package/v1",
  "digest": "sha256:...",
  "size_bytes": 41234,
  "file_count": 6,
  "files": [{"path": "SKILL.md", "size": 810, "sha256": "...", "executable": false}],
  "entrypoint": "scripts/main.py",
  "has_scripts": true,
  "skill": {"name": "...", "description": "...", "license": "MIT", "allowed_tools": []}
}
```

The manifest is the contract between ingestion, the UI, and the future runtime:
`files[].sha256` lets the runtime re-verify after download without trusting
object storage.

## 5. Interaction with classification

Phase 3 makes the weight axis real. `weight_class` was already derived from
`PackageFacts`; until now `present` was always false, so every Skill was
`declarative`.

| Package state | `weight_class` |
|---|---|
| no package | `declarative` |
| package with no scripts and no entrypoint | `packaged` |
| package with scripts or an entrypoint | `executable` |

Two rules keep this honest:

1. **Attaching or detaching a package recomputes weight and `data_scope`,
   and bumps `draft_revision`.** Binding changes the draft, so the revision must
   move or a concurrent editor would silently overwrite the classification.
2. **Saving a draft recomputes weight from the attached package, not from the
   form.** Without this, saving any draft would reset a packaged Skill to
   `declarative` and skip the sandbox at run time.

`risk_level` is untouched by packaging. An executable package adds `code` to
`data_scope`; it does not raise risk. A packager is a distribution channel, not
a business consequence.

## 6. API surface

| Method | Path | Permission | Behaviour |
|---|---|---|---|
| `GET` | `/api/v1/skills/{key}/package` | `skill.read` | manifest, from Postgres, no object read |
| `POST` | `/api/v1/skills/{key}/package?filename=` | `skill.manage` | raw zip body; verify, store, bind |
| `DELETE` | `/api/v1/skills/{key}/package` | `skill.manage` | unbind, recompute weight, delete object |
| `POST` | `/api/v1/skills/import?filename=` | `skill.manage` | raw zip body; verify, create the Skill **and** bind, `201` |

The upload takes a raw body rather than multipart. The endpoint accepts exactly
one artefact, and streaming lets the size ceiling fire before the bytes are
buffered — the same pattern `knowledge_upload` already uses, and it avoids adding
`python-multipart` for a single call site.

Ordering inside `attach_package`:

1. reject by size ceiling
2. inspect the archive (pure)
3. fail fast if object storage is unconfigured (`503`)
4. write bytes to S3 **before** opening the transaction
5. open the transaction: lock the Skill row, insert the package, re-point
   `draft_package_id`, recompute classification, audit
6. delete the superseded object once the transaction commits

A slow upload therefore never holds a row lock, and an object left behind by a
rolled-back insert is garbage rather than a correctness problem. If the
transaction fails, the freshly written object is deleted.

### Import is create, not attach

`POST /skills/import` closes the gap the attach endpoint deliberately leaves:
before it existed, a zip could only be added to a Skill that already had a key, so
"take this archive and make it a Skill" was impossible from the UI.

The archive is the source of truth for everything a form would have asked for:

| Field | Source |
|---|---|
| `name` | `SKILL.md` frontmatter `name`, else the stripped top-level directory |
| `description` | frontmatter `description`, else the first line of the body |
| `instructions` | the `SKILL.md` body |
| `key` | slug of the name; a taken key gets `-2`, `-3`, … |
| `tags` | frontmatter `tags`, capped at 8 entries of 32 chars |
| `weight_class` / `data_scope` | derived from the package facts, as always |

`creation_mode` is stored as `package`, so the editor and the audit trail show
provenance. `SkillCreateMode` (what `POST /skills` accepts) deliberately excludes
it — a caller cannot ask for a packaged Skill through the generic create body.

Two consequences of doing it in one transaction:

- The storage key embeds the Skill key, so the row must exist before the object
  can be written. Unlike `attach_package`, the object write happens *inside* the
  transaction. That is safe here because the row is brand new and invisible to
  every other reader, so there is no lock to contend on.
- `draft_revision` stays at `1`. This is one creation event, not a create
  followed by an attach; the `UPDATE` only sets `draft_package_id`.

A body longer than the 20 000-character instruction column is rejected with
`skill_package_instructions_too_long` instead of being truncated: silently
dropping part of a third party's instructions changes what the Skill does.

## 7. Frontend surface

The upload surface is deliberately narrow: this phase is **management**, not
execution. An operator can attach, replace, inspect, and remove a package; nothing
here mounts or runs it.

### Where it lives

| Page | Section | Capability |
|---|---|---|
| Editor (`/skills/{key}/edit?section=runtime`) | bottom of the runtime tab | upload, replace, remove, inspect |
| Detail (`/skills/{key}?tab=resources`) | its own panel | inspect only |
| Create (`/skills/create`) | fourth mode card | import a zip into a new Skill |

Import sits with the creation modes because that is what it is: a way to obtain a
Skill, not a way to manage one that exists. It is rendered as a full-width row
below the three authoring modes — importing is not authoring, and squeezing it
into a fourth column would have made four narrow cards out of three comfortable
ones.

The editor's runtime tab is the primary entry because the package decides
`weight_class`, which in turn decides the runtime safety policy — the control
belongs next to the policy it constrains, not in a generic "files" area. The
detail page is read-only so a reviewer can see what is attached without entering
an editable surface.

There is deliberately **no catalogue-level "Import" button**. That button's
meaning is "start creating a Skill", and the backend has no endpoint that turns
an archive into a new Skill. Offering the entry point without the endpoint would
be a dead end.

### Upload is attach

`POST` binds immediately: the bytes go to object storage, the draft revision
increments, and `weight_class` is recomputed in the same call. There is no
"verify, then confirm" step, because the backend has no inspect-only endpoint and
adding one would buy a two-phase state machine for a reversible mistake — a wrong
archive is removed with one click, and the cost of being wrong is one orphaned
object.

The mitigation lives on the client instead: an obviously wrong file (not a `.zip`,
over the 50 MB ceiling) is rejected before the request is sent. Everything else —
paths, symlinks, nesting, native payloads, `SKILL.md`, encoding — is decided by
the server, because only the server's verdict is authoritative.

### What the card shows

| State | Content |
|---|---|
| empty | drag target, with the constraints inline: root `SKILL.md`, ≤50 MB, ≤200 files |
| attached | `filename`, tier tag, script tag, size, file count, entrypoint, digest prefix, upload time |
| expanded | the manifest's file list; script entries carry a `script` tag |
| rejected | the server's code mapped to a sentence that names the fix |

Rejections are stable codes, and each one is translated rather than surfaced raw:

| Code | Shown as |
|---|---|
| `skill_package_missing_manifest` | no `SKILL.md` — it must be at the root, or inside a single top-level folder |
| `skill_package_executable_payload` | native payloads like `.exe` / `.dll` / `.bat`; scripts are allowed and tagged |
| `skill_package_path_traversal` | an escaping path such as `..` or an absolute path |
| `skill_package_compression_ratio` | suspicious ratio, possibly a decompression bomb |
| `skill_package_storage_unavailable` | object storage unconfigured — a platform problem, not a package problem |

An unrecognised code falls back to a generic line rather than rendering the raw
detail, so a future server rule stays diagnosable without leaking internals.

### Replacing and removing

Replacing reuses the same `POST`; the server keeps one row and one object.
Removing uses a confirmation that states both consequences — the tier drops back
to `declarative` and the draft revision increments — because both are visible and
neither is obvious.

After a successful attach the editor updates its `currentRecord` from the response
instead of refetching. Refetching would re-derive the form values from the server
and silently discard unsaved edits; taking the record keeps the revision in sync
for the next save while leaving the form alone.

## 8. Storage configuration

`skill_s3_endpoint / bucket / access_key / secret_key` are new settings; each
falls back to the corresponding `knowledge_s3_*` value. A single-bucket
deployment keeps working with no configuration change, and an operator can split
Skill packages onto their own bucket (different lifecycle, different retention)
by setting four variables.

`skill_package_bytes` (default 50 MB) is the upload ceiling. It intentionally
matches the sandbox workdir quota so a package that ingests can also be unpacked.

## 9. What this phase does not do

| Not implemented | Why, and what it needs |
|---|---|
| Runtime mounting | P2. Needs download → digest re-verify → unpack → read-only bind mount into the sandbox workdir. Deliberately out of this phase: the platform is at *management*, not *use*. |
| Script execution | Out of scope here. Requires the existing `uploaded_code` gate: `docker` provider + `execution_sandbox_required` + `execution_untrusted_tenants_enabled`. `local` rejects it outright. |
| Remote URL import | P3. Reuses this ingestion policy; needs a host whitelist, private-range rejection, no redirects, and a streamed size cap. |
| Package download / per-file download | Not needed for management. The manifest already carries paths, sizes and digests; serving bytes back means another authenticated streaming route and its own audit. |
| Package GC across Skills | Not needed yet: one working package per Skill, replaced in place. |

Because runtime mounting is not wired, an `executable` Skill is currently
classified but not runnable by the platform. That is stated rather than papered
over: the acceptance surface must not claim execution it cannot perform.

## 10. Deletion and replacement

A Skill carries exactly one working package. Attaching a second archive deletes
the previous row and, after commit, its object. This keeps the invariant "the
draft points at the bytes the editor describes" without a reference count.

Consequence: `duplicate` does not copy the package. The copy starts declarative
and the author re-uploads. Sharing one object between two Skills is a P2
concern, when version pinning makes reference counting worth its complexity.

## 11. Verification

| Suite | Result |
|---|---|
| `tests/test_skill_package_importing.py` (ingestion policy, table-driven) | 23 passed |
| `tests/test_skill_library_api_postgres.py` (17 existing + 6 attach cases + 4 import cases) | 27 passed |
| `tests/test_skill_library_contracts.py` | 7 passed |
| `tests/test_skill_classification.py` | 32 passed |
| `tests/test_skill_package_migrations.py` (upgrade → reject dangling FK → downgrade → upgrade; `filename` backfill and constraints) | 2 passed |
| Platform regression (`test_platform_postgres`, `test_access_control`, `test_platform_settings`) | 28 passed |
| `ruff check src tests migrations/versions` | clean |

89 Skill tests pass in one run (23 + 32 + 27 + 7).

Frontend:

| Check | Result |
|---|---|
| `npm run typecheck` | clean |
| `npm run check:i18n` | 3558 translations in zh-CN, zh-TW, en, hi |
| `npm run build` | built (only the pre-existing >500 kB chunk warning) |
| `npx playwright test tests/skills.spec.ts` | 20 passed |
| New cases | `P3-UI-01` attach → re-tier, `P3-UI-02` rejection message, `P3-UI-03` read-only detail panel |

The six API cases assert, in order: binding a declarative package moves weight to
`packaged` and bumps the revision; the supplied `filename` is echoed back; a
Windows-style path is reduced to its basename; an executable package is flagged
with `has_scripts` and adds `code` to `data_scope`; saving a draft does **not**
downgrade weight; replacing a package leaves one row and one object; a rejection
stores nothing and leaves the revision untouched.

The e2e suite aborts requests to `fonts.googleapis.com`. `login.css` imports two
web fonts, and offline that stylesheet import never settles — the `load` event
never fires and every `page.reload()` fails on a timeout unrelated to the code
under test. This is a test-environment guard, not a product change; the dev
server still requests the fonts.

## 12. Catalogue usage and ratings

The catalogue shows four headline numbers (total, published, in use, average
rating), a usage/rating line on every card, and a popular rail. All of them are
**derived from recorded behaviour** — none is a column an author fills in.

### Two append-only tables

| Table | Grain | Why this grain |
|---|---|---|
| `skill_usage_daily` | one row per Skill per day, with `runs` and `succeeded` | A Skill running 100k times a day must not create 100k rows; the writer rolls up in place |
| `skill_ratings` | one row per rater per Skill (unique), `score` 1–5 | Keeps the average honest and makes re-rating an update, not a duplicate |

They are keyed by day and carry the success count so the detail page's analytics
tab can read the same rows later instead of inventing a second source.

### Why derived, not stored

A `usage_count` column on `skills` would need every writer to remember to bump
it, and any bad import would corrupt the total irreversibly. With facts:

* the trend arrows are a window comparison (`current_date - 29 … current_date`
  versus the 30 days before), not a value someone maintains;
* a wrong run can be deleted without leaving a counter that never recovers;
* `usage_count` is `sum(runs)` and `success_rate` is `sum(succeeded)/sum(runs)`,
  so the card can never disagree with the rail.

Rows are joined to the list query through a `LATERAL` aggregate, so a page of
cards is still one round-trip.

### Trend semantics

`change` is `null` when there is no comparable prior window (a fresh catalogue,
or fewer than 60 days of history). The UI renders no chip in that case rather
than claiming "0%" — "flat" and "unknown" are different statements, and the
arrow must not assert the second while meaning the first.

The same asymmetry bit once: `u.day > current_date - 30` yields 29 days, so every
trend read negative. Both windows are now exactly 30 days.

### Sample data

`skill_library/seed.py` writes 90 days of usage and a fixed set of ratings for
the eight sample Skills, derived from a hash of the Skill key so every install
shows the same demo. It anchors the series on the database's `current_date`
(Python's date and Postgres' clock disagree across midnight/timezone, which
leaves the newest days empty and flips the trend). Seeding is skipped per Skill
when any row already exists, so a re-run never doubles the figures.

There is **no runtime writer yet**: Skills are not executed by agents on this
build, so nothing records real invocations. When the sandboxed runtime lands it
writes the same daily rows and the numbers start moving on their own.

### Pagination and ordering

The list is paginated in SQL (`LIMIT`/`OFFSET` against the filtered count), so
ordering has to be applied there too. Sorting the rows of one page would reorder
that page and leave the sequence across pages wrong — the page boundaries would
disagree with the order the reader sees.

`sort` accepts three keys and is mapped to a fixed `ORDER BY` fragment, never
interpolated:

| `sort` | Order |
|---|---|
| `latest` (default) | `updated_at DESC, id` |
| `name` | `name, id` |
| `usage` | `usage_total DESC, name, id` |

`usage` orders by the same `LATERAL` aggregate the card displays, so "most used"
cannot disagree with the number on the card. `id` is the tiebreaker everywhere:
without it two rows with the same timestamp could swap places between page
requests and a row would appear twice or vanish.

An unknown `sort` falls back to `latest` instead of returning 422: a stale client
or a bookmarked URL should still render a list.


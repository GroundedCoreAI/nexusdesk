"""Fetch and sanitize PR context for the LLM.

Everything returned here is **untrusted data** (spec section 13.1): it comes
from the PR author's diff and description, and is only ever passed to the LLM
as data — never executed, never interpolated into shell commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from github_client import GitHubClient

# A single file whose patch exceeds this is truncated in the LLM prompt; the
# file still counts toward completeness tracking.
MAX_PATCH_CHARS_PER_FILE = 12_000
# Hard cap on the whole diff sent to the model, to keep token cost bounded.
MAX_TOTAL_DIFF_CHARS = 120_000

# Paths that are noise for review purposes (lockfiles, generated code).
IGNORED_PATH_PREFIXES = (
    "backend/uv.lock",
    "frontend/package-lock.json",
    "backend/requirements.txt",  # generated from uv.lock
)


@dataclass
class ChangedFile:
    path: str
    status: str  # added | modified | removed | renamed | ...
    additions: int
    deletions: int
    patch: str | None  # None when GitHub omitted the patch (too large / binary)
    ignored: bool = False
    truncated: bool = False


@dataclass
class PRContext:
    number: int
    title: str
    author: str
    base_ref: str
    head_ref: str
    head_sha: str  # always re-fetched from the PR API, never GITHUB_SHA
    draft: bool
    body: str
    files: list[ChangedFile] = field(default_factory=list)

    @property
    def changed_files(self) -> int:
        return len(self.files)

    @property
    def changed_lines(self) -> int:
        return sum(f.additions + f.deletions for f in self.files)

    @property
    def reviewable_files(self) -> list[ChangedFile]:
        return [f for f in self.files if not f.ignored]

    @property
    def files_without_patch(self) -> list[ChangedFile]:
        return [f for f in self.reviewable_files if f.patch is None and f.status != "removed"]


def fetch_pr_context(client: GitHubClient, number: int) -> PRContext:
    """Load PR metadata and the full changed-file list via the GitHub API."""
    pr = client.get_pr(number)
    files = [
        ChangedFile(
            path=item["filename"],
            status=item["status"],
            additions=item.get("additions", 0),
            deletions=item.get("deletions", 0),
            patch=item.get("patch"),
            ignored=item["filename"].startswith(IGNORED_PATH_PREFIXES),
        )
        for item in client.list_pr_files(number)
    ]
    return PRContext(
        number=number,
        title=pr.get("title") or "",
        author=(pr.get("user") or {}).get("login") or "unknown",
        base_ref=pr["base"]["ref"],
        head_ref=pr["head"]["ref"],
        head_sha=pr["head"]["sha"],
        draft=bool(pr.get("draft")),
        body=pr.get("body") or "",
        files=files,
    )


def render_diff_for_llm(ctx: PRContext) -> str:
    """Render the diff text for the prompt, with per-file and total caps.

    Files dropped by the total cap are marked ``truncated`` so the model and
    the policy engine know the review is not complete.
    """
    parts: list[str] = []
    total = 0
    omitted: list[str] = []
    for index, f in enumerate(ctx.reviewable_files):
        header = f"=== {f.path} ({f.status}, +{f.additions}/-{f.deletions}) ==="
        if f.patch is None:
            body = "[patch unavailable: binary, too large, or removed file]"
        else:
            body = f.patch
            if len(body) > MAX_PATCH_CHARS_PER_FILE:
                body = body[:MAX_PATCH_CHARS_PER_FILE] + "\n[... file patch truncated ...]"
                f.truncated = True
        chunk = f"{header}\n{body}"
        if total + len(chunk) > MAX_TOTAL_DIFF_CHARS:
            omitted = [x.path for x in ctx.reviewable_files[index:]]
            for x in ctx.reviewable_files[index:]:
                x.truncated = True
            break
        parts.append(chunk)
        total += len(chunk)
    if omitted:
        parts.append(f"[... {len(omitted)} file(s) omitted from prompt: {', '.join(omitted)} ...]")
    return "\n\n".join(parts)

"""Thin GitHub REST API client used by the review pipeline.

Authenticated with the short-lived GitHub App installation token produced by
``actions/create-github-app-token`` in the workflow. The token is passed via
the ``GITHUB_APP_TOKEN`` environment variable, used only for the duration of
the job, and never logged (spec section 13.3).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubApiError(RuntimeError):
    """Raised for any non-retryable GitHub API failure."""


class GitHubClient:
    def __init__(self, repo: str, token: str | None = None) -> None:
        self.repo = repo
        token = token if token is not None else os.environ.get("GITHUB_APP_TOKEN", "")
        if not token:
            raise GitHubApiError("GITHUB_APP_TOKEN is not set; cannot call GitHub API")
        self._http = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:  # noqa: PYI034 - runtime class, returns self
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low-level helpers -------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        if response.status_code == 422:
            # Validation failures (e.g. an inline comment on a line outside the
            # diff) are expected and handled by callers.
            raise UnprocessableEntity(response.text)
        if response.status_code >= 400:
            raise GitHubApiError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
        if response.status_code == 204:
            return None
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self._request("PATCH", path, **kwargs)

    # -- pull requests -------------------------------------------------------

    def get_pr(self, number: int) -> dict[str, Any]:
        return self.get(f"/repos/{self.repo}/pulls/{number}")

    def list_pr_files(self, number: int) -> list[dict[str, Any]]:
        """All changed files, paginated (100 per page, GitHub caps at 3000)."""
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self.get(
                f"/repos/{self.repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            if not batch:
                break
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    # -- reviews ---------------------------------------------------------------

    def create_review(
        self,
        number: int,
        head_sha: str,
        event: str,
        body: str,
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"commit_id": head_sha, "event": event, "body": body}
        if comments:
            payload["comments"] = comments
        return self.post(f"/repos/{self.repo}/pulls/{number}/reviews", json=payload)

    # -- check runs ------------------------------------------------------------

    def list_check_runs(self, ref: str, check_name: str) -> list[dict[str, Any]]:
        data = self.get(
            f"/repos/{self.repo}/commits/{ref}/check-runs",
            params={"check_name": check_name},
        )
        return data.get("check_runs", [])

    def create_check_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post(f"/repos/{self.repo}/check-runs", json=payload)

    def update_check_run(self, check_run_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.patch(f"/repos/{self.repo}/check-runs/{check_run_id}", json=payload)


class UnprocessableEntity(GitHubApiError):
    """HTTP 422 — e.g. inline comment anchored outside the diff."""

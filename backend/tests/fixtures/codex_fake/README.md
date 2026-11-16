# Fake Codex integration fixture

This fixture is an intentionally deterministic protocol simulator for Phase 5 integration tests. It is not a Codex implementation and cannot prove provider compatibility or production security.

Build and run it from this directory:

```sh
docker compose build
docker compose run --rm -e FAKE_CODEX_SCENARIO=success fake-codex-cli
docker compose run --rm -e FAKE_CODEX_SCENARIO=malformed fake-codex-cli
```

The CLI mode emits bounded JSONL events. The app-server mode reads JSON-RPC requests from stdin and emits initialize/turn responses and notifications. Supported scenarios are `success`, `malformed`, `hang`, and `child` (CLI only). The image has no credentials and runs as an unprivileged user.

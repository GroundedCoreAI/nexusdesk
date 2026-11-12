# Quickstart

This page takes you from nothing to a running NexusDesk demo, and shows how to confirm the agent actually works. Expect about ten minutes.

## Prerequisites

| Item | Requirement |
|---|---|
| Docker | 20.10 or newer |
| Docker Compose | v2 (`docker compose`) |
| Docker Desktop | Use **Linux containers** |
| Network | The first run pulls images or builds the frontend |

## Option 1 — build locally

```bash
# Linux / macOS
sh nexusdesk quickstart
```

```powershell
# Windows PowerShell
.\nexusdesk.ps1 quickstart
```

The first run compiles the frontend and builds images, so it takes a while; later runs reuse the cache.

## Option 2 — use the published image

```bash
NEXUSDESK_IMAGE_REGISTRY=docker.io/groundedcore/ NEXUSDESK_VERSION=latest \
  docker compose -f deploy/quickstart/compose.yaml up -d
```

## Verify the stack is up

Open `https://localhost:8080`.

The demo uses a self-signed certificate, so the browser warns you — continue anyway. Certificate setup and LAN access are covered in the [deployment guide](https://github.com/GroundedCoreAI/nexusdesk/blob/integration/deploy/README.md).

Sign in with `admin` / `nexusdesk` (local demo only).

## Run your first conversation

Open the preconfigured `sample-support` conversation and try two prompts:

1. **"How long does shipping take?"** — the agent retrieves from the knowledge base and answers with references.
2. **"帮我创建工单"** (create a ticket for me) — the agent drafts a ticket and waits for your confirmation before creating it.

These two steps verify the retrieval path and the tool-calling plus human-confirmation path respectively.

## Explore the industry case packs

The demo ships 9 industry case packs: 9 knowledge bases, 18 agent drafts and 36 documents.

- Every resource name carries the `[案例]` (case) prefix;
- Filter the agent list with **Scope → Cases only**;
- See [Industry examples](../guides/industry-examples.md) for details.

## Optional execution path and rollback

Run the commands in this section from the repository root. Quickstart has one embedded Worker (`AGENT_EMBEDDED_WORKER=true`) and uses the legacy execution path by default (`AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false`), with no additional UI or service. The `app` service has its own healthcheck, but container status does not replace path-log and Run-terminal checks. For a controlled Orchestrator trial, explicitly opt in and recreate `app`:

```bash
AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true \
  docker compose -f deploy/quickstart/compose.yaml up -d --force-recreate app
```

The switch takes effect at process startup. It is not request-level hot switching and does not automatically fall back to legacy for a failed Run. Restore the default path with:

```bash
AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false \
  docker compose -f deploy/quickstart/compose.yaml up -d --force-recreate app
```

Do not use `docker compose restart` to apply new environment values. See the [rollout and rollback runbook](../operations/agent-execution-orchestrator-rollout.en.md) for mixed Workers, observability, and production rollback.

## Troubleshooting

**Port already in use** — free `8080` or change the port mapping in the compose file.

**Image pull fails** — make sure `NEXUSDESK_IMAGE_REGISTRY` ends with a slash and the registry is reachable.

**The page keeps loading** — the frontend may still be compiling; watch `docker compose -f deploy/quickstart/compose.yaml logs -f web`.

## Security note

The demo uses a **simulated model**, so answers do not reflect real model quality. The default account is for local use only and is not a production authentication boundary. Keep the default `127.0.0.1` binding; if you need external access, restrict source IPs with a security group or firewall.

## Next steps

- Deploy for real: [Middleware](../operations/middleware.md), [Database migrations](../operations/database-migrations.md)
- Learn the product: [Platform guide](../guides/platform.md)
- Understand the runtime: [Agent Runtime](../architecture/runtime.md)

# Agent Answer Streaming (LISTEN/NOTIFY)

[中文](streaming-design.md) · **English**

**Status: implemented.** The Runtime and open API stream model text through `model.delta` events using PostgreSQL LISTEN/NOTIFY.

| Data | Delivery | Replay behavior |
|---|---|---|
| Run lifecycle and tool progress | Durable `runtime_events` rows | Replayable with `Last-Event-ID` or `after` |
| Final answer | Persisted run output and `run.completed` | Always available after completion |
| Model text deltas | Transient notifications, never inserted into the event log | Best effort; no event ID and no replay |

The internal SSE stream may include text and reasoning deltas. The public API forwards visible answer text only; reasoning and tool-call fragments remain internal. A disconnect or lost notification can degrade the experience to receiving the complete answer at completion, but does not change the durable result.

The [Chinese design document](streaming-design.md) retains the original design background and describes per-round rendering, delivery guarantees, and public/internal presentation rules.

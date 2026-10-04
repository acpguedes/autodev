# ADR-031: Streaming Output Events and the Chunk-Redaction Rule

- **Status:** Accepted
- **Date:** 2026-10-04
- **Authors:** AutoDev platform team
- **Related epic:** E64 (S3)
- **Relates to:** RFC-009 (execution action contract), E33 (secret redaction in `emit_event`)

## Context

Secret redaction runs inside `emit_event()` and scrubs exact live secret values
from each payload. That is sound for whole-output events but not for a stream:
a value split across two chunks matches in neither. E64-S3 streams stdout/stderr
while a process runs, which would otherwise create a new exfiltration path.

## Decision

1. `execution.action.output` `{actionId, stream, chunk, seq}` is appended to the
   catalog (additive, MINOR per §19.1). The terminal `completed`/`failed` event
   still carries the full tail-capped output, so consumers may replace the
   accumulated chunks with it.
2. **Chunk-redaction rule (binding on every future streaming producer):** emit
   only on line boundaries, carrying the unfinished tail over until its newline
   (or process end). A line longer than the event cap is cut at its last
   whitespace, never mid-token. Redaction itself stays in `emit_event()`.
3. The sandbox stays free of the event bus: it takes an optional per-job
   `on_chunk(stream, text)` callback and the executor emits.
4. Both sandbox paths use `Popen` with one reader thread per pipe (no two-pipe
   deadlock) and `errors="replace"` decoding. On timeout the Docker path
   explicitly runs `docker kill <name>` (the container is named), since killing
   the `docker run` client does not stop it.

## Consequences

- A secret contained in one line is never split across events; a secret with
  embedded whitespace spanning an over-cap line is a residual, documented risk.
- Output lines appear in the panel while the process runs; the final event's
  content is unchanged from the blocking capture.
